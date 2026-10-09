import { useI18n } from "../i18n/I18nContext.jsx";

const LABELS = { ru: "RU", kz: "KZ", en: "EN" };

export default function LangSwitch() {
  const { lang, setLang, t, langs } = useI18n();

  return (
    <div
      className="lang-switch"
      role="group"
      aria-label={t("lang.label")}
    >
      {langs.map((code, index) => (
        <span key={code} style={{ display: "contents" }}>
          {index > 0 ? <span aria-hidden="true">|</span> : null}
          <button
            type="button"
            data-lang={code}
            className={lang === code ? "is-active" : undefined}
            aria-pressed={lang === code ? "true" : "false"}
            onClick={() => setLang(code)}
          >
            {LABELS[code]}
          </button>
        </span>
      ))}
    </div>
  );
}
