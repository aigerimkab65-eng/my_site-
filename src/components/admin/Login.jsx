import { useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { adminApi, setCsrfToken } from "../../lib/adminApi.js";

export default function Login({ onSuccess }) {
  const { t, localizeError } = useI18n();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = await adminApi(
        "/api/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password }),
        },
        localizeError
      );
      if (data?.csrfToken) setCsrfToken(data.csrfToken);
      setPassword("");
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function togglePassword() {
    setShowPassword((prev) => !prev);
  }

  return (
    <section className="admin-card" id="login-card">
      <h1>{t("admin.loginTitle")}</h1>
      <p className="admin-note">{t("admin.loginNote")}</p>
      <form id="login-form" onSubmit={handleSubmit}>
        <label className="field">
          <span>{t("admin.password")}</span>
          <span className="password-wrap">
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              className={`password-eye${showPassword ? " is-open" : ""}`}
              id="toggle-password"
              type="button"
              aria-label={showPassword ? t("admin.hidePassword") : t("admin.showPassword")}
              aria-pressed={showPassword ? "true" : "false"}
              onClick={togglePassword}
            >
              <svg className="eye-on" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"
                />
                <circle
                  cx="12"
                  cy="12"
                  r="2.6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                />
              </svg>
              <svg className="eye-off" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  d="M3 3l18 18M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a18.4 18.4 0 0 1-3.2 3.8M6.1 6.8C3.7 8.5 2 12 2 12s3.5 6 10 6c1.3 0 2.5-.2 3.6-.6"
                />
              </svg>
            </button>
          </span>
        </label>
        {error ? (
          <p className="admin-error" id="login-error">
            {error}
          </p>
        ) : (
          <p className="admin-error" id="login-error" hidden />
        )}
        <button className="btn-outline" type="submit" disabled={submitting}>
          {t("admin.enter")}
        </button>
      </form>
    </section>
  );
}
