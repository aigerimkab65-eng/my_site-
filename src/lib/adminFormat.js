import { I18N } from "../i18n/translations.js";

export function translateFor(key, lang) {
  const code = lang === "kz" || lang === "en" ? lang : "ru";
  const dict = I18N[code] || I18N.ru;
  if (dict[key] != null) return dict[key];
  return I18N.ru[key] != null ? I18N.ru[key] : key;
}

export function currencySuffix(currency, t) {
  const code = (currency || "kzt").toLowerCase();
  if (code === "usd") return t("shop.currency.usd");
  if (code === "rub") return t("shop.currency.rub");
  return t("shop.currency.kzt");
}

export function formatPrice(value, currency, t, lang = "ru") {
  if (value === "" || value === null || value === undefined) return t("shop.onRequest");
  const num = Number(value);
  if (!Number.isFinite(num)) return t("shop.onRequest");
  const locale = lang === "en" ? "en-US" : "ru-RU";
  return new Intl.NumberFormat(locale).format(num) + currencySuffix(currency, t);
}

export function statusLabel(status, t) {
  const key = "admin.status." + status;
  const value = t(key);
  return value === key ? status : value;
}

export function sourceLabel(source, t) {
  const key = "admin.source." + source;
  const value = t(key);
  return value === key ? source : value;
}

export function formatDate(ts, lang = "ru") {
  const value = Number(ts);
  if (!Number.isFinite(value)) return "—";
  const locale = lang === "en" ? "en-US" : lang === "kz" ? "kk-KZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

export function orderLang(order) {
  const lang = String(order?.lang || "ru").toLowerCase();
  return lang === "kz" || lang === "en" ? lang : "ru";
}

export function normalizeWaPhone(phone) {
  let digits = String(phone || "").replace(/\D+/g, "");
  if (!digits) return "";
  if (digits.length === 11 && digits.startsWith("8")) digits = "7" + digits.slice(1);
  else if (digits.length === 10) digits = "7" + digits;
  return digits;
}

export function getOrderClientName(order) {
  const direct = String(order?.clientName || "").trim();
  if (direct && direct !== "—") return direct;
  const msg = String(order?.message || "");
  const labeled = msg.match(/(?:Имя|Name|Аты)\s*:\s*([^\n\r.]+)/i);
  if (labeled) return labeled[1].trim();
  return "";
}

export function getOrderClientPhone(order) {
  const direct = String(order?.clientPhone || "").trim();
  if (direct && direct !== "—") return direct;
  const msg = String(order?.message || "");
  const labeled = msg.match(/(?:Телефон|Phone|телефон)\s*:\s*([+\d\s()-]+)/i);
  if (labeled) return labeled[1].trim();
  return "";
}

export function buildClientWaReply(order) {
  const lang = orderLang(order);
  const name = getOrderClientName(order);
  const service = String(order?.serviceName || order?.lastServiceName || "").trim();
  let template;
  if (service) {
    template = name ? "admin.waReplyNamedService" : "admin.waReplyService";
  } else {
    template = name ? "admin.waReplyNamed" : "admin.waReply";
  }
  return translateFor(template, lang)
    .replace("{name}", name)
    .replace("{service}", service);
}

export function waHref(phone, message) {
  const digits = normalizeWaPhone(phone);
  if (!digits) return "";
  const text = message || "";
  return "https://wa.me/" + digits + (text ? "?text=" + encodeURIComponent(text) : "");
}

export function orderWaHref(order) {
  if (!order) return "";
  const phone = getOrderClientPhone(order);
  if (!phone) return "";
  return waHref(phone, buildClientWaReply(order));
}

export function openOrderWhatsApp(order, t) {
  if (!order) return;
  const href = orderWaHref(order);
  if (!href) {
    alert(t("admin.waNoPhone"));
    return;
  }
  window.open(href, "_blank", "noopener,noreferrer");
}

export function openClientWhatsApp(client, t) {
  if (!client) return;
  const orderLike = {
    clientName: client.name,
    clientPhone: client.phone,
    serviceName: client.lastServiceName || "",
    lang: client.lang || "ru",
  };
  openOrderWhatsApp(orderLike, t);
}
