# ADR 0005: Derive Other Cases from Shared Evidence

## Status

Accepted

## Decision

Shkandal does not persist Case-to-Case navigation relations. Public Case pages
derive up to ten Other Cases from shared supporting Articles, materialized
Events, or Mentioned Entities. Results rank by the number of shared evidence
types, then Article, Event, and Entity overlap, followed by recency.

Duplicate detection remains separate from navigation. The Duplicate Audit
calculates Article-overlap candidates directly and records only immutable audit
provenance and merge outcomes.
