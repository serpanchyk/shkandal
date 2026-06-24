import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ArticleCard } from "@/components/article-card";
import { SourceLogo } from "@/components/source-logo";
import { ViewCounter } from "@/components/view-counter";
import { getCase } from "@/lib/api";
import { formatCount } from "@/lib/ukrainian";

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const dossier = await getCase(slug);
  if (!dossier) return {};
  return {
    title: dossier.title_uk,
    description: dossier.summary_uk,
    alternates: { canonical: `/cases/${slug}` },
    openGraph: { title: dossier.title_uk, description: dossier.summary_uk, type: "article" },
  };
}

function eventDate(event: {
  event_year: number | null;
  event_month: number | null;
  event_day: number | null;
}) {
  if (!event.event_year) return "дата невідома";
  return [event.event_day, event.event_month, event.event_year].filter(Boolean).join(".");
}

export default async function CasePage({ params }: { params: Params }) {
  const { slug } = await params;
  const dossier = await getCase(slug);
  if (!dossier) notFound();

  return (
    <main className="pageShell dossierPage">
      <ViewCounter slug={slug} />
      <Link className="backLink" href="/">← усі справи</Link>
      <header className="dossierHero">
        <p className="kicker">досьє суспільно важливої справи</p>
        <h1 className="caseTitle">{dossier.title_uk}</h1>
        <p className="dossierSummary">{dossier.summary_uk}</p>
        <div className="metrics">
          <span>{formatCount(dossier.article_count, ["матеріал", "матеріали", "матеріалів"])}</span>
          <span>{formatCount(dossier.event_count, ["подія", "події", "подій"])}</span>
          <span>{formatCount(dossier.view_count, ["перегляд", "перегляди", "переглядів"])}</span>
        </div>
      </header>

      <section aria-labelledby="sources-title" className="sourceStrip panel">
        <div>
          <p className="sectionCode">01 / provenance</p>
          <h2 id="sources-title">Джерела справи</h2>
        </div>
        <div className="sourceLogos">
          {dossier.sources.map((source) => (
            <a href={source.homepage_url} key={source.slug} rel="noopener noreferrer" target="_blank" title={`${source.name}: ${formatCount(source.article_count ?? 0, ["матеріал", "матеріали", "матеріалів"])}`}>
              <SourceLogo name={source.name} path={source.logo_path} />
              <span className="srOnly">{source.name}</span>
            </a>
          ))}
        </div>
      </section>

      <section aria-labelledby="timeline-title" className="dossierSection">
        <div className="sectionHeading">
          <p className="sectionCode">02 / timeline</p>
          <h2 id="timeline-title">Хронологія</h2>
        </div>
        <details className="sectionDisclosure" open>
          <summary className="sectionDisclosureSummary">
            {formatCount(dossier.events.length, ["подія", "події", "подій"])}
          </summary>
          <div className="timeline">
            {dossier.events.length ? dossier.events.map((event) => (
              <article className="timelineEvent" key={event.slug}>
                <div className="eventDate">{eventDate(event)}</div>
                <div>
                  <h3>{event.title_uk}</h3>
                  {event.description_uk ? <p>{event.description_uk}</p> : null}
                  {event.location_uk ? <p className="location">місце / {event.location_uk}</p> : null}
                  <details>
                    <summary>{formatCount(event.supporting_articles.length, ["джерело події", "джерела події", "джерел події"])}</summary>
                    <div className="articleList">
                      {event.supporting_articles.map((article) => <ArticleCard article={article} key={article.url} />)}
                    </div>
                  </details>
                </div>
              </article>
            )) : <p className="emptyState">Події ще не виділено. Матеріали справи доступні нижче.</p>}
          </div>
        </details>
      </section>

      <section aria-labelledby="entities-title" className="dossierSection">
        <div className="sectionHeading">
          <p className="sectionCode">03 / mentions</p>
          <h2 id="entities-title">Згадані особи та організації</h2>
        </div>
        <details className="sectionDisclosure entitiesArchive" open>
          <summary className="sectionDisclosureSummary">
            {formatCount(dossier.entities.length, [
              "згадана особа або організація",
              "згадані особи або організації",
              "згаданих осіб або організацій",
            ])}
          </summary>
          <div className="entityGrid">
            {dossier.entities.map((entity) => (
              <Link className="entityCard" href={`/entities/${entity.slug}`} key={entity.slug}>
                <span>{entity.entity_type} / {formatCount(entity.mention_count, ["згадка", "згадки", "згадок"])}</span>
                <h3>{entity.canonical_name_uk}</h3>
                {entity.description_uk ? <p>{entity.description_uk}</p> : null}
              </Link>
            ))}
          </div>
        </details>
      </section>

      {dossier.other_cases.length ? (
        <section aria-labelledby="other-cases-title" className="dossierSection">
          <div className="sectionHeading">
            <p className="sectionCode">04 / links</p>
            <h2 id="other-cases-title">Інші справи</h2>
          </div>
          <details className="sectionDisclosure otherCasesArchive" open>
            <summary className="sectionDisclosureSummary">
              {formatCount(dossier.other_cases.length, [
                "інша справа",
                "інші справи",
                "інших справ",
              ])}
            </summary>
            <div className="relatedGrid">
              {dossier.other_cases.map((otherCase) => (
                <Link href={`/cases/${otherCase.slug}`} key={otherCase.slug}>
                  <h3 className="caseTitle">{otherCase.title_uk}</h3>
                  <p>{otherCase.summary_uk}</p>
                </Link>
              ))}
            </div>
          </details>
        </section>
      ) : null}

      <section aria-labelledby="articles-title" className="dossierSection">
        <div className="sectionHeading">
          <p className="sectionCode">05 / evidence</p>
          <h2 id="articles-title">Усі матеріали справи</h2>
        </div>
        <details className="sectionDisclosure articleArchive">
          <summary className="sectionDisclosureSummary">
            {formatCount(dossier.articles.length, [
              "матеріал справи",
              "матеріали справи",
              "матеріалів справи",
            ])}
          </summary>
          <div className="articleList">
            {dossier.articles.map((article) => <ArticleCard article={article} key={article.url} />)}
          </div>
        </details>
      </section>

      <p className="disclaimer">{dossier.disclaimer_uk}</p>
    </main>
  );
}
