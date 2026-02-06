"""
NeweggShopper — Newegg.com adapter for ShopperBase.

Full implementation: search, check-price, product details,
add-to-cart, cart, and order history.
"""

import urllib.parse
from pathlib import Path

from base import ShopperBase


class NeweggShopper(ShopperBase):
    DOMAIN = "newegg.com"
    DISPLAY_NAME = "Newegg"

    async def search(self, query: str, limit: int = 5, screenshot: str = None) -> dict:
        """Search Newegg products."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.newegg.com/p/pl?d={encoded}"
            await self.navigate(url, wait=4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            safe_query = query.replace("'", "\\'")
            data = await self.evaluate(f"""
                (() => {{
                    const limit = {limit};
                    const results = [];
                    const cards = document.querySelectorAll('.item-cell, .item-container');
                    for (const card of cards) {{
                        if (results.length >= limit) break;

                        const titleEl = card.querySelector('.item-title');
                        const title = titleEl ? titleEl.textContent.trim() : null;
                        if (!title) continue;

                        const href = titleEl?.href || titleEl?.closest('a')?.href || null;

                        // Extract item number from URL (includes dashes like 3D5-006G-00047)
                        let itemNumber = null;
                        if (href) {{
                            const match = href.match(/\\/p\\/([\\w-]+)/);
                            itemNumber = match ? match[1] : null;
                        }}

                        const priceEl = card.querySelector('.price-current');
                        let price = null;
                        if (priceEl) {{
                            const dollars = priceEl.querySelector('strong');
                            const cents = priceEl.querySelector('sup');
                            if (dollars) {{
                                price = '$' + dollars.textContent.trim() +
                                        (cents ? cents.textContent.trim() : '');
                            }}
                        }}

                        const ratingEl = card.querySelector('.item-rating i');
                        const rating = ratingEl ? ratingEl.getAttribute('aria-label') : null;

                        const reviewsEl = card.querySelector('.item-rating-num');
                        const reviews = reviewsEl ? reviewsEl.textContent.trim() : null;

                        const shippingEl = card.querySelector('.price-ship');
                        const shipping = shippingEl ? shippingEl.textContent.trim() : null;

                        const dealEl = card.querySelector('.item-flag, .item-promo');
                        const deal_badge = dealEl ? dealEl.textContent.trim() : null;

                        const listPriceEl = card.querySelector('.price-was-data');
                        let list_price = listPriceEl ? listPriceEl.textContent.trim() : null;
                        if (list_price && !list_price.startsWith('$')) list_price = '$' + list_price;

                        results.push({{
                            item_number: itemNumber,
                            title: title,
                            price: price,
                            list_price: list_price,
                            rating: rating,
                            reviews: reviews,
                            shipping: shipping,
                            deal_badge: deal_badge,
                            url: href
                        }});
                    }}

                    return {{
                        query: '{safe_query}',
                        result_count: results.length,
                        results: results
                    }};
                }})()
            """)

            result = {"success": True}
            result.update(data)
            if screenshot:
                result["screenshot"] = screenshot
            return result

        finally:
            await self.close()

    async def check_price(self, product_id: str, screenshot: str = None) -> dict:
        """Get price/availability for a Newegg product."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            url = f"https://www.newegg.com/p/{product_id}"
            await self.navigate(url)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate("""
                (() => {
                    const titleEl = document.querySelector('.product-title');
                    const title = titleEl ? titleEl.textContent.trim() : null;

                    const priceEl = document.querySelector('.price-current');
                    let price = null;
                    if (priceEl) {
                        const dollars = priceEl.querySelector('strong');
                        const cents = priceEl.querySelector('sup');
                        if (dollars) {
                            price = '$' + dollars.textContent.trim() +
                                    (cents ? cents.textContent.trim() : '');
                        }
                    }

                    const listPriceEl = document.querySelector('.price-was-data');
                    let list_price = listPriceEl ? listPriceEl.textContent.trim() : null;
                    if (list_price && !list_price.startsWith('$')) list_price = '$' + list_price;

                    const discountEl = document.querySelector('.price-save-percent');
                    const discount_pct = discountEl ? discountEl.textContent.trim() : null;

                    const addBtn = document.querySelector('.btn-primary[title*="Add to cart"], .btn-primary.btn-wide');
                    const in_stock = !!addBtn;

                    const availEl = document.querySelector('.product-inventory strong');
                    const availability = availEl ? availEl.textContent.trim() : null;

                    const ratingEl = document.querySelector('.product-rating .rating');
                    const rating = ratingEl ? ratingEl.getAttribute('aria-label') : null;

                    const reviewsEl = document.querySelector('.product-review .btn');
                    const reviews = reviewsEl ? reviewsEl.textContent.trim() : null;

                    const sellerEl = document.querySelector('.product-seller strong');
                    const seller = sellerEl ? sellerEl.textContent.trim() : null;

                    const shippingEl = document.querySelector('.product-shipping .product-shipped-by');
                    const shipping = shippingEl ? shippingEl.textContent.trim() : null;

                    return {
                        item_number: window.location.pathname.split('/').pop() || null,
                        title: title,
                        price: price,
                        list_price: list_price,
                        discount_pct: discount_pct,
                        availability: availability,
                        in_stock: in_stock,
                        seller: seller,
                        shipping: shipping,
                        deal_badge: null,
                        coupon: null,
                        rating: rating,
                        reviews: reviews,
                        url: window.location.href
                    };
                })()
            """)

            result = {"success": True}
            result.update(data)
            if screenshot:
                result["screenshot"] = screenshot
            return result

        finally:
            await self.close()

    async def product_details(self, product_id: str, screenshot: str = None) -> dict:
        """Full product details — delegates to check_price for Newegg."""
        return await self.check_price(product_id, screenshot)

    async def add_to_cart(self, product_id: str, screenshot: str = None) -> dict:
        """Add a product to cart by item number."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            url = f"https://www.newegg.com/p/{product_id}"
            await self.navigate(url, wait=4)

            data = await self.evaluate("""
                (() => {
                    const titleEl = document.querySelector('.product-title');
                    const title = titleEl ? titleEl.textContent.trim() : null;

                    // Try multiple button selectors — Newegg changes these
                    const btn = document.querySelector('.product-buy .btn-primary') ||
                                document.querySelector('.product-buy button') ||
                                document.querySelector('.btn-primary[title*="Add to cart"]') ||
                                document.querySelector('.btn-primary.btn-wide');
                    if (!title) return { error: 'Product page not found' };
                    if (!btn) return { error: 'Product not available for purchase' };

                    // Check for out of stock text
                    const buyArea = document.querySelector('.product-buy');
                    if (buyArea && buyArea.textContent.toLowerCase().includes('out of stock')) {
                        return { error: 'Product is out of stock' };
                    }

                    btn.click();
                    return { clicked: true, product: title };
                })()
            """)

            if data.get("error"):
                return {"success": False, "error": data["error"], "item_number": product_id}

            await self.page.sleep(4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            # Get cart count from header
            cart_data = await self.evaluate("""
                (() => {
                    const el = document.querySelector('.header-cart .cart-qty') ||
                               document.querySelector('.nav-cart-number') ||
                               document.querySelector('#cart-qty');
                    return el ? el.textContent.trim() : '0';
                })()
            """)
            count_val = cart_data if isinstance(cart_data, str) else str(cart_data.get("value", "0"))

            result = {
                "success": True,
                "added": True,
                "item_number": product_id,
                "product": data.get("product"),
                "cart_count": count_val,
            }
            if screenshot:
                result["screenshot"] = screenshot
            return result

        finally:
            await self.close()

    async def view_cart(self, screenshot: str = None) -> dict:
        """View current cart contents."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            await self.navigate("https://secure.newegg.com/shop/cart", wait=4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate("""
                (() => {
                    const items = [];
                    const seen = new Set();

                    // Cart item rows — try multiple container selectors
                    const rows = document.querySelectorAll(
                        '.item-container, .items-row, [class*="item-cell"]'
                    );

                    for (const row of rows) {
                        const titleEl = row.querySelector('a.item-title') ||
                                        row.querySelector('.item-title') ||
                                        row.querySelector('a[title]');
                        if (!titleEl) continue;

                        const title = titleEl.textContent.trim();
                        if (!title || title.length < 3) continue;

                        const href = titleEl.href || titleEl.closest('a')?.href || null;
                        let itemNumber = null;
                        if (href) {
                            const match = href.match(/\\/p\\/([\\w-]+)/);
                            itemNumber = match ? match[1] : null;
                        }

                        // Deduplicate — cart page has recommendation/warranty sections
                        // that repeat the same product links
                        const key = itemNumber || title;
                        if (seen.has(key)) continue;
                        seen.add(key);

                        const priceEl = row.querySelector('.price-current') ||
                                        row.querySelector('[class*="price"]');
                        let price = null;
                        if (priceEl) {
                            const dollars = priceEl.querySelector('strong');
                            const cents = priceEl.querySelector('sup');
                            if (dollars) {
                                price = '$' + dollars.textContent.trim() +
                                        (cents ? cents.textContent.trim() : '');
                            } else {
                                const text = priceEl.textContent.trim();
                                if (text.includes('$')) price = text;
                            }
                        }

                        const qtyEl = row.querySelector('select[name*="qty"], input[name*="qty"]') ||
                                      row.querySelector('.item-qty select, .item-qty input');
                        const quantity = qtyEl ? (qtyEl.value || '1') : '1';

                        items.push({
                            title: title,
                            price: price,
                            quantity: quantity,
                            item_number: itemNumber
                        });
                    }

                    // Cart count from page header text e.g. "Shopping Cart (1 Item)"
                    const headerText = document.body.innerText;
                    const countMatch = headerText.match(/Shopping Cart\\s*\\((\\d+)\\s*Item/i);
                    const pageCount = countMatch ? countMatch[1] : String(items.length);

                    // Total/subtotal
                    const totalEl = document.querySelector('.summary-content-total strong') ||
                                    document.querySelector('.summary-content-total') ||
                                    document.querySelector('.summary-content .item-total');
                    let subtotal = null;
                    if (totalEl) {
                        const text = totalEl.textContent.trim();
                        const match = text.match(/\\$[\\d,.]+/);
                        subtotal = match ? match[0] : text;
                    }

                    return {
                        cart_count: pageCount,
                        items: items,
                        subtotal: subtotal,
                        url: window.location.href
                    };
                })()
            """)

            result = {"success": True}
            result.update(data)
            if screenshot:
                result["screenshot"] = screenshot
            return result

        finally:
            await self.close()

    async def my_orders(self, limit: int = 10, screenshot: str = None) -> dict:
        """List recent Newegg orders."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            # Navigate to Newegg homepage, then find order history link
            await self.navigate("https://www.newegg.com", wait=3)
            # Extract the actual order history URL from the account menu
            order_url = await self.evaluate("""
                (() => {
                    // Look for order-related links in account dropdown or page
                    const links = document.querySelectorAll('a[href*="order"], a[href*="Order"]');
                    for (const link of links) {
                        const href = link.href || '';
                        const text = (link.textContent || '').toLowerCase();
                        if (text.includes('order') && href.includes('newegg')) {
                            return href;
                        }
                    }
                    return null;
                })()
            """)
            target = order_url if isinstance(order_url, str) and order_url.startswith('http') \
                else "https://secure.newegg.com/orders/list"
            await self.navigate(target, wait=5)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            # Detect auth redirect — Newegg account pages require fresh login
            landed_url = await self.evaluate("window.location.href")
            if isinstance(landed_url, dict):
                url_str = landed_url.get("value", str(landed_url))
            else:
                url_str = str(landed_url)
            if "signin" in url_str or "identity" in url_str:
                return {
                    "success": False,
                    "error": "Newegg requires re-authentication for order history. "
                             "Log into secure.newegg.com in Chrome, then retry.",
                    "url": url_str
                }

            data = await self.evaluate(f"""
                (() => {{
                    const limit = {limit};
                    const allText = document.body.innerText;

                    // Newegg order numbers are typically numeric
                    const orderIdPattern = /\\b\\d{{9,15}}\\b/g;
                    const candidates = allText.match(orderIdPattern) || [];
                    const orderIds = [...new Set(candidates)].slice(0, limit);

                    // Product links
                    const productLinks = document.querySelectorAll(
                        'a[href*="/p/"], a[href*="/Product/"]'
                    );
                    const products = [];
                    const seen = new Set();
                    for (const link of productLinks) {{
                        const text = link.textContent.trim();
                        if (text && text.length > 5 && text.length < 200 && !seen.has(text)) {{
                            seen.add(text);
                            const itemMatch = link.href.match(/\\/p\\/([\\w-]+)/);
                            products.push({{
                                name: text,
                                item_number: itemMatch ? itemMatch[1] : null,
                                url: link.href
                            }});
                        }}
                        if (products.length >= limit) break;
                    }}

                    // Dates — Newegg uses MM/DD/YYYY format
                    const datePattern = /\\b\\d{{1,2}}\\/\\d{{1,2}}\\/\\d{{4}}\\b/g;
                    const dates = [...new Set(allText.match(datePattern) || [])].slice(0, limit);

                    return {{
                        order_count: orderIds.length,
                        order_ids: orderIds,
                        products: products,
                        dates: dates,
                        url: window.location.href
                    }};
                }})()
            """)

            result = {"success": True}
            result.update(data)
            if screenshot:
                result["screenshot"] = screenshot
            return result

        finally:
            await self.close()
