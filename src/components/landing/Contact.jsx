import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";
import {
  TELEGRAM_DM,
  TELEGRAM_PORTFOLIO,
  buildOrderPayload,
} from "../../lib/whatsapp.js";

export default function Contact({ onOpenLead, visitorId }) {
  const { t, lang } = useI18n();
  const { ref, visible } = useReveal();

  function openContactWa() {
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
    <section
      ref={ref}
      className={`tickets reveal${visible ? " is-visible" : ""}`}
      id="contact"
    >
      <div className="tickets-inner">
        <div className="tickets-copy">
          <h2 dangerouslySetInnerHTML={{ __html: t("contact.title") }} />
          <ul className="meta-list">
            <li dangerouslySetInnerHTML={{ __html: t("contact.format") }} />
          </ul>
          <div className="contact-btns">
            <a
              className="btn-fill"
              href={TELEGRAM_DM}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("contact.telegram")}
            </a>
            <button
              type="button"
              className="btn-ghost-light js-wa-contact"
              onClick={openContactWa}
            >
              {t("contact.whatsapp")}
            </button>
            <a
              className="btn-ghost-light"
              href={TELEGRAM_PORTFOLIO}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("contact.work")}
            </a>
          </div>
        </div>
        <div className="tickets-visual" aria-hidden="true">
          <div className="ticket t1">
            <span>{t("ticket.project")}</span>
            <strong>{t("ticket.visual")}</strong>
            <em>{t("ticket.meta")}</em>
          </div>
          <div className="ticket t2">
            <span>{t("ticket.project")}</span>
            <strong>{t("ticket.video")}</strong>
            <em>{t("ticket.meta")}</em>
          </div>
        </div>
      </div>
    </section>
  );
}
