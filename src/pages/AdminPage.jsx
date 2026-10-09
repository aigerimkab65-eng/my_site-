import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import LangSwitch from "../components/LangSwitch.jsx";
import { useI18n } from "../i18n/I18nContext.jsx";
import { adminApi } from "../lib/adminApi.js";
import Login from "../components/admin/Login.jsx";
import Orders from "../components/admin/Orders.jsx";
import Clients from "../components/admin/Clients.jsx";
import Products from "../components/admin/Products.jsx";
import OrderModal from "../components/admin/OrderModal.jsx";

export default function AdminPage() {
  const { t, localizeError } = useI18n();
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState("orders");
  const [orderFilter, setOrderFilter] = useState("");
  const [orders, setOrders] = useState([]);
  const [orderStats, setOrderStats] = useState({});
  const [clients, setClients] = useState([]);
  const [clientsTotal, setClientsTotal] = useState(0);
  const [products, setProducts] = useState([]);
  const [editingOrder, setEditingOrder] = useState(null);
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

  const loadOrders = useCallback(
    async (filter = orderFilter) => {
      const query = filter ? "?status=" + encodeURIComponent(filter) : "";
      const data = await adminApi("/api/orders" + query, {}, localizeError);
      setOrders(data.orders || []);
      setOrderStats(data.stats || {});
    },
    [orderFilter, localizeError]
  );

  const loadClients = useCallback(async () => {
    const data = await adminApi("/api/clients", {}, localizeError);
    const list = data.clients || [];
    setClients(list);
    setClientsTotal(data.total != null ? data.total : list.length);
  }, [localizeError]);

  const loadProducts = useCallback(async () => {
    const data = await adminApi("/api/products", {}, localizeError);
    setProducts(Array.isArray(data) ? data : []);
  }, [localizeError]);

  const loadPanelData = useCallback(async () => {
    await Promise.all([loadOrders(), loadClients(), loadProducts()]);
  }, [loadOrders, loadClients, loadProducts]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await adminApi("/api/me", {}, localizeError);
        if (cancelled) return;
        if (me.ok) {
          setAuthed(true);
          setTab("orders");
          setChecking(false);
          try {
            await loadPanelData();
          } catch (_) {
            // Panel stays open; lists can be refreshed manually.
          }
          return;
        }
      } catch (_) {
        // not logged in
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

  // Re-render labels/lists when language changes (t identity changes with lang)
  useEffect(() => {
    if (!authed) return;
    if (tab === "orders") loadOrders().catch(() => {});
    else if (tab === "clients") loadClients().catch(() => {});
    else if (tab === "products") loadProducts().catch(() => {});
  }, [t]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleLoginSuccess() {
    setAuthed(true);
    setTab("orders");
    await loadPanelData();
  }

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await adminApi("/api/logout", { method: "POST" }, localizeError);
    } catch (_) {
      // Still leave the panel even if the request fails.
    } finally {
      setEditingOrder(null);
      setAuthed(false);
      setLoggingOut(false);
    }
  }

  async function handleFilterChange(status) {
    setOrderFilter(status);
    try {
      await loadOrders(status);
    } catch (error) {
      alert(error.message);
    }
  }

  async function handleRefreshOrders() {
    setRefreshingOrders(true);
    try {
      await loadOrders();
    } catch (error) {
      alert(error.message);
    } finally {
      setRefreshingOrders(false);
    }
  }

  async function handleRefreshClients() {
    setRefreshingClients(true);
    try {
      await loadClients();
    } catch (error) {
      alert(error.message);
    } finally {
      setRefreshingClients(false);
    }
  }

  async function handleRefreshProducts() {
    setRefreshingProducts(true);
    try {
      await loadProducts();
    } catch (error) {
      alert(error.message);
    } finally {
      setRefreshingProducts(false);
    }
  }

  async function handleOrdersChanged() {
    await Promise.all([loadOrders(), loadClients()]);
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
            <h1>{t("admin.loginTitle")}</h1>
            <p className="admin-note">{t("admin.loginNote")}</p>
          </section>
        ) : !authed ? (
          <Login onSuccess={handleLoginSuccess} />
        ) : (
          <section id="panel">
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
              stats={orderStats}
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
              onHidden={loadClients}
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
