import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { load, save } from "../lib/storage";
import en from "./locales/en";
import ru from "./locales/ru";
import uzCyrl from "./locales/uz-Cyrl";
import uzLatn from "./locales/uz-Latn";

export const LANGUAGES = [
  { code: "ru", short: "RU" },
  { code: "en", short: "EN" },
  { code: "uz-Cyrl", short: "ЎЗ" },
  { code: "uz-Latn", short: "UZ" },
] as const;

export type LangCode = (typeof LANGUAGES)[number]["code"];

const LANG_KEY = "argus.lang";

i18n.use(initReactI18next).init({
  resources: {
    ru: { translation: ru },
    en: { translation: en },
    "uz-Cyrl": { translation: uzCyrl },
    "uz-Latn": { translation: uzLatn },
  },
  lng: load<LangCode>(LANG_KEY, "ru"),
  fallbackLng: "ru",
  interpolation: { escapeValue: false },
});

document.documentElement.lang = i18n.language;

export function setLanguage(code: LangCode) {
  i18n.changeLanguage(code);
  document.documentElement.lang = code;
  save(LANG_KEY, code);
}

/** Locale used for dates and numbers. */
export function intlLocale(): string {
  return i18n.language === "en" ? "en-GB" : i18n.language;
}

export default i18n;
