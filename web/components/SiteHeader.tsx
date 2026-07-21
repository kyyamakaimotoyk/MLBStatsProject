"use client";

import Link from "next/link";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/translations";

export default function SiteHeader() {
  const { lang, setLang, t } = useLang();

  const nav = [
    { href: "/", label: t.nav.tonight },
    { href: "/record", label: t.nav.record },
    { href: "/teams", label: t.nav.teams },
    { href: "/players", label: t.nav.players },
    { href: "/performance", label: t.nav.modelLab },
    { href: "/about", label: t.nav.about },
  ];

  const langButton = (l: Lang, label: string) => (
    <button
      type="button"
      aria-pressed={lang === l}
      onClick={() => setLang(l)}
      className={
        lang === l
          ? "rounded border border-[var(--accent-mark)] px-1.5 py-0.5 font-semibold"
          : "rounded border border-transparent px-1.5 py-0.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
      }
      style={lang === l ? { color: "var(--accent-text)" } : undefined}
    >
      {label}
    </button>
  );

  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3">
        <span className="font-semibold">⚾ MLB Stats</span>
        <nav className="flex flex-wrap gap-4 text-sm">
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1 text-xs" aria-label="Language / 言語">
          {langButton("en", "EN")}
          {langButton("ja", "日本語")}
        </div>
      </div>
    </header>
  );
}
