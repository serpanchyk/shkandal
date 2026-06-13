import Link from "next/link";

import { CaseCard } from "@/components/case-card";
import { EventTicker } from "@/components/event-ticker";
import { getCaseFeed, getLatestEvents, type CaseSort } from "@/lib/api";
import { formatCount } from "@/lib/ukrainian";

const sorts: Array<[CaseSort, string]> = [
  ["trending", "у тренді"],
  ["latest", "останні оновлення"],
  ["newest", "нові справи"],
  ["popular", "популярні"],
  ["biggest", "найбільші"],
];

type SearchParams = Promise<{ sort?: string; page?: string; query?: string }>;

export default async function Home({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const sort = sorts.some(([value]) => value === params.sort)
    ? (params.sort as CaseSort)
    : "trending";
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const query = params.query?.trim();
  const [feed, events] = await Promise.all([getCaseFeed(sort, page, query), getLatestEvents()]);
  if (!feed) throw new Error("Не вдалося завантажити стрічку справ.");
  if (!events) throw new Error("Не вдалося завантажити останні події.");

  return (
    <main className="pageShell">
      <section className="feedIntro">
        <div>
          <p className="kicker">від окремих новин — до живої хронології справи</p>
          <h1 className="feedTitle">Справи, за якими варто стежити</h1>
        </div>
        <EventTicker events={events} />
      </section>

      {query ? (
        <div className="resultHeader">
          <p>
            Результати для <strong>«{query}»</strong> ·{" "}
            {formatCount(feed.total_items, ["справа", "справи", "справ"])}
          </p>
          <Link href="/">очистити пошук</Link>
        </div>
      ) : (
        <nav aria-label="Сортування справ" className="sortTabs">
          {sorts.map(([value, label]) => (
            <Link
              aria-current={sort === value ? "page" : undefined}
              href={`/?sort=${value}`}
              key={value}
            >
              {label}
            </Link>
          ))}
        </nav>
      )}

      {feed.items.length ? <section className="caseGrid">
        {feed.items.map((item) => (
          <CaseCard item={item} key={item.slug} />
        ))}
      </section> : <p className="emptyState">Справ не знайдено.</p>}

      {feed.total_pages > 1 ? (
        <nav aria-label="Сторінки" className="pagination">
          {feed.page > 1 ? (
            <Link href={`/?${new URLSearchParams({ ...(query ? { query } : { sort }), page: String(feed.page - 1) })}`}>
              ← попередня
            </Link>
          ) : <span />}
          <span>
            {feed.page} / {feed.total_pages}
          </span>
          {feed.page < feed.total_pages ? (
            <Link href={`/?${new URLSearchParams({ ...(query ? { query } : { sort }), page: String(feed.page + 1) })}`}>
              наступна →
            </Link>
          ) : <span />}
        </nav>
      ) : null}
    </main>
  );
}
