import {
  createContext,
  type ReactNode,
  useContext,
  useMemo,
  useState,
} from "react";
import { catalogs, type Locale, type MessageKey } from "./messages";

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function initialLocale(): Locale {
  try {
    const stored = window.localStorage.getItem("fcp.locale");
    if (stored === "en" || stored === "el") {
      return stored;
    }
  } catch {
    // Storage may be unavailable (private mode); fall back to the browser language.
  }
  return navigator.language.toLowerCase().startsWith("el") ? "el" : "en";
}

export function I18nProvider({
  children,
  locale: fixed,
}: {
  children: ReactNode;
  locale?: Locale;
}) {
  const [locale, setLocaleState] = useState<Locale>(fixed ?? initialLocale());
  const value = useMemo<I18nValue>(
    () => ({
      locale,
      setLocale: (next) => {
        setLocaleState(next);
        document.documentElement.lang = next;
        try {
          window.localStorage.setItem("fcp.locale", next);
        } catch {
          // Not persisted; the choice still applies for this session.
        }
      },
      t: (key) => catalogs[locale][key],
    }),
    [locale],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return value;
}
