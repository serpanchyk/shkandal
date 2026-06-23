export type CaseSort = "latest" | "newest" | "popular" | "biggest" | "trending";

export type SourcePreview = {
  slug: string;
  name: string;
  source_type: string;
  homepage_url: string;
  logo_path: string | null;
  article_count: number | null;
};

export type ArticlePreview = {
  title: string;
  url: string;
  published_at: string | null;
  image_url: string | null;
  source: SourcePreview;
};

export type CaseFeedItem = {
  slug: string;
  title_uk: string;
  summary_uk: string;
  latest_article_at: string | null;
  article_count: number;
  view_count: number;
  image_url: string | null;
};

export type CaseFeedPage = {
  items: CaseFeedItem[];
  sort: CaseSort;
  query: string | null;
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
};

export type OtherCase = {
  slug: string;
  title_uk: string;
  summary_uk: string;
};

export type EntityPreview = {
  slug: string;
  canonical_name_uk: string;
  entity_type: string;
  description_uk: string | null;
  mention_count: number;
};

export type EventPreview = {
  slug: string;
  title_uk: string;
  description_uk: string | null;
  event_year: number | null;
  event_month: number | null;
  event_day: number | null;
  event_date_precision: string;
  location_uk: string | null;
  supporting_articles: ArticlePreview[];
};

export type LatestEvent = {
  title_uk: string;
  event_year: number;
  event_month: number | null;
  event_day: number | null;
  event_date_precision: string;
  location_uk: string | null;
};

export type CasePage = {
  slug: string;
  title_uk: string;
  summary_uk: string;
  latest_article_at: string | null;
  article_count: number;
  event_count: number;
  view_count: number;
  sources: SourcePreview[];
  entities: EntityPreview[];
  events: EventPreview[];
  articles: ArticlePreview[];
  other_cases: OtherCase[];
  disclaimer_uk: string;
};

export type EntityPage = {
  slug: string;
  canonical_name_uk: string;
  entity_type: string;
  aliases: string[];
  description_uk: string;
  cases: OtherCase[];
  articles: ArticlePreview[];
};

const backendUrl =
  process.env.BACKEND_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://localhost:8000";

async function request<T>(path: string): Promise<T | null> {
  const response = await fetch(`${backendUrl}${path}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Backend request failed: ${response.status}`);
  return (await response.json()) as T;
}

export function getCaseFeed(sort: CaseSort, page: number, query?: string) {
  const params = new URLSearchParams({ sort, page: String(page) });
  if (query) params.set("query", query);
  return request<CaseFeedPage>(`/api/cases?${params}`);
}

export function getLatestEvents() {
  return request<LatestEvent[]>("/api/events/latest");
}

export function getCase(slug: string) {
  return request<CasePage>(`/api/cases/${encodeURIComponent(slug)}`);
}

export function getEntity(slug: string) {
  return request<EntityPage>(`/api/entities/${encodeURIComponent(slug)}`);
}

export function getSitemapEntries() {
  return request<Array<{ path: string; updated_at: string }>>("/api/sitemap");
}
