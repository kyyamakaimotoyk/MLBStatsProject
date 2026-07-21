"use client";

// Client-side language switching (the hoopmodel.com pattern). This site is a
// static export (S3+CloudFront, no server at runtime), so locale sub-path
// routing isn't available — instead the language lives in React context,
// persists in localStorage, and defaults to the browser's preferred language
// on first visit.

import { createContext, useContext, useEffect, useState } from "react";
import { translations, type Dict, type Lang } from "./translations";

const STORAGE_KEY = "moundmodel-lang";

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void } | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Static HTML is prerendered in English; the saved/browser language is
  // applied after hydration so server and client markup never mismatch.
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    // Must run post-hydration (localStorage doesn't exist at prerender time),
    // so the one-shot setState here is unavoidable.
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "ja") setLangState(saved);
    else if (navigator.language.toLowerCase().startsWith("ja")) setLangState("ja");
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = (l: Lang) => {
    setLangState(l);
    localStorage.setItem(STORAGE_KEY, l);
  };

  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>;
}

export function useLang(): { lang: Lang; setLang: (l: Lang) => void; t: Dict } {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used inside <LanguageProvider>");
  return { lang: ctx.lang, setLang: ctx.setLang, t: translations[ctx.lang] };
}
