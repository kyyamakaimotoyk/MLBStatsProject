"use client";

// Cookie-consent banner backing Consent Mode v2. Auto-opens on first visit
// (only when a Google integration is configured); reopens any time via the
// footer's / privacy page's "cookie settings" button. position:fixed, so it
// never shifts page content.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLang } from "@/lib/i18n";
import { CONSENT_OPEN_EVENT, readStoredConsent, saveConsent } from "@/lib/consent";
import { ADSENSE_CLIENT, GA_MEASUREMENT_ID } from "@/lib/ads";

export default function ConsentBanner() {
  const { t } = useLang();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(CONSENT_OPEN_EVENT, show);
    if ((GA_MEASUREMENT_ID || ADSENSE_CLIENT) && !readStoredConsent()) setOpen(true);
    return () => window.removeEventListener(CONSENT_OPEN_EVENT, show);
  }, []);

  if (!open) return null;

  const choose = (granted: boolean) => {
    saveConsent(granted);
    setOpen(false);
  };

  return (
    <div
      role="dialog"
      aria-label={t.consent.title}
      className="fixed inset-x-0 bottom-0 z-50 border-t border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-700 dark:bg-zinc-900/95"
    >
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
        <p className="min-w-60 flex-1 text-sm text-zinc-600 dark:text-zinc-300">
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">
            {t.consent.title}
          </span>{" "}
          {t.consent.body}{" "}
          <Link href="/privacy" className="underline hover:text-zinc-900 dark:hover:text-zinc-100">
            {t.consent.privacyLink}
          </Link>
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => choose(false)}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:border-[var(--accent-mark)] dark:border-zinc-600"
          >
            {t.consent.declineAll}
          </button>
          <button
            type="button"
            onClick={() => choose(true)}
            className="rounded px-3 py-1.5 text-sm font-semibold hover:opacity-90"
            style={{ backgroundColor: "var(--btn-bg)", color: "var(--btn-text)" }}
          >
            {t.consent.acceptAll}
          </button>
        </div>
      </div>
    </div>
  );
}
