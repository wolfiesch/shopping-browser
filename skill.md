Base directory for this skill: /Users/wolfgangschoenberger/.claude/skills/shopping-browser

# Shopping Browser Skill

Multi-site shopping automation with price tracking, session pooling, and enriched data extraction. Currently supports Amazon and Newegg, with an adapter architecture for adding more sites.

## When to Use This Skill

Trigger when user needs:
- Product price checking on Amazon or Newegg
- Shopping searches across supported sites
- Price tracking and alerts for products
- Adding to cart, viewing cart, or viewing orders on Amazon or Newegg
- Any authenticated shopping site access

**Prerequisite**: Must be logged into the target site in Chrome.

## Critical: Always Use run.py Wrapper

**NEVER call cli.py directly. ALWAYS use `python scripts/run.py`:**

```bash
# CORRECT:
python scripts/run.py amazon search "RTX 5090"

# WRONG:
python scripts/cli.py amazon search "RTX 5090"  # Missing venv!
```

## Commands

### Site Commands (amazon, newegg)

#### Search
```bash
python scripts/run.py amazon search "RTX 5090" --limit 5
python scripts/run.py newegg search "mechanical keyboard" --limit 3
```
Returns: results[] with title, price, list_price, rating, reviews, prime/deal_badge

#### Check Price
```bash
python scripts/run.py amazon check-price B0DN1492LG
python scripts/run.py newegg check-price N82E16835181195
```
Returns: title, price, list_price, discount_pct, availability, in_stock, seller, shipping, deal_badge, coupon, rating, reviews

#### Full Product Details
```bash
python scripts/run.py amazon product B0DN1492LG --screenshot /tmp/p.png
```
Returns: All check-price fields + brand, features, image_count

#### Add to Cart
```bash
python scripts/run.py amazon add-to-cart B09B8DQ26F
python scripts/run.py newegg add-to-cart 0RN-005A-00SR1
```

#### View Cart
```bash
python scripts/run.py amazon cart
python scripts/run.py newegg cart
```

#### My Orders
```bash
python scripts/run.py amazon my-orders --limit 5
python scripts/run.py newegg my-orders --limit 5
```
Note: Newegg orders require an active `secure.newegg.com` session in Chrome.

### Price Tracking

#### Track a Product
```bash
python scripts/run.py track amazon B0DN1492LG
```
Fetches current price, starts tracking. Idempotent.

#### Stop Tracking
```bash
python scripts/run.py untrack amazon B0DN1492LG
```

#### View Price History
```bash
python scripts/run.py history amazon B0DN1492LG --days 30
```
Returns: min/max/avg summary + full observation history

#### View Alerts
```bash
python scripts/run.py alerts
python scripts/run.py alerts --all          # Include acknowledged
python scripts/run.py ack-alerts            # Acknowledge all
```
Alert types: price_drop, back_in_stock, deal

#### Refresh All Tracked
```bash
python scripts/run.py check-all
```
Cronnable — checks all tracked products and generates alerts.

### Session Pool

```bash
python scripts/run.py pool start    # Start daemon (backgrounds)
python scripts/run.py pool stop     # Stop daemon
python scripts/run.py pool status   # Show active sessions
```

With pool running, commands reuse browser sessions (~1-2s vs ~5s cold start).

## Output Format

All commands return JSON on stdout, diagnostics on stderr. Exit code 0 = success, 1 = failure.

```json
{
  "success": true,
  "asin": "B0DN1492LG",
  "title": "Product Name...",
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
  "reviews": "(553)"
}
```

## Machine Interface (Codex Compatibility)

All fields are always present (null if not available, never omitted). JSON schemas:

### check-price / product response
```
success: boolean
asin|item_number: string|null
title: string|null
price: string|null         # "$209.99"
list_price: string|null    # "$249.99"
discount_pct: string|null  # "-16%"
availability: string|null
in_stock: boolean
prime: boolean
seller: string|null
shipping: string|null
deal_badge: string|null
coupon: string|null
rating: string|null
reviews: string|null
url: string|null
```

### search response
```
success: boolean
query: string
result_count: integer
results: array of {asin|item_number, title, price, list_price, rating, reviews, prime|shipping, deal_badge, url}
```

### track response
```
success: boolean
product_db_id: integer
action: "started"|"reactivated"|"already_tracking"
initial_price: string|null
title: string|null
```

### history response
```
success: boolean
site: string
product_id: string
title: string|null
summary: {min, max, avg, current, observations}
history: array of {price, list_price, discount_pct, in_stock, seller, shipping, deal_badge, coupon, recorded_at}
```

### alerts response
```
success: boolean
count: integer
alerts: array of {alert_type, message, old_value, new_value, created_at, site, product_id, title}
```

## Architecture

```
                    ┌─────────────────────────────┐
                    │     cli.py (Unified CLI)     │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼──────┐  ┌─────▼──────┐  ┌──────▼────────┐
     │ AmazonShopper │  │NeweggShopper│  │  PriceTracker │
     │  (adapter)    │  │  (adapter)  │  │   (db/tracker) │
     └───────┬───────┘  └──────┬─────┘  └──────┬────────┘
             │                 │                │
     ┌───────▼─────────────────▼────┐   ┌──────▼────────┐
     │     ShopperBase (base.py)    │   │ SQLite (WAL)  │
     │  browser mgmt, cookies, CDP  │   │  prices.db    │
     └───────┬──────────────────────┘   └───────────────┘
             │
     ┌───────▼──────────────┐
     │   Session Pool       │
     │  (Unix socket daemon)│
     └───────┬──────────────┘
             │
     ┌───────▼──────────────┐
     │  Chrome (nodriver)   │
     │  + CDP cookie inject │
     └─────────────────────┘
```

Shares virtual environment with stealth-browser skill (nodriver, pycryptodome).

## Adding a New Site Adapter

1. Create `scripts/adapters/newsite.py` extending `ShopperBase`
2. Set `DOMAIN` and `DISPLAY_NAME`
3. Implement `search()`, `check_price()`, `product_details()`
4. Register in `scripts/adapters/__init__.py`

## Data Storage

- `data/prices.db` — SQLite price tracking database
- `data/screenshots/` — Saved screenshots
- `data/pool.sock` — Session pool Unix socket (runtime)
- `data/pool.pid` — Session pool PID file (runtime)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cookie extraction failed" | Log into the site in Chrome first |
| "stealth-browser venv not found" | Run stealth-browser setup first |
| Pool daemon won't start | Check `data/pool.pid` for stale PID |
| Null titles in search | Fixed — uses cascading selector chain |
| Missing price fields | Check if product page loaded (try with --screenshot) |
| Newegg "requires re-authentication" | Newegg orders need a fresh `secure.newegg.com` session — log in via Chrome |
