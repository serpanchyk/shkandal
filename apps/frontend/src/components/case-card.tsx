import Image from "next/image";
import Link from "next/link";

import type { CaseFeedItem } from "@/lib/api";
import { formatCount } from "@/lib/ukrainian";

const dateFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export type CaseCardVariant = "lead" | "supporting" | "list";

export function CaseCard({
  item,
  variant,
}: {
  item: CaseFeedItem;
  variant: CaseCardVariant;
}) {
  return (
    <article className={`caseCard caseCard--${variant}`} data-case-variant={variant}>
      {item.image_url ? (
        <div className="caseCardImage">
          <Image
            alt=""
            fill
            sizes={
              variant === "lead"
                ? "(max-width: 800px) 100vw, 60vw"
                : variant === "list"
                  ? "(max-width: 800px) 100vw, 240px"
                  : "(max-width: 800px) 100vw, 40vw"
            }
            src={item.image_url}
            unoptimized
          />
        </div>
      ) : null}
      <div className="caseCardBody">
        <h2 className="caseTitle">
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
