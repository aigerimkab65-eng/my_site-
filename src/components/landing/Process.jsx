import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";

export default function Process() {
  const { t } = useI18n();
  const { ref, visible } = useReveal();

  return (
    <section
      ref={ref}
      className={`process-block reveal${visible ? " is-visible" : ""}`}
      id="process"
    >
      <div className="process-inner">
        <p className="script light">{t("process.label")}</p>
        <h2>{t("process.title")}</h2>
        <ol className="process-list">
          <li dangerouslySetInnerHTML={{ __html: t("process.1") }} />
          <li dangerouslySetInnerHTML={{ __html: t("process.2") }} />
          <li dangerouslySetInnerHTML={{ __html: t("process.3") }} />
          <li dangerouslySetInnerHTML={{ __html: t("process.4") }} />
        </ol>
      </div>
    </section>
  );
}
