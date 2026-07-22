"use client";

// Loads gtag.js and the AdSense loader (consent defaults are already queued by
// the bootstrap script in layout.tsx), and reports SPA navigations to GA —
// the static export navigates client-side, so `config`'s automatic page_view
// is disabled and every view is sent from here instead.

import Script from "next/script";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { ADSENSE_CLIENT, GA_MEASUREMENT_ID } from "@/lib/ads";

export default function GoogleTags() {
  const pathname = usePathname();

  useEffect(() => {
    if (!GA_MEASUREMENT_ID) return;
    window.gtag?.("event", "page_view", {
      page_location: window.location.href,
      page_title: document.title,
    });
  }, [pathname]);

  return (
    <>
      {GA_MEASUREMENT_ID && (
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
          strategy="afterInteractive"
        />
      )}
      {ADSENSE_CLIENT && (
        <Script
          src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`}
          strategy="afterInteractive"
          crossOrigin="anonymous"
        />
      )}
    </>
  );
}
