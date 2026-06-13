import Link from "next/link";

import { CaseCard } from "@/components/case-card";
import { EventTicker } from "@/components/event-ticker";
import { Pagination } from "@/components/pagination";
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
  const hasFeaturedCases = !query && feed.page === 1;
  const featuredCases = hasFeaturedCases ? feed.items.slice(0, 5) : [];
  const listedCases = hasFeaturedCases ? feed.items.slice(5) : feed.items;

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

      {featuredCases.length ? (
        <section aria-label="Головні справи" className="featuredCases">
          <CaseCard item={featuredCases[0]} variant="lead" />
          {featuredCases.length > 1 ? (
            <div className="supportingCases">
              {featuredCases.slice(1).map((item) => (
                <CaseCard item={item} key={item.slug} variant="supporting" />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {listedCases.length ? (
        <section aria-label={hasFeaturedCases ? "Більше справ" : "Справи"} className="caseList">
          {hasFeaturedCases ? <h2 className="caseListHeading">Більше справ</h2> : null}
          {listedCases.map((item) => (
            <CaseCard item={item} key={item.slug} variant="list" />
          ))}
        </section>
      ) : feed.items.length ? null : <p className="emptyState">Справ не знайдено.</p>}

      {feed.total_pages > 1 ? (
        <Pagination page={feed.page} query={query} sort={sort} totalPages={feed.total_pages} />
      ) : null}
    </main>
  );
}
