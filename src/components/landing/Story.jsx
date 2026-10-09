import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";

export default function Story() {
  const { t } = useI18n();
  const { ref, visible } = useReveal();

  return (
    <section
      ref={ref}
      className={`story reveal${visible ? " is-visible" : ""}`}
      id="about"
    >
      <div className="story-inner">
        <div className="story-text">
          <h2>{t("story.title")}</h2>
          <p>{t("story.p1")}</p>
          <p>{t("story.p2")}</p>
        </div>
        <div className="story-photo">
          <img src="/assets/about.jpg" alt={t("story.alt")} />
        </div>
      </div>
    </section>
  );
}
