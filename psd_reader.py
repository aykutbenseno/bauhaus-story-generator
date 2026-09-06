"""
BAUHAUS PSD Reader
==================
PSD dosyasından zone pozisyonlarını okur ve template görselini üretir.

PSD'de şu isimlerde katmanlar olmalı (visibility kapalı olsun):
  zone_name   — ürün adı metninin yerleştirileceği alan
  zone_price  — çizili orijinal fiyatın alanı
  zone_box    — indirimli fiyat kutusunun alanı
  zone_image  — ürün görselinin yerleştirileceği alan
  zone_code   — ürün kodu metninin alanı

Bu katmanlar Photoshop'ta gizli (göz ikonu kapalı) olarak kaydedilmeli.
Pozisyon bilgileri okunur ama template render'ına dahil edilmezler.
"""
import io
from PIL import Image

ZONE_KEYS = {"name", "price", "box", "image", "code"}


def read_psd(psd_bytes: bytes) -> tuple[Image.Image | None, dict]:
    """
    PSD dosyasını açar, zone katmanlarının pozisyonlarını okur,
    görünür katmanları composite ederek template görselini döndürür.

    Returns
    -------
    template : PIL Image (RGBA) — arka plan katmanlarının birleşimi
    zones    : dict — zone_* katmanlarının pixel pozisyonları
               Örnek: {"name": {"top": 490, "left": 60, "bottom": 620, "right": 700}}
    """
    try:
        from psd_tools import PSDImage
    except ImportError:
        print("[psd_reader] psd-tools kurulu değil.")
        return None, {}

    try:
        psd = PSDImage.open(io.BytesIO(psd_bytes))
    except Exception as e:
        print(f"[psd_reader] PSD açılamadı: {e}")
        return None, {}

    zones = {}

    # Tüm katmanları tara — zone_ ile başlayanları kaydet
    for layer in psd.descendants():
        lname = layer.name.strip().lower()
        if lname.startswith("zone_"):
            key = lname[5:]   # "zone_name" → "name"
            if key in ZONE_KEYS:
                zones[key] = {
                    "top":    layer.top,
                    "left":   layer.left,
                    "bottom": layer.bottom,
                    "right":  layer.right,
                }

    # Composite → template
    # (zone katmanları PSD'de gizli kayıtlıysa otomatik dahil edilmez)
    try:
        template_img = psd.composite()
        return template_img.convert("RGBA"), zones
    except Exception as e:
        print(f"[psd_reader] Composite hatası: {e}")
        return None, zones


def validate_zones(zones: dict) -> list[str]:
    """
    Hangi zone'ların eksik olduğunu döndürür.
    Boş liste → tüm zone'lar mevcut.
    """
    missing = []
    for key in ZONE_KEYS:
        if key not in zones:
            missing.append(f"zone_{key}")
    return missing


def zones_summary(zones: dict) -> str:
    """UI'da göstermek için okunabilir özet."""
    if not zones:
        return "Zone katmanı bulunamadı."
    lines = []
    labels = {
        "name":  "Ürün adı",
        "price": "Orijinal fiyat",
        "box":   "İndirim kutusu",
        "image": "Ürün görseli",
        "code":  "Ürün kodu",
    }
    for key in ZONE_KEYS:
        if key in zones:
            z = zones[key]
            lines.append(
                f"✅ **{labels.get(key, key)}** — "
                f"({z['left']}, {z['top']}) → ({z['right']}, {z['bottom']})"
            )
        else:
            lines.append(f"❌ **{labels.get(key, key)}** — zone_{key} katmanı bulunamadı")
    return "\n".join(lines)
