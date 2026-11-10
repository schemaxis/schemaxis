# Querying adaptor strength

`schemaxis assessments` returns a machine-readable inventory of registered
application providers, their authorable document routes and adaptor-owned
strength estimates. `schemaxis assessments --format text` prints a compact human
summary; `--app PROVIDER` selects one provider and may be repeated. The
[generated index](generated/adaptor-assessments.md) includes each rationale,
denominator and material limitation. Discovery includes provider and route counts
and compact assessment links; capability application summaries expose the same
scores and full-query command.

```sh
schemaxis assessments
schemaxis assessments --app freecad
schemaxis assessments --format text
schemaxis assessments --compare verification/2026-10-25-adaptor-assessments.json
```

A provider is an installed/registered integration, including enabled external
plugins. A route is an authorable document version. Multiple correction versions,
rendering routes or assembly routes do not become additional applications. This
inventory does not scan for executable installations. Plugins disabled or excluded
by the existing registry are not counted; visible plugin faults remain separate.
A provider without an assessment is reported as `missing`, never zero percent.
Malformed editorial metadata is reported as `invalid` with a structured fault; it
does not remove a provider, alter its routes or block planning/execution.

## Rubric version 1

Both dimensions are subjective editorial estimates rounded to five percentage
points. They are not measured ratios, native API call counts or statistical
probabilities. Confidence (`low`, `medium`, `high`) describes uncertainty in the
editorial estimate; it does not describe verification success.

| Anchor | Whole-application breadth | Abstraction within the declared supported workflows |
| --- | --- | --- |
| 0% | No useful workflow coverage. | Raw native procedures and configuration dominate. |
| 25% | A few useful families; major application areas missing. | Thin typed wrappers; users assemble most domain decisions. |
| 50% | Several central families; substantial gaps. | Domain operations, units and constraints; substantial manual composition. |
| 75% | Most central workflows; specialist gaps. | Workflow intent, defaults, requirements and useful deliverables; some native detail remains. |
| 100% | Essentially complete useful application breadth; exceptional justification needed. | Complete supported-task intent and coherent decisions/handoffs without material native plumbing. |

**Breadth** assesses useful functionality across the whole targeted application
or library. Each record names the functional families used as its denominator.
Those families are editorial categories, not equally weighted API buckets. A
workflow may cover application functionality without mapping one-to-one to API
methods. Scores account for useful families, depth and exclusions; operation and
test counts are supporting evidence rather than denominators.

**Abstraction** asks how directly the named supported slice expresses a user's
intent and decisions. Named requirements, physical units, sensible defaults,
reusable task composition and useful deliverables can improve abstraction.
Typed native properties alone usually provide less abstraction. A deliberate
low-level choice can still be appropriate; this score is not an overall quality
rank. A narrowly focused cantilever or root-isolation task can have high
abstraction and very low whole-application breadth. Generated native catalogues
can offer broad declarations with more uneven abstraction.

The first scored baseline is dated 25 October 2026 and covers 41 providers and
47 routes. Its evidence is the source contracts, guides and completion records
at assessment time, not a new execution of every application. Premiere remains
native-unqualified; whisper.cpp correction/caption routes remain host-only.
Neither fact is hidden by a score. The earlier October programme assessment is
historical; its decision to avoid percentages has been superseded for this
scored system.

## What percentages help and obscure

Explicit scores make progress visible, support rough relative triage and expose
judgements that might otherwise remain implicit. They are easy for people and
agents to query and can guide investment when combined with workflow value.

They also suggest a precision the evidence does not possess. Native products
have different sizes and functional boundaries; a single feature can matter much
more than many minor options. An assessment can change because its denominator
or editorial understanding changed. Five-point rounding, explicit scopes,
rationales, confidence and retained baselines help, but do not remove those
limits. Do not average providers into a product completeness percentage, treat
small score differences as decisive, or advertise a narrow abstraction score as
whole-application coverage. Customer demand and practical workflow value remain
separate product evidence.

The [focused host acceptance note](../verification/2026-10-25-adaptor-assessments.md)
records the exercised invariants and limitations.

## Ownership, validation and maintenance

Each adaptor owns `assessment.json` beside its existing `adaptor.json` and
`readiness.json`. The framework enumerates the existing registry and reads this
resource through the same package-resource boundary used for plugins. There is
no second registration list and no application-specific assessment branch in the
framework. Discovery stays dependency-free and does not import native runtimes.

The record includes a versioned rubric, assessment version/date/assessor,
provider/document versions, assessed routes, source fingerprint, both metric
scopes/statuses/rationales/confidence, repository-relative evidence and material
limitations. Validation rejects unsupported versions, malformed scopes,
non-integer/out-of-range/unrounded percentages, duplicated routes, invalid dates,
missing explanations (including whitespace-prefixed TODO placeholders), dates
later than the current civil date anywhere in the world, and non-portable
evidence references. The date check uses the current UTC instant plus fourteen
hours, so a valid local date is not rejected at a timezone boundary. All current
estimates use `subjective`; a future measured methodology needs a new explicit rubric,
rather than silently reinterpreting these scores.

When changing an adaptor:

1. Reconsider the two rationales and denominators against the useful changed
   workflow, including remaining omissions. A bug fix or added test need not
   increase either score. Keep old assessments visibly stale until reviewed.
2. Update the adaptor-owned record and increment `assessmentVersion`; set the
   assessment date and preserve the actual reviewed routes. Refresh
   `sourceFingerprint` with `schemaxis.assessments.source_fingerprint(PROVIDER)`.
3. Retain concrete evidence references. Recheck confidence in the estimate;
   native verification and runtime availability continue through readiness and
   source-bound qualification, independently of strength metadata.
4. Run the assessment tests and regenerate the current index with
   `PYTHONPATH=src python3 tools/generate_adaptor_assessments.py`. Its `--check`
   mode detects drift, and the shared host suite compares the real generated index
   against the live report. New provider scaffolds may remain explicitly unassessed
   until a useful editorial review exists; never fill them with optimistic scores.
5. At a useful progress checkpoint, create a **new** dated snapshot using
   `--write-baseline verification/YYYY-MM-DD-adaptor-assessments.json`. Existing
   files are refused before changing the current index. Never regenerate an old
   accepted baseline to simulate improvement.

The fingerprint hashes every adaptor-owned resource file regardless of extension,
including native HTML, JSX, GDScript, ImageJ macros and binary resources.
It excludes assessment/readiness/qualification/upstream/Studio/guidance metadata,
Python bytecode, cache/version-control/dependency directories, tests, repository
guides outside the adaptor package and shared framework code. Adaptor-local
guides are included. Route-inventory or
primary-version changes also mark an assessment `stale`. An assessed route absent
from the current registry is allowed as an explicitly historical scope: it makes
the record stale, never registers or re-enables that route, and requires review
before the assessment can be described as current. `current` only means no
change detected in that declared scope; shared framework changes, upstream
releases and newly discovered limitations can still require editorial review.
It does not mean native-qualified, latest-upstream-compatible or recently tested.

`--compare` preserves provider additions/removals and returns point deltas only
when rubric and complete metric scope are unchanged. Scope changes produce
`comparable: false` and a null delta; stale current records retain their label.
A delta is a change in editorial estimate, not measured functional progress.
Reports retain explicit `selection` provenance. When either snapshot is filtered,
comparison uses only mutually selected providers. Unselected baseline providers
are listed as `baselineNotSelected`, not removed; current providers outside a
filtered baseline are listed as `currentNotSelectedInBaseline`, not added.
Baselines without explicit selection provenance are rejected, because their
entries cannot establish whether omitted providers were removed or unselected.
Use full snapshots to compare full provider inventories.
The default JSON retains full assessment records; text output is deliberately compact. Comparison details require JSON output.

The public index generator refuses enabled external plugins before writing
anything; set `SCHEMAXIS_ADAPTOR_PLUGINS=off` to generate builtin product material.
The shared index parity test likewise selects builtin providers from the existing
registry. Normal queries continue to include installed plugins. Save their JSON
output separately for an installed-inventory baseline. Failed baseline writes are
removed when incomplete; a completed dated baseline is never overwritten.
