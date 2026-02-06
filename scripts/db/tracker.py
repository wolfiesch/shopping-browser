"""
PriceTracker — SQLite-backed price tracking with alert generation.
"""

import re
from datetime import datetime

from .models import get_connection


def _parse_price(price_str: str | None) -> float | None:
    """Extract numeric price from string like '$209.99'."""
    if not price_str:
        return None
    match = re.search(r'[\d,]+\.?\d*', price_str.replace(',', ''))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


class PriceTracker:
    def __init__(self):
        self.conn = get_connection()

    def track(self, site: str, product_id: str, title: str = None, url: str = None) -> dict:
        """Start tracking a product. Idempotent — reactivates if already tracked."""
        cursor = self.conn.execute(
            "SELECT id, active FROM products WHERE site = ? AND product_id = ?",
            (site, product_id)
        )
        row = cursor.fetchone()

        if row:
            if not row["active"]:
                self.conn.execute(
                    "UPDATE products SET active = 1 WHERE id = ?", (row["id"],)
                )
                self.conn.commit()
            return {"success": True, "product_db_id": row["id"], "action": "reactivated" if not row["active"] else "already_tracking"}

        self.conn.execute(
            "INSERT INTO products (site, product_id, title, url) VALUES (?, ?, ?, ?)",
            (site, product_id, title, url)
        )
        self.conn.commit()
        db_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"success": True, "product_db_id": db_id, "action": "started"}

    def untrack(self, site: str, product_id: str) -> dict:
        """Stop tracking (preserves history)."""
        self.conn.execute(
            "UPDATE products SET active = 0 WHERE site = ? AND product_id = ?",
            (site, product_id)
        )
        self.conn.commit()
        return {"success": True, "action": "untracked"}

    def record_price(self, site: str, product_id: str, data: dict) -> dict:
        """Record a price observation and check for alerts."""
        cursor = self.conn.execute(
            "SELECT id, title, alert_threshold FROM products WHERE site = ? AND product_id = ?",
            (site, product_id)
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Product not tracked"}

        db_id = row["id"]
        threshold = row["alert_threshold"]

        # Update title if we have one now
        if data.get("title") and not row["title"]:
            self.conn.execute(
                "UPDATE products SET title = ? WHERE id = ?",
                (data["title"], db_id)
            )

        price_val = _parse_price(data.get("price"))
        list_price_val = _parse_price(data.get("list_price"))

        self.conn.execute(
            """INSERT INTO price_history
               (product_id, price, list_price, discount_pct, in_stock,
                seller, shipping, deal_badge, coupon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                db_id, price_val, list_price_val,
                data.get("discount_pct"),
                1 if data.get("in_stock") else 0,
                data.get("seller"), data.get("shipping"),
                data.get("deal_badge"), data.get("coupon"),
            )
        )
        self.conn.commit()

        # Check for alerts
        alerts = self._check_alerts(db_id, data, price_val, threshold)
        return {"success": True, "price": price_val, "alerts": alerts}

    def _check_alerts(self, db_id: int, data: dict, current_price: float | None, threshold: float) -> list:
        """Check for alert conditions against previous observations."""
        alerts = []

        # Get previous observation
        prev = self.conn.execute(
            """SELECT price, in_stock, deal_badge FROM price_history
               WHERE product_id = ? ORDER BY recorded_at DESC LIMIT 1 OFFSET 1""",
            (db_id,)
        ).fetchone()

        if not prev:
            return alerts

        # Price drop alert
        if current_price and prev["price"] and current_price < prev["price"]:
            drop_pct = ((prev["price"] - current_price) / prev["price"]) * 100
            if drop_pct >= threshold:
                alert = {
                    "type": "price_drop",
                    "message": f"Price dropped {drop_pct:.1f}%: ${prev['price']:.2f} → ${current_price:.2f}",
                    "old_value": str(prev["price"]),
                    "new_value": str(current_price),
                }
                self.conn.execute(
                    "INSERT INTO alerts (product_id, alert_type, message, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                    (db_id, alert["type"], alert["message"], alert["old_value"], alert["new_value"])
                )
                alerts.append(alert)

        # Back in stock
        if data.get("in_stock") and not prev["in_stock"]:
            alert = {
                "type": "back_in_stock",
                "message": "Product is back in stock!",
                "old_value": "out_of_stock",
                "new_value": "in_stock",
            }
            self.conn.execute(
                "INSERT INTO alerts (product_id, alert_type, message, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                (db_id, alert["type"], alert["message"], alert["old_value"], alert["new_value"])
            )
            alerts.append(alert)

        # Deal alert
        if data.get("deal_badge") and not prev["deal_badge"]:
            alert = {
                "type": "deal",
                "message": f"New deal: {data['deal_badge']}",
                "old_value": None,
                "new_value": data["deal_badge"],
            }
            self.conn.execute(
                "INSERT INTO alerts (product_id, alert_type, message, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                (db_id, alert["type"], alert["message"], alert["old_value"], alert["new_value"])
            )
            alerts.append(alert)

        if alerts:
            self.conn.commit()
        return alerts

    def get_history(self, site: str, product_id: str, days: int = 30) -> dict:
        """Get price history with summary stats."""
        cursor = self.conn.execute(
            "SELECT id, title FROM products WHERE site = ? AND product_id = ?",
            (site, product_id)
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Product not tracked"}

        db_id = row["id"]
        entries = self.conn.execute(
            """SELECT price, list_price, discount_pct, in_stock, seller,
                      shipping, deal_badge, coupon, recorded_at
               FROM price_history
               WHERE product_id = ?
                 AND recorded_at >= datetime('now', ?)
               ORDER BY recorded_at DESC""",
            (db_id, f"-{days} days")
        ).fetchall()

        history = [dict(e) for e in entries]
        prices = [e["price"] for e in entries if e["price"] is not None]

        summary = {}
        if prices:
            summary = {
                "min": min(prices),
                "max": max(prices),
                "avg": round(sum(prices) / len(prices), 2),
                "current": prices[0] if prices else None,
                "observations": len(entries),
            }

        return {
            "success": True,
            "site": site,
            "product_id": product_id,
            "title": row["title"],
            "summary": summary,
            "history": history,
        }

    def get_alerts(self, unack_only: bool = True) -> dict:
        """Get pending alerts."""
        if unack_only:
            rows = self.conn.execute(
                """SELECT a.*, p.site, p.product_id, p.title
                   FROM alerts a JOIN products p ON a.product_id = p.id
                   WHERE a.acknowledged = 0
                   ORDER BY a.created_at DESC"""
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT a.*, p.site, p.product_id, p.title
                   FROM alerts a JOIN products p ON a.product_id = p.id
                   ORDER BY a.created_at DESC LIMIT 50"""
            ).fetchall()

        return {
            "success": True,
            "alerts": [dict(r) for r in rows],
            "count": len(rows),
        }

    def acknowledge_alerts(self) -> dict:
        """Mark all alerts as acknowledged."""
        self.conn.execute("UPDATE alerts SET acknowledged = 1 WHERE acknowledged = 0")
        self.conn.commit()
        return {"success": True}

    def get_tracked_products(self) -> list:
        """Get all actively tracked products."""
        rows = self.conn.execute(
            "SELECT site, product_id, title, url FROM products WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    async def check_all(self, adapter_factory) -> dict:
        """Refresh prices for all tracked products.

        Args:
            adapter_factory: Callable(site) -> ShopperBase instance
        """
        products = self.get_tracked_products()
        results = []

        for p in products:
            try:
                adapter = adapter_factory(p["site"])
                data = await adapter.check_price(p["product_id"])
                if data.get("success"):
                    record = self.record_price(p["site"], p["product_id"], data)
                    results.append({
                        "site": p["site"],
                        "product_id": p["product_id"],
                        "title": data.get("title", p.get("title")),
                        "price": data.get("price"),
                        "alerts": record.get("alerts", []),
                    })
                else:
                    results.append({
                        "site": p["site"],
                        "product_id": p["product_id"],
                        "error": data.get("error"),
                    })
            except Exception as e:
                results.append({
                    "site": p["site"],
                    "product_id": p["product_id"],
                    "error": str(e),
                })

        return {
            "success": True,
            "checked": len(results),
            "results": results,
        }

    def close(self):
        self.conn.close()
