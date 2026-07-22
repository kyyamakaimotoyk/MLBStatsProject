"use client";

import Link from "next/link";
import { useLang } from "@/lib/i18n";
import { openConsentBanner } from "@/lib/consent";

export default function SiteFooter() {
  const { t } = useLang();

  return (
    <footer className="border-t border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-4 text-xs text-zinc-500">
        <span>{t.site.disclaimer}</span>
        <span className="ml-auto flex gap-4">
          <Link href="/privacy" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            {t.footer.privacy}
          </Link>
          <button
            type="button"
            onClick={openConsentBanner}
            className="hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            {t.footer.cookieSettings}
          </button>
        </span>
      </div>
    </footer>
  );
}
