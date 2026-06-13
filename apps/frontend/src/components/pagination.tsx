import Link from "next/link";

type PaginationItem = number | "ellipsis";

function paginationItems(currentPage: number, totalPages: number): PaginationItem[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  const visiblePages = [...pages]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right);

  const items: PaginationItem[] = [];
  visiblePages.forEach((page, index) => {
    const previousPage = visiblePages[index - 1];
    if (previousPage && page - previousPage > 1) items.push("ellipsis");
    items.push(page);
  });
  return items;
}

export function Pagination({
  page,
  totalPages,
  sort,
  query,
}: {
  page: number;
  totalPages: number;
  sort: string;
  query?: string;
}) {
  function href(targetPage: number) {
    return `/?${new URLSearchParams({
      ...(query ? { query } : { sort }),
      page: String(targetPage),
    })}`;
  }

  return (
    <nav aria-label="Сторінки" className="pagination">
      {page === 1 ? (
        <span aria-disabled="true" className="paginationDirection paginationDisabled">
          ← <span>попередня</span>
        </span>
      ) : (
        <Link className="paginationDirection" href={href(page - 1)}>
          ← <span>попередня</span>
        </Link>
      )}
      <div className="paginationPages">
        {paginationItems(page, totalPages).map((item, index) =>
          item === "ellipsis" ? (
            <span aria-hidden="true" className="paginationEllipsis" key={`ellipsis-${index}`}>
              …
            </span>
          ) : (
            <Link
              aria-current={page === item ? "page" : undefined}
              href={href(item)}
              key={item}
            >
              {item}
            </Link>
          ),
        )}
      </div>
      {page === totalPages ? (
        <span aria-disabled="true" className="paginationDirection paginationDisabled">
          <span>наступна</span> →
        </span>
      ) : (
        <Link className="paginationDirection" href={href(page + 1)}>
          <span>наступна</span> →
        </Link>
      )}
    </nav>
  );
}
