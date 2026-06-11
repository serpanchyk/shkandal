import Image from "next/image";
import Link from "next/link";

import type { CaseFeedItem } from "@/lib/api";

const dateFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function CaseCard({ item, lead = false }: { item: CaseFeedItem; lead?: boolean }) {
  return (
    <article className={`caseCard ${lead ? "caseCardLead" : ""}`}>
      {item.image_url ? (
        <div className="caseCardImage">
          <Image alt="" fill priority={lead} sizes={lead ? "(max-width: 800px) 100vw, 55vw" : "(max-width: 800px) 100vw, 50vw"} src={item.image_url} unoptimized />
        </div>
      ) : null}
      <div className="caseCardBody">
        <p className="caseIndex">справа / {item.slug}</p>
        <h2>
          <Link href={`/cases/${item.slug}`}>{item.title_uk}</Link>
        </h2>
        <p className="caseSummary">{item.summary_uk}</p>
        <div className="metrics">
          <span>{item.article_count} матеріалів</span>
          <span>{item.view_count} переглядів</span>
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
