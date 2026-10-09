"""Brand colors and public contacts for PDF export (copied from the site, not imported)."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
FONTS_DIR = PACKAGE_DIR / "fonts"
ROOT = PACKAGE_DIR.parent
LOGO_PATH = ROOT / "assets" / "logo.png"

# Colors from src/styles.css :root
MILKY = "#f5f1ea"
SANDY = "#c8ad8d"
GOLD = "#b8955a"
GRAPHITE = "#222222"
GRAY = "#6e675e"
WHITE = "#ffffff"
LINE = (34 / 255, 34 / 255, 34 / 255, 0.14)  # rgba for ReportLab Color

# Site contacts (same values as src/lib/whatsapp.js / landing)
BRAND_NAME = "Aigerim Kabaeva"
BRAND_ROLE = "AI Creator"
TELEGRAM_DM = "https://t.me/aigerim_aicreator"
TELEGRAM_HANDLE = "@aigerim_aicreator"
WHATSAPP = "https://wa.me/77007002132"
WHATSAPP_DISPLAY = "+7 700 700 21 32"
# No separate website domain on the landing — portfolio channel is the public work link.
SITE_URL = "https://t.me/portfolioaigerimkabayeva"

# Seller requisites for invoice PDF (replace with real values later).
SELLER = {
    "name": "ИП Кабаева Айгерим",
    "bin": "000000000000",
    "address": "г. Алматы, ул. Примерная, д. 1",
    "bank": "АО «Народный Банк Казахстана»",
    "iik": "KZ000000000000000000",
    "bik": "HSBKKZKX",
    "kbe": "19",
    "phone": "+7 700 700 21 32",
    "telegram": "@aigerim_aicreator",
    "director_fio": "Кабаева А. А.",
    # 0 = Без НДС; 16 = НДС выделяется из цены (price × 16 / 116)
    "vat_rate": 0,
}

# Catalog layout
PAGE_MARGIN = 36  # pt (~12.7 mm)
COLS = 2
ROWS = 3
CARDS_PER_PAGE = COLS * ROWS
IMAGE_MAX_SIDE = 1200
