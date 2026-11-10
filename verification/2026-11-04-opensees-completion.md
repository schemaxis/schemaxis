# OpenSees planar elastic truss completion — 4 November 2026

This review covers the new bounded planar pin-jointed elastic network product,
not the whole OpenSees application. The capability-family map and explicit
upstream exclusions are retained in `docs/opensees.md`. Runtime acceptance,
source-bound qualification and documentation admission are separate checks.

Registration/schema/semantics: adaptor-owned document route with typed nested
nodes, members, loads and named requirement records; finite bounds, unique IDs,
valid connectivity/targets, stability and small-strain/deformation preflight.
Host tests cover deterministic immutable planning and literal triangle mechanics.

Native mapping/execution: stable OpenSees 3.8.0 via OpenSeesPy 3.8.0.0 in isolated
processes. Native identities, connectivity, coordinates, fixed DOFs, material
tangent and basic stiffness-derived area are read back. Every native response
is independently checked by host direct stiffness and global force/moment balance.
Fresh-process reconstruction of retained physical JSON is explicitly distinguished
from native database persistence. Shared timeout/cancellation and retained logs
apply; fresh-directory publication prevents overwriting previous evidence.

Discovery/guidance/help/examples: curated structural search, ambiguous stress and
unsupported-physics negative cases; complete reviewed schema/operation guidance;
editable standalone and Studio triangle, signed-load and redundant-network
starters; local guide, generated operation reference and packaged contextual Help.

Tests/qualification: focused host/admission/guidance conformance, independent
triangle and area-scaling literals, native signed-load and redundant mixed-stiffness
cases, unmet measured limit, publication/native evidence tamper and lifecycle
controls. Detailed executed results are appended after the final bounded runs.

Maintenance/assessment: official distribution/GitHub and PyPI checked 4 November 2026;
engine3.8.0 and package3.8.0.0 are latest stable. Public API docs have older banners;
observed native probes establish this runtime mapping. Subjective whole-app breadth
and supported-workflow abstraction remain distinct from qualification. Bulk local
transcripts remain ignored under `evidence/`.

Not applicable: no MPI, dynamic time batches, interactive native inspection,
persistent live edits, native database save or file conversion operation. These
optional decisions are explicit in development/completion metadata. Workflow and
composition are declared through the shared contracts. Source/property editing
uses existing document controls and complete replanning; no framework app branches.

## Executed results

- Focused host suite: 7 tests passed; schema/planner agreement, deterministic
  immutable defaults, exact semantic faults, literal triangle/area-scaling
  mechanics, redundant and signed-load support, independent response mutations.
- Shared assessment suite: 20 tests passed, including real generated-index parity;
  assessment generator `--check` passed. Accepted historical baselines unchanged.
- Production Studio search/Help regression: 520 tests passed, including every
  OpenSees query, ambiguous stress, unsupported-physics exclusion and operation
  Help resolution.
- Guidance audit: 29 reviewed records; no pending or stale records. Readiness
  `--app opensees --admission --check` passed with generated Help present.
- Reference/schema, packaged Help and assessment generated-output checks passed
  with temporary integrated assets. Shared generated assets are deliberately
  restored for coordinated integration; integration must regenerate and recheck
  them before final product admission. The owned OpenSees reference/schemas remain.
- Bounded native acceptance: 23 checks passed across triangle, doubled area,
  uplift/lateral loads, a redundant mixed-stiffness rectangle and double-pin
  zero-force member with independently queried high-precision area. Tamper checks
  cover every publication, authored/plan/native/worker/submission evidence and
  changed native force with refreshed ordinary hashes. Unmet serviceability,
  timeout, missing package and mocked unsupported engine are distinct rejections.
- Workflow unchanged attempts reuse verified evidence; corrupted member CSV
  causes a fresh native attempt; changed authored workflow rejects resume with
  `RESUME_MISMATCH`. No unverified reuse is accepted.
- Canonical source-bound native conformance passed 5 cases, independent literal
  displacement/force/reaction witnesses, missing/tampered publications and
  authored/plan/verification evidence, timeout and prelaunch cancellation. It is
  repeated and recorded after shared-asset restoration; the registered receipt
  identifies exact source and observed engine/package versions. Integration makes
  that source identity stale and requires its own fresh final receipt.

Native proof is serial, bounded to the named fixtures, and establishes elastic
response/reconstruction rather than safety, whole-application breadth, MPI or
native project persistence. No unsupported optional feature is advertised as
qualified. Local bulk evidence remains outside version control.
