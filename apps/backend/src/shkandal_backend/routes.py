"""Public reader API routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from shkandal_backend.public_repository import PublicRepository
from shkandal_backend.schemas import (
    CaseFeedPage,
    CasePage,
    CaseSort,
    EntityPage,
    LatestEvent,
    SitemapEntry,
    ViewCount,
)

router = APIRouter(prefix="/api")


async def public_repository(request: Request) -> PublicRepository:
    return cast(PublicRepository, request.app.state.public_repository)


Repository = Annotated[PublicRepository, Depends(public_repository)]


@router.get("/cases", response_model=CaseFeedPage)
async def cases(
    repository: Repository,
    sort: CaseSort = "trending",
    query: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> CaseFeedPage:
    return await repository.case_feed(sort=sort, query=query, page=page)


@router.get("/events/latest", response_model=list[LatestEvent])
async def latest_events(repository: Repository) -> list[LatestEvent]:
    return await repository.latest_events()


@router.get("/cases/{slug}", response_model=CasePage)
async def case_page(slug: str, repository: Repository) -> CasePage | RedirectResponse:
    result = await repository.case_page(slug)
    if result is None:
        redirect_lookup = getattr(repository, "case_redirect_slug", None)
        redirect_slug = await redirect_lookup(slug) if redirect_lookup is not None else None
        if redirect_slug is not None:
            return RedirectResponse(url=f"/api/cases/{redirect_slug}", status_code=307)
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.post("/cases/{slug}/views", response_model=ViewCount)
async def count_case_view(slug: str, repository: Repository) -> ViewCount:
    count = await repository.increment_case_view(slug)
    if count is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return ViewCount(view_count=count)


@router.get("/entities/{slug}", response_model=EntityPage)
async def entity_page(slug: str, repository: Repository) -> EntityPage:
    result = await repository.entity_page(slug)
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@router.get("/sitemap", response_model=list[SitemapEntry])
async def sitemap(repository: Repository) -> list[SitemapEntry]:
    return await repository.sitemap_entries()
