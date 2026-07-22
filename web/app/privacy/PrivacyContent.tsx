"use client";

import { useLang } from "@/lib/i18n";
import { openConsentBanner } from "@/lib/consent";

// Bump this whenever the policy's substance changes.
const LAST_UPDATED = "2026-07-22";

export default function PrivacyContent() {
  const { t } = useLang();
  const p = t.privacy;

  const section = (title: string, bodies: string[]) => (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {bodies.map((b) => (
        <p key={b.slice(0, 32)} className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
          {b}
        </p>
      ))}
    </section>
  );

  return (
    <div className="mx-auto max-w-2xl space-y-8 py-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{p.title}</h1>
        <p className="text-xs text-zinc-500">{p.updated(LAST_UPDATED)}</p>
      </header>

      <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">{p.intro}</p>

      {section(p.hostTitle, [p.hostBody])}
      {section(p.analyticsTitle, [p.analyticsBody])}
      {section(p.adsTitle, [p.adsBody1, p.adsBody2])}

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{p.consentTitle}</h2>
        <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">{p.consentBody}</p>
        <button
          type="button"
          onClick={openConsentBanner}
          className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:border-[var(--accent-mark)] dark:border-zinc-700"
        >
          {p.cookieSettings}
        </button>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{p.linksTitle}</h2>
        <ul className="list-inside list-disc space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
          {p.links.map((l) => (
            <li key={l.href}>
              <a
                href={l.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--accent-text)] hover:underline"
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {section(p.contactTitle, [p.contactBody])}

      <p className="text-xs text-zinc-400">{p.changesBody}</p>
    </div>
  );
}
