/**
 * Public starting prices (KZT). Keep in sync with ai/tools/catalog.py
 * (SERVICE_PRICES_KZT). Server overwrites CRM priceFrom from that catalog.
 */
export const SERVICE_PRICES_KZT = {
  "ai.photo": 25000,
  "ai.video": 45000,
  "ai.viz3d": 30000,
  "ai.anim": 15000,
  "ai.character": 30000,
  "design.carousel": 25000,
  "design.card": 10000,
  "design.info": 10000,
  "design.pack": 35000,
  "sites.card": 50000,
  "sites.landing": 100000,
};

/** Approximate FX for display only (not for billing). ~540₸/$ and ~5.5₸/₽. */
export const KZT_TO_RUB = 0.18;
export const KZT_TO_USD = 0.00185;
export const CURRENCY_KEY = "price-currency";
export const CURRENCY_SYMBOL = { kzt: "₸", rub: "₽", usd: "$" };

export function getPriceCurrency() {
  try {
    const saved = localStorage.getItem(CURRENCY_KEY);
    if (saved === "rub" || saved === "usd" || saved === "kzt") return saved;
  } catch (_) {}
  return "kzt";
}

export function setPriceCurrency(currency) {
  try {
    localStorage.setItem(CURRENCY_KEY, currency);
  } catch (_) {}
}

export function convertFromKzt(amountKzt, currency) {
  const value = Number(amountKzt);
  if (!Number.isFinite(value)) return 0;
  if (currency === "rub") return Math.round(value * KZT_TO_RUB);
  if (currency === "usd") return Math.round(value * KZT_TO_USD);
  return Math.round(value);
}

export function formatServicePrice(amountKzt, currency, lang, fromLabel) {
  const amount = convertFromKzt(amountKzt, currency);
  const locale = lang === "en" ? "en-US" : "ru-RU";
  const number = new Intl.NumberFormat(locale).format(amount);
  const symbol = CURRENCY_SYMBOL[currency] || CURRENCY_SYMBOL.kzt;
  if (lang === "kz") return number + " " + symbol + " бастап";
  const prefix = fromLabel || "от";
  return prefix + " " + number + " " + symbol;
}
