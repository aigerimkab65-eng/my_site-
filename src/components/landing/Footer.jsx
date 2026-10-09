import { useI18n } from "../../i18n/I18nContext.jsx";
import {
  TELEGRAM_DM,
  TELEGRAM_PORTFOLIO,
  buildOrderPayload,
} from "../../lib/whatsapp.js";

export default function Footer({ onOpenLead, visitorId }) {
  const { t, lang } = useI18n();

  function openFooterWa() {
    onOpenLead?.(
      buildOrderPayload({
        source: "contact",
        serviceName: t("contact.whatsapp") || "WhatsApp",
        message: t("chat.waText"),
        visitorId,
        lang,
      })
    );
  }

  return (
    <footer className="footer">
      <span>© 2026 Aigerim Kabaeva</span>
      <div className="footer-links">
        <button type="button" className="footer-wa-btn js-wa-contact" onClick={openFooterWa}>
          WhatsApp
        </button>
        <a href={TELEGRAM_DM} target="_blank" rel="noopener noreferrer">
          Telegram
        </a>
        <a
          href={TELEGRAM_PORTFOLIO}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("nav.work")}
        </a>
      </div>
    </footer>
  );
}
