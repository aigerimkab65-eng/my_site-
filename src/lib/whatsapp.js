import { SERVICE_PRICES_KZT } from "./prices.js";

export const WA_NUMBER = "77007002132";
export const WA_BASE = `https://wa.me/${WA_NUMBER}`;
export const TELEGRAM_DM = "https://t.me/aigerim_aicreator";
export const TELEGRAM_PORTFOLIO = "https://t.me/portfolioaigerimkabayeva";
export const LEAD_CONTACT_KEY = "ak-lead-contact";

export function waLink(text) {
  return `${WA_BASE}?text=${encodeURIComponent(text)}`;
}

/**
 * Open a blank tab synchronously (while still in a user gesture), then navigate
 * it after an async save. Avoids popup blockers that kill window.open after await.
 * Returns { finish(url), cancel() }.
 */
export function prepareExternalTab() {
  let tab = null;
  try {
    tab = window.open("about:blank", "_blank");
  } catch (_) {
    tab = null;
  }

  function cancel() {
    if (tab && !tab.closed) {
      try {
        tab.close();
      } catch (_) {}
    }
    tab = null;
  }

  function finish(url) {
    const href = String(url || "");
    if (!href) {
      cancel();
      return false;
    }
    if (tab && !tab.closed) {
      try {
        tab.opener = null;
      } catch (_) {}
      try {
        tab.location.href = href;
        return true;
      } catch (_) {
        cancel();
      }
    }
    // Fallback when the blank tab was blocked.
    try {
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      return true;
    } catch (_) {
      return false;
    }
  }

  return { finish, cancel };
}

export function buildOrderPayload({
  source,
  serviceId = "",
  serviceName = "",
  message = "",
  visitorId = "",
  lang = "ru",
  priceFrom,
  currency,
}) {
  const resolvedPrice =
    priceFrom !== undefined
      ? priceFrom
      : serviceId && SERVICE_PRICES_KZT[serviceId] != null
        ? SERVICE_PRICES_KZT[serviceId]
        : null;
  return {
    source,
    serviceId,
    serviceName,
    message,
    priceFrom: resolvedPrice,
    currency: currency || "kzt",
    lang,
    visitorId: visitorId || "",
    pagePath:
      typeof window !== "undefined"
        ? window.location.pathname + window.location.hash
        : "/",
  };
}

export function buildLeadWhatsAppMessage(
  baseMessage,
  name,
  phone,
  t,
  { priceLabel } = {}
) {
  const lines = [];
  if (baseMessage) lines.push(baseMessage);
  if (priceLabel) lines.push(t("lead.waPrice") + ": " + priceLabel);
  lines.push("");
  lines.push(t("lead.waName") + ": " + name);
  lines.push(t("lead.waPhone") + ": " + phone);
  return lines.join("\n").trim();
}

export function loadLeadContact() {
  try {
    const raw = localStorage.getItem(LEAD_CONTACT_KEY);
    if (!raw) return { name: "", phone: "" };
    const data = JSON.parse(raw);
    if (data && typeof data === "object") {
      return {
        name: data.name ? String(data.name).slice(0, 80) : "",
        phone: data.phone ? String(data.phone).slice(0, 20) : "",
      };
    }
  } catch (_) {}
  return { name: "", phone: "" };
}

export function saveLeadContact(name, phone) {
  try {
    localStorage.setItem(LEAD_CONTACT_KEY, JSON.stringify({ name, phone }));
  } catch (_) {}
}
