# Authoring adaptor discovery

Discovery is a deliverable in the [completion checklist](adaptor-completion.md).
Use the existing adaptor `capabilities` binding; declarations remain authoritative
for native identities and executable contracts. Keep application terms at application
level and operation terms at operation level. Useful descriptions distinguish
neighbouring operations, supported scope, inputs and outputs. Include domain names,
task verbs, common synonyms/acronyms, native names and alternative user phrasing
where relevant. A word list cannot establish editorial quality.

## Metadata and projections

The capability binding may return `application` with `label`, `purpose`, `keywords`,
and `operations` with the existing `purpose`, `keywords`, `groups`, `related`,
`semantics` and `examples`. Existing bindings remain accepted without the new
metadata; the opt-in completion gate reports omissions. Operation keywords are
optional in the public discovery contract, but completion requires curated terms.
Application keywords describe the application; they are not copied into operation
search. Legacy manifest keywords still participate in each operation search for
compatibility: keep them narrow and audit misleading matches when changing them.

| Surface | Actual consumed metadata | Matching and ordering |
| --- | --- | --- |
| CLI / agent capability search | Canonical operation ID, purpose, native name, legacy manifest keywords, operation keywords via `CapabilityCatalogue.operation_search_text`. | Casefolded whitespace tokens, AND substring matching; optional exact declared-kind facets; canonical-ID order and bounded pagination. |
| Studio adaptor selection | ID/display name, scope, legacy keywords/operation names, plus app label/purpose/keywords and all supported operation search projections. | Lowercase contiguous trimmed query substring; existing adaptor order. |
| Studio Add | Title, conceptual description, retained native description, group and the same operation search projection. Document controls retain their own description. | Locale lowercase contiguous query substring; exact/prefix/substring title scores 10/5/3, stable source order on ties. |
| Help | Topic title and tokens from packaged topic text plus the same operation search projection for operation topics. A curated operation topic also lists its declared option, input and enumerated names (`nativeTerms`), which match only as whole identifiers (`compareTo` finds its operation, the word "compare" does not). | Lowercase whitespace tokens, AND substring; each token scores 10 for exact title, 5 for title substring; descending score then locale title order. |

The shared projection reuses metadata, while each surface keeps its existing
matching/ordering contract. Finding an item does not establish suitability ranking.
Help/Add title boosts are narrow navigation heuristics. Broader relevance ranking,
semantic search and a matching-policy redesign are separately scoped future work.
Application terms must not make every operation match every query. For non-node
routes with a declared `operation` selector, Add exposes one selector control per
schema-declared operation and resolves its own Help; it does not fabricate graph
nodes or invent undeclared document operations.

Packaged default guides reuse the primary readiness route guide, with an optional
adaptor-owned `studio.json` `helpGuide` for a different user-facing guide. Contextual
operation topics still resolve independently to each generated operation reference.

## Adaptor-owned acceptance cases

Return `searchCases` from the capability binding, preferably loading an adaptor-owned
`search-cases.json`. There is no second registry. Each case has a unique slug `id`,
`query`, `kind` (`synonym`, `multiword`, `ambiguous`, `negative`), `status`
(`pending` or `reviewed`), optional capability `scope` (default `app/PROVIDER`),
and `expected`/optional `excluded` maps from surface to canonical IDs:

```json
{"id": "frequency-language", "query": "Bode", "kind": "synonym", "status": "reviewed",
 "scope": "app/ngspice",
 "expected": {"capabilities": ["operation/ngspice/acSweep"],
              "adaptor": ["app/ngspice"], "add": ["operation/ngspice/acSweep"],
              "help": ["operation/ngspice/acSweep"]},
 "excluded": {"capabilities": ["operation/ngspice/rcStep"],
              "add": ["operation/ngspice/rcStep"]}}
```

A negative case has empty expected arrays and nonempty excluded arrays. Expected
membership permits additional matches; excluded membership detects misleading
results. Help may legitimately mention neighbours in explanatory prose, so curate
negative assertions separately by surface. Ambiguity cases should expect all useful
interpretations and make no unimplemented suitability-ranking claim. Review wording,
include multiword phrases and misleading matches, and cover all four surfaces and
all four kinds across the case set. Do not mark a scaffold's cases reviewed.

Admission validates case structure/IDs and exercises actual capability matching
and pagination. `tests/unit/test_adaptor_completion.py` exercises representative CLI
and public agent paths. `search-acceptance.test.mjs` discovers all installed
adaptor-owned cases, obtains actual Studio server projections and invokes production
selection/Add/Help search functions; browser regression covers the rendered paths.
Run the tests separately: normal admission does not launch Node, browsers or native
apps. Retain observed cases/results with the completion review.
