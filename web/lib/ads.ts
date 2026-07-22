// Google monetization config — the ONE place ad/analytics identifiers live.
// These are public identifiers (they ship in the page source by design), so
// committing them is fine. An empty string disables that integration
// site-wide, so the site builds and runs before the Google accounts exist.

import { CONSENT_DENIED_REGIONS, CONSENT_STORAGE_KEY } from "./consent";

// Google Analytics: Admin -> Data streams -> web stream "Measurement ID".
export const GA_MEASUREMENT_ID = "G-WJPRTDM1MM"; // e.g. "G-XXXXXXXXXX"

// AdSense: Settings -> Account -> Account information "Publisher ID".
// The same ID (minus the "ca-" prefix) goes in public/ads.txt.
export const ADSENSE_CLIENT = "ca-pub-8164683714910600"; // e.g. "ca-pub-1234567890123456"

// One entry per ad placement; the value is the ad unit's "slot" ID (create a
// Display ad unit per placement in the AdSense console). An empty slot
// renders nothing in production and a dashed placeholder in dev.
export const AD_SLOTS = {
  homeMid: "", // Tonight page, between tonight's picks and recent results
  recordMid: "", // Record page, between the pick-by-pick strip and the charts
} as const;

export type AdPlacement = keyof typeof AD_SLOTS;

// Inline <script> injected at the top of <body> by app/layout.tsx. It defines
// the gtag stub, sets Consent Mode v2 defaults (denied in the EEA/UK/CH until
// the visitor opts in), replays any stored choice, and queues the GA config —
// all before gtag.js / adsbygoogle.js load, so no pre-consent cookies are set.
export function googleBootstrapScript(): string {
  const lines = [
    "window.dataLayer=window.dataLayer||[];",
    "function gtag(){dataLayer.push(arguments);}",
    "window.gtag=gtag;",
    'gtag("consent","default",{ad_storage:"granted",ad_user_data:"granted",ad_personalization:"granted",analytics_storage:"granted"});',
    'gtag("consent","default",{ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied",analytics_storage:"denied",wait_for_update:500,' +
      `region:${JSON.stringify(CONSENT_DENIED_REGIONS)}});`,
    'gtag("set","ads_data_redaction",true);',
    `try{var c=JSON.parse(localStorage.getItem(${JSON.stringify(CONSENT_STORAGE_KEY)})||"null");` +
      'if(c&&c.v===1){var s=c.granted?"granted":"denied";' +
      'gtag("consent","update",{ad_storage:s,ad_user_data:s,ad_personalization:s,analytics_storage:s});}}catch(e){}',
  ];
  if (GA_MEASUREMENT_ID) {
    lines.push(
      'gtag("js",new Date());',
      `gtag("config",${JSON.stringify(GA_MEASUREMENT_ID)},{send_page_view:false});`,
    );
  }
  return lines.join("");
}
