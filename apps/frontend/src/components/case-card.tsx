import Image from "next/image";
import Link from "next/link";

import type { CaseFeedItem } from "@/lib/api";
import { formatCount } from "@/lib/ukrainian";

const dateFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function CaseCard({ item }: { item: CaseFeedItem }) {
  return (
    <article className="caseCard">
      {item.image_url ? (
        <div className="caseCardImage">
          <Image alt="" fill sizes="(max-width: 800px) 100vw, (max-width: 1100px) 50vw, 33vw" src={item.image_url} unoptimized />
        </div>
      ) : null}
      <div className="caseCardBody">
        <h2>
          <Link href={`/cases/${item.slug}`}>{item.title_uk}</Link>
        </h2>
        <p className="caseSummary">{item.summary_uk}</p>
        <div className="metrics">
          <span>{formatCount(item.article_count, ["матеріал", "матеріали", "матеріалів"])}</span>
          <span>{formatCount(item.view_count, ["перегляд", "перегляди", "переглядів"])}</span>
          <span>
            {item.latest_article_at
              ? `оновлено ${dateFormat.format(new Date(item.latest_article_at))}`
              : "дата оновлення невідома"}
          </span>
        </div>
      </div>
    </article>
  );
}
