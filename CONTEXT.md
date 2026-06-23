# Shkandal Context

Shkandal turns Ukrainian source articles into public reader-facing dossiers about
public-interest cases in Ukraine.

## Language

**Article Relevance**:
An article is relevant when it can support a Ukrainian public dossier about a public scandal, corruption investigation, political or legal case, institutional decision, or socially important accountability story in Ukraine. It does not need to contain a complete scandal by itself, name all actors, or produce a timeline event.
_Avoid_: newsworthiness, importance, virality

**Standalone Relevance**:
Article relevance that can be judged from the article's own content because it contains enough accountability substance to justify case resolution.
_Avoid_: obvious relevance, direct relevance

**Contextual Relevance**:
Article relevance that depends on a clear connection to an already relevant case because the article advances, documents, or updates that case despite being thin by itself.
_Avoid_: weak relevance, secondary news

**Relevance Candidate**:
An article with enough relevance signal to be evaluated by case resolution, but not yet accepted as public dossier evidence.
_Avoid_: relevant article, final relevance

**Ukraine Connection**:
A material connection to Ukrainian people, institutions, companies, public money, territory, law, courts, public policy, war impact, or Ukrainian society. Foreign stories only have this connection when they materially affect Ukraine or involve Ukrainian actors.
_Avoid_: Ukrainian-language article, international news

**Institutional Decision**:
A public-body decision with accountability stakes, such as misuse of power or funds, investigation, prosecution, sanctions, dismissal, public conflict, rights impact, major public risk, or a tie to an already relevant case. Routine announcements are not institutional decisions for Shkandal.
_Avoid_: announcement, press release, routine update

**Case**:
A reader-facing dossier about one durable public-interest story. Accountability
stories, concrete institutional processes, and exceptionally notable incidents
may qualify. Shared actors, similar incidents, or broad topics alone do not
establish Case identity.
_Avoid_: article cluster, actor dossier, broad topic

**Material Article Contribution**:
Evidence or context that advances, documents, corrects, or materially explains a
Case. An incidental background mention is not a material contribution.
_Avoid_: mention, keyword match

**Other Cases**:
Distinct public Cases shown as derived reader navigation because they share at
least one supporting Article, materialized Event, or Mentioned Entity. This is
not a persisted editorial relationship or evidence that the Cases are identical.
_Avoid_: related case, possible duplicate

**Possible Duplicate Cases**:
Cases likely describing the same durable accountability story and therefore
candidates for eventual merge.
_Avoid_: related cases, uncertain relationship

**Case Coherence Audit**:
A recurring evaluation of whether every linked Article belongs to a Case's one
durable public-interest story. It preserves relevant repetition and may split
mixed stories or detach links that belong to no concrete durable story.
_Avoid_: cluster validation, relevance review

**Case Public-Interest Audit**:
A recurring evaluation of whether a coherent Case remains a durable story worth
publishing. Routine incidents, isolated headlines, and broad topic umbrellas do
not qualify.
_Avoid_: popularity check, lifecycle status

**Case Duplicate Audit**:
An evaluation of whether two Article-overlap candidate Cases describe the same
durable story or remain distinct.
_Avoid_: similarity check, Case Coherence Audit

**Case Audit Pipeline**:
The ordered automatic correction process of Case Coherence Audit, Case
Public-Interest Audit, and Case Duplicate Audit.
_Avoid_: one combined audit

**Hidden Case**:
A terminal editorial rejection that remains fully preserved internally but is
excluded from public and retrieval surfaces.
_Avoid_: inactive Case, archived Case

**Merged Case**:
A duplicate Case absorbed into a surviving Case. Its public identity redirects
to the survivor.
_Avoid_: hidden Case, deleted Case

**Case Split**:
An automatic correction that preserves the dominant durable story on the
original Case and creates new Cases for other coherent stories. Articles may
materially contribute to multiple resulting Cases.
_Avoid_: exclusive partition, duplicate merge

**Case Publication**:
The serialized operation that makes complete reader-facing Case state visible
by updating Case copy, article assignments, materialized Entity/Event links,
counts, and rebuildable vectors before PostgreSQL commits.
_Avoid_: case save, partial update

**Entity**:
A global durable real-world actor directly mentioned in supporting articles.
Aliases and true renames may identify the same Entity, while successor bodies
and independently acting named subdivisions are separate Entities.
_Avoid_: keyword, incidental mention, parent institution

**Mentioned Entity**:
An Entity materially linked to a Case through supporting articles. The link
establishes a source-backed mention, not guilt, responsibility, or formal participation.
_Avoid_: participant, implicated actor, suspect

**Source**:
A curated media outlet, institution, court, NGO, government body, or other
publisher whose original articles support public Cases.
_Avoid_: media, authority score

**Event**:
One strict real-world occurrence supported by at least one article. Mentions
identify the same Event only when their known date, actors, institution, action,
object, and location are compatible; missing facts may be added, but conflicting
known facts indicate a different or unresolved Event.
_Avoid_: development thread, article summary, procedural stage group
