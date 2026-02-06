"""
AmazonShopper — Amazon.com adapter for ShopperBase.

Migrated from amazon-browser/scripts/amazon.py with unified CDP parsing,
enriched data extraction, and fixed title selectors.
"""

import urllib.parse
from pathlib import Path

from base import ShopperBase

SCREENSHOT_DIR = Path(__file__).parent.parent.parent / "data" / "screenshots"


class AmazonShopper(ShopperBase):
    DOMAIN = "amazon.com"
    DISPLAY_NAME = "Amazon"

    async def search(self, query: str, limit: int = 5, screenshot: str = None) -> dict:
        """Search Amazon products."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.amazon.com/s?k={encoded}"
            await self.navigate(url, wait=4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            safe_query = query.replace("'", "\\'")
            data = await self.evaluate(f"""
                (() => {{
                    const limit = {limit};
                    const results = [];
                    const cards = document.querySelectorAll('[data-component-type="s-search-result"]');
                    for (const card of cards) {{
                        if (results.length >= limit) break;
                        const asin = card.dataset.asin;
                        if (!asin) continue;

                        // Title: Amazon now splits brand (h2) from product name
                        // ([data-cy="title-recipe"] a). Try full title first.
                        const titleRecipeLink = card.querySelector('[data-cy="title-recipe"] a');
                        const h2 = card.querySelector('h2');
                        let title = titleRecipeLink?.textContent?.trim() || null;
                        if (!title && h2) {{
                            const truncFull = h2.querySelector('.a-truncate-full');
                            const textNormal = h2.querySelector('.a-text-normal');
                            title = (truncFull?.textContent?.trim()) ||
                                    (textNormal?.textContent?.trim()) ||
                                    h2.textContent?.trim() || null;
                        }}
                        if (title && title.length < 5) title = null;

                        const linkEl = titleRecipeLink || card.querySelector('h2 a');
                        const href = linkEl ? linkEl.href : null;

                        // Price: prefer .a-offscreen (pre-formatted), fallback to whole+fraction
                        const offscreenPrice = card.querySelector('.a-price .a-offscreen');
                        let price = offscreenPrice ? offscreenPrice.textContent.trim() : null;
                        if (!price) {{
                            const priceWhole = card.querySelector('.a-price .a-price-whole');
                            const priceFrac = card.querySelector('.a-price .a-price-fraction');
                            if (priceWhole) {{
                                price = '$' + priceWhole.textContent.trim() +
                                        (priceFrac ? priceFrac.textContent.trim() : '00');
                            }}
                        }}

                        const ratingEl = card.querySelector('.a-icon-alt');
                        const rating = ratingEl ? ratingEl.textContent.trim() : null;
                        // Reviews: try adjacent span, then aria-label count
                        const reviewsLink = card.querySelector('a[href*="customerReviews"], a[href*="#reviews"]');
                        const reviewsEl = reviewsLink || card.querySelector('[aria-label*="stars"] + span');
                        const reviews = reviewsEl ? reviewsEl.textContent.trim() : null;
                        const primeEl = card.querySelector('[aria-label="Amazon Prime"], .s-prime');
                        const dealEl = card.querySelector('.a-badge-text, .a-badge-label-inner');
                        const listPriceEl = card.querySelector('.a-text-price .a-offscreen');
                        const listPriceText = listPriceEl?.textContent?.trim() || null;

                        results.push({{
                            asin: asin,
                            title: title,
                            price: price,
                            list_price: listPriceText,
                            rating: rating,
                            reviews: reviews,
                            prime: !!primeEl,
                            deal_badge: dealEl ? dealEl.textContent.trim() : null,
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
        """Get price/availability for a product by ASIN."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            url = f"https://www.amazon.com/dp/{product_id}"
            await self.navigate(url, wait=4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate("""
                (() => {
                    const title = document.getElementById('productTitle');

                    // Price: check each selector for actual price text (not just element existence)
                    // because some .a-offscreen elements exist but have empty text
                    let price = null;
                    for (const sel of ['.priceToPay .a-offscreen',
                                       '#corePrice_feature_div .a-offscreen',
                                       '#apex_offerDisplay_desktop .a-offscreen',
                                       '.a-price .a-offscreen']) {
                        const el = document.querySelector(sel);
                        const t = el?.textContent?.trim();
                        if (t && t.match(/\\$[\\d,]+/)) { price = t; break; }
                    }

                    const availEl = document.getElementById('availability');
                    let availability = null;
                    if (availEl) {
                        const lines = availEl.innerText.trim().split('\\n').filter(l => l.trim());
                        availability = lines.join(' ').trim() || null;
                    }

                    const addBtn = document.getElementById('add-to-cart-button');
                    const ratingEl = document.querySelector('#acrPopover .a-icon-alt');
                    const reviewsEl = document.getElementById('acrCustomerReviewText');

                    // Seller: cascade through possible containers
                    const sellerEl = document.querySelector('#merchant-info') ||
                                     document.querySelector('#sellerProfileTriggerId') ||
                                     document.querySelector('#tabular-buybox .tabular-buybox-text[tabular-attribute-name="Sold by"] a') ||
                                     document.querySelector('#buyBoxAccordion [tabular-attribute-name="Sold by"] a');
                    let seller = sellerEl ? sellerEl.textContent.trim() : null;
                    if (seller && seller.length < 2) seller = null;

                    // Shipping: get full delivery text, not just bold portion
                    const deliveryBlock = document.querySelector('#mir-layout-DELIVERY_BLOCK') ||
                                          document.querySelector('#deliveryMessageMirId');
                    let shipping = null;
                    if (deliveryBlock) {
                        const lines = deliveryBlock.innerText.trim().split('\\n').filter(l => l.trim());
                        shipping = lines[0] || null;
                    }

                    const dealEl = document.querySelector('#dealBadge_feature_div .a-badge-text, .a-badge-label-inner');
                    const discountEl = document.querySelector('.savingsPercentage');
                    const _listPriceRaw = document.querySelector('.a-text-price .a-offscreen')?.textContent?.trim();
                    const listPriceEl = (_listPriceRaw && _listPriceRaw.match(/\$[\d,]+/)) ? _listPriceRaw : null;
                    const couponEl = document.querySelector('#couponBadge .a-color-success');
                    const primeEl = document.querySelector('#primeFactsDesktop_feature_div [aria-label="Amazon Prime"], [aria-label="Amazon Prime"]');

                    return {
                        asin: document.querySelector('input[name="ASIN"]')?.value || null,
                        title: title ? title.textContent.trim() : null,
                        price: price,
                        list_price: listPriceEl || null,
                        discount_pct: discountEl ? discountEl.textContent.trim() : null,
                        availability: availability,
                        in_stock: !!addBtn,
                        prime: !!primeEl,
                        seller: seller,
                        shipping: shipping,
                        deal_badge: dealEl ? dealEl.textContent.trim() : null,
                        coupon: couponEl ? couponEl.textContent.trim() : null,
                        rating: ratingEl ? ratingEl.textContent.trim() : null,
                        reviews: reviewsEl ? reviewsEl.textContent.trim() : null,
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
        """Full product details including features, images, etc."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            url = f"https://www.amazon.com/dp/{product_id}"
            await self.navigate(url, wait=4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate("""
                (() => {
                    const title = document.getElementById('productTitle');

                    // Price: check each selector for actual price text (not just element existence)
                    // because some .a-offscreen elements exist but have empty text
                    let price = null;
                    for (const sel of ['.priceToPay .a-offscreen',
                                       '#corePrice_feature_div .a-offscreen',
                                       '#apex_offerDisplay_desktop .a-offscreen',
                                       '.a-price .a-offscreen']) {
                        const el = document.querySelector(sel);
                        const t = el?.textContent?.trim();
                        if (t && t.match(/\\$[\\d,]+/)) { price = t; break; }
                    }

                    const availEl = document.getElementById('availability');
                    let availability = null;
                    if (availEl) {
                        const lines = availEl.innerText.trim().split('\\n').filter(l => l.trim());
                        availability = lines.join(' ').trim() || null;
                    }

                    const features = [];
                    document.querySelectorAll('#feature-bullets li span.a-list-item').forEach(el => {
                        const text = el.textContent.trim();
                        if (text) features.push(text);
                    });

                    const brandEl = document.getElementById('bylineInfo');
                    const brand = brandEl ? brandEl.textContent.trim() : null;

                    const images = [];
                    document.querySelectorAll('#altImages .a-button-thumbnail img').forEach(img => {
                        const src = img.src?.replace(/\\._.*_\\./, '.');
                        if (src) images.push(src);
                    });

                    const addBtn = document.getElementById('add-to-cart-button');
                    const ratingEl = document.querySelector('#acrPopover .a-icon-alt');
                    const reviewsEl = document.getElementById('acrCustomerReviewText');

                    // Seller: cascade through possible containers
                    const sellerEl = document.querySelector('#merchant-info') ||
                                     document.querySelector('#sellerProfileTriggerId') ||
                                     document.querySelector('#tabular-buybox .tabular-buybox-text[tabular-attribute-name="Sold by"] a') ||
                                     document.querySelector('#buyBoxAccordion [tabular-attribute-name="Sold by"] a');
                    let seller = sellerEl ? sellerEl.textContent.trim() : null;
                    if (seller && seller.length < 2) seller = null;

                    // Shipping: get full delivery text, not just bold portion
                    const deliveryBlock = document.querySelector('#mir-layout-DELIVERY_BLOCK') ||
                                          document.querySelector('#deliveryMessageMirId');
                    let shipping = null;
                    if (deliveryBlock) {
                        const lines = deliveryBlock.innerText.trim().split('\\n').filter(l => l.trim());
                        shipping = lines[0] || null;
                    }

                    const dealEl = document.querySelector('#dealBadge_feature_div .a-badge-text, .a-badge-label-inner');
                    const discountEl = document.querySelector('.savingsPercentage');
                    const _listPriceRaw = document.querySelector('.a-text-price .a-offscreen')?.textContent?.trim();
                    const listPriceEl = (_listPriceRaw && _listPriceRaw.match(/\$[\d,]+/)) ? _listPriceRaw : null;
                    const couponEl = document.querySelector('#couponBadge .a-color-success');
                    const primeEl = document.querySelector('#primeFactsDesktop_feature_div [aria-label="Amazon Prime"], [aria-label="Amazon Prime"]');

                    return {
                        asin: document.querySelector('input[name="ASIN"]')?.value || null,
                        title: title ? title.textContent.trim() : null,
                        brand: brand,
                        price: price,
                        list_price: listPriceEl || null,
                        discount_pct: discountEl ? discountEl.textContent.trim() : null,
                        availability: availability,
                        in_stock: !!addBtn,
                        prime: !!primeEl,
                        seller: seller,
                        shipping: shipping,
                        deal_badge: dealEl ? dealEl.textContent.trim() : null,
                        coupon: couponEl ? couponEl.textContent.trim() : null,
                        rating: ratingEl ? ratingEl.textContent.trim() : null,
                        reviews: reviewsEl ? reviewsEl.textContent.trim() : null,
                        features: features,
                        image_count: images.length,
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

    async def add_to_cart(self, product_id: str, screenshot: str = None) -> dict:
        """Add a product to cart by ASIN."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            url = f"https://www.amazon.com/dp/{product_id}"
            await self.navigate(url)

            data = await self.evaluate("""
                (() => {
                    const title = document.getElementById('productTitle');
                    const btn = document.getElementById('add-to-cart-button');
                    if (!title) return { error: 'Product page not found' };
                    if (!btn) return { error: 'Product not available for purchase' };
                    btn.click();
                    return {
                        clicked: true,
                        product: title.textContent.trim()
                    };
                })()
            """)

            if data.get("error"):
                return {"success": False, "error": data["error"], "asin": product_id}

            await self.page.sleep(4)

            if screenshot:
                await self.page.save_screenshot(screenshot)

            cart_data = await self.evaluate("""
                document.getElementById('nav-cart-count')?.textContent?.trim() || '0'
            """)
            count_val = cart_data if isinstance(cart_data, str) else str(cart_data.get("value", "0"))

            result = {
                "success": True,
                "added": True,
                "asin": product_id,
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
            await self.navigate("https://www.amazon.com/gp/cart/view.html")

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate("""
                (() => {
                    const count = document.getElementById('nav-cart-count')?.textContent?.trim() || '0';
                    const items = [];
                    document.querySelectorAll('.sc-list-item:not(.sc-list-item-removed)').forEach(item => {
                        const titleEl = item.querySelector('.sc-product-title, .a-truncate-full');
                        const priceEl = item.querySelector('.sc-product-price, .sc-price');
                        const qtyEl = item.querySelector('.sc-quantity-textfield');
                        const asinEl = item.closest('[data-asin]');
                        if (titleEl) {
                            items.push({
                                title: titleEl.textContent.trim(),
                                price: priceEl ? priceEl.textContent.trim() : null,
                                quantity: qtyEl ? qtyEl.value : '1',
                                asin: asinEl ? asinEl.dataset.asin : null
                            });
                        }
                    });
                    const subtotalEl = document.getElementById('sc-subtotal-amount-activecart');
                    const subtotal = subtotalEl ? subtotalEl.textContent.trim() : null;
                    return {
                        cart_count: count,
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
        """List recent Amazon orders."""
        await self.ensure_browser()
        if not self.browser:
            return {"success": False, "error": "Cookie extraction failed"}

        try:
            await self.navigate("https://www.amazon.com/gp/your-account/order-history")

            if screenshot:
                await self.page.save_screenshot(screenshot)

            data = await self.evaluate(f"""
                (() => {{
                    const limit = {limit};
                    const allText = document.body.innerText;

                    const orderIdPattern = /\\d{{3}}-\\d{{7}}-\\d{{7}}/g;
                    const orderIds = [...new Set(allText.match(orderIdPattern) || [])].slice(0, limit);

                    const productLinks = document.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"]');
                    const products = [];
                    const seen = new Set();
                    for (const link of productLinks) {{
                        const text = link.textContent.trim();
                        if (text && text.length > 5 && text.length < 200 && !seen.has(text)) {{
                            seen.add(text);
                            const asinMatch = link.href.match(/\\/dp\\/([A-Z0-9]{{10}})/);
                            products.push({{
                                name: text,
                                asin: asinMatch ? asinMatch[1] : null,
                                url: link.href
                            }});
                        }}
                        if (products.length >= limit) break;
                    }}

                    const datePattern = /(?:January|February|March|April|May|June|July|August|September|October|November|December)\\s+\\d{{1,2}},\\s+\\d{{4}}/g;
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
