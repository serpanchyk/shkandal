import type { MetadataRoute } from "next";

import { getSitemapEntries } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
  const entries = (await getSitemapEntries()) ?? [];
  return [
    { url: origin, lastModified: new Date() },
    ...entries.map((entry) => ({ url: `${origin}${entry.path}`, lastModified: new Date(entry.updated_at) })),
  ];
}
