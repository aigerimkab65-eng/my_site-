import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { formatPrice } from "../../lib/adminFormat.js";
import { downloadFile } from "../../lib/downloadFile.js";

function productImageSrc(product) {
  const image = (product?.image || "").replace(/^\//, "");
  if (!image) return "";
  return "/" + image;
}

function ProductRow({ product, checked, onToggle, t, lang }) {
  const src = productImageSrc(product);
  const kindKey =
    (product.kind || "product") === "service"
      ? "admin.kindService"
      : "admin.kindProduct";

  return (
    <article className={`admin-product-row${checked ? " is-selected" : ""}`}>
      <label className="admin-product-check">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(product.id)}
          aria-label={product.name || product.id}
        />
      </label>
      <div className="admin-product-thumb" aria-hidden="true">
        {src ? (
          <img src={src} alt="" loading="lazy" />
        ) : (
          <span className="admin-product-thumb-fallback">
            {(product.name || "?").trim().charAt(0).toUpperCase() || "?"}
          </span>
        )}
      </div>
      <div className="admin-product-body">
        <strong>{product.name || "—"}</strong>
        <p className="admin-product-meta">
          <span className="admin-product-kind">{t(kindKey)}</span>
          <span aria-hidden="true"> · </span>
          <span>
            {formatPrice(product.price, product.currency || "kzt", t, lang)}
          </span>
        </p>
      </div>
    </article>
  );
}

export default function Products({
  products,
  onRefresh,
  refreshing,
  hidden,
}) {
  const { t, lang, localizeError } = useI18n();
  const [selected, setSelected] = useState(() => new Set());
  const [pdfLang, setPdfLang] = useState(lang);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPdfLang(lang);
  }, [lang]);

  const ids = useMemo(() => products.map((p) => p.id), [products]);
  const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
  const selectedCount = selected.size;

  function toggleOne(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(ids));
    }
  }

  async function handleDownloadPdf() {
    setError("");
    setDownloading(true);
    try {
      const params = new URLSearchParams();
      params.set("lang", pdfLang || "ru");
      if (selectedCount > 0) {
        params.set("ids", Array.from(selected).join(","));
      }
      await downloadFile("/api/products/catalog.pdf?" + params.toString(), {
        fallbackName: "Catalog.pdf",
        localizeError,
      });
    } catch (err) {
      setError(err.message || t("admin.pdfError"));
    } finally {
      setDownloading(false);
    }
  }

  const pdfButtonLabel =
    selectedCount > 0
      ? t("admin.pdfDownloadSelected").replace("{count}", String(selectedCount))
      : t("admin.pdfDownloadAll");

  return (
    <section className="admin-view" id="products-view" hidden={hidden}>
      <div className="admin-head">
        <div>
          <h1>{t("admin.listTitle")}</h1>
          <p className="admin-note">{t("admin.productsNote")}</p>
        </div>
        <div className="admin-head-actions">
          <button
            className="btn-outline"
            type="button"
            disabled={refreshing}
            onClick={onRefresh}
          >
            {t("admin.refresh")}
          </button>
        </div>
      </div>

      <div className="admin-pdf-bar">
        <label className="admin-pdf-lang">
          <span>{t("admin.pdfLang")}</span>
          <select
            value={pdfLang}
            onChange={(e) => setPdfLang(e.target.value)}
            disabled={downloading}
          >
            <option value="ru">RU</option>
            <option value="kz">KZ</option>
            <option value="en">EN</option>
          </select>
        </label>
        <button
          className="btn-solid"
          type="button"
          disabled={downloading || !products.length}
          onClick={handleDownloadPdf}
        >
          {downloading ? t("admin.pdfLoading") : pdfButtonLabel}
        </button>
        <span className="admin-pdf-count">
          {t("admin.pdfSelected").replace("{count}", String(selectedCount))}
        </span>
      </div>

      {error ? <p className="admin-error">{error}</p> : null}

      {!products.length ? (
        <p className="shop-empty">{t("admin.empty")}</p>
      ) : (
        <>
          <label className="admin-product-select-all">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
            />
            <span>{t("admin.pdfSelectAll")}</span>
          </label>
          <div className="admin-product-list" id="products-list">
            {products.map((product) => (
              <ProductRow
                key={product.id}
                product={product}
                checked={selected.has(product.id)}
                onToggle={toggleOne}
                t={t}
                lang={lang}
              />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
