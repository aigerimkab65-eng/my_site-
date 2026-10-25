import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { adminApi } from "../../lib/adminApi.js";
import { formatPrice } from "../../lib/adminFormat.js";
import { downloadFile } from "../../lib/downloadFile.js";

const EMPTY_FORM = {
  name: "",
  kind: "product",
  currency: "kzt",
  price: "",
  description: "",
};

function productImageSrc(product) {
  const image = (product?.image || "").replace(/^\//, "");
  if (!image) return "";
  return "/" + image;
}

function priceToInput(price) {
  if (price === null || price === undefined || price === "") return "";
  return String(price);
}

function ProductRow({
  product,
  checked,
  onToggle,
  onEdit,
  onDelete,
  deleting,
  t,
  lang,
}) {
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
      <div className="admin-product-row-actions">
        <button
          className="text-link"
          type="button"
          onClick={() => onEdit(product)}
          disabled={deleting}
        >
          {t("admin.edit")}
        </button>
        <button
          className="text-link admin-delete"
          type="button"
          onClick={() => onDelete(product)}
          disabled={deleting}
        >
          {deleting ? t("admin.deleting") : t("admin.delete")}
        </button>
      </div>
    </article>
  );
}

export default function Products({
  products,
  onRefresh,
  onDeleted,
  refreshing,
  hidden,
}) {
  const { t, lang, localizeError } = useI18n();
  const [selected, setSelected] = useState(() => new Set());
  const [pdfLang, setPdfLang] = useState(lang);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [existingImage, setExistingImage] = useState("");
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState("");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState("");
  const formRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    setPdfLang(lang);
  }, [lang]);

  useEffect(() => {
    return () => {
      if (photoPreview) URL.revokeObjectURL(photoPreview);
    };
  }, [photoPreview]);

  const ids = useMemo(() => products.map((p) => p.id), [products]);

  // Drop selections for products that disappeared after refresh.
  useEffect(() => {
    const alive = new Set(ids);
    setSelected((prev) => {
      let changed = false;
      const next = new Set();
      prev.forEach((id) => {
        if (alive.has(id)) next.add(id);
        else changed = true;
      });
      return changed ? next : prev;
    });
  }, [ids]);

  const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
  const selectedCount = selected.size;
  const isEditing = Boolean(editingId);

  function resetForm() {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setExistingImage("");
    setPhotoFile(null);
    setFormError("");
    if (photoPreview) URL.revokeObjectURL(photoPreview);
    setPhotoPreview("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handlePhotoChange(event) {
    const file = event.target.files?.[0] || null;
    if (photoPreview) URL.revokeObjectURL(photoPreview);
    setPhotoFile(file);
    setPhotoPreview(file ? URL.createObjectURL(file) : "");
  }

  function startEdit(product) {
    setFormError("");
    setError("");
    setEditingId(product.id);
    setForm({
      name: product.name || "",
      kind: product.kind === "service" ? "service" : "product",
      currency: product.currency || "kzt",
      price: priceToInput(product.price),
      description: product.description || "",
    });
    setExistingImage(productImageSrc(product));
    setPhotoFile(null);
    if (photoPreview) URL.revokeObjectURL(photoPreview);
    setPhotoPreview("");
    if (fileRef.current) fileRef.current.value = "";
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError("");
    setError("");

    const name = form.name.trim();
    if (!name) {
      setFormError(t("error.needName"));
      return;
    }
    if (!isEditing && !photoFile) {
      setFormError(t("error.needPhoto"));
      return;
    }

    const body = new FormData();
    body.append("name", name);
    body.append("kind", form.kind);
    body.append("currency", form.currency);
    body.append("price", String(form.price).trim());
    body.append("description", form.description.trim());
    if (photoFile) body.append("image", photoFile);

    setSaving(true);
    try {
      const url = isEditing ? "/api/products/" + editingId : "/api/products";
      await adminApi(url, { method: "POST", body }, localizeError);
      resetForm();
      await onRefresh();
    } catch (err) {
      setFormError(err.message || t("admin.loadError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(product) {
    if (!product?.id || deletingId) return;
    const label = product.name || product.id;
    if (!confirm(t("admin.confirmDelete").replace("{name}", label))) return;
    setError("");
    setFormError("");
    setDeletingId(product.id);
    try {
      await adminApi(
        "/api/products/" + encodeURIComponent(product.id),
        { method: "DELETE" },
        localizeError
      );
      // Drop from UI immediately so the site catalog can't look "stuck"
      // if a refresh fails or the user checks the public page right away.
      onDeleted?.(product.id);
      if (editingId === product.id) resetForm();
      await onRefresh();
    } catch (err) {
      setError(err.message || t("admin.loadError"));
    } finally {
      setDeletingId("");
    }
  }

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

  const previewSrc = photoPreview || existingImage;

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

      <div className="admin-card admin-product-form" ref={formRef}>
        <h2 className="admin-list-title">
          {isEditing ? t("admin.editTitle") : t("admin.newTitle")}
        </h2>
        <form id="product-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>{t("admin.name")}</span>
            <input
              type="text"
              name="name"
              maxLength={120}
              required
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              disabled={saving}
            />
          </label>

          <div className="field-row">
            <label className="field">
              <span>{t("admin.kind")}</span>
              <select
                name="kind"
                value={form.kind}
                onChange={(e) => updateField("kind", e.target.value)}
                disabled={saving}
              >
                <option value="product">{t("admin.kindProduct")}</option>
                <option value="service">{t("admin.kindService")}</option>
              </select>
            </label>
            <label className="field">
              <span>{t("admin.currency")}</span>
              <select
                name="currency"
                value={form.currency}
                onChange={(e) => updateField("currency", e.target.value)}
                disabled={saving}
              >
                <option value="kzt">{t("admin.currencyKzt")}</option>
                <option value="usd">{t("admin.currencyUsd")}</option>
                <option value="rub">{t("admin.currencyRub")}</option>
              </select>
            </label>
          </div>

          <label className="field">
            <span>{t("admin.price")}</span>
            <input
              type="text"
              name="price"
              inputMode="decimal"
              placeholder={t("admin.priceHint")}
              value={form.price}
              onChange={(e) => updateField("price", e.target.value)}
              disabled={saving}
            />
          </label>

          <label className="field">
            <span>{t("admin.description")}</span>
            <textarea
              name="description"
              rows={3}
              maxLength={2000}
              value={form.description}
              onChange={(e) => updateField("description", e.target.value)}
              disabled={saving}
            />
          </label>

          <label className="field">
            <span>{t("admin.photo")}</span>
            <input
              ref={fileRef}
              type="file"
              name="image"
              accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"
              required={!isEditing}
              onChange={handlePhotoChange}
              disabled={saving}
            />
          </label>

          {previewSrc ? (
            <div className="admin-product-form-preview">
              <img src={previewSrc} alt="" />
            </div>
          ) : null}

          {formError ? <p className="admin-error">{formError}</p> : null}

          <div className="admin-actions">
            <button className="btn-solid" type="submit" disabled={saving}>
              {isEditing ? t("admin.save") : t("admin.add")}
            </button>
            {isEditing ? (
              <button
                className="text-link"
                type="button"
                disabled={saving}
                onClick={resetForm}
              >
                {t("admin.cancel")}
              </button>
            ) : null}
          </div>
        </form>
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
                onEdit={startEdit}
                onDelete={handleDelete}
                deleting={deletingId === product.id}
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
