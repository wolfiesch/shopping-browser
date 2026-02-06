# Shopping Browser

[![CI](https://github.com/wolfiesch/shopping-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/wolfiesch/shopping-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Multi-site shopping automation with authenticated browsing, price tracking, and session pooling. Uses Chrome's own cookies via CDP injection to interact with shopping sites as you — no API keys needed.

Currently supports **Amazon** and **Newegg**, with an adapter architecture for adding more sites.

## How It Works

Shopping Browser launches a stealth Chrome instance, injects your real Chrome cookies via the Chrome DevTools Protocol, and navigates shopping sites using JavaScript evaluation. The session pool keeps browsers warm between commands for fast response times.

```
┌─────────────────────────────────────┐
│         CLI  (run.py → cli.py)      │
└──────────┬──────────┬───────────────┘
           │          │
  Site commands    Tracking commands
           │          │
  ┌────────▼────┐  ┌──▼──────────────┐
  │  Adapters   │  │  PriceTracker   │
  │  Amazon     │  │  (SQLite + WAL) │
  │  Newegg     │  └─────────────────┘
  └──────┬──────┘
         │
  ┌──────▼──────────────────┐
  │  ShopperBase            │
  │  Cookie inject + CDP    │
  │  Pool-aware browsing    │
  └──────┬──────────────────┘
         │
  ┌──────▼──────────────────┐
  │  Session Pool (daemon)  │
  │  Unix socket, per-domain│
  │  Health checks + refresh│
  └──────┬──────────────────┘
         │
  ┌──────▼──────────────────┐
  │  Chrome via nodriver    │
  │  CDP protocol           │
  └─────────────────────────┘
```

## Prerequisites

1. **stealth-browser skill** — Shopping Browser shares its virtual environment:
   ```bash
   cd ~/.claude/skills/stealth-browser
   python3 scripts/setup_environment.py
   ```

2. **Chrome** — Logged into the target sites (Amazon, Newegg, etc.). Cookies are extracted directly from your Chrome profile.

## Quick Start

```bash
cd ~/.claude/skills/shopping-browser

# Start the session pool (optional, but ~2x faster)
python scripts/run.py pool start

# Search for a product
python scripts/run.py amazon search "RTX 5090" --limit 5

# Check a specific product's price
python scripts/run.py amazon check-price B0DN1492LG

# Start tracking a product for price alerts
python scripts/run.py track amazon B0DN1492LG

# Stop the pool when done
python scripts/run.py pool stop
```

> **Important**: Always use `python scripts/run.py`, never `python scripts/cli.py` directly. The runner script activates the correct virtual environment.

## CLI Reference

### Site Commands

Available for each supported site (`amazon`, `newegg`).

#### search

Search for products by keyword.

```bash
python scripts/run.py amazon search "mechanical keyboard" --limit 3
python scripts/run.py newegg search "DDR5 RAM" --limit 10
```

Returns: `results[]` with title, price, list_price, rating, reviews, prime/shipping, deal_badge, url.

#### check-price

Get current pricing and availability for a product.

```bash
python scripts/run.py amazon check-price B0DN1492LG
python scripts/run.py newegg check-price N82E16835181195
```

Returns: title, price, list_price, discount_pct, availability, in_stock, seller, shipping, deal_badge, coupon, rating, reviews.

#### product

Full product details (extends check-price with features, brand, images).

```bash
python scripts/run.py amazon product B0DN1492LG --screenshot /tmp/debug.png
```

The `--screenshot` flag saves a page capture for debugging selector issues.

#### add-to-cart

Add a product to your cart.

```bash
python scripts/run.py amazon add-to-cart B09B8DQ26F
python scripts/run.py newegg add-to-cart N82E16835181195
```

Returns: success status, product info, updated cart count.

#### cart

View current cart contents.

```bash
python scripts/run.py amazon cart
python scripts/run.py newegg cart
```

Returns: items with title/price/quantity, subtotal.

#### my-orders

View recent order history.

```bash
python scripts/run.py amazon my-orders --limit 5
python scripts/run.py newegg my-orders --limit 10
```

Returns: order IDs, product links, dates.

### Price Tracking Commands

#### track / untrack

Start or stop tracking a product. Tracking is idempotent — re-tracking a product reactivates it. Untracking is a soft delete that preserves history.

```bash
python scripts/run.py track amazon B0DN1492LG
python scripts/run.py untrack amazon B0DN1492LG
```

#### history

View price history for a tracked product.

```bash
python scripts/run.py history amazon B0DN1492LG --days 30
```

Returns min/max/avg summary plus full observation timeline.

#### alerts / ack-alerts

View and acknowledge price alerts.

```bash
python scripts/run.py alerts           # Pending alerts only
python scripts/run.py alerts --all     # Include acknowledged
python scripts/run.py ack-alerts       # Mark all as read
```

#### check-all

Refresh prices for all tracked products. Designed to be cronnable.

```bash
python scripts/run.py check-all
```

Visits each tracked product, records the price, and generates alerts for significant changes.

### Session Pool Commands

```bash
python scripts/run.py pool start     # Start daemon (backgrounds itself)
python scripts/run.py pool stop      # Graceful shutdown
python scripts/run.py pool status    # Show active sessions and stats
```

## Session Pool

The session pool is an optional background daemon that keeps browser sessions alive between CLI invocations. Without it, every command cold-starts Chrome, injects cookies, and navigates from scratch (~5-8s). With the pool, subsequent commands reuse an existing authenticated browser (~1-2s).

**How it works:**
- Runs as a forked daemon, communicating over a Unix socket (`data/pool.sock`)
- Maintains one browser per domain (e.g., one for Amazon, one for Newegg)
- Health-checks sessions via CDP before reuse — auto-recreates if Chrome crashed
- Refreshes cookies every 10 minutes to handle auth expiry
- Cleans up idle sessions after 5 minutes

The pool is transparent to adapters — `ShopperBase.ensure_browser()` tries the pool first and falls back to a fresh browser if the pool isn't running.

## Price Tracking

Price tracking uses a local SQLite database (`data/prices.db`) with WAL mode for safe concurrent access.

### Alert Types

| Alert | Trigger | Example |
|-------|---------|---------|
| `price_drop` | Price drops by >= threshold (default 5%) | "$249.99 → $209.99 (16% drop)" |
| `back_in_stock` | Was out of stock, now available | "Back in stock" |
| `deal` | Deal badge appeared | "Deal badge: Limited time deal" |

### Automated Monitoring

Use `check-all` in a cron job to poll all tracked products on a schedule:

```cron
# Check prices every 6 hours
0 */6 * * * cd ~/.claude/skills/shopping-browser && python scripts/run.py check-all 2>/dev/null
```

### Database Schema

Three tables: `products` (tracked items), `price_history` (observations), and `alerts` (generated notifications). Indexes on `(product_id, recorded_at)` for efficient history queries and `(acknowledged, created_at)` for alert retrieval.

## Adding a New Site Adapter

1. Create `scripts/adapters/yoursite.py`:

```python
from base import ShopperBase

class YourSiteShopper(ShopperBase):
    DOMAIN = "yoursite.com"
    DISPLAY_NAME = "YourSite"

    async def search(self, query, limit=5, screenshot=None) -> dict:
        await self.ensure_browser()
        await self.navigate(f"https://www.yoursite.com/search?q={query}")
        results = await self.evaluate("/* JS to extract results */")
        return {"success": True, "query": query, "results": results}

    async def check_price(self, product_id, screenshot=None) -> dict:
        await self.ensure_browser()
        await self.navigate(f"https://www.yoursite.com/product/{product_id}")
        data = await self.evaluate("/* JS to extract price data */")
        return {"success": True, **data}

    async def product_details(self, product_id, screenshot=None) -> dict:
        return await self.check_price(product_id, screenshot)
```

2. Register in `scripts/adapters/__init__.py`:

```python
_LAZY_ADAPTERS = {
    "newegg": ("adapters.newegg", "NeweggShopper"),
    "yoursite": ("adapters.yoursite", "YourSiteShopper"),
}
```

3. The CLI auto-generates subcommands — `python scripts/run.py yoursite search "query"` works immediately.

**Required methods**: `search()`, `check_price()`, `product_details()`
**Optional methods**: `add_to_cart()`, `view_cart()`, `my_orders()` (default: raises "not supported")

## Output Format

All commands emit JSON on stdout and diagnostics on stderr. Exit code `0` means success, `1` means failure.

```json
{
  "success": true,
  "asin": "B0DN1492LG",
  "title": "NVIDIA GeForce RTX 5090...",
  "price": "$209.99",
  "list_price": "$249.99",
  "discount_pct": "-16%",
  "in_stock": true,
  "prime": true,
  "seller": "Amazon.com",
  "shipping": "FREE delivery Thursday",
  "deal_badge": null,
  "coupon": null,
  "rating": "4.8 out of 5 stars",
  "reviews": "(553)",
  "url": "https://www.amazon.com/dp/B0DN1492LG"
}
```

**Stability guarantee**: All documented fields are always present in responses. Fields are `null` when unavailable, never omitted. This makes output safe for piping into `jq` or consuming from automation scripts.

## Data Storage

| Path | Purpose |
|------|---------|
| `data/prices.db` | SQLite price tracking database (WAL mode) |
| `data/screenshots/` | Debug screenshots (created on demand) |
| `data/pool.sock` | Session pool Unix socket (runtime only) |
| `data/pool.pid` | Session pool PID file (runtime only) |

The `data/` directory is gitignored.

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|---------|
| "Cookie extraction failed" | Not logged into the site in Chrome | Log in via Chrome first |
| "stealth-browser venv not found" | Shared dependency not set up | Run `stealth-browser/scripts/setup_environment.py` |
| Pool daemon won't start | Stale PID file from a crash | Delete `data/pool.pid` and retry |
| Null titles in search results | Page selectors didn't match | Use `--screenshot` to inspect what loaded |
| Missing price fields | Product page didn't fully load | Try again — or increase wait time in `navigate()` |
| Pool health check fails | Chrome process crashed | Pool auto-recreates the session on next acquire |
