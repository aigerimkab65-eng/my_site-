import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import LangSwitch from "../components/LangSwitch.jsx";
import { useI18n } from "../i18n/I18nContext.jsx";
import {
  AdminApiError,
  adminApi,
  clearCsrfToken,
  setCsrfToken,
} from "../lib/adminApi.js";
import Login from "../components/admin/Login.jsx";
import Orders from "../components/admin/Orders.jsx";
import Clients from "../components/admin/Clients.jsx";
import Products from "../components/admin/Products.jsx";
import OrderModal from "../components/admin/OrderModal.jsx";

function isAuthLost(error) {
  // Only 401 = session gone. CSRF/Origin 403 must NOT force logout (user is still logged in).
  return error instanceof AdminApiError && error.status === 401;
}

export default function AdminPage() {
  const { t, localizeError } = useI18n();
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState("orders");
  const [orderFilter, setOrderFilter] = useState("");
  const [orders, setOrders] = useState([]);
  const [orderStats, setOrderStats] = useState(null);
  const [clients, setClients] = useState([]);
  const [clientsTotal, setClientsTotal] = useState(0);
  const [products, setProducts] = useState([]);
  const [editingOrder, setEditingOrder] = useState(null);
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelError, setPanelError] = useState("");
  const [refreshingOrders, setRefreshingOrders] = useState(false);
  const [refreshingClients, setRefreshingClients] = useState(false);
  const [refreshingProducts, setRefreshingProducts] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const orderModalOpen = Boolean(editingOrder);

  useEffect(() => {
    document.body.classList.add("admin-page");
    return () => {
      document.body.classList.remove("admin-page");
      document.body.classList.remove("modal-open");
    };
  }, []);

  useEffect(() => {
    document.title = t("admin.pageTitle");
  }, [t]);

  useEffect(() => {
    if (orderModalOpen) {
      document.body.classList.add("modal-open");
    } else {
      document.body.classList.remove("modal-open");
    }
  }, [orderModalOpen]);

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key !== "Escape") return;
      if (orderModalOpen) setEditingOrder(null);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [orderModalOpen]);

  const forceLogout = useCallback(() => {
    clearCsrfToken();
    setAuthed(false);
    setEditingOrder(null);
    setOrders([]);
    setOrderStats(null);
    setClients([]);
    setClientsTotal(0);
    setProducts([]);
    setPanelError("");
    setPanelLoading(false);
  }, []);

  const handleAuthError = useCallback(
    (error, context) => {
      console.error("[admin]", context, error);
      if (isAuthLost(error)) {
        forceLogout();
        return true;
      }
      return false;
    },
    [forceLogout]
  );

  const loadOrders = useCallback(
    async (filter = orderFilter) => {
      const query = filter ? "?status=" + encodeURIComponent(filter) : "";
      const data = await adminApi("/api/orders" + query, {}, localizeError);
      if (!Array.isArray(data.orders)) {
        throw new AdminApiError("Некорректный ответ сервера (orders)", {
          status: 200,
          data,
        });
      }
      setOrders(data.orders);
      setOrderStats(
        data.stats && typeof data.stats === "object" ? data.stats : { total: 0, byStatus: {} }
      );
    },
    [orderFilter, localizeError]
  );

  const loadClients = useCallback(async () => {
    const data = await adminApi("/api/clients", {}, localizeError);
    if (!Array.isArray(data.clients)) {
      throw new AdminApiError("Некорректный ответ сервера (clients)", {
        status: 200,
        data,
      });
    }
    setClients(data.clients);
    setClientsTotal(
      typeof data.total === "number" ? data.total : data.clients.length
    );
  }, [localizeError]);

  const loadProducts = useCallback(async () => {
    const data = await adminApi("/api/products", {}, localizeError);
    if (!Array.isArray(data)) {
      throw new AdminApiError("Некорректный ответ сервера (products)", {
        status: 200,
        data,
      });
    }
    setProducts(data);
  }, [localizeError]);

  const loadPanelData = useCallback(async () => {
    setPanelLoading(true);
    setPanelError("");
    try {
      await Promise.all([loadOrders(), loadClients(), loadProducts()]);
    } catch (error) {
      if (handleAuthError(error, "loadPanelData")) return;
      setPanelError(error.message || t("admin.loadError"));
      throw error;
    } finally {
      setPanelLoading(false);
    }
  }, [loadOrders, loadClients, loadProducts, handleAuthError, t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await adminApi("/api/me", {}, localizeError);
        if (cancelled) return;
        if (me.ok) {
          if (me.csrfToken) setCsrfToken(me.csrfToken);
          setAuthed(true);
          setTab("orders");
          setChecking(false);
          try {
            await loadPanelData();
          } catch (error) {
            // panelError already set inside loadPanelData (unless auth lost)
            if (!isAuthLost(error)) {
              console.error("[admin] initial panel load failed", error);
            }
          }
          return;
        }
        clearCsrfToken();
      } catch (error) {
        console.error("[admin] session check failed", error);
        clearCsrfToken();
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Initial session check only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh active tab labels/lists when language changes
  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    (async () => {
      try {
        if (tab === "orders") await loadOrders();
        else if (tab === "clients") await loadClients();
        else if (tab === "products") await loadProducts();
        if (!cancelled) setPanelError("");
      } catch (error) {
        if (cancelled) return;
        if (handleAuthError(error, "lang-refresh")) return;
        setPanelError(error.message || t("admin.loadError"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleLoginSuccess() {
    setAuthed(true);
    setTab("orders");
    setPanelError("");
    try {
      await loadPanelData();
    } catch (error) {
      if (!isAuthLost(error)) {
        console.error("[admin] post-login load failed", error);
      }
    }
  }

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await adminApi("/api/logout", { method: "POST" }, localizeError);
    } catch (error) {
      console.error("[admin] logout request failed", error);
    } finally {
      forceLogout();
      setLoggingOut(false);
    }
  }

  async function handleFilterChange(status) {
    setOrderFilter(status);
    setRefreshingOrders(true);
    try {
      await loadOrders(status);
      setPanelError("");
    } catch (error) {
      if (handleAuthError(error, "filterOrders")) return;
      setPanelError(error.message);
    } finally {
      setRefreshingOrders(false);
    }
  }

  async function handleRefreshOrders() {
    setRefreshingOrders(true);
    try {
      await loadOrders();
      setPanelError("");
    } catch (error) {
      if (handleAuthError(error, "refreshOrders")) return;
      setPanelError(error.message);
    } finally {
      setRefreshingOrders(false);
    }
  }

  async function handleRefreshClients() {
    setRefreshingClients(true);
    try {
      await loadClients();
      setPanelError("");
    } catch (error) {
      if (handleAuthError(error, "refreshClients")) return;
      setPanelError(error.message);
    } finally {
      setRefreshingClients(false);
    }
  }

  async function handleRefreshProducts() {
    setRefreshingProducts(true);
    try {
      await loadProducts();
      setPanelError("");
    } catch (error) {
      if (handleAuthError(error, "refreshProducts")) return;
      setPanelError(error.message);
    } finally {
      setRefreshingProducts(false);
    }
  }

  async function handleOrdersChanged() {
    try {
      await Promise.all([loadOrders(), loadClients()]);
      setPanelError("");
    } catch (error) {
      if (handleAuthError(error, "ordersChanged")) return;
      setPanelError(error.message);
    }
  }

  async function handleRetryPanel() {
    try {
      await loadPanelData();
    } catch (_) {
      // panelError set by loadPanelData
    }
  }

  return (
    <>
      <header className="topbar">
        <Link className="brand-mark" to="/">
          <img
            className="logo-mark"
            src="/assets/logo.png?v=20"
            alt="AK"
            width={48}
            height={43}
          />
          <span className="logo-text">
            <span className="logo-name">Aigerim Kabaeva</span>
            <span className="logo-role">{t("admin.role")}</span>
          </span>
        </Link>
        <div className="topbar-side">
          <LangSwitch />
          <a className="text-link" href="/#services">
            {t("admin.toSite")}
          </a>
        </div>
      </header>

      <main className="admin-wrap">
        {checking ? (
          <section className="admin-card" aria-busy="true">
            <h1>{t("admin.checkingSession")}</h1>
            <p className="admin-note">{t("admin.checkingSessionNote")}</p>
          </section>
        ) : !authed ? (
          <Login onSuccess={handleLoginSuccess} />
        ) : (
          <section id="panel">
            {panelError ? (
              <div className="admin-card admin-panel-error" role="alert">
                <p className="admin-error">{panelError}</p>
                <button
                  className="btn-outline"
                  type="button"
                  onClick={handleRetryPanel}
                  disabled={panelLoading}
                >
                  {t("admin.retry")}
                </button>
              </div>
            ) : null}

            {panelLoading && !panelError ? (
              <p className="admin-note" aria-live="polite">
                {t("admin.loadingPanel")}
              </p>
            ) : null}

            <div className="admin-tabs" role="tablist" aria-label="Admin sections">
              <button
                className={`admin-tab${tab === "orders" ? " is-active" : ""}`}
                type="button"
                role="tab"
                id="tab-orders"
                aria-selected={tab === "orders" ? "true" : "false"}
                data-tab="orders"
                onClick={() => setTab("orders")}
              >
                {t("admin.tabOrders")}
              </button>
              <button
                className={`admin-tab${tab === "clients" ? " is-active" : ""}`}
                type="button"
                role="tab"
                id="tab-clients"
                aria-selected={tab === "clients" ? "true" : "false"}
                data-tab="clients"
                onClick={() => setTab("clients")}
              >
                <span>{t("admin.tabClients")}</span>
                <span
                  className="admin-tab-count"
                  id="clients-tab-count"
                  hidden={clientsTotal <= 0}
                >
                  {clientsTotal}
                </span>
              </button>
              <button
                className={`admin-tab${tab === "products" ? " is-active" : ""}`}
                type="button"
                role="tab"
                id="tab-products"
                aria-selected={tab === "products" ? "true" : "false"}
                data-tab="products"
                onClick={() => setTab("products")}
              >
                <span>{t("admin.tabProducts")}</span>
                <span
                  className="admin-tab-count"
                  hidden={products.length <= 0}
                >
                  {products.length}
                </span>
              </button>
            </div>

            <Orders
              orders={orders}
              stats={orderStats || {}}
              filter={orderFilter}
              onFilterChange={handleFilterChange}
              onRefresh={handleRefreshOrders}
              onLogout={handleLogout}
              onOpenOrder={setEditingOrder}
              refreshing={refreshingOrders}
              loggingOut={loggingOut}
              hidden={tab !== "orders"}
            />

            <Clients
              clients={clients}
              onRefresh={handleRefreshClients}
              onHidden={async () => {
                try {
                  await loadClients();
                } catch (error) {
                  if (handleAuthError(error, "hideClient")) return;
                  setPanelError(error.message);
                }
              }}
              refreshing={refreshingClients}
              hidden={tab !== "clients"}
            />

            <Products
              products={products}
              onRefresh={handleRefreshProducts}
              refreshing={refreshingProducts}
              hidden={tab !== "products"}
            />
          </section>
        )}
      </main>

      <OrderModal
        order={editingOrder}
        onClose={() => setEditingOrder(null)}
        onSaved={handleOrdersChanged}
        onDeleted={handleOrdersChanged}
      />
    </>
  );
}
