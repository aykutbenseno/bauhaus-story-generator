"""
BAUHAUS TR product image scraper.
Strategy order:
  0. Direct image URL (if caller already knows it — no HTTP request needed)
  1. SAP Hybris OCC REST API  (less protected than HTML pages)
  2. Open Graph meta tag
  3. JSON-LD structured data
  4. HTML selectors (BAUHAUS / SAP Commerce patterns)
  5. Largest <img> fallback
Uses cloudscraper to bypass Cloudflare JS challenges where possible.
"""
import io
import json
import re

from PIL import Image

try:
    import cloudscraper
    _SESSION = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
except Exception:
    import requests as _requests
    _SESSION = _requests.Session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.bauhaus.com.tr/",
}

TIMEOUT = 25


def _get(url: str, as_json: bool = False):
    """Fetch a URL. Returns response or None."""
    headers = dict(HEADERS)
    if as_json:
        headers["Accept"] = "application/json"
    try:
        resp = _SESSION.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"[scraper] GET failed: {e}")
        return None


def fetch_product_image(
    product_url: str,
    direct_image_url: str | None = None,
) -> Image.Image | None:
    """
    Fetch the best product image.

    Parameters
    ----------
    product_url       : BAUHAUS TR ürün sayfası URL'si
    direct_image_url  : Kullanıcı tarafından sağlanan direkt CDN URL'si (opsiyonel).
                        Varsa scrape atlanır, bu URL direkt indirilir.
    """
    # ── Strategy 0: caller already has the image URL ───────────────────────
    if direct_image_url and direct_image_url.strip().startswith("http"):
        img = _download(direct_image_url.strip())
        if img:
            return img

    # ── Strategy 1: SAP Hybris OCC API ────────────────────────────────────
    product_code = _extract_product_code(product_url)
    if product_code:
        img = _try_hybris_api(product_code)
        if img:
            return img

    # ── Fetch HTML (strategies 2-5) ────────────────────────────────────────
    resp = _get(product_url)
    if resp is None:
        print(f"[scraper] Page fetch failed for: {product_url}")
        return None
    html = resp.text

    # Strategy 2: Open Graph
    img_url = _og_image(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 3: JSON-LD
    img_url = _jsonld_image(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 4: BAUHAUS / SAP selectors
    img_url = _html_selector(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 5: Largest img
    img_url = _largest_img(html)
    if img_url:
        return _download(img_url)

    print(f"[scraper] All strategies exhausted: {product_url}")
    return None


# ── Private helpers ──────────────────────────────────────────────────────────

def _extract_product_code(url: str) -> str | None:
    """Extract product code from BAUHAUS TR URL. e.g. /p/61578160 → '61578160'"""
    m = re.search(r'/p/(\d+)', url)
    if m:
        return m.group(1)
    # Trailing digits fallback
    m = re.search(r'/(\d{6,})(?:[/?#]|$)', url)
    return m.group(1) if m else None


def _try_hybris_api(product_code: str) -> Image.Image | None:
    """Try SAP Hybris OCC REST API to get product image URL."""
    api_urls = [
        f"https://www.bauhaus.com.tr/rest/v2/bauhaus/products/{product_code}?fields=images",
        f"https://www.bauhaus.com.tr/api/products/{product_code}",
    ]
    for api_url in api_urls:
        resp = _get(api_url, as_json=True)
        if resp is None:
            continue
        try:
            data = resp.json()
            # SAP Hybris image format: [{format:'zoom', url:'...'}, ...]
            images = data.get("images", [])
            if not images and "data" in data:
                images = data["data"].get("images", [])
            # Prefer 'zoom' or 'product' format (highest quality)
            for fmt in ("zoom", "product", "thumbnail"):
                for img_data in images:
                    if img_data.get("format") == fmt:
                        url = img_data.get("url", "")
                        if url:
                            if url.startswith("/"):
                                url = "https://www.bauhaus.com.tr" + url
                            return _download(url)
            # Fallback: first image in list
            if images:
                url = images[0].get("url", "")
                if url:
                    if url.startswith("/"):
                        url = "https://www.bauhaus.com.tr" + url
                    return _download(url)
        except Exception as e:
            print(f"[scraper] API parse error: {e}")
            continue
    return None


def _og_image(html: str) -> str | None:
    m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']', html)
    if m:
        return m.group(1)
    m = re.search(r'<meta\s+content=["\'](.*?)["\']\s+property=["\']og:image["\']', html)
    return m.group(1) if m else None


def _jsonld_image(html: str) -> str | None:
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                data = data[0]
            img = data.get("image")
            if isinstance(img, list):
                img = img[0]
            if isinstance(img, str):
                return img
            if isinstance(img, dict):
                return img.get("url")
        except Exception:
            continue
    return None


def _html_selector(html: str) -> str | None:
    patterns = [
        r'<img[^>]+id=["\']zoom_\d*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'<img[^>]+class=["\'][^"\']*product[^"\']*primary[^"\']*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'<img[^>]+class=["\'][^"\']*main-image[^"\']*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'<img[^>]+id=["\']product[_-]?image["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'data-zoom-image=["\'](https?://[^"\']+)["\']',
        r'data-main-image=["\'](https?://[^"\']+)["\']',
        r'src=["\'](https?://[^"\']*(?:medias|sys_master)[^"\']+(?:jpg|jpeg|png|webp))["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _largest_img(html: str) -> str | None:
    candidates = re.findall(
        r'<img[^>]+src=["\'](https?://[^"\']+\.(jpg|jpeg|png|webp))["\']',
        html, re.IGNORECASE
    )
    for url, _ in candidates:
        if any(k in url.lower() for k in ("product", "urun", "medias", "images", "sys_master")):
            return url
    return candidates[0][0] if candidates else None


def _download(url: str) -> Image.Image | None:
    if url.startswith("//"):
        url = "https:" + url
    resp = _get(url)
    if resp is None:
        return None
    try:
        return Image.open(io.BytesIO(resp.content))
    except Exception as e:
        print(f"[scraper] Image open failed ({url}): {e}")
        return None
