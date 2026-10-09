import { useI18n } from "../../i18n/I18nContext.jsx";
import {
  formatDate,
  formatPrice,
  getOrderClientName,
  getOrderClientPhone,
  openOrderWhatsApp,
  sourceLabel,
  statusLabel,
} from "../../lib/adminFormat.js";

const FILTERS = [
  { status: "", key: "admin.filterAll" },
  { status: "new", key: "admin.status.new" },
  { status: "in_progress", key: "admin.status.in_progress" },
  { status: "done", key: "admin.status.done" },
  { status: "cancelled", key: "admin.status.cancelled" },
];

function CrmStats({ stats }) {
  const { t } = useI18n();
  const items = [
    { key: "total", label: t("admin.statTotal"), value: stats?.total || 0 },
    { key: "new", label: t("admin.status.new"), value: stats?.byStatus?.new || 0 },
    {
      key: "in_progress",
      label: t("admin.status.in_progress"),
      value: stats?.byStatus?.in_progress || 0,
    },
    { key: "done", label: t("admin.status.done"), value: stats?.byStatus?.done || 0 },
  ];

  return (
    <div className="crm-stats" id="crm-stats">
      {items.map((item) => (
        <div
          key={item.key}
          className={`crm-stat${item.key === "new" && item.value > 0 ? " is-hot" : ""}`}
        >
          <strong>{String(item.value)}</strong>
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function OrderRow({ order, onOpen }) {
  const { t, lang } = useI18n();
  const name = getOrderClientName(order);
  const phone = getOrderClientPhone(order);
  const clientLabel = [name, phone].filter(Boolean).join(" · ");
  const titleText = clientLabel || order.serviceName || t("admin.orderUntitled");

  function handleWa(event) {
    event.preventDefault();
    openOrderWhatsApp(order, t);
  }

  return (
    <article className={`crm-item status-${order.status || "new"}`}>
      <div className="crm-item-top">
        {phone ? (
          <button
            type="button"
            className="crm-client-link"
            title="WhatsApp"
            onClick={handleWa}
          >
            {titleText}
          </button>
        ) : (
          <strong>{titleText}</strong>
        )}
        <span className="crm-badge">{statusLabel(order.status, t)}</span>
      </div>
      <p className="crm-item-meta">
        {[
          formatDate(order.createdAt, lang),
          order.serviceName || sourceLabel(order.source, t),
          order.priceFrom != null
            ? formatPrice(order.priceFrom, order.currency || "kzt", t, lang)
            : t("shop.onRequest"),
        ].join(" · ")}
      </p>
      <p className="crm-item-message">{order.message || "—"}</p>
      <div className="crm-item-actions">
        <button type="button" className="text-link" onClick={() => onOpen(order)}>
          {t("admin.openOrder")}
        </button>
        <button type="button" className="text-link" onClick={handleWa}>
          WhatsApp
        </button>
      </div>
    </article>
  );
}

export default function Orders({
  orders,
  stats,
  filter,
  onFilterChange,
  onRefresh,
  onLogout,
  onOpenOrder,
  refreshing,
  loggingOut,
  hidden,
}) {
  const { t } = useI18n();

  return (
    <section className="admin-view" id="orders-view" hidden={hidden}>
      <div className="admin-head">
        <div>
          <h1>{t("admin.ordersTitle")}</h1>
          <p className="admin-note">{t("admin.ordersNote")}</p>
        </div>
        <div className="admin-head-actions">
          <button
            className="btn-outline"
            id="refresh-orders"
            type="button"
            disabled={refreshing}
            onClick={onRefresh}
          >
            {t("admin.refresh")}
          </button>
          <button
            className="text-link"
            id="logout"
            type="button"
            disabled={loggingOut}
            onClick={onLogout}
          >
            {t("admin.logout")}
          </button>
        </div>
      </div>
      <CrmStats stats={stats} />
      <div
        className="crm-filters"
        role="group"
        aria-label={t("admin.filterLabel")}
      >
        {FILTERS.map((item) => (
          <button
            key={item.status || "all"}
            type="button"
            className={`crm-filter${filter === item.status ? " is-active" : ""}`}
            data-status={item.status}
            onClick={() => onFilterChange(item.status)}
          >
            {t(item.key)}
          </button>
        ))}
      </div>
      <div className="crm-list" id="order-list">
        {!orders.length ? (
          <p className="shop-empty">{t("admin.ordersEmpty")}</p>
        ) : (
          orders.map((order) => (
            <OrderRow key={order.id} order={order} onOpen={onOpenOrder} />
          ))
        )}
      </div>
    </section>
  );
}
