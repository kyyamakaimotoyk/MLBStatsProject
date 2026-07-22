// Google Consent Mode v2 state. The bootstrap script in app/layout.tsx sets
// region-scoped defaults before any Google script loads; the banner and the
// privacy page call saveConsent() to record the visitor's choice.
//
// Deliberately NOT a "use client" module: layout.tsx (a server component)
// imports the region list and storage key for the bootstrap script, so every
// `window` access here is guarded.

export const CONSENT_STORAGE_KEY = "moundmodel-consent";
export const CONSENT_OPEN_EVENT = "moundmodel:consent-open";

// EEA + UK + Switzerland: consent defaults to "denied" here until the visitor
// opts in (GDPR / UK GDPR / Swiss FADP); everywhere else defaults to granted.
export const CONSENT_DENIED_REGIONS = [
  "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
  "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
  "SI", "ES", "SE", // EU
  "IS", "LI", "NO", // rest of the EEA
  "GB", "CH",
];

export type StoredConsent = { v: 1; granted: boolean; ts: string };

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
    adsbygoogle?: unknown[];
  }
}

export function readStoredConsent(): StoredConsent | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as StoredConsent) : null;
    return parsed && parsed.v === 1 ? parsed : null;
  } catch {
    return null;
  }
}

export function saveConsent(granted: boolean) {
  const stored: StoredConsent = { v: 1, granted, ts: new Date().toISOString() };
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // Storage blocked — the consent update below still applies this session.
  }
  const s = granted ? "granted" : "denied";
  window.gtag?.("consent", "update", {
    ad_storage: s,
    ad_user_data: s,
    ad_personalization: s,
    analytics_storage: s,
  });
}

export function openConsentBanner() {
  window.dispatchEvent(new Event(CONSENT_OPEN_EVENT));
}
