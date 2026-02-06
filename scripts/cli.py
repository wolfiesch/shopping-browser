"""
Unified CLI for shopping-browser — routes commands to the right adapter.

Usage:
    python cli.py amazon search "RTX 5090" --limit 5
    python cli.py amazon check-price B0DN1492LG
    python cli.py amazon product B0DN1492LG --screenshot /tmp/p.png
    python cli.py amazon add-to-cart B09B8DQ26F
    python cli.py amazon cart
    python cli.py amazon my-orders --limit 5
    python cli.py track amazon B0DN1492LG
    python cli.py untrack amazon B0DN1492LG
    python cli.py history amazon B0DN1492LG
    python cli.py alerts
    python cli.py check-all
    python cli.py pool start|stop|status
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure scripts dir is on path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))


def get_adapter(site: str):
    """Get an adapter instance for a site."""
    from adapters import get_adapter as _get
    cls = _get(site)
    return cls()


def adapter_factory(site: str):
    """Factory function for PriceTracker.check_all()."""
    return get_adapter(site)


def main():
    parser = argparse.ArgumentParser(
        description="Shopping Browser — Multi-site shopping CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python cli.py amazon search "RTX 5090" --limit 5
  python cli.py amazon check-price B0DN1492LG
  python cli.py track amazon B0DN1492LG
  python cli.py alerts
  python cli.py pool status"""
    )

    sub = parser.add_subparsers(dest="command")

    # ── Site commands (amazon, newegg, etc.) ──────────────────────────────
    # These are handled dynamically based on available adapters
    from adapters import list_sites
    for site in list_sites():
        site_parser = sub.add_parser(site, help=f"{site.title()} commands")
        site_sub = site_parser.add_subparsers(dest="action")

        # search
        p = site_sub.add_parser("search", help="Search products")
        p.add_argument("query", help="Search query")
        p.add_argument("--limit", "-n", type=int, default=5)
        p.add_argument("--screenshot", "-s")

        # check-price
        p = site_sub.add_parser("check-price", help="Get price/availability")
        p.add_argument("product_id", help="Product ID (ASIN, Item#, etc.)")
        p.add_argument("--screenshot", "-s")

        # product
        p = site_sub.add_parser("product", help="Full product details")
        p.add_argument("product_id", help="Product ID")
        p.add_argument("--screenshot", "-s")

        # add-to-cart
        p = site_sub.add_parser("add-to-cart", help="Add to cart")
        p.add_argument("product_id", help="Product ID")
        p.add_argument("--screenshot", "-s")

        # cart
        p = site_sub.add_parser("cart", help="View cart")
        p.add_argument("--screenshot", "-s")

        # my-orders
        p = site_sub.add_parser("my-orders", help="List orders")
        p.add_argument("--limit", "-n", type=int, default=10)
        p.add_argument("--screenshot", "-s")

    # ── Tracking commands ─────────────────────────────────────────────────

    p = sub.add_parser("track", help="Start tracking a product")
    p.add_argument("site", help="Site (amazon, newegg, etc.)")
    p.add_argument("product_id", help="Product ID")

    p = sub.add_parser("untrack", help="Stop tracking a product")
    p.add_argument("site", help="Site")
    p.add_argument("product_id", help="Product ID")

    p = sub.add_parser("history", help="View price history")
    p.add_argument("site", help="Site")
    p.add_argument("product_id", help="Product ID")
    p.add_argument("--days", "-d", type=int, default=30)

    p = sub.add_parser("alerts", help="View pending alerts")
    p.add_argument("--all", action="store_true", help="Include acknowledged")

    sub.add_parser("check-all", help="Refresh all tracked products")
    sub.add_parser("ack-alerts", help="Acknowledge all alerts")

    # ── Pool commands ─────────────────────────────────────────────────────

    p = sub.add_parser("pool", help="Session pool management")
    p.add_argument("pool_action", choices=["start", "stop", "status"])

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    result = dispatch(args)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("success") else 1)


def dispatch(args) -> dict:
    """Route command to the appropriate handler."""
    cmd = args.command

    # Pool commands
    if cmd == "pool":
        from session_pool import cmd_start, cmd_stop, cmd_status
        if args.pool_action == "start":
            return cmd_start() or {"success": True}  # None in daemon child
        elif args.pool_action == "stop":
            cmd_stop()
            return {"success": True}
        elif args.pool_action == "status":
            return cmd_status()

    # Tracking commands
    if cmd == "track":
        return _cmd_track(args)
    if cmd == "untrack":
        return _cmd_untrack(args)
    if cmd == "history":
        return _cmd_history(args)
    if cmd == "alerts":
        return _cmd_alerts(args)
    if cmd == "check-all":
        return asyncio.run(_cmd_check_all())
    if cmd == "ack-alerts":
        return _cmd_ack_alerts()

    # Site commands
    return asyncio.run(_dispatch_site(args))


async def _dispatch_site(args) -> dict:
    """Dispatch a site-specific command."""
    site = args.command
    action = getattr(args, "action", None)
    if not action:
        return {"success": False, "error": f"No action specified for {site}"}

    adapter = get_adapter(site)
    screenshot = getattr(args, "screenshot", None)

    if action == "search":
        return await adapter.search(args.query, args.limit, screenshot)
    elif action == "check-price":
        return await adapter.check_price(args.product_id, screenshot)
    elif action == "product":
        return await adapter.product_details(args.product_id, screenshot)
    elif action == "add-to-cart":
        return await adapter.add_to_cart(args.product_id, screenshot)
    elif action == "cart":
        return await adapter.view_cart(screenshot)
    elif action == "my-orders":
        return await adapter.my_orders(args.limit, screenshot)
    else:
        return {"success": False, "error": f"Unknown action: {action}"}


def _cmd_track(args) -> dict:
    """Start tracking a product — fetches current price first."""
    from db.tracker import PriceTracker

    # First, get current data
    adapter = get_adapter(args.site)
    data = asyncio.run(adapter.check_price(args.product_id))

    tracker = PriceTracker()
    try:
        result = tracker.track(
            args.site, args.product_id,
            title=data.get("title"),
            url=data.get("url"),
        )

        # Record initial price
        if data.get("success"):
            tracker.record_price(args.site, args.product_id, data)
            result["initial_price"] = data.get("price")
            result["title"] = data.get("title")

        return result
    finally:
        tracker.close()


def _cmd_untrack(args) -> dict:
    from db.tracker import PriceTracker
    tracker = PriceTracker()
    try:
        return tracker.untrack(args.site, args.product_id)
    finally:
        tracker.close()


def _cmd_history(args) -> dict:
    from db.tracker import PriceTracker
    tracker = PriceTracker()
    try:
        return tracker.get_history(args.site, args.product_id, args.days)
    finally:
        tracker.close()


def _cmd_alerts(args) -> dict:
    from db.tracker import PriceTracker
    tracker = PriceTracker()
    try:
        return tracker.get_alerts(unack_only=not getattr(args, "all", False))
    finally:
        tracker.close()


def _cmd_ack_alerts() -> dict:
    from db.tracker import PriceTracker
    tracker = PriceTracker()
    try:
        return tracker.acknowledge_alerts()
    finally:
        tracker.close()


async def _cmd_check_all() -> dict:
    from db.tracker import PriceTracker
    tracker = PriceTracker()
    try:
        return await tracker.check_all(adapter_factory)
    finally:
        tracker.close()


if __name__ == "__main__":
    main()
