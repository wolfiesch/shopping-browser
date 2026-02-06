"""
NeweggShopper — Newegg.com adapter for ShopperBase.

Proof-of-concept implementing search and check-price to validate
the adapter pattern generalizes beyond Amazon.
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
