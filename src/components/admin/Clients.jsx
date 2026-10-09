import { useEffect, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { adminApi } from "../../lib/adminApi.js";
import { formatDate, openClientWhatsApp } from "../../lib/adminFormat.js";

function ClientCard({ client, onHidden }) {
  const { t, lang, localizeError } = useI18n();
  const [note, setNote] = useState(client.note || "");
  const [saving, setSaving] = useState(false);
  const [saveLabel, setSaveLabel] = useState(null);
  const [hiding, setHiding] = useState(false);

  useEffect(() => {
    setNote(client.note || "");
  }, [client.note, client.phoneKey, client.id]);

  useEffect(() => {
    if (saveLabel == null) return undefined;
    const timer = setTimeout(() => setSaveLabel(null), 1200);
    return () => clearTimeout(timer);
  }, [saveLabel]);

  async function handleSave() {
    setSaving(true);
    try {
      await adminApi(
        "/api/clients/" + encodeURIComponent(client.phoneKey || client.id),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            note,
            name: client.name,
            phone: client.phone,
          }),
        },
        localizeError
      );
      setSaveLabel(t("admin.clientSaved"));
    } catch (error) {
      alert(error.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleHide() {
    if (!confirm(t("admin.confirmHideClient"))) return;
    setHiding(true);
    try {
      await adminApi(
        "/api/clients/" + encodeURIComponent(client.phoneKey || client.id),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            hidden: true,
            note,
            name: client.name,
            phone: client.phone,
          }),
        },
        localizeError
      );
      await onHidden();
    } catch (error) {
      alert(error.message);
      setHiding(false);
    }
  }

  return (
    <article className="client-card" data-phone-key={client.phoneKey || client.id}>
      <div className="client-card-top">
        <strong>{client.name || client.phone || t("admin.orderUntitled")}</strong>
        <span className="client-orders-badge">
          {t("admin.clientOrders").replace("{count}", String(client.orderCount || 0))}
        </span>
      </div>
      <p className="client-phone">{client.phone || "—"}</p>
      <p className="client-meta">
        {client.lastOrderAt
          ? t("admin.clientLastOrder").replace(
              "{date}",
              formatDate(client.lastOrderAt, lang)
            )
          : t("admin.clientNoOrders")}
      </p>
      <label className="client-note-field">
        <span className="client-note-label">{t("admin.clientNote")}</span>
        <textarea
          className="client-note"
          rows={3}
          maxLength={2000}
          placeholder={t("admin.clientNoteHint")}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <div className="client-actions">
        <button
          type="button"
          className="btn-outline"
          disabled={saving}
          onClick={handleSave}
        >
          {saveLabel || t("admin.clientSave")}
        </button>
        <button
          type="button"
          className="btn-solid"
          onClick={(event) => {
            event.preventDefault();
            openClientWhatsApp(client, t);
          }}
        >
          WhatsApp
        </button>
        <button
          type="button"
          className="text-link"
          disabled={hiding}
          onClick={handleHide}
        >
          {t("admin.clientHide")}
        </button>
      </div>
    </article>
  );
}

export default function Clients({
  clients,
  onRefresh,
  onHidden,
  refreshing,
  hidden,
}) {
  const { t } = useI18n();

  return (
    <section className="admin-view" id="clients-view" hidden={hidden}>
      <div className="admin-head">
        <div>
          <h1>{t("admin.clientsTitle")}</h1>
          <p className="admin-note">{t("admin.clientsNote")}</p>
        </div>
        <div className="admin-head-actions">
          <button
            className="btn-outline"
            id="refresh-clients"
            type="button"
            disabled={refreshing}
            onClick={onRefresh}
          >
            {t("admin.refresh")}
          </button>
        </div>
      </div>
      <div className="clients-grid" id="clients-list">
        {!clients.length ? (
          <p className="shop-empty">{t("admin.clientsEmpty")}</p>
        ) : (
          clients.map((client) => (
            <ClientCard
              key={client.phoneKey || client.id}
              client={client}
              onHidden={onHidden}
            />
          ))
        )}
      </div>
    </section>
  );
}
