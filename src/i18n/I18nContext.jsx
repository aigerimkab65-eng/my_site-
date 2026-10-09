import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ERROR_KEYS, I18N, LANGS, STORAGE_KEY } from "./translations.js";

const I18nContext = createContext(null);

function readStoredLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (LANGS.includes(saved)) return saved;
  } catch (_) {}
  return "ru";
}

function applyDocumentLang(lang) {
  document.documentElement.lang = lang === "kz" ? "kk" : lang;
  document.documentElement.setAttribute("data-lang", lang);
  document.documentElement.removeAttribute("data-lang-pending");
}

function translate(key, lang) {
  const dict = I18N[lang] || I18N.ru;
  if (dict[key] != null) return dict[key];
  return I18N.ru[key] != null ? I18N.ru[key] : key;
}

export function I18nProvider({
  children,
  titleKey,
  descriptionKey = "meta.description",
}) {
  const [lang, setLangState] = useState(readStoredLang);

  const setLang = useCallback((next) => {
    const lang = LANGS.includes(next) ? next : "ru";
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (_) {}
    setLangState(lang);
  }, []);

  const t = useCallback(
    (key) => translate(key, lang),
    [lang]
  );

  const localizeError = useCallback(
    (message) => {
      const key = ERROR_KEYS[message];
      return key ? translate(key, lang) : message;
    },
    [lang]
  );

  useEffect(() => {
    applyDocumentLang(lang);

    if (titleKey) {
      document.title = translate(titleKey, lang);
    }

    if (descriptionKey) {
      const meta = document.querySelector('meta[name="description"]');
      if (meta) {
        meta.setAttribute("content", translate(descriptionKey, lang));
      }
    }

    window.dispatchEvent(new CustomEvent("langchange", { detail: lang }));
  }, [lang, titleKey, descriptionKey]);

  const value = useMemo(
    () => ({ lang, setLang, t, localizeError, langs: LANGS }),
    [lang, setLang, t, localizeError]
  );

  return (
    <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}
