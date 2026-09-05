"""
BAUHAUS TR product image scraper.
Tries multiple strategies in priority order to obtain the main product photo.
"""
import io
import json
import re
import requests
from PIL import Image

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
    "DNT": "1",
}

TIMEOUT = 20   # seconds


def fetch_product_image(url: str) -> Image.Image | None:
    """
    Fetch the best product image from a BAUHAUS TR product URL.
    Returns a PIL Image or None if all strategies fail.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[scraper] Page fetch failed: {e}")
        return None

    # Strategy 1 — Open Graph image (fastest, usually highest-quality)
    img_url = _og_image(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 2 — JSON-LD structured data
    img_url = _jsonld_image(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 3 — BAUHAUS TR-specific HTML selectors
    img_url = _html_selector(html)
    if img_url:
        img = _download(img_url)
        if img:
            return img

    # Strategy 4 — Largest <img> on the page (last resort)
    img_url = _largest_img(html)
    if img_url:
        return _download(img_url)

    print(f"[scraper] All strategies exhausted for: {url}")
    return None


# ── Private helpers ──────────────────────────────────────────────────────────

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
    """Try BAUHAUS TR / SAP Commerce product image patterns."""
    patterns = [
        # SAP Commerce (Hybris) — common at BAUHAUS
        r'<img[^>]+id=["\']zoom_\d*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'<img[^>]+class=["\'][^"\']*product[^"\']*primary[^"\']*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'<img[^>]+class=["\'][^"\']*main-image[^"\']*["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        # Generic
        r'<img[^>]+id=["\']product[_-]?image["\'][^>]+src=["\'](https?://[^"\']+)["\']',
        r'data-zoom-image=["\'](https?://[^"\']+)["\']',
        r'data-main-image=["\'](https?://[^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _largest_img(html: str) -> str | None:
    """Return the first large product-looking image src found."""
    candidates = re.findall(
        r'<img[^>]+src=["\'](https?://[^"\']+\.(jpg|jpeg|png|webp))["\']',
        html, re.IGNORECASE
    )
    # Prefer URLs containing product-ish keywords
    for url, _ in candidates:
        if any(k in url.lower() for k in ("product", "urun", "medias", "images")):
            return url
    return candidates[0][0] if candidates else None


def _download(url: str) -> Image.Image | None:
    """Download and open an image from a URL."""
    if url.startswith("//"):
        url = "https:" + url
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content))
    except Exception as e:
        print(f"[scraper] Image download failed ({url}): {e}")
        return None
