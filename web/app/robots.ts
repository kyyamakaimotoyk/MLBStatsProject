import type { MetadataRoute } from "next";

export const dynamic = "force-static"; // required under output: "export"

// Served as /robots.txt in the static export. The site wants to be indexed;
// nothing is disallowed — the pages render client-side, so crawlers must be
// able to fetch the /_next/ JS bundles too.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: "https://moundmodel.com/sitemap.xml",
  };
}
