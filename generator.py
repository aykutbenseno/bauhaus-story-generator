"""
BAUHAUS Story Generator — Image Composition Engine
Pixel coordinates are calibrated for 1080×1920 Instagram Story format.
Layout is dynamic: price rows shift down based on how many name lines are used.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"

# ── Layout constants (calibrated to 1080×1920) ──────────────────────────────
LEFT_MARGIN   = 60    # px from left for all text elements

# Product name (TazWt07Bold, white)
NAME_Y        = 490   # top of first line  ← moved down from 436
NAME_LINE_H   = 72    # px between line starts
NAME_FONT_SZ  = 62
NAME_MAX_LN   = 3
NAME_GAP      = 28    # gap between last name line and orig price

# Original / crossed-out price (TazWt07Bold, white + strikethrough)
# ORIG_Y is calculated dynamically from name bottom + NAME_GAP
ORIG_FONT_SZ  = 52
STRIKE_EXTEND = 12    # px beyond text on each side
ORIG_TO_BOX   = 14   # gap between orig price bottom and discount box top

# Discounted price pill (TazBlack, white text on salmon box)
BOX_X1        = 55
BOX_RADIUS    = 18
DISC_FONT_SZ  = 90
DISC_PAD_X    = 22   # horizontal padding inside box
DISC_PAD_Y    = 12   # vertical padding inside box
BOX_FILL      = (242, 148, 154)   # salmon/pink background
DISC_COLOR    = (255, 255, 255)   # white text
BOX_TO_IMG    = 55   # min gap between box bottom and product image top

# Product image placement area
IMG_TOP        = 840   # minimum y for product image  ← raised slightly
IMG_BOT        = 1565
IMG_MARGIN_X   = 30   # horizontal margin from canvas edge

# Product code (TazWt07Bold, white)
CODE_Y         = 1628
CODE_FONT_SZ   = 38
CODE_PREFIX    = "Ürün kodu: "


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f"{name}.otf"), size=size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Word-wrap text to fit within max_w pixels."""
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


def remove_bg(img: Image.Image, threshold: int = 235) -> Image.Image:
    """
    Remove white / near-white background from a product image.
    Works well for BAUHAUS product shots on plain white backgrounds.
    Also handles light-grey backgrounds common in retailer photography.
    """
    img = img.convert("RGBA")
    data = list(img.getdata())
    new = []
    for r, g, b, a in data:
        if r > threshold and g > threshold and b > threshold:
            new.append((r, g, b, 0))          # fully transparent
        elif r > 220 and g > 200 and b > 200:  # light-grey edge fade
            alpha = int(((r - 220) / 35) * 255)
            new.append((r, g, b, 255 - alpha))
        else:
            new.append((r, g, b, a))
    img.putdata(new)
    return img


def create_story(
    template: Image.Image,
    product_img: Image.Image,
    product_name: str,
    original_price: str,
    discounted_price: str,
    product_code: str,
    bg_threshold: int = 235,
) -> Image.Image:
    """
    Compose a single 1080×1920 story image.

    Parameters
    ----------
    template        : clean background PNG (no text, no product)
    product_img     : product photo (will have white bg removed)
    product_name    : e.g. "Leo Rattan Oturma Grubu Gri"
    original_price  : e.g. "44.900 TL"
    discounted_price: e.g. "35.900 TL"
    product_code    : e.g. "61578160"
    bg_threshold    : white-bg removal sensitivity (200-255)
    """
    # Scale factors in case template isn't exactly 1080×1920
    canvas = template.copy().convert("RGBA")
    W, H = canvas.size
    sx, sy = W / 1080, H / 1920

    draw = ImageDraw.Draw(canvas)

    # ── Fonts ─────────────────────────────────────────────────────────────
    f_name  = _font("TazWt07Bold", int(NAME_FONT_SZ  * sx))
    f_orig  = _font("TazWt07Bold", int(ORIG_FONT_SZ  * sx))
    f_disc  = _font("TazBlack",    int(DISC_FONT_SZ  * sx))
    f_code  = _font("TazWt07Bold", int(CODE_FONT_SZ  * sx))

    lm = int(LEFT_MARGIN * sx)          # left margin (scaled)

    # ── Product name (white, bold, up to 3 lines) ─────────────────────────
    max_text_w = int(W * 0.60)          # use ~60% of width for name
    lines = _wrap(product_name, f_name, max_text_w)[:NAME_MAX_LN]
    name_start_y = int(NAME_Y * sy)
    for i, line in enumerate(lines):
        y = name_start_y + i * int(NAME_LINE_H * sy)
        draw.text((lm, y), line, font=f_name, fill="white")

    # Dynamic: original price starts just below the last name line
    last_name_line_bottom = (
        name_start_y
        + (len(lines) - 1) * int(NAME_LINE_H * sy)
        + int(NAME_FONT_SZ * sy)      # approximate text height
    )
    oy = last_name_line_bottom + int(NAME_GAP * sy)

    # ── Original price + strikethrough ────────────────────────────────────
    draw.text((lm, oy), original_price, font=f_orig, fill="white")
    bb = f_orig.getbbox(original_price)
    pw = bb[2] - bb[0]
    ph = bb[3] - bb[1]
    mid_y = oy + ph // 2 + int(2 * sy)
    ext = int(STRIKE_EXTEND * sx)
    draw.line(
        [(lm - ext, mid_y), (lm + pw + ext, mid_y)],
        fill="white",
        width=max(2, int(3 * sy)),
    )

    # ── Discounted price pill ──────────────────────────────────────────────
    # Measure text to size the box
    db = f_disc.getbbox(discounted_price)
    dw = db[2] - db[0]
    dh = db[3] - db[1]
    pad_x = int(DISC_PAD_X * sx)
    pad_y = int(DISC_PAD_Y * sy)

    # Dynamic: box top = orig price bottom + gap
    orig_bottom = oy + ph
    bx1 = int(BOX_X1 * sx)
    by1 = orig_bottom + int(ORIG_TO_BOX * sy)
    bx2 = bx1 + dw + pad_x * 2
    by2 = by1 + dh + pad_y * 2
    rad  = int(BOX_RADIUS * sx)

    # Draw box on a separate RGBA layer for clean compositing
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rounded_rectangle([bx1, by1, bx2, by2], radius=rad, fill=(*BOX_FILL, 255))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)  # re-bind after composite

    draw.text((bx1 + pad_x, by1 + pad_y), discounted_price, font=f_disc, fill=DISC_COLOR)

    # ── Product image ──────────────────────────────────────────────────────
    # Ensure product image starts below the price box (dynamic lower bound)
    box_bottom = by2
    area_top  = max(int(IMG_TOP * sy), box_bottom + int(BOX_TO_IMG * sy))
    area_bot  = int(IMG_BOT  * sy)
    area_h    = area_bot - area_top
    margin_x  = int(IMG_MARGIN_X * sx)
    avail_w   = W - margin_x * 2

    prod = remove_bg(product_img, threshold=bg_threshold)
    scale = min(avail_w / prod.width, area_h / prod.height) * 0.92
    nw, nh = int(prod.width * scale), int(prod.height * scale)
    prod = prod.resize((nw, nh), Image.LANCZOS)

    px = (W - nw) // 2
    py = area_top + (area_h - nh) // 2
    canvas.paste(prod, (px, py), prod)

    # ── Product code ───────────────────────────────────────────────────────
    draw.text(
        (lm, int(CODE_Y * sy)),
        f"{CODE_PREFIX}{product_code}",
        font=f_code,
        fill="white",
    )

    return canvas.convert("RGB")
