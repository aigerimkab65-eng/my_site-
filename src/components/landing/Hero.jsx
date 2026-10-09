import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";
import { TELEGRAM_DM, TELEGRAM_PORTFOLIO } from "../../lib/whatsapp.js";

export default function Hero() {
  const { t } = useI18n();
  const { ref, visible } = useReveal(true);

  return (
    <section
      ref={ref}
      className={`hero reveal${visible ? " is-visible" : ""}`}
    >
      <div className="hero-copy">
        <h1>
          <span>AI CONTENT</span>
          <span>&amp; DIGITAL.</span>
        </h1>
        <p className="tagline">{t("hero.tagline")}</p>
        <div className="hero-actions">
          <a
            className="btn-outline"
            href={TELEGRAM_DM}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("hero.discuss")}
          </a>
          <a
            className="text-link"
            href={TELEGRAM_PORTFOLIO}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("hero.work")}
          </a>
        </div>
      </div>
      <div className="hero-visual">
        <img src="/assets/hero.jpg" alt={t("hero.alt")} />
      </div>
    </section>
  );
}
