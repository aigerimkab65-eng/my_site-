import { useEffect, useRef } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { useModalA11y } from "../../hooks/useModalA11y.js";
import {
  TELEGRAM_DM,
  TELEGRAM_PORTFOLIO,
  buildOrderPayload,
} from "../../lib/whatsapp.js";

export default function ContactModal({ open, onClose, onOpenLead, visitorId }) {
  const { t, lang } = useI18n();
  const closeRef = useRef(null);
  const cardRef = useRef(null);

  useModalA11y(open, cardRef, closeRef);

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function openWa() {
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
    <div className="lead-modal" id="contact-modal" hidden={!open}>
      <div
        className="lead-modal-backdrop"
        id="contact-modal-backdrop"
        onClick={onClose}
      />
      <div
        ref={cardRef}
        className="lead-modal-card contact-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="contact-modal-title"
        tabIndex={-1}
      >
        <button
          ref={closeRef}
          className="lead-modal-close"
          id="contact-modal-close"
          type="button"
          aria-label={t("lead.close")}
          onClick={onClose}
        >
          ×
        </button>
        <p className="lead-modal-eyebrow">{t("nav.contact")}</p>
        <h2
          id="contact-modal-title"
          dangerouslySetInnerHTML={{ __html: t("contact.title") }}
        />
        <p
          className="lead-modal-text"
          dangerouslySetInnerHTML={{ __html: t("contact.format") }}
        />
        <div className="contact-modal-actions">
          <a
            className="btn-solid"
            href={TELEGRAM_DM}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("contact.telegram")}
          </a>
          <button
            type="button"
            className="btn-outline js-wa-contact"
            onClick={openWa}
          >
            {t("contact.whatsapp")}
          </button>
          <a
            className="btn-outline"
            href={TELEGRAM_PORTFOLIO}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("contact.work")}
          </a>
        </div>
      </div>
    </div>
  );
}
