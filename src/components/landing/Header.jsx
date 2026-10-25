import LangSwitch from "../LangSwitch.jsx";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { TELEGRAM_PORTFOLIO } from "../../lib/whatsapp.js";

export default function Header({ onContactOpen }) {
  const { t } = useI18n();

  return (
    <header className="topbar">
      <a className="brand-mark" href="#top" aria-label="Aigerim Kabaeva — AI Creator">
        <img
          className="logo-mark"
          src="/assets/logo.png?v=20"
          alt="AK"
          width="48"
          height="43"
        />
        <span className="logo-text">
          <span className="logo-name">Aigerim Kabaeva</span>
          <span className="logo-role">AI Creator</span>
        </span>
      </a>
      <nav className="pill-nav" aria-label={t("nav.label")}>
        <a href="#services">{t("nav.services")}</a>
        <a href="#shop">{t("nav.shop")}</a>
        <a href="#process">{t("nav.process")}</a>
        <a
          href={TELEGRAM_PORTFOLIO}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("nav.work")}
        </a>
        <a
          href="#contact"
          className="js-contact-open"
          onClick={(event) => {
            event.preventDefault();
            onContactOpen?.();
          }}
        >
          {t("nav.contact")}
        </a>
        <LangSwitch />
      </nav>
    </header>
  );
}
