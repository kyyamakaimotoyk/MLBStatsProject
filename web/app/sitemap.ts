import type { MetadataRoute } from "next";

export const dynamic = "force-static"; // required under output: "export"

const BASE = "https://moundmodel.com";

// Served as /sitemap.xml in the static export. Section roots only: the
// detail views (/players/detail, /teams/team) are query-param pages with
// no static content of their own.
export default function sitemap(): MetadataRoute.Sitemap {
  const daily = ["", "/record", "/teams", "/players", "/batters", "/performance"];
  return [
    ...daily.map((path) => ({
      url: `${BASE}${path}/`,
      changeFrequency: "daily" as const,
      priority: path === "" ? 1 : 0.7,
    })),
    { url: `${BASE}/about/`, changeFrequency: "monthly" as const, priority: 0.4 },
    { url: `${BASE}/privacy/`, changeFrequency: "monthly" as const, priority: 0.2 },
  ];
}
