"""
BAUHAUS Story Generator — Streamlit Web App
"""
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from PIL import Image

import generator
import scraper


# ── Helpers (tanımlı olmaları gerekiyor — dosyanın üstünde) ──────────────────

def _extract_sheet_id(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1) if m else None


def _col_to_idx(letter: str) -> int:
    return ord(letter.upper()) - ord("A")


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BAUHAUS Story Generator",
    page_icon="🏠",
    layout="centered",
)

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🏠 BAUHAUS Story Generator")
st.markdown("Google Sheets'teki ürün listesinden otomatik Instagram Story üretir.")
st.divider()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Ayarlar")

    template_file = st.file_uploader(
        "📐 Template PNG",
        type=["png", "jpg", "jpeg"],
        help=(
            "Ürün görseli ve metin içermeyen temiz arka plan şablonu. "
            "Photoshop'ta sadece arka plan katmanlarını dışa aktar."
        ),
    )

    bg_threshold = st.slider(
        "Beyaz arka plan silme hassasiyeti",
        min_value=200,
        max_value=255,
        value=238,
        help="Düşük değer daha agresif siler (koyu ürünler için artır)",
    )

    st.divider()
    st.caption("Font: Taz Black & Taz Wt07 Bold")
    st.caption("Çıktı: 1080×1920 px PNG — ZIP")

# ── Google Sheets URL ─────────────────────────────────────────────────────────
st.subheader("1. Google Sheets Bağlantısı")
st.caption(
    "Sheets → Dosya → Paylaş → **Link ile görüntüleyebilir** seçeneğini aktif et."
)

sheets_url = st.text_input(
    "Google Sheets URL",
    placeholder="https://docs.google.com/spreadsheets/d/...",
    label_visibility="collapsed",
)

# ── Column mapping ────────────────────────────────────────────────────────────
st.subheader("2. Sütun Sırası")
st.caption(
    "Excel'deki sütun harflerini seç. "
    "Örnek: A=Ürün Kodu, B=Ürün Adı, C=Çizili, D=İndirimli, E=Link"
)

col_labels = ["A", "B", "C", "D", "E", "F", "G", "H"]

cc1, cc2, cc3, cc4, cc5 = st.columns(5)
with cc1:
    col_code  = st.selectbox("Ürün Kodu",    col_labels, index=0)
with cc2:
    col_name  = st.selectbox("Ürün Adı",     col_labels, index=1)
with cc3:
    col_orig  = st.selectbox("Çizili Fiyat", col_labels, index=2)
with cc4:
    col_disc  = st.selectbox("İndirimli",    col_labels, index=3)
with cc5:
    col_link  = st.selectbox("Ürün Linki",   col_labels, index=4)

# ── Template reminder ─────────────────────────────────────────────────────────
st.subheader("3. Template & Üretim")
if not template_file:
    st.info(
        "⬅️ Sol panelden template PNG'yi yükle — "
        "Photoshop'ta sadece arka plan katmanı + BAUHAUS logosu görünür olsun, "
        "ürün + metin katmanları kapalı olsun."
    )

# ── Generate ──────────────────────────────────────────────────────────────────
btn = st.button("🚀 Story'leri Oluştur", type="primary", use_container_width=True)

if btn:
    # Validation
    errors = []
    if not sheets_url:
        errors.append("Google Sheets URL boş.")
    if not template_file:
        errors.append("Template PNG yüklenmedi.")
    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    # Load template
    template = Image.open(template_file)

    # Parse Sheets URL → CSV export
    sheet_id = _extract_sheet_id(sheets_url)
    if not sheet_id:
        st.error("Geçersiz Google Sheets URL'si. URL'nin /d/... kısmını kontrol et.")
        st.stop()

    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df = pd.read_csv(csv_url, header=0)
    except Exception as ex:
        st.error(f"Google Sheets okunamadı: {ex}\nPaylaşım iznini kontrol et.")
        st.stop()

    if df.empty:
        st.warning("Sheets dosyası boş.")
        st.stop()

    # Map letter columns to 0-indexed positions
    col_idx = {
        "code":  _col_to_idx(col_code),
        "name":  _col_to_idx(col_name),
        "orig":  _col_to_idx(col_orig),
        "disc":  _col_to_idx(col_disc),
        "link":  _col_to_idx(col_link),
    }

    st.success(f"✅ {len(df)} ürün bulundu.")
    st.divider()

    progress_bar = st.progress(0.0, text="Başlatılıyor…")
    status_txt   = st.empty()
    preview_area = st.empty()

    zip_buf = io.BytesIO()
    errors_log = []

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (_, row) in enumerate(df.iterrows()):
            row = row.tolist()
            try:
                product_code   = str(row[col_idx["code"]]).strip()
                product_name   = str(row[col_idx["name"]]).strip()
                original_price = str(row[col_idx["orig"]]).strip()
                disc_price     = str(row[col_idx["disc"]]).strip()
                product_url    = str(row[col_idx["link"]]).strip()
            except IndexError:
                errors_log.append(f"Satır {i+1}: sütun indeksi aralık dışı.")
                continue

            pct = i / len(df)
            progress_bar.progress(pct, text=f"İşleniyor ({i+1}/{len(df)}): {product_name}")
            status_txt.caption(f"🔗 {product_url}")

            # Fetch product image
            prod_img = scraper.fetch_product_image(product_url)
            if prod_img is None:
                errors_log.append(
                    f"Satır {i+1} — **{product_name}**: görsel alınamadı, atlandı."
                )
                continue

            # Generate story
            try:
                story = generator.create_story(
                    template=template,
                    product_img=prod_img,
                    product_name=product_name,
                    original_price=original_price,
                    discounted_price=disc_price,
                    product_code=product_code,
                    bg_threshold=bg_threshold,
                )
            except Exception as ex:
                errors_log.append(f"Satır {i+1} — **{product_name}**: üretim hatası — {ex}")
                continue

            # Save to ZIP
            img_buf = io.BytesIO()
            story.save(img_buf, format="PNG")
            img_buf.seek(0)
            filename = f"{i+1:02d}_{product_code}.png"
            zf.writestr(filename, img_buf.getvalue())

            # Live preview (last generated)
            preview_area.image(
                story,
                caption=f"{i+1}. {product_name}",
                width=300,
            )

    progress_bar.progress(1.0, text="✅ Tamamlandı!")
    status_txt.empty()

    if errors_log:
        with st.expander(f"⚠️ {len(errors_log)} ürün atlandı"):
            for e in errors_log:
                st.markdown(f"- {e}")

    # Download button
    zip_buf.seek(0)
    st.download_button(
        label="⬇️ Tüm Story'leri İndir (ZIP)",
        data=zip_buf.getvalue(),
        file_name="bauhaus_stories.zip",
        mime="application/zip",
        use_container_width=True,
        type="primary",
    )
