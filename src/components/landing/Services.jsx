import { useMemo, useState } from "react";
import { useI18n } from "../../i18n/I18nContext.jsx";
import { useReveal } from "../../hooks/useReveal.js";
import {
  SERVICE_PRICES_KZT,
  formatServicePrice,
  getPriceCurrency,
  setPriceCurrency,
} from "../../lib/prices.js";
import { TELEGRAM_PORTFOLIO, buildOrderPayload } from "../../lib/whatsapp.js";

const AI_SERVICES = [
  {
    id: "ai.photo",
    titleKey: "services.ai.photo.title",
    textKey: "services.ai.photo.text",
    messageKey: "services.ai.photo.wa",
  },
  {
    id: "ai.video",
    titleKey: "services.ai.video.title",
    textKey: "services.ai.video.text",
  },
  {
    id: "ai.viz3d",
    titleKey: "services.ai.viz3d.title",
    textKey: "services.ai.viz3d.text",
  },
  {
    id: "ai.anim",
    titleKey: "services.ai.anim.title",
    textKey: "services.ai.anim.text",
  },
  {
    id: "ai.character",
    titleKey: "services.ai.character.title",
    textKey: "services.ai.character.text",
  },
];

const DESIGN_SERVICES = [
  {
    id: "design.carousel",
    titleKey: "services.design.carousel.title",
    textKey: "services.design.carousel.text",
  },
  {
    id: "design.card",
    titleKey: "services.design.card.title",
    textKey: "services.design.card.text",
  },
  {
    id: "design.info",
    titleKey: "services.design.info.title",
    textKey: "services.design.info.text",
  },
  {
    id: "design.pack",
    titleKey: "services.design.pack.title",
    textKey: "services.design.pack.text",
  },
];

function ServiceCard({ service, currency, onOpenLead, visitorId }) {
  const { t, lang } = useI18n();
  const title = t(service.titleKey);
  const message = service.messageKey
    ? t(service.messageKey)
    : t("services.waOrder").replace("{name}", title);
  const price = formatServicePrice(
    SERVICE_PRICES_KZT[service.id],
    currency,
    lang,
    t("services.price.from")
  );

  function handleOrder() {
    onOpenLead?.(
      buildOrderPayload({
        source: "service",
        serviceId: service.id,
        serviceName: title,
        message,
        visitorId,
        lang,
      })
    );
  }

  return (
    <article className="service-card">
      <h4>{title}</h4>
      <p className="service-desc">{t(service.textKey)}</p>
      <p className="service-price" data-price-id={service.id}>
        {price}
      </p>
      <div className="service-actions">
        <a
          className="btn-outline"
          href={TELEGRAM_PORTFOLIO}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("services.viewWork")}
        </a>
        <button
          type="button"
          className="btn-solid js-wa-order"
          data-wa-name={service.titleKey}
          {...(service.messageKey
            ? { "data-wa-message": service.messageKey }
            : {})}
          onClick={handleOrder}
        >
          {t("services.orderWa")}
        </button>
      </div>
    </article>
  );
}

export default function Services({ onOpenLead, visitorId }) {
  const { t, lang } = useI18n();
  const { ref: introRef, visible: introVisible } = useReveal();
  const [open, setOpen] = useState(false);
  const [currency, setCurrency] = useState(getPriceCurrency);

  const currencies = useMemo(
    () => [
      { code: "kzt", label: "₸ KZT" },
      { code: "rub", label: "₽ RUB" },
      { code: "usd", label: "$ USD" },
    ],
    []
  );

  function selectCurrency(code) {
    setPriceCurrency(code);
    setCurrency(code);
  }

  function handleCustom() {
    onOpenLead?.(
      buildOrderPayload({
        source: "custom",
        serviceName: t("services.cta.title"),
        message: t("services.waCustom"),
        visitorId,
        lang,
      })
    );
  }

  return (
    <section className="expo services-block" id="services">
      <div
        ref={introRef}
        className={`services-intro reveal${introVisible ? " is-visible" : ""}`}
      >
        <h2 className="expo-title">{t("services.title")}</h2>
        <p className="services-lead">{t("services.lead")}</p>
        <button
          type="button"
          className="btn-outline services-toggle"
          id="services-toggle"
          aria-expanded={open ? "true" : "false"}
          aria-controls="services-panel"
          onClick={() => setOpen((value) => !value)}
        >
          {t(open ? "services.toggle.close" : "services.toggle.open")}
        </button>
      </div>

      <div
        className={`services-panel${open ? " is-open" : ""}`}
        id="services-panel"
        aria-hidden={open ? "false" : "true"}
      >
        <div className="services-panel-inner">
          <div
            className="currency-switch"
            role="group"
            aria-label={t("services.currency.label")}
          >
            {currencies.map((item) => (
              <button
                key={item.code}
                type="button"
                className={`currency-btn${currency === item.code ? " is-active" : ""}`}
                data-currency={item.code}
                aria-pressed={currency === item.code ? "true" : "false"}
                onClick={() => selectCurrency(item.code)}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="service-cat">
            <h3 className="service-cat-title">{t("services.ai.title")}</h3>
            <div className="service-grid">
              {AI_SERVICES.map((service) => (
                <ServiceCard
                  key={service.id}
                  service={service}
                  currency={currency}
                  onOpenLead={onOpenLead}
                  visitorId={visitorId}
                />
              ))}
            </div>
          </div>

          <div className="service-cat">
            <h3 className="service-cat-title">{t("services.design.title")}</h3>
            <div className="service-grid">
              {DESIGN_SERVICES.map((service) => (
                <ServiceCard
                  key={service.id}
                  service={service}
                  currency={currency}
                  onOpenLead={onOpenLead}
                  visitorId={visitorId}
                />
              ))}
            </div>
          </div>

          <div className="service-cta">
            <h3>{t("services.cta.title")}</h3>
            <p>{t("services.cta.text")}</p>
            <button
              type="button"
              className="btn-solid js-wa-custom"
              onClick={handleCustom}
            >
              {t("services.cta.button")}
            </button>
            <p className="service-note">{t("services.note")}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
