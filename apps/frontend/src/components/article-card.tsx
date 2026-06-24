import Image from "next/image";

import type { ArticlePreview } from "@/lib/api";

const dateFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function ArticleCard({ article }: { article: ArticlePreview }) {
  return (
    <a className="articleCard" href={article.url} rel="noopener noreferrer" target="_blank">
      <div
        aria-hidden="true"
        className={`articleCardImage${article.image_url ? "" : " articleCardImage--empty"}`}
      >
        {article.image_url ? (
          <Image alt="" height={70} src={article.image_url} unoptimized width={90} />
        ) : null}
      </div>
      <div>
        <p className="articleMeta">
          {article.source.name}
          {article.published_at ? ` · ${dateFormat.format(new Date(article.published_at))}` : ""}
        </p>
        <h3>{article.title}</h3>
      </div>
      <span aria-hidden="true" className="externalArrow">
        ↗
      </span>
    </a>
  );
}
