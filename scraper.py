"""
BAUHAUS TR product image scraper.
Strategy order:
  0. Direct image URL (caller already has it — no HTTP)
  1. SAP Hybris OCC REST API
  2. Headless Chromium via Selenium (bypasses Cloudflare JS challenges)
     → OG tag / JSON-LD / selectors / largest-img from rendered HTML
  3. requests / cloudscraper fallback (same sub-strategies)
"""
import io
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

# ── HTTP session (cloudscraper preferred) ────────────────────────────────────
try:
    import cloudscraper
    _SESSION = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
except Exception:
    import requests as _req
    _SESSION = _req.Session()

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

# ── Chromium locations (Streamlit Cloud / Ubuntu) ────────────────────────────
_CHROMIUM_BINS = [
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
]
_CHROMEDRIVER_BINS = [
    "/usr/bin/chromedriver",
    "/usr/lib/chromium-browser/chromedriver",
    "/usr/lib/chromium/chromedriver",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_product_image(
    product_url: str,
    direct_image_url: str | None = None,
) -> Image.Image | None:
    """
    Fetch the best product image for a BAUHAUS TR URL.

    Parameters
    ----------
    product_url       : BAUHAUS TR ürün sayfası URL'si
    direct_image_url  : Kullanıcı tarafından sağlanan direkt CDN linki (opsiyonel).
    """
    # ── Strategy 0: caller already has the image URL ─────────────────────────
    if direct_image_url and str(direct_image_url).strip().startswith("http"):
        img = _download(direct_image_url.strip())
        if img:
            return img

    # ── Strategy 1: SAP Hybris OCC REST API ──────────────────────────────────
    product_code = _extract_product_code(product_url)
    if product_code:
        img = _try_hybris_api(product_code)
        if img:
            return img

    # ── Strategy 2: Headless Chromium (main Cloudflare bypass) ───────────────
    html = _selenium_fetch_html(product_url)
    if html:
        img = _extract_from_html(html, product_url)
        if img:
            return img

    # ── Strategy 3: requests / cloudscraper fallback ──────────────────────────
    resp = _get(product_url)
    if resp:
        img = _extract_from_html(resp.text, product_url)
        if img:
            return img

    print(f"[scraper] All strategies exhausted: {product_url}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Selenium / headless Chromium
# ─────────────────────────────────────────────────────────────────────────────

def _selenium_fetch_html(url: str) -> str | None:
    """
    Open URL in headless Chromium, wait for JS (incl. Cloudflare challenge),
    return final page source.  Returns None if selenium/chrome not available.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        # Locate Chromium binary
        for binary in _CHROMIUM_BINS:
            if Path(binary).exists():
                opts.binary_location = binary
                break

        # Locate chromedriver
        driver_bin = None
        for dp in _CHROMEDRIVER_BINS:
            if Path(dp).exists():
                driver_bin = dp
                break
        if driver_bin is None:
            driver_bin = shutil.which("chromedriver")
        if driver_bin is None:
            print("[scraper] chromedriver not found — selenium strategy skipped")
            return None

        service = Service(driver_bin)
        driver = webdriver.Chrome(service=service, options=opts)

        # Mask webdriver fingerprint
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )

        try:
            driver.get(url)
            time.sleep(5)   # wait for Cloudflare JS challenge to resolve
            return driver.page_source
        finally:
            driver.quit()

    except Exception as e:
        print(f"[scraper] Selenium failed ({url}): {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# HTML extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_from_html(html: str, base_url: str) -> Image.Image | None:
    """Try OG → JSON-LD → selectors → largest-img from any HTML string."""
    origin = _origin(base_url)
    for fn in (_og_image, _jsonld_image, _html_selector, _largest_img):
        img_url = fn(html)
        if img_url:
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                img_url = origin + img_url
            img = _download(img_url)
            if img:
                return img
    return None


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


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
        r'<img[^>]+src=["\']((?:https?:)?//[^"\']+\.(jpg|jpeg|png|webp))["\']',
        html, re.IGNORECASE
    )
    for url, _ in candidates:
        if any(k in url.lower() for k in ("product", "urun", "medias", "images", "sys_master")):
            return url
    return candidates[0][0] if candidates else None


# ─────────────────────────────────────────────────────────────────────────────
# SAP Hybris OCC API
# ─────────────────────────────────────────────────────────────────────────────

def _extract_product_code(url: str) -> str | None:
    m = re.search(r'/p/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/(\d{6,})(?:[/?#]|$)', url)
    return m.group(1) if m else None


def _try_hybris_api(product_code: str) -> Image.Image | None:
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
            images = data.get("images", [])
            if not images and "data" in data:
                images = data["data"].get("images", [])
            for fmt in ("zoom", "product", "thumbnail"):
                for img_data in images:
                    if img_data.get("format") == fmt:
                        img_url = img_data.get("url", "")
                        if img_url:
                            if img_url.startswith("/"):
                                img_url = "https://www.bauhaus.com.tr" + img_url
                            return _download(img_url)
            if images:
                img_url = images[0].get("url", "")
                if img_url:
                    if img_url.startswith("/"):
                        img_url = "https://www.bauhaus.com.tr" + img_url
                    return _download(img_url)
        except Exception as e:
            print(f"[scraper] API parse error: {e}")
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Low-level HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _get(url: str, as_json: bool = False):
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
