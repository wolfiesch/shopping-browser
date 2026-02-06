"""
Session Pool Daemon — Keeps browser sessions warm for fast reuse.

Architecture: Unix domain socket daemon managing a pool of browser instances.
CLI ←→ Unix socket ←→ Daemon ←→ Chrome (nodriver)

Usage:
    python session_pool.py start    # Start daemon (backgrounds itself)
    python session_pool.py stop     # Stop daemon
    python session_pool.py status   # Check daemon status
"""

import asyncio
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

# Add stealth-browser scripts to path
STEALTH_SCRIPTS = Path.home() / ".claude" / "skills" / "stealth-browser" / "scripts"
sys.path.insert(0, str(STEALTH_SCRIPTS))
# Add shopping-browser scripts to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

DATA_DIR = Path(__file__).parent.parent / "data"
SOCKET_PATH = DATA_DIR / "pool.sock"
PID_FILE = DATA_DIR / "pool.pid"

IDLE_TIMEOUT = 300      # 5 minutes
COOKIE_REFRESH = 600    # 10 minutes


class SessionPool:
    """Manages a pool of browser sessions keyed by domain."""

    def __init__(self):
        self.sessions = {}  # domain → {browser, page, last_used, created}
        self._running = True

    async def acquire(self, domain: str) -> dict:
        """Get or create a browser session for a domain."""
        if domain in self.sessions:
            session = self.sessions[domain]
            port = session["port"]

            # Health check: verify Chrome is still alive
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=2
                )
            except Exception:
                print(f"[pool] Stale session for {domain} (port {port}), recreating", file=sys.stderr)
                await self._stop_session(session)
                del self.sessions[domain]
                return await self.acquire(domain)  # Recurse to create fresh

            session["last_used"] = time.time()
            print(f"[pool] Reusing session for {domain}", file=sys.stderr)
            return {
                "success": True, "reused": True, "domain": domain,
                "host": "127.0.0.1", "port": port,
            }

        # Create new session
        print(f"[pool] Creating new session for {domain}", file=sys.stderr)
        try:
            from config import BROWSER_ARGS
            from chrome_cookies import extract_cookies as extract_chrome_cookies
            from base import inject_cookies
            import nodriver as uc

            cookie_result = extract_chrome_cookies([domain], decrypt=True)
            if not cookie_result.get("success"):
                return {"success": False, "error": "Cookie extraction failed"}

            browser = await uc.start(headless=True, browser_args=BROWSER_ARGS)
            page = await browser.get(f"https://www.{domain}")
            await page.sleep(1)

            await inject_cookies(browser, cookie_result["cookies"], domain)

            port = browser.config.port
            now = time.time()
            self.sessions[domain] = {
                "browser": browser,
                "page": page,
                "port": port,
                "last_used": now,
                "created": now,
                "cookies_refreshed": now,
            }

            return {
                "success": True, "reused": False, "domain": domain,
                "host": "127.0.0.1", "port": port,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def release(self, domain: str) -> dict:
        """Mark a session as available (no-op — session stays in pool)."""
        if domain in self.sessions:
            self.sessions[domain]["last_used"] = time.time()
        return {"success": True}

    async def _stop_session(self, session: dict):
        """Safely stop a browser session — disconnect WebSocket, then kill process if we own it."""
        browser = session.get("browser")
        if not browser:
            return
        try:
            if browser.connection:
                await browser.connection.disconnect()
        except Exception:
            pass
        try:
            if browser._process:
                browser._process.terminate()
        except Exception:
            pass

    async def cleanup_idle(self):
        """Remove sessions idle for too long."""
        now = time.time()
        to_remove = []
        for domain, session in self.sessions.items():
            if now - session["last_used"] > IDLE_TIMEOUT:
                to_remove.append(domain)

        for domain in to_remove:
            print(f"[pool] Cleaning up idle session: {domain}", file=sys.stderr)
            await self._stop_session(self.sessions[domain])
            del self.sessions[domain]

    async def refresh_cookies(self):
        """Re-inject fresh cookies into long-running sessions."""
        now = time.time()
        for domain, session in self.sessions.items():
            if now - session.get("cookies_refreshed", 0) > COOKIE_REFRESH:
                try:
                    from chrome_cookies import extract_cookies as extract_chrome_cookies
                    from base import inject_cookies

                    cookie_result = extract_chrome_cookies([domain], decrypt=True)
                    if cookie_result.get("success"):
                        await inject_cookies(
                            session["browser"],
                            cookie_result["cookies"],
                            domain
                        )
                        session["cookies_refreshed"] = now
                        print(f"[pool] Refreshed cookies for {domain}", file=sys.stderr)
                except Exception as e:
                    print(f"[pool] Cookie refresh failed for {domain}: {e}", file=sys.stderr)

    def status(self) -> dict:
        """Get pool status."""
        sessions = {}
        now = time.time()
        for domain, s in self.sessions.items():
            sessions[domain] = {
                "idle_seconds": round(now - s["last_used"]),
                "age_seconds": round(now - s["created"]),
            }
        return {
            "running": True,
            "sessions": sessions,
            "session_count": len(self.sessions),
        }

    async def shutdown(self):
        """Stop all sessions."""
        self._running = False
        for domain, session in list(self.sessions.items()):
            await self._stop_session(session)
        self.sessions.clear()


async def handle_client(reader, writer, pool):
    """Handle a client connection."""
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=5)
        if not data:
            return

        request = json.loads(data.decode().strip())
        action = request.get("action")

        if action == "acquire":
            response = await pool.acquire(request["domain"])
        elif action == "release":
            response = await pool.release(request["domain"])
        elif action == "status":
            response = pool.status()
        elif action == "shutdown":
            response = {"success": True, "message": "Shutting down"}
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
            writer.close()
            await pool.shutdown()
            return
        else:
            response = {"success": False, "error": f"Unknown action: {action}"}

        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
    except Exception as e:
        try:
            writer.write(json.dumps({"success": False, "error": str(e)}).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def maintenance_loop(pool):
    """Periodic maintenance: cleanup idle sessions, refresh cookies."""
    while pool._running:
        await asyncio.sleep(30)
        await pool.cleanup_idle()
        await pool.refresh_cookies()


async def run_daemon():
    """Run the session pool daemon."""
    pool = SessionPool()

    # Clean up stale socket
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, pool),
        path=str(SOCKET_PATH)
    )

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Handle signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(pool.shutdown()))

    print(f"[pool] Session pool daemon started (PID {os.getpid()})", file=sys.stderr)
    print(f"[pool] Socket: {SOCKET_PATH}", file=sys.stderr)

    # Start maintenance
    maintenance = asyncio.create_task(maintenance_loop(pool))

    try:
        async with server:
            while pool._running:
                await asyncio.sleep(1)
    finally:
        maintenance.cancel()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        if PID_FILE.exists():
            PID_FILE.unlink()
        print("[pool] Daemon stopped", file=sys.stderr)


def send_command(action: str, **kwargs) -> dict:
    """Send a command to the running daemon."""
    import socket as sock

    if not SOCKET_PATH.exists():
        return {"success": False, "error": "Daemon not running (no socket)"}

    try:
        s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
        s.connect(str(SOCKET_PATH))
        request = json.dumps({"action": action, **kwargs})
        s.sendall(request.encode() + b"\n")

        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\n" in response:
                break
        s.close()
        return json.loads(response.decode().strip())
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_start() -> dict:
    """Start the daemon. Returns dict (caller handles JSON output)."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            return {"success": False, "error": f"Already running (PID {pid})"}
        except ProcessLookupError:
            PID_FILE.unlink()

    # Fork to background
    pid = os.fork()
    if pid > 0:
        # Parent — wait briefly to confirm startup
        time.sleep(1)
        if PID_FILE.exists():
            return {"success": True, "pid": int(PID_FILE.read_text().strip())}
        else:
            return {"success": False, "error": "Daemon failed to start"}

    # Child — become daemon
    os.setsid()
    sys.stdin = open(os.devnull, 'r')
    sys.stdout = open(os.devnull, 'w')
    # Keep stderr for logging
    asyncio.run(run_daemon())


def cmd_stop():
    """Stop the daemon."""
    result = send_command("shutdown")
    if not result.get("success") and PID_FILE.exists():
        # Force kill
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            result = {"success": True, "message": f"Sent SIGTERM to PID {pid}"}
        except Exception as e:
            result = {"success": False, "error": str(e)}
        finally:
            if PID_FILE.exists():
                PID_FILE.unlink()
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()
    print(json.dumps(result))


def cmd_status():
    """Check daemon status. Returns dict (caller handles JSON output)."""
    if not PID_FILE.exists():
        return {"success": True, "running": False}
    result = send_command("status")
    result["success"] = True
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: session_pool.py {start|stop|status}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "start":
        result = cmd_start()
        if result:  # None in child (daemon) process
            print(json.dumps(result, indent=2))
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "status":
        result = cmd_status()
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
