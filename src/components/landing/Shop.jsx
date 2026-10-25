import { useCallback, useEffect, useMemo, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";
import { formatPrice } from "../../lib/adminFormat.js";
import { buildOrderPayload } from "../../lib/whatsapp.js";

function productImageSrc(product) {
  const image = (product?.image || "").replace(/^\//, "");
  if (!image) return "";
  return "/" + image;
}

function ProductCard({ product, onOpenLead, visitorId, t, lang }) {
  const src = productImageSrc(product);
  const kindKey =
    (product.kind || "product") === "service"
      ? "shop.kind.service"
      : "shop.kind.product";
  const price = formatPrice(product.price, product.currency || "kzt", t, lang);

  function handleOrder() {
    const name = product.name || "";
    onOpenLead?.(
      buildOrderPayload({
        source: "shop",
        serviceId: product.id,
        serviceName: name,
        message: t("shop.orderText") + name,
        visitorId,
        lang,
        priceFrom:
          product.price === "" || product.price == null ? null : product.price,
        currency: product.currency || "kzt",
      })
    );
  }

  return (
    <article className="shop-card">
      {src ? (
        <img src={src} alt="" loading="lazy" />
      ) : (
        <div className="shop-card-placeholder" aria-hidden="true" />
      )}
      <div className="shop-body">
        <p className="shop-kind">{t(kindKey)}</p>
        <h3>{product.name || "—"}</h3>
        <p className="shop-price">{price}</p>
        {product.description ? <p>{product.description}</p> : null}
        <button className="btn-outline" type="button" onClick={handleOrder}>
          {t("shop.order")}
        </button>
      </div>
    </article>
  );
}

export default function Shop({ onOpenLead, visitorId }) {
  const { t, lang, localizeError } = useI18n();
  const { ref, visible } = useReveal();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [currencyFilter, setCurrencyFilter] = useState("all");
  const [kindFilter, setKindFilter] = useState("all");

  const loadProducts = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/products", { cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(
          localizeError(
            (data && data.error) || t("shop.error")
          )
        );
      }
      if (!Array.isArray(data)) {
        throw new Error(t("shop.error"));
      }
      setProducts(data);
    } catch (err) {
      setProducts([]);
      setError(err.message || t("shop.error"));
    } finally {
      setLoading(false);
    }
  }, [localizeError, t]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const filtered = useMemo(() => {
    return products.filter((product) => {
      const currency = (product.currency || "kzt").toLowerCase();
      const kind = (product.kind || "product").toLowerCase();
      if (currencyFilter !== "all" && currency !== currencyFilter) return false;
      if (kindFilter !== "all" && kind !== kindFilter) return false;
      return true;
    });
  }, [products, currencyFilter, kindFilter]);

  return (
    <section
      className={`shop reveal${visible ? " is-visible" : ""}`}
      id="shop"
      ref={ref}
    >
      <h2 className="expo-title">{t("shop.title")}</h2>

      {!loading && !error && products.length > 0 ? (
        <div className="shop-filters">
          <label className="shop-filter">
            <span>{t("shop.filter.kind")}</span>
            <select
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
            >
              <option value="all">{t("shop.filter.all")}</option>
              <option value="product">{t("shop.kind.product")}</option>
              <option value="service">{t("shop.kind.service")}</option>
            </select>
          </label>
          <label className="shop-filter">
            <span>{t("shop.filter.currency")}</span>
            <select
              value={currencyFilter}
              onChange={(e) => setCurrencyFilter(e.target.value)}
            >
              <option value="all">{t("shop.filter.all")}</option>
              <option value="kzt">KZT</option>
              <option value="usd">USD</option>
              <option value="rub">RUB</option>
            </select>
          </label>
        </div>
      ) : null}

      {loading ? (
        <p className="shop-empty">{t("shop.loading")}</p>
      ) : error ? (
        <div className="shop-empty">
          <p>{error}</p>
          <button className="btn-outline" type="button" onClick={loadProducts}>
            {t("shop.retry")}
          </button>
        </div>
      ) : !products.length ? (
        <p className="shop-empty">{t("shop.empty")}</p>
      ) : !filtered.length ? (
        <p className="shop-empty">{t("shop.filter.empty")}</p>
      ) : (
        <div className="shop-grid">
          {filtered.map((product) => (
            <ProductCard
              key={product.id}
              product={product}
              onOpenLead={onOpenLead}
              visitorId={visitorId}
              t={t}
              lang={lang}
            />
          ))}
        </div>
      )}
    </section>
  );
}
