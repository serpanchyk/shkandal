import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArticleCard } from "@/components/article-card";
import { getEntity } from "@/lib/api";

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const entity = await getEntity(slug);
  if (!entity) return {};
  return {
    title: entity.canonical_name_uk,
    description: entity.description_uk,
    alternates: { canonical: `/entities/${slug}` },
  };
}

export default async function EntityPage({ params }: { params: Params }) {
  const { slug } = await params;
  const entity = await getEntity(slug);
  if (!entity) notFound();

  return (
    <main className="pageShell dossierPage">
      <Link className="backLink" href="/">← усі справи</Link>
      <header className="dossierHero entityHero">
        <p className="kicker">{entity.entity_type} / entity</p>
        <h1>{entity.canonical_name_uk}</h1>
        <p className="dossierSummary">{entity.description_uk}</p>
        {entity.aliases.length ? <p className="aliases">також: {entity.aliases.join(", ")}</p> : null}
      </header>
      <section className="dossierSection">
        <div className="sectionHeading"><p className="sectionCode">01 / cases</p><h2>Пов’язані справи</h2></div>
        <div className="relatedGrid">
          {entity.cases.map((item) => <Link href={`/cases/${item.slug}`} key={item.slug}><h3 className="caseTitle">{item.title_uk}</h3><p>{item.summary_uk}</p></Link>)}
        </div>
      </section>
      <section className="dossierSection">
        <div className="sectionHeading"><p className="sectionCode">02 / evidence</p><h2>Матеріали зі згадками</h2></div>
        <div className="articleList">{entity.articles.map((article) => <ArticleCard article={article} key={article.url} />)}</div>
      </section>
    </main>
  );
}
