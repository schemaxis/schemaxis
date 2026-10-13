# Source review and reuse assessment

Reviewed 2026-10-03 against Schemaxis `4487292`. No native applications were
started for this review.

## Existing Schemaxis capabilities

| Finding | Source |
| --- | --- |
| Operation IDs must be unique; adaptor IDs need not be. Artifact/value dependencies refer to earlier operations. | `src/schemaxis/workflow.py:validate` |
| Workflow-wide dimensions/definitions/settings, scoped document references and finite analytics exist. | `src/schemaxis/adaptor_runtime.py:workflow_inputs`, `InputProgram`; `docs/adaptor-runtime.md` |
| Scalar JSON/numeric CSV result references are resolved after verified producer outputs. | `src/schemaxis/parallel.py:resolve`; `docs/adaptor-runtime.md` |
| Feedback is already bounded, deterministic and replay-verified, with Gmsh/FreeCAD policies. General workflow feedback is not yet a public authored contract. | `src/schemaxis/feedback.py`; `docs/feedback-studies.md` |
| Workflow diagram, shared source/property editing, diagnostics and undo already exist. | `src/schemaxis/workflow_authoring.py`, `authoring.py`, `console_ui/workflow.mjs`, `console_ui/authoring.mjs` |
| Geometry/image picks are revision-bound historical references; images currently support one pixel, not regions. | `src/schemaxis/console_references.py` |
| FreeCAD has bounded semantic edge selection, named measurements and one-parameter design studies. | `docs/freecad-selections.md`, `freecad-measurements.md`, `freecad-design-studies.md`; adaptor implementations |
| Table inspection uses immutable snapshots, paging and typed historical ranges; no cell editing/formula engine. | `docs/typed-inspection.md`; `console_ui/inspection.mjs` |
| ParaView live support owns a serial worker, bounded tessellation and preview; it does not attach to arbitrary existing GUI sessions. | `src/schemaxis/adaptors/paraview/live.py`, `live_native.py` |
| Python package, bundled browser assets and private executable configuration exist; no Schemaxis desktop installer was found. | `pyproject.toml`; `docs/installation.md` |

An earlier informal description understated workflow-wide parameter support.
Current code and the newer common-runtime documentation correct that assessment.

Documentation drift to repair during implementation:

The specific workflow-context and membership statements below were
corrected in the first development milestone; this list records the review baseline.

- `docs/json-input.md` says workflow envelopes lack authoring containers, although
  the current parser accepts common `dimensions`, `definitions` and `settings`.
- `docs/design/adaptor-candidates.md` repeats the older restriction on workflow
  parameter fields.
- Older workspace delivery-plan paragraphs predate the implemented discovery and
  agent service. Preserve their historical context; current capability claims
  should point to current contracts and evidence.

A host-only example probe also found a concrete planner limitation. An artifact-only
FreeCAD STEP → Gmsh input with literal mesh size is replaced by a synthetic path
without a STEP extension, and Gmsh's host planner rejects it as `INVALID_RESOURCE`.
The main example uses a legitimate upstream height measurement to choose mesh size;
its result-dependent plan is explicitly deferred. The paired probe preserves the
artifact-only limitation in `design-checks.json`. D0/D1 must qualify typed deferred
artifact planning instead of weakening Gmsh's native input checks.

First-milestone update: artifact/value-dependent plans are now explicitly deferred;
resolved consumer inputs and resource requirements are checked before dispatch.
The original `design-checks.json` remains historical evidence of the defect.
See implementation status and the new handoff regression tests for its correction.

## Existing Qt grid widget

An existing custom-painted Qt number-grid widget was reviewed as a reference for
table interaction. It is a useful interaction implementation, but not a standalone
general table widget: its selection, coordinate and number-specific value model are
coupled to the widget. Its grid can extend through zero-valued regions and
mathematical coordinates; ordinary data tables have row identities, headers,
missing cells, strings and values where zero is meaningful. Its Ctrl+Arrow jump
compares nonzero status, special-cases axis and bounds positions, and has a
bounded search, so it is a poor drop-in definition for spreadsheet navigation.

Reuse recommendation:

| Item | Recommendation |
| --- | --- |
| Cursor, anchor, range extension, edit-mode separation | Reuse the interaction concepts and turn them into explicit table tests |
| Keyboard shortcuts, focus retention, zoom and rectangular clipboard flow | Use as reference behaviour, with ordinary-table semantics specified separately |
| Custom paint implementation and number-specific value model | Do not transplant into the browser creator |
| Direct C++ widget reuse | Consider only if a later Qt client is approved; first extract a value-model interface and qualify it as a general widget |
| Windows/Linux packaging work | Useful packaging reference, not a ready Schemaxis installer |

The first table specification should distinguish empty from numeric zero and
read-only results from editable case values. Arrow moves one cell; Shift extends
from the anchor; Ctrl+Arrow moves to the current contiguous occupied region's end
when the next cell is occupied, otherwise to the next occupied cell or table edge;
Ctrl+Shift adds extension. At a region edge it must progress into the next region
on a repeated press. Null/absent/empty-string are empty; `0`, `false` and whitespace
strings are occupied unless a column contract explicitly normalises them. Limits
are the declared table extent, not the loaded page; fetch metadata/pages rather
than guessing beyond a page. Include empty tables, gaps, isolated cells, zero,
large ranges, first/last row and cancelled editing in acceptance.

Copy/paste must validate the complete rectangle before recording one undo group;
preserve tabs/newlines using the declared clipboard format. Result snapshots remain
immutable. Edited data become a separate authored case/input with provenance.
No formulas are interpreted from pasted strings in the first release.

No code from the reviewed widget was copied here. If a future change extracts
code, retain provenance and the original licence notice and verify any separately
bundled third-party dependencies before distribution.

## ParaView and native-window options

Official ParaView documentation supports Python scripting in its desktop shell
and tracing GUI actions, with stated trace limitations. It supports the possibility
of a dedicated integration; it does not prove complete declarative reverse-sync
or a supported way to extract a chosen panel from someone else's running session.
[ParaView scripting](https://docs.paraview.org/en/latest/UsersGuide/introduction.html#scripting-in-paraview).

ParaView's 5.13 tutorial demonstrates browser rendering using trame and a compatible
Python environment. This is a candidate optional view backend, not a qualified
Schemaxis integration. No package was installed or runtime changed during review.
[ParaView trame tutorial](https://docs.paraview.org/en/v5.13.1/Tutorials/ClassroomTutorials/targetedTrame.html).

Qt's `QWindow::fromWinId` may fail when foreign-window support is unavailable.
Qt also cautions against using that wrapper to inspect/control the foreign
window's state. Therefore window embedding is not the general authoring protocol.
This conclusion is an architecture inference from Qt's documented boundary.
[Qt API documentation](https://doc.qt.io/qt-6/qwindow.html#fromWinId).

The recommended path is an app-independent view/control contract, a managed
ParaView worker first, and a separately tested rich view later. Native desktop
attachment, if added, needs explicit ownership, allowed edits, revision/capture,
disconnect/reconnect and unsupported-native-edit behaviour. Arbitrary GUI tracing
must never silently promote executable Python into template input.

## Review validation scope

`design-checks.json` records host-only checks of the illustrative workflow and
two bindings against the current planner. It does not validate a new production
template loader: none has been implemented. It does not show that the physical
car workflow, native feedback, Qt reuse or embedded ParaView works. No benchmark
model, native replay, GUI build or solver was run for this design.
