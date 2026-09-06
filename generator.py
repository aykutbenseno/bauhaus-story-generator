"""
BAUHAUS Story Generator — Image Composition Engine
===================================================
1080×1920 Instagram Story formatı için piksel koordinatları.
Layout dinamik: fiyat satırları kullanılan isim satırı sayısına göre kayar.
PSD'den gelen zone pozisyonları hardcoded sabitleri override eder.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"

# ── Layout sabitleri (1080×1920 referans) ───────────────────────────────────
LEFT_MARGIN   = 60

# Ürün adı (TazWt07Bold, beyaz)
NAME_Y        = 490
NAME_LINE_H   = 72
NAME_FONT_SZ  = 62
NAME_MAX_LN   = 3
NAME_GAP      = 28    # son isim satırı altı → orijinal fiyat arası boşluk

# Orijinal / çizili fiyat (TazWt07Bold, beyaz + üstü çizili)
ORIG_FONT_SZ  = 52
STRIKE_EXTEND = 12
ORIG_TO_BOX   = 14   # orijinal fiyat altı → indirim kutusu üstü

# İndirim fiyatı pill (TazBlack, beyaz metin / somon kutu)
BOX_X1        = 55
BOX_RADIUS    = 18
DISC_FONT_SZ  = 90
DISC_PAD_X    = 22
DISC_PAD_Y    = 12
BOX_FILL      = (242, 148, 154)
DISC_COLOR    = (255, 255, 255)
BOX_TO_IMG    = 55   # kutu altı → görsel üstü min boşluk

# Ürün görseli
IMG_TOP       = 840
IMG_BOT       = 1565
IMG_MARGIN_X  = 30

# Ürün kodu (TazWt07Bold, beyaz)
CODE_Y        = 1628
CODE_FONT_SZ  = 38
CODE_PREFIX   = "Ürün kodu: "


# ── Font yükleyici ───────────────────────────────────────────────────────────

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = ASSETS / f"{name}.otf"
    if not path.exists():
        # Alternatif uzantılar
        for ext in (".ttf", ".OTF", ".TTF"):
            alt = ASSETS / f"{name}{ext}"
            if alt.exists():
                path = alt
                break
    return ImageFont.truetype(str(path), size=size)


# ── Metin sarma ──────────────────────────────────────────────────────────────

def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], []
    for word in words:
        test = " ".join(cur + [word])
        w = font.getbbox(test)[2] - font.getbbox(test)[0]
        if w <= max_w:
            cur.append(word)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [word]
    if cur:
        lines.append(" ".join(cur))
    return lines


# ── Arka plan kaldırma ───────────────────────────────────────────────────────

def _rembg_session():
    """rembg oturumu — Streamlit cache ile tek seferlik yüklenir."""
    try:
        import streamlit as st
        from rembg import new_session

        @st.cache_resource(show_spinner=False)
        def _load():
            return new_session("u2netp")   # 4 MB hafif model

        return _load()
    except Exception:
        return None


def remove_bg(img: Image.Image, threshold: int = 235) -> Image.Image:
    """
    Ürün görselinden arka planı kaldırır.

    Sırasıyla dener:
    1. rembg (ML tabanlı — lifestyle ve karmaşık arka planlar için)
    2. Piksel threshold (sade beyaz arka plan için hızlı fallback)
    """
    img = img.convert("RGBA")

    # ── 1. rembg (ML) ─────────────────────────────────────────────────────
    try:
        from rembg import remove as rembg_remove
        session = _rembg_session()
        kwargs = {"session": session} if session else {}
        result = rembg_remove(img, **kwargs)

        # Sonucun anlamlı olup olmadığını kontrol et
        alpha_data = list(result.getchannel("A").getdata())
        total = len(alpha_data)
        transparent = sum(1 for v in alpha_data if v < 10)
        if transparent / total > 0.06:   # %6'dan fazla transparan → başarılı
            return result
    except Exception as e:
        print(f"[generator] rembg başarısız: {e}")

    # ── 2. Threshold — beyaz / açık gri arka plan ─────────────────────────
    data = list(img.getdata())
    new = []
    for r, g, b, a in data:
        if r > threshold and g > threshold and b > threshold:
            new.append((r, g, b, 0))
        elif r > 220 and g > 200 and b > 200:
            alpha_val = int(((r - 220) / 35) * 255)
            new.append((r, g, b, 255 - alpha_val))
        else:
            new.append((r, g, b, a))
    img.putdata(new)
    return img


# ── Ana kompozisyon fonksiyonu ────────────────────────────────────────────────

def create_story(
    template: Image.Image,
    product_img: Image.Image,
    product_name: str,
    original_price: str,
    discounted_price: str,
    product_code: str,
    bg_threshold: int = 235,
    zones: dict | None = None,
    font_name: str = "TazWt07Bold",
    font_disc: str = "TazBlack",
) -> Image.Image:
    """
    Tek bir 1080×1920 story görseli oluşturur.

    Parameters
    ----------
    template         : temiz arka plan PNG (metin ve ürün yok)
    product_img      : ürün fotoğrafı
    product_name     : örn. "Leo Rattan Oturma Grubu Gri"
    original_price   : örn. "44.900 TL"
    discounted_price : örn. "35.900 TL"
    product_code     : örn. "61578160"
    bg_threshold     : beyaz bg silme hassasiyeti (200–255)
    zones            : psd_reader'dan gelen zone pozisyonları (opsiyonel)
    font_name        : normal/bold font dosya adı (assets/ klasöründe)
    font_disc        : indirim fiyatı için font dosya adı
    """
    canvas = template.copy().convert("RGBA")
    W, H = canvas.size
    sx, sy = W / 1080, H / 1920

    draw = ImageDraw.Draw(canvas)

    # ── Fontlar ──────────────────────────────────────────────────────────
    f_name = _font(font_name, int(NAME_FONT_SZ * sx))
    f_orig = _font(font_name, int(ORIG_FONT_SZ * sx))
    f_disc = _font(font_disc, int(DISC_FONT_SZ * sx))
    f_code = _font(font_name, int(CODE_FONT_SZ * sx))

    # ── Zone → piksel yardımcı fonksiyonlar ──────────────────────────────
    def zv(key: str, attr: str, fallback: float) -> int:
        """Zone değeri varsa kullan, yoksa sabiti ölçekle."""
        if zones and key in zones:
            val = zones[key][attr]
            return int(val * (sy if attr in ("top", "bottom") else sx))
        return int(fallback)

    # Sol kenar boşluğu ve maksimum metin genişliği
    lm = zv("name", "left", LEFT_MARGIN * sx)
    if zones and "name" in zones:
        max_text_w = int((zones["name"]["right"] - zones["name"]["left"]) * sx)
    else:
        max_text_w = int(W * 0.60)

    # ── Ürün adı ─────────────────────────────────────────────────────────
    lines = _wrap(product_name, f_name, max_text_w)[:NAME_MAX_LN]
    name_start_y = zv("name", "top", NAME_Y * sy)

    for i, line in enumerate(lines):
        y = name_start_y + i * int(NAME_LINE_H * sy)
        draw.text((lm, y), line, font=f_name, fill="white")

    last_name_bottom = (
        name_start_y
        + (len(lines) - 1) * int(NAME_LINE_H * sy)
        + int(NAME_FONT_SZ * sy)
    )

    # ── Orijinal fiyat + üstü çizili ─────────────────────────────────────
    # zone_price varsa o Y'den başla, yoksa isim altından dinamik hesapla
    if zones and "price" in zones:
        oy = int(zones["price"]["top"] * sy)
    else:
        oy = last_name_bottom + int(NAME_GAP * sy)

    draw.text((lm, oy), original_price, font=f_orig, fill="white")
    bb = f_orig.getbbox(original_price)
    pw = bb[2] - bb[0]
    ph = bb[3] - bb[1]
    mid_y = oy + ph // 2 + int(2 * sy)
    ext   = int(STRIKE_EXTEND * sx)
    draw.line(
        [(lm - ext, mid_y), (lm + pw + ext, mid_y)],
        fill="white",
        width=max(2, int(3 * sy)),
    )

    # ── İndirim fiyatı kutusu ─────────────────────────────────────────────
    db = f_disc.getbbox(discounted_price)
    dw = db[2] - db[0]
    dh = db[3] - db[1]
    pad_x = int(DISC_PAD_X * sx)
    pad_y = int(DISC_PAD_Y * sy)

    bx1 = zv("box", "left", BOX_X1 * sx)

    # Kutu Y'si: zone_box varsa kullan, yoksa orijinal fiyat altından dinamik
    if zones and "box" in zones:
        by1 = int(zones["box"]["top"] * sy)
    else:
        orig_bottom = oy + ph
        by1 = orig_bottom + int(ORIG_TO_BOX * sy)

    bx2 = bx1 + dw + pad_x * 2
    by2 = by1 + dh + pad_y * 2
    rad = int(BOX_RADIUS * sx)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rounded_rectangle([bx1, by1, bx2, by2], radius=rad, fill=(*BOX_FILL, 255))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    draw.text((bx1 + pad_x, by1 + pad_y), discounted_price, font=f_disc, fill=DISC_COLOR)

    # ── Ürün görseli ──────────────────────────────────────────────────────
    if zones and "image" in zones:
        z = zones["image"]
        area_top  = int(z["top"]    * sy)
        area_bot  = int(z["bottom"] * sy)
        img_left  = int(z["left"]   * sx)
        img_right = int(z["right"]  * sx)
    else:
        box_bottom = by2
        area_top  = max(int(IMG_TOP * sy), box_bottom + int(BOX_TO_IMG * sy))
        area_bot  = int(IMG_BOT * sy)
        img_left  = int(IMG_MARGIN_X * sx)
        img_right = W - int(IMG_MARGIN_X * sx)

    area_h  = area_bot - area_top
    avail_w = img_right - img_left

    prod  = remove_bg(product_img, threshold=bg_threshold)
    scale = min(avail_w / prod.width, area_h / prod.height) * 0.92
    nw, nh = int(prod.width * scale), int(prod.height * scale)
    prod  = prod.resize((nw, nh), Image.LANCZOS)

    px = (img_left + img_right - nw) // 2
    py = area_top + (area_h - nh) // 2
    canvas.paste(prod, (px, py), prod)

    # ── Ürün kodu ─────────────────────────────────────────────────────────
    code_y = zv("code", "top",  CODE_Y * sy)
    code_x = zv("code", "left", lm)
    draw.text(
        (code_x, code_y),
        f"{CODE_PREFIX}{product_code}",
        font=f_code,
        fill="white",
    )

    return canvas.convert("RGB")
