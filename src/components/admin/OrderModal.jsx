import { useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { useModalA11y } from "../../hooks/useModalA11y.js";
import { adminApi } from "../../lib/adminApi.js";
import { downloadFile } from "../../lib/downloadFile.js";
import {
  formatDate,
  formatPrice,
  getOrderClientName,
  getOrderClientPhone,
  openOrderWhatsApp,
  orderWaHref,
  sourceLabel,
} from "../../lib/adminFormat.js";

export default function OrderModal({ order, onClose, onSaved, onDeleted }) {
  const { t, lang, localizeError } = useI18n();
  const [status, setStatus] = useState("new");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [invoiceLang, setInvoiceLang] = useState("ru");
  const [downloadingInvoice, setDownloadingInvoice] = useState(false);
  const statusRef = useRef(null);
  const cardRef = useRef(null);

  const open = Boolean(order);
  useModalA11y(open, cardRef, statusRef);

  useEffect(() => {
    if (!order) return;
    setStatus(order.status || "new");
    setNotes(order.notes || "");
    setError("");
    const orderLang = String(order.lang || "ru").toLowerCase();
    setInvoiceLang(
      orderLang === "kz" || orderLang === "en" ? orderLang : "ru"
    );
  }, [order]);

  if (!open) {
    return (
      <div className="admin-modal" id="order-modal" hidden>
        <div className="admin-modal-backdrop" id="order-modal-backdrop" />
        <div
          className="admin-modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="order-form-title"
        />
      </div>
    );
  }

  const clientName = getOrderClientName(order);
  const clientPhone = getOrderClientPhone(order);
  const clientWa = orderWaHref(order);
  const meta = [
    formatDate(order.createdAt, lang),
    sourceLabel(order.source, t),
    order.priceFrom != null
      ? formatPrice(order.priceFrom, order.currency || "kzt", t, lang)
      : t("shop.onRequest"),
    (order.lang || "ru").toUpperCase(),
  ].join(" · ");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    if (!order?.id) return;
    setSaving(true);
    try {
      await adminApi(
        "/api/orders/" + order.id,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, notes }),
        },
        localizeError
      );
      onClose();
      await onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!order?.id || deleting) return;
    if (!confirm(t("admin.confirmDeleteOrder"))) return;
    setError("");
    setDeleting(true);
    try {
      await adminApi(
        "/api/orders/" + order.id,
        { method: "DELETE" },
        localizeError
      );
      onClose();
      await onDeleted();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  }

  function handleWa(event) {
    event.preventDefault();
    openOrderWhatsApp(order, t);
  }

  async function handleInvoicePdf() {
    if (!order?.id || downloadingInvoice) return;
    setError("");
    setDownloadingInvoice(true);
    try {
      const params = new URLSearchParams();
      params.set("lang", invoiceLang || "ru");
      await downloadFile(
        "/api/orders/" +
          encodeURIComponent(order.id) +
          "/invoice.pdf?" +
          params.toString(),
        {
          fallbackName: "Schet-faktura.pdf",
          localizeError,
        }
      );
    } catch (err) {
      setError(err.message || t("admin.invoicePdfError"));
    } finally {
      setDownloadingInvoice(false);
    }
  }

  return (
    <div className="admin-modal" id="order-modal">
      <div
        className="admin-modal-backdrop"
        id="order-modal-backdrop"
        onClick={onClose}
      />
      <div
        ref={cardRef}
        className="admin-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="order-form-title"
        tabIndex={-1}
      >
        <div className="admin-modal-head">
          <h2 id="order-form-title">{t("admin.orderEditTitle")}</h2>
          <button
            className="admin-modal-close"
            id="close-order-modal"
            type="button"
            aria-label={t("admin.close")}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <form id="order-form" onSubmit={handleSubmit}>
          <input type="hidden" name="id" id="order-id" value={order.id} readOnly />
          <p className="crm-order-meta" id="order-meta">
            {meta}
          </p>
          <div className="field-row">
            <label className="field">
              <span>{t("admin.clientName")}</span>
              <input
                type="text"
                name="clientName"
                id="order-client-name"
                readOnly
                value={clientName || "—"}
              />
            </label>
            <label className="field">
              <span>{t("admin.clientPhone")}</span>
              <input
                type="text"
                name="clientPhone"
                id="order-client-phone"
                readOnly
                value={clientPhone || "—"}
              />
            </label>
          </div>
          <label className="field">
            <span>{t("admin.orderService")}</span>
            <input
              type="text"
              name="serviceName"
              id="order-service"
              readOnly
              value={order.serviceName || "—"}
            />
          </label>
          <label className="field">
            <span>{t("admin.orderMessage")}</span>
            <textarea
              name="message"
              id="order-message"
              rows={4}
              readOnly
              value={order.message || ""}
            />
          </label>
          <label className="field">
            <span>{t("admin.orderStatus")}</span>
            <select
              name="status"
              id="order-status"
              required
              ref={statusRef}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="new">{t("admin.status.new")}</option>
              <option value="in_progress">{t("admin.status.in_progress")}</option>
              <option value="done">{t("admin.status.done")}</option>
              <option value="cancelled">{t("admin.status.cancelled")}</option>
            </select>
          </label>
          <label className="field">
            <span>{t("admin.orderNotes")}</span>
            <textarea
              name="notes"
              id="order-notes"
              rows={3}
              maxLength={2000}
              placeholder={t("admin.orderNotesHint")}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          {error ? (
            <p className="admin-error" id="order-form-error">
              {error}
            </p>
          ) : (
            <p className="admin-error" id="order-form-error" hidden />
          )}
          <div className="admin-actions">
            <button
              className="btn-outline"
              type="submit"
              id="order-save-btn"
              disabled={saving}
            >
              {t("admin.save")}
            </button>
            {clientWa ? (
              <a
                className="btn-solid"
                id="order-open-wa"
                href={clientWa}
                target="_blank"
                rel="noopener noreferrer"
                onClick={handleWa}
              >
                {t("admin.openWa")}
              </a>
            ) : (
              <button
                className="btn-solid"
                type="button"
                id="order-open-wa"
                disabled
              >
                {t("admin.openWa")}
              </button>
            )}
            <label className="admin-invoice-lang">
              <span className="visually-hidden">{t("admin.invoicePdfLang")}</span>
              <select
                value={invoiceLang}
                onChange={(e) => setInvoiceLang(e.target.value)}
                disabled={downloadingInvoice}
                aria-label={t("admin.invoicePdfLang")}
              >
                <option value="ru">RU</option>
                <option value="kz">KZ</option>
                <option value="en">EN</option>
              </select>
            </label>
            <button
              className="btn-outline"
              type="button"
              id="order-invoice-pdf-btn"
              disabled={downloadingInvoice}
              onClick={handleInvoicePdf}
            >
              {downloadingInvoice
                ? t("admin.invoicePdfLoading")
                : t("admin.invoicePdfDownload")}
            </button>
            <button
              className="text-link admin-delete"
              type="button"
              id="order-delete-btn"
              disabled={deleting || saving}
              onClick={handleDelete}
            >
              {deleting ? t("admin.deleting") : t("admin.delete")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
