# Studio validation in workflow context

An operation draft inside a saved workflow now validates against that workflow's
current revision. This fixes false standalone diagnostics for future `$artifact`
inputs and workflow-scoped definitions, while retaining the ordinary parent
validator's dependency, ordering, provider and concrete-value checks.

The validation request identifies the parent document, revision and operation
together. The server checks those identities, validates a copied parent containing
the draft and enforces the combined one-MiB limit. Validation does not save the
draft, change focus or revision, or launch a native application. Faults receive
draft-relative field coordinates only when their operation provenance is known;
faults in another operation or connection stay at the draft root with the original
workflow location retained.

Future inputs can be reached indirectly through workflow definitions. The normal
input resolver determines whether validation is deferred. A separate
`requiresWorkflow` result also keeps concrete values resolved from workflow
definitions in their parent context. Workbench Preview and Run check this before
publishing the draft or creating a standalone document. Plain concrete operations
retain standalone preview behaviour. Local expressions resolved in context are
conservatively kept with that context too.

The shared editor validator also handles heterogeneous schema alternatives more
carefully. It narrows genuine tag branches without treating an impure conditional
as a tag selector. Selected conditional constraints and invalid constructor fields
remain visible; ambiguous unselected alternatives do not produce false errors.

## Evidence

- Fifteen focused host tests cover workflow and workflow-design versions 1/2,
  revision and provider checks, reference shape and order, faults from same-named
  nodes in different operations, indirect references, concrete definitions and
  read-only behaviour with native process creation forbidden.
- Three actual browser tests cover direct artifacts, indirect artifacts and
  concrete workflow definitions. Guarded previews make no write requests and
  preserve the parent and revision.
- The alternative-validator followup passed 24 unit tests and killed ten new
  mutants. Its comparison corpus retained diagnostics across 217 examples and
  8,680 deliberate corruptions. Earlier mutation evidence is retained separately.
- Independent Fable review accepted the final fixes and the indirect-reference
  followup, with no outstanding blocker.
- Final integration on 18 October 2026 ran all 1,867 host tests (33 skips, no
  failures) and all 55 Studio test files (439 tests: 436 passed, three existing
  skips, no failures or TODOs). The 2,871-file public integration inventory was
  unchanged throughout the run. Reference, Help and guidance checks passed.

Ignored evidence is in
`evidence/programme-20261017/integration-openai-20261018/`, under
`studio-workflow-context`, `studio-workflow-context-r1`,
`studio-workflow-context-indirect`, `studio-alternatives-review-fixes`,
`studio-review-followups`, `studio-indirect-review` and
`freecad-phase2-final-integration`.

This checks drafts against the saved parent revision. It does not execute future
producers, establish the contents of unproduced artifacts or provide a native
mount editor. Final input checks still occur when workflow dependencies resolve.
