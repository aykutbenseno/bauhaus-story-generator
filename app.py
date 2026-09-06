"""
BAUHAUS Story Generator — Streamlit Web App
"""
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

import generator
import scraper
import psd_reader


# ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

def _extract_sheet_id(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1) if m else None


def _col_to_idx(letter: str) -> int:
    return ord(letter.upper()) - ord("A")


# ── Sayfa ayarları ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BAUHAUS Story Generator",
    page_icon="🏠",
    layout="centered",
)

st.title("🏠 BAUHAUS Story Generator")
st.markdown("Google Sheets'teki ürün listesinden otomatik Instagram Story üretir.")
st.divider()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Ayarlar")

    # ── Template seçimi ───────────────────────────────────────────────────
    st.subheader("📐 Template")
    template_mode = st.radio(
        "Template kaynağı",
        ["PSD dosyası (önerilen)", "PNG dosyası"],
        index=0,
        help=(
            "PSD: Photoshop dosyası yükle — pozisyonlar otomatik okunur.\n"
            "PNG: Temiz arka plan PNG yükle — koordinatlar sabit kalır."
        ),
    )

    zones = {}
    template = None

    if template_mode == "PSD dosyası (önerilen)":
        psd_file = st.file_uploader(
            "PSD Dosyası",
            type=["psd"],
            help=(
                "Photoshop dosyası. İçinde şu isimli gizli katmanlar olmalı:\n"
                "zone_name / zone_price / zone_box / zone_image / zone_code"
            ),
        )
        if psd_file:
            with st.spinner("PSD okunuyor…"):
                psd_bytes = psd_file.read()
                template, zones = psd_reader.read_psd(psd_bytes)

            if template:
                missing = psd_reader.validate_zones(zones)
                if missing:
                    st.warning(
                        f"Şu zone katmanları bulunamadı: {', '.join(missing)}\n"
                        "Eksik zone'lar için sabit koordinatlar kullanılacak."
                    )
                with st.expander("🗺️ Zone pozisyonları", expanded=False):
                    st.markdown(psd_reader.zones_summary(zones))
                st.success("✅ PSD yüklendi")
            else:
                st.error("PSD açılamadı. psd-tools kurulu mu?")
    else:
        template_file = st.file_uploader(
            "PNG Template",
            type=["png", "jpg", "jpeg"],
            help="Ürün ve metin içermeyen temiz arka plan şablonu.",
        )
        if template_file:
            template = Image.open(template_file)

    # ── Font seçimi ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔤 Fontlar")
    assets_dir = Path("assets")
    available_fonts = sorted(
        [f.stem for f in assets_dir.glob("*.otf")]
        + [f.stem for f in assets_dir.glob("*.ttf")]
    ) if assets_dir.exists() else []

    default_name_idx = (
        available_fonts.index("TazWt07Bold")
        if "TazWt07Bold" in available_fonts else 0
    )
    default_disc_idx = (
        available_fonts.index("TazBlack")
        if "TazBlack" in available_fonts else 0
    )

    if available_fonts:
        font_name = st.selectbox(
            "Metin & Fiyat fontu", available_fonts, index=default_name_idx
        )
        font_disc = st.selectbox(
            "İndirim fiyatı fontu", available_fonts, index=default_disc_idx
        )
    else:
        st.caption("Font bulunamadı — assets/ klasörünü kontrol et.")
        font_name = "TazWt07Bold"
        font_disc = "TazBlack"

    # ── Görsel ayarları ───────────────────────────────────────────────────
    st.divider()
    st.subheader("🖼️ Görsel")
    bg_threshold = st.slider(
        "Beyaz arka plan silme hassasiyeti",
        min_value=200,
        max_value=255,
        value=238,
        help="Lifestyle görseller için rembg otomatik devreye girer.",
    )

    st.divider()
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

# ── Sütun eşleştirme ──────────────────────────────────────────────────────────
st.subheader("2. Sütun Sırası")
st.caption(
    "Excel'deki sütun harflerini seç. "
    "Örnek: A=Ürün Kodu, B=Ürün Adı, C=Çizili, D=İndirimli, E=Link"
)

col_labels      = ["A", "B", "C", "D", "E", "F", "G", "H"]
col_labels_none = ["(yok)"] + col_labels

cc1, cc2, cc3, cc4, cc5 = st.columns(5)
with cc1:
    col_code = st.selectbox("Ürün Kodu",    col_labels, index=0)
with cc2:
    col_name = st.selectbox("Ürün Adı",     col_labels, index=1)
with cc3:
    col_orig = st.selectbox("Çizili Fiyat", col_labels, index=2)
with cc4:
    col_disc = st.selectbox("İndirimli",    col_labels, index=3)
with cc5:
    col_link = st.selectbox("Ürün Linki",   col_labels, index=4)

st.caption(
    "**İpucu:** Görsel otomatik alınamıyorsa Sheets'e bir 'Görsel URL' sütunu ekle."
)
cc6, _ = st.columns([1, 4])
with cc6:
    col_img_url = st.selectbox(
        "Görsel URL (opsiyonel)",
        col_labels_none,
        index=0,
        help="Scraper çalışmıyorsa direkt CDN linki için sütun seç.",
    )

# ── Template hatırlatması ─────────────────────────────────────────────────────
st.subheader("3. Template & Üretim")
if template is None:
    st.info(
        "⬅️ Sol panelden template yükle.\n\n"
        "**PSD (önerilen):** Photoshop'ta zone_ katmanlarını ekle, gizli kaydet.\n"
        "**PNG:** Photoshop'ta ürün + metin katmanlarını kapat, export et."
    )

# ── Üret butonu ───────────────────────────────────────────────────────────────
btn = st.button("🚀 Story'leri Oluştur", type="primary", use_container_width=True)

if btn:
    # Doğrulama
    errors = []
    if not sheets_url:
        errors.append("Google Sheets URL boş.")
    if template is None:
        errors.append("Template yüklenmedi (PSD veya PNG).")
    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    # Sheets → CSV
    sheet_id = _extract_sheet_id(sheets_url)
    if not sheet_id:
        st.error("Geçersiz Google Sheets URL'si.")
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

    col_idx = {
        "code":    _col_to_idx(col_code),
        "name":    _col_to_idx(col_name),
        "orig":    _col_to_idx(col_orig),
        "disc":    _col_to_idx(col_disc),
        "link":    _col_to_idx(col_link),
        "img_url": _col_to_idx(col_img_url) if col_img_url != "(yok)" else None,
    }

    st.success(f"✅ {len(df)} ürün bulundu.")
    if zones:
        st.info(f"📐 PSD zone pozisyonları aktif ({len(zones)}/5 zone okundu)")
    st.divider()

    progress_bar = st.progress(0.0, text="Başlatılıyor…")
    status_txt   = st.empty()
    preview_area = st.empty()

    zip_buf    = io.BytesIO()
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
                img_url_direct = (
                    str(row[col_idx["img_url"]]).strip()
                    if col_idx["img_url"] is not None
                    else None
                )
            except IndexError:
                errors_log.append(f"Satır {i+1}: sütun indeksi aralık dışı.")
                continue

            pct = i / len(df)
            progress_bar.progress(pct, text=f"İşleniyor ({i+1}/{len(df)}): {product_name}")
            status_txt.caption(f"🔗 {product_url}")

            # Ürün görseli çek
            prod_img = scraper.fetch_product_image(
                product_url,
                direct_image_url=img_url_direct,
            )
            if prod_img is None:
                errors_log.append(
                    f"Satır {i+1} — **{product_name}**: görsel alınamadı, atlandı."
                )
                continue

            # Story oluştur
            try:
                story = generator.create_story(
                    template=template,
                    product_img=prod_img,
                    product_name=product_name,
                    original_price=original_price,
                    discounted_price=disc_price,
                    product_code=product_code,
                    bg_threshold=bg_threshold,
                    zones=zones if zones else None,
                    font_name=font_name,
                    font_disc=font_disc,
                )
            except Exception as ex:
                errors_log.append(f"Satır {i+1} — **{product_name}**: üretim hatası — {ex}")
                continue

            # ZIP'e ekle
            img_buf = io.BytesIO()
            story.save(img_buf, format="PNG")
            img_buf.seek(0)
            filename = f"{i+1:02d}_{product_code}.png"
            zf.writestr(filename, img_buf.getvalue())

            # Canlı önizleme
            preview_area.image(story, caption=f"{i+1}. {product_name}", width=300)

    progress_bar.progress(1.0, text="✅ Tamamlandı!")
    status_txt.empty()

    if errors_log:
        with st.expander(f"⚠️ {len(errors_log)} ürün atlandı"):
            for e in errors_log:
                st.markdown(f"- {e}")

    # İndir
    zip_buf.seek(0)
    st.download_button(
        label="⬇️ Tüm Story'leri İndir (ZIP)",
        data=zip_buf.getvalue(),
        file_name="bauhaus_stories.zip",
        mime="application/zip",
        use_container_width=True,
        type="primary",
    )
