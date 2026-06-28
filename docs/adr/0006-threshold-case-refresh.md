# ADR 0006: Refresh Case Copy on Square Evidence Thresholds

## Status

Accepted

## Context

Regenerating reader-facing Case title and summary after every article link keeps
copy fresh but spends an LLM call for routine evidence growth. Case resolution
also becomes harder to reason about when it both decides Case identity and
creates public copy.

## Decision

Case resolution only links existing Cases or creates internal active Cases.
New Cases use the Article Card title as an internal seed and keep
`summary_uk = null`, so public surfaces hide them until Case Refresh creates
reader-facing copy. The planner schedules `refresh_case` for Cases with missing
public summaries and for ordinary evidence growth at square article counts:
`1`, `4`, `9`, `16`, and so on.

Case Refresh regenerates title and summary, records the refreshed article count,
and upserts the rebuildable Case vector. Split and merge repairs always enqueue
an immediate high-priority Case Refresh after the structural mutation commits.

## Consequences

New Cases may exist internally and in retrieval before they are public. Mature
Cases refresh less often as evidence grows, reducing LLM load. After split or
merge repairs, readers may briefly see structurally repaired evidence with the
previous or audit-provided copy until the high-priority refresh succeeds.
