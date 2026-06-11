import Link from "next/link";

import { CaseCard } from "@/components/case-card";
import { getCaseFeed, type CaseSort } from "@/lib/api";

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
  const feed = await getCaseFeed(sort, page, query);
  if (!feed) throw new Error("Не вдалося завантажити стрічку справ.");

  const [lead, ...items] = feed.items;
  return (
    <main className="pageShell">
      <section className="feedIntro">
        <div>
          <p className="kicker">живий контекст замість одноразових новин</p>
          <h1>Справи, за якими варто стежити</h1>
        </div>
        <p>
          Автоматично зібрані досьє з хронологією, згаданими особами та прямими
          посиланнями на відкриті джерела.
        </p>
      </section>

      <form action="/" className="searchForm">
        <label htmlFor="query">Пошук справи за назвою</label>
        <div>
          <input defaultValue={query} id="query" minLength={2} name="query" placeholder="Наприклад, закупівля дронів" />
          <button type="submit">знайти</button>
        </div>
      </form>

      {query ? (
        <div className="resultHeader">
          <p>
            Результати для <strong>«{query}»</strong> · {feed.total_items}
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

      {lead ? <CaseCard item={lead} lead /> : <p className="emptyState">Справ не знайдено.</p>}
      <section className="caseGrid">
        {items.map((item) => (
          <CaseCard item={item} key={item.slug} />
        ))}
      </section>

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
