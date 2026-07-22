"use client";

// A CLS-proof AdSense unit. The frame's height is fixed in CSS (globals.css
// `.ad-frame`), so the space is reserved before any ad script runs; the <ins>
// fills the frame, data-full-width-responsive is off so Google never resizes
// it, and overflow-hidden clips anything oversized. If no ad fills, the space
// stays blank — reserved emptiness over layout shift, by design.

import { useEffect, useRef } from "react";
import { useLang } from "@/lib/i18n";
import { AD_SLOTS, ADSENSE_CLIENT, type AdPlacement } from "@/lib/ads";

export default function AdSlot({ placement }: { placement: AdPlacement }) {
  const slot = AD_SLOTS[placement];
  const enabled = Boolean(ADSENSE_CLIENT && slot);
  const ref = useRef<HTMLModElement>(null);
  const { t } = useLang();

  useEffect(() => {
    if (!enabled) return;
    const ins = ref.current;
    // Pages remount on navigation; only request an ad for a fresh <ins>.
    if (!ins || ins.getAttribute("data-adsbygoogle-status")) return;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      // Loader blocked (ad blocker etc.) — the frame just stays empty.
    }
  }, [enabled]);

  if (!enabled) {
    if (process.env.NODE_ENV === "production") return null;
    return (
      <div className="ad-frame flex items-center justify-center rounded border border-dashed border-zinc-300 text-xs text-zinc-400 dark:border-zinc-700">
        AdSlot “{placement}” — set IDs in lib/ads.ts (dev-only placeholder)
      </div>
    );
  }

  return (
    <div aria-hidden={false}>
      <div className="text-center text-[10px] uppercase tracking-widest text-zinc-400">
        {t.ads.label}
      </div>
      <div className="ad-frame overflow-hidden">
        <ins
          ref={ref}
          className="adsbygoogle block h-full w-full"
          data-ad-client={ADSENSE_CLIENT}
          data-ad-slot={slot}
          data-full-width-responsive="false"
        />
      </div>
    </div>
  );
}
