# ADR 0004: Run Case Audits Automatically in a Fixed Order

## Status

Accepted

## Decision

Shkandal automatically runs Case Coherence, Public-Interest, and Duplicate
Audits in that order after evidence changes and on a periodic fallback. There
is no human approval step. Every audit uses a specialized structured decision,
records immutable provenance, makes no mutation when inconclusive, and applies
decisive changes under the existing serialized Case publication locks.
Duplicate Audit candidates are calculated directly from shared Articles. A pair
qualifies when it shares at least one Article and the overlap covers at least
30% of the smaller Case.
