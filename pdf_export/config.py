"""Brand colors and public contacts for PDF export (copied from the site, not imported)."""

from pathlib import Path
import os

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

# Seller requisites for invoice PDF — loaded from .env (no hardcoded stubs).
# Required for invoice generation; optional fields may be empty.
SELLER_ENV_KEYS = {
    "name": "SELLER_NAME",
    "bin": "SELLER_BIN",
    "address": "SELLER_ADDRESS",
    "bank": "SELLER_BANK",
    "iik": "SELLER_IIK",
    "bik": "SELLER_BIK",
    "kbe": "SELLER_KBE",
    "phone": "SELLER_PHONE",
    "telegram": "SELLER_TELEGRAM",
    "director_fio": "SELLER_DIRECTOR",
    "vat_rate": "SELLER_VAT_RATE",
}

SELLER_REQUIRED = (
    "name",
    "bin",
    "address",
    "bank",
    "iik",
    "bik",
    "kbe",
    # vat_rate must be set explicitly (0 = Без НДС). Empty env is an error, not a silent default.
    "vat_rate",
)

SELLER_FIELD_LABELS = {
    "name": "SELLER_NAME (название / ИП)",
    "bin": "SELLER_BIN (БИН/ИИН)",
    "address": "SELLER_ADDRESS (адрес)",
    "bank": "SELLER_BANK (банк)",
    "iik": "SELLER_IIK (ИИК)",
    "bik": "SELLER_BIK (БИК)",
    "kbe": "SELLER_KBE (КБе)",
    "phone": "SELLER_PHONE",
    "telegram": "SELLER_TELEGRAM",
    "director_fio": "SELLER_DIRECTOR",
    "vat_rate": "SELLER_VAT_RATE",
}


class SellerConfigError(ValueError):
    """Raised when required seller requisites are missing from the environment."""

    def __init__(self, missing_keys):
        self.missing = list(missing_keys)
        labels = [SELLER_FIELD_LABELS.get(k, k) for k in self.missing]
        message = (
            "Не заполнены реквизиты продавца для счёта: "
            + ", ".join(labels)
            + ". Задайте их в .env и перезапустите сервер."
        )
        super().__init__(message)


def _load_dotenv_best_effort():
    """Read ROOT/.env into os.environ without overwriting existing values."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        return


def get_seller(*, require_complete=True):
    """
    Load seller requisites from environment variables.

    If require_complete is True (invoice generation), raise SellerConfigError
    when any required field is empty — never invent placeholder values.
    """
    _load_dotenv_best_effort()
    seller = {}
    for field, env_key in SELLER_ENV_KEYS.items():
        raw = os.environ.get(env_key, "")
        seller[field] = str(raw).strip() if raw is not None else ""

    # vat_rate: required when generating invoices. Empty = missing (no silent 0%/12%).
    # Explicit "0" means Без НДС and is written as such on the PDF.
    vat_raw = seller.get("vat_rate") or ""
    vat_parsed = None
    if vat_raw != "":
        try:
            vat_parsed = float(vat_raw)
            if vat_parsed < 0 or vat_parsed > 100 or not (vat_parsed == vat_parsed):
                raise ValueError("out of range")
        except ValueError as exc:
            if require_complete:
                raise SellerConfigError(["vat_rate"]) from exc
            vat_parsed = None

    if require_complete:
        missing = [
            key
            for key in SELLER_REQUIRED
            if key != "vat_rate" and not seller.get(key)
        ]
        if vat_raw == "" or vat_parsed is None:
            missing.append("vat_rate")
        if missing:
            raise SellerConfigError(missing)

    seller["vat_rate"] = 0.0 if vat_parsed is None else vat_parsed
    return seller


# Catalog layout
PAGE_MARGIN = 36  # pt (~12.7 mm)
COLS = 2
ROWS = 3
CARDS_PER_PAGE = COLS * ROWS
IMAGE_MAX_SIDE = 1200
