import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { useModalA11y } from "../../hooks/useModalA11y.js";
import { formatPrice } from "../../lib/adminFormat.js";
import {
  buildLeadWhatsAppMessage,
  loadLeadContact,
  prepareExternalTab,
  saveLeadContact,
  waLink,
} from "../../lib/whatsapp.js";

function leadPriceLabel(priceFrom, currency, t, lang) {
  if (priceFrom === null || priceFrom === undefined) return "";
  return formatPrice(priceFrom, currency || "kzt", t, lang);
}

export default function LeadModal({ open, order, onClose }) {
  const { t, lang, localizeError } = useI18n();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef(null);
  const cardRef = useRef(null);
  const mountedRef = useRef(true);
  const externalRef = useRef(null);
  const submittingRef = useRef(false);
  // Same key for every retry while this modal stay open — prevents duplicate orders
  // if the network fails after the server already saved the lead.
  const idempotencyKeyRef = useRef(null);

  useModalA11y(open, cardRef, nameRef);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      externalRef.current?.cancel();
      externalRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const contact = loadLeadContact();
    setName(contact.name);
    setPhone(contact.phone);
    setError("");
    setSubmitting(false);
    submittingRef.current = false;
    idempotencyKeyRef.current = null;
    return undefined;
  }, [open, order]);

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key === "Escape" && !submittingRef.current) onClose?.();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function requestClose() {
    if (submittingRef.current) return;
    onClose?.();
  }

  const serviceLine = order?.serviceName
    ? t("lead.serviceLine").replace("{name}", order.serviceName)
    : t("lead.serviceFallback");

  async function handleSubmit(event) {
    event.preventDefault();
    if (!order || submittingRef.current) return;
    const trimmedName = name.trim();
    const trimmedPhone = phone.trim();
    setError("");
    if (trimmedName.length < 2) {
      setError(t("lead.errorName"));
      nameRef.current?.focus();
      return;
    }
    if (trimmedPhone.replace(/\D+/g, "").length < 10) {
      setError(t("lead.errorPhone"));
      return;
    }

    const buildMessage = (priceFrom, currency) =>
      buildLeadWhatsAppMessage(order.message, trimmedName, trimmedPhone, t, {
        priceLabel: leadPriceLabel(priceFrom, currency, t, lang),
      });

    const payload = {
      ...order,
      clientName: trimmedName,
      clientPhone: trimmedPhone,
      message: buildMessage(order.priceFrom, order.currency),
    };

    // Lock before opening a tab so a double-click cannot spawn two flows.
    submittingRef.current = true;
    setSubmitting(true);

    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `lead-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    const idempotencyKey = idempotencyKeyRef.current;

    // Must open while still in the click gesture — before any await.
    const external = prepareExternalTab();
    externalRef.current = external;

    try {
      const response = await fetch("/api/orders", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({ ...payload, idempotencyKey }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          localizeError(data.error || t("lead.errorSave"))
        );
      }
      saveLeadContact(trimmedName, data.clientPhone || trimmedPhone);
      // Prefer server price (catalog/DB truth) for the WhatsApp text.
      const waMessage = buildMessage(
        data.priceFrom !== undefined ? data.priceFrom : order.priceFrom,
        data.currency || order.currency
      );
      external.finish(waLink(waMessage));
      externalRef.current = null;
      if (mountedRef.current) onClose?.();
    } catch (err) {
      external.cancel();
      externalRef.current = null;
      if (mountedRef.current) {
        setError(err.message || t("lead.errorSave"));
      }
    } finally {
      submittingRef.current = false;
      if (mountedRef.current) setSubmitting(false);
    }
  }

  return (
    <div className="lead-modal" id="lead-modal" hidden={!open}>
      <div
        className="lead-modal-backdrop"
        id="lead-modal-backdrop"
        onClick={requestClose}
      />
      <div
        ref={cardRef}
        className="lead-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lead-modal-title"
        tabIndex={-1}
      >
        <button
          className="lead-modal-close"
          id="lead-modal-close"
          type="button"
          aria-label={t("lead.close")}
          onClick={requestClose}
          disabled={submitting}
        >
          ×
        </button>
        <p className="lead-modal-eyebrow">{t("lead.eyebrow")}</p>
        <h2 id="lead-modal-title">{t("lead.title")}</h2>
        <p className="lead-modal-text" id="lead-modal-service">
          {serviceLine}
        </p>
        <form id="lead-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>{t("lead.name")}</span>
            <input
              ref={nameRef}
              type="text"
              name="name"
              id="lead-name"
              maxLength={80}
              autoComplete="name"
              required
              placeholder={t("lead.nameHint")}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="field">
            <span>{t("lead.phone")}</span>
            <input
              type="tel"
              name="phone"
              id="lead-phone"
              maxLength={20}
              autoComplete="tel"
              required
              placeholder={t("lead.phoneHint")}
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
          </label>
          <p
            className="lead-modal-error"
            id="lead-form-error"
            hidden={!error}
          >
            {error}
          </p>
          <div className="lead-modal-actions">
            <button
              className="btn-solid"
              type="submit"
              id="lead-submit"
              disabled={submitting}
              data-i18n="lead.submit"
            >
              {t("lead.submit")}
            </button>
            <button
              className="text-link"
              type="button"
              id="lead-cancel"
              onClick={requestClose}
              disabled={submitting}
            >
              {t("lead.cancel")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
