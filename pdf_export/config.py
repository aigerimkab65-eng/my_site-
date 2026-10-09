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

# Catalog layout
PAGE_MARGIN = 36  # pt (~12.7 mm)
COLS = 2
ROWS = 3
CARDS_PER_PAGE = COLS * ROWS
IMAGE_MAX_SIDE = 1200
