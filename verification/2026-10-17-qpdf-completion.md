# QPDF completion review — 17 October 2026

QPDF adds **bounded page assembly**: captured unencrypted local PDFs, named and ordered
page selection with repeats and relative clockwise quarter turns produce one new PDF,
published with a per-page summary and verified against the captured sources by fresh
QPDF and MuPDF observation. It is not a PDF sanitiser, repair tool, editor or malware
boundary, and it does not describe the whole PDF grammar. The route uses normal Schemaxis
planning, execution, verification, workflow reuse, handoff and finite composition. No
authored native code or paths reach a command line. Runtime scope is QPDF 12.4.2 with the
shared MuPDF 1.28.5 observer, serial POSIX. **Accepted by the supervisor on 18 October 2026**:
source-current native receipts are registered for QPDF and MuPDF, and QPDF 12.4.2 is absorbed
for this bounded scope. The final integration evidence and limits are recorded below.

## Checklist review

| Item | Result and evidence |
| --- | --- |
| registration | `schemaxis.qpdf/1` manifest with executable `qpdf`, flag `--qpdf`, route `runOptions {"oracle": "mupdf"}` using the shared `--mupdf`, `acceptedArtifacts ["pdf"]`, workflow/composition/resource/reuse hooks and explicit supported/unsupported feature decisions. Discovery and planning import no native module. |
| schema | Closed declarations: 1–4 `{name, path}` sources and 1–200 `{source, page, rotate}` pages with a typed `rotate` enum (default 0). Declarations cannot express an open alias map, so sources are a named list. No `pageLabels` field exists; unknown fields refuse. 50 host tests cover schema/declaration parity, exact fault locations and deterministic immutable plans. |
| semantics | Names, absolute `.pdf` paths, distinct names/paths, declared-and-used sources and in-range integers are validated at authored locations before any native process. Bounded envelope (below) refuses unsupported input with stable faults before publication; invalid timeouts fault before any effect. |
| native-mapping | `qpdf --empty --pages … -- --rotate=+N:K --remove-page-labels --deterministic-id --stream-data=preserve --object-streams=preserve` built only from fixed names and planned integers; `--suppress-recovery` on every read; `--warning-exit-0` is never used. MuPDF `PDFDocument`/`PDFObject`/`PDFPage`/`Pixmap`/`StructuredText` with an in-memory page-local `Rotate` override before loading; nothing is saved. Only MediaBox, CropBox, Resources and Rotate inherit; UserUnit and optional boxes are page-local. |
| execution | Every native stage runs through the shared cancellable process-tree runner under one cumulative deadline with POSIX AS (1 GiB QPDF, 2 GiB MuPDF), FSIZE 64 MiB and CPU 120 s caps; `remaining_timeout` is consulted before every launch and after the final host work; a launcher binds consumed inputs. Reads of sources, the publication and logs are bounded, regular and non-following; scratch copies use the same bytes that were hashed. Source and final PDFs share one JSON parser with identical byte/object/depth limits and malformed native JSON is a declared fault. |
| discovery | Curated merge/combine/reorder/extract/repeat/qpdf terms; owned reviewed multiword, synonym, ambiguous and negative cases (sanitise/redact/encrypt and OCR/render/preview refuse this route). Shared Studio search regression is supervisor-owned. |
| guidance | All 12 route/schema addresses plus the operation have reviewed conceptual guidance; audit: 13 reviewed, 0 pending, 0 stale. Physical-page numbering, relative rotation, discarded document data, refused features and budgets are explicit. |
| help | `docs/qpdf.md` states the bounded claim, setup (including the `unzip` requirement), the refusal table, losses, the exactly implemented verification contract and limits. The supervisor generated `docs/generated/qpdf-operations.md` and packaged Help; freshness checks and actual Studio contextual Help passed. |
| examples | Baseline (5 pages, repeat, one rotated repeat), held-out variant (reversed, per-instance rotations), a schema-valid invalid example (undeclared source), QPDF→MuPDF and QPDF→QPDF workflows, and the editable Studio starter. Hand-built literal fixtures are committed. |
| tests | `tests/unit/test_qpdf.py` (50 host tests, synthetic QPDF JSON for every admission, geometry, envelope and comparison branch, fake-runtime failure mapping, trusted-script properties) and `tools/qualify_qpdf.py` native qualification. |
| qualification | Full bounded product qualification passed. After the final Studio test repair, fresh common native conformance passed and source-current receipts were registered in the QPDF and MuPDF adaptor packages. See final integration below. |
| maintenance | `upstream.json`: latest-stable policy against the official GitHub release feed; QPDF 12.4.2 absorbed after bounded native acceptance and independent review. No second runtime family. |

## Supported envelope and loss boundaries

Selected pages may carry only `Type, Parent, Resources, Contents, MediaBox, CropBox, Rotate,
BleedBox, TrimBox, ArtBox, UserUnit` and an absent, null or empty `Annots`; their page-tree
ancestors only `Type, Parent, Kids, Count, MediaBox, CropBox, Rotate, Resources`. Only selected
pages and their effective resources are scanned; siblings are never read. A contextual scan
distinguishes field names, `/Type /Subtype /S` values and resource-map keys. The catalogue may
hold known discarded data (information, XMP, outlines, names, open action, viewer preferences,
language, page layout/mode, page labels); forms, signatures, permissions, layers, output
intents, tagged structure, threads, associated files, extensions and unknown entries refuse.
Geometry is typed (ordered non-empty boxes, CropBox/optional boxes inside MediaBox, integer
multiple-of-90 rotation, finite positive local UserUnit) with physical (UserUnit-scaled) side
≤ 8192 points and 36 dpi raster budgets (4096 per side, 16,777,216 pixels across all output
pages, repeats included) enforced before any raster is allocated. This is a bounded
allow-list, not a complete passive-PDF grammar; content-stream operators and font, image and
colour semantics are not scanned. Document-level losses are recorded in every plan.

## Verification contract (as implemented)

Normal `verify` resolves the current trusted QPDF and MuPDF (explicit, invocation context,
stored configuration, then `SCHEMAXIS_QPDF`/`SCHEMAXIS_MUPDF`), never a receipt path.
It reads the captured sources and publication once, then in fresh bounded processes re-admits
each source, checks the published PDF (QPDF check and JSON, catalogue, trailer, page-tree
membership/order, per-page boxes/UserUnit and `Rotate = (source + rotate) mod 360`) and
compares each output page with its captured source page, rendered with the page-local
`Rotate` overridden in memory, for **exact** 36 dpi raster, text and native geometry. The
retained diagnostics actually checked are: plan equals the recomputed plan; capture record
matches the captured bytes; the receipt lists exactly the two publications with current
digests; the summary equals the freshly recomputed summary; retained evidence files
(authored input, plan, capture record, captured sources, stage logs/launchers/bindings/
submissions) keep their digests. Stage logs are provenance, hash-bound but not reinterpreted.
Missing or wrong runtimes, timeouts and cancellation fault. No persistent cache, no general PDF parser.

## Native qualification (fresh directory `evidence/programme-20261017/integration-openai-20261018/qpdf-owner-corrections/qual-r3-full-b`)

Command: `tools/qualify_qpdf.py --qpdf <isolated QPDF 12.4.2> --mupdf <isolated MuPDF 1.28.5>
--output-directory <new>` (all six phases, serial, 449.0 s, `verified: true`, after the review corrections below; an earlier
full run of the same tool, `qual-r2-full`, predates them and is historical). Runtimes: official
QPDF 12.4.2 Linux release (checksum-verified, isolated) and the isolated source-built MuPDF
1.28.5. Prototype feasibility counts from the earlier design turns are historical and are not
counted here.

- **Shared kit** (`kit`): two cases (ordered-assembly 5 pages, reversed-rotated 4 pages), the
  runner timeout and pre-launch cancellation probes, 10 integrity probes per case (missing and
  tampered authored input, plan, receipt and both publications) — passed. The independent
  literal oracle (hand-built fixtures; sizes, quadrant colours and text known by construction, no
  QPDF or source-to-output comparison) matched all 9 published pages after each rotation.
- **Replaced-publication tamper matrix** (`tamper`, public `registry.verify`): the actual PDF was
  replaced and the receipt digest and publication companions refreshed, in three forgery modes
  (hashes refreshed; original summary kept; summary forged and refreshed). 14 hostile classes — swapped,
  dropped and extra pages, wrong rotation, stale CropBox, different resource colour with identical content
  stream, a moved 6-point mark, one changed digit, truncated, zero-byte and garbage files, an encrypted
  copy, an injected page action and an injected catalogue open action — gave **42/42
  `VERIFICATION_FAILED`**, each with its specific first failing contract recorded. Equivalent bytes
  (identical, and an object-stream re-save) were **accepted 4/4** with an unforged summary; the
  **2/2** equivalent cases with a forged summary were rejected.
- **Negatives** (`negatives`): 55 refusals with exact expected faults and no publication — catalogue,
  page, resource and action features, geometry and physical-size cases, encryption (empty user password,
  user password, owner-restricted), a missing `startxref`, malformed input, non-PDF header, over-size source, past-end page,
  500-page limit, 134 repeated A4 pages (budget), a prohibited selected sibling, missing and symbolic-link sources.
  Accepted and verified: decoy resource names, discarded document data (output catalogue is exactly the page
  tree), a prohibited but unselected sibling, decoy `/Ref` and `/OPI` resource names, and **133 repeated A4 pages** (exact budget).
  Two further inputs are admitted and then refused after assembly by the fresh observation (see Corrections): a page `/Parent` off its
  `/Kids` path and a null `/Rotate` under an inherited rotation; both fail `VERIFICATION_FAILED`, leave a failed `result.json` and no receipt.
  An aggregate-source parity probe (three valid 12.2 MB sources, 36.7 MB together) is refused by a new run (`INVALID_PDF_SOURCE`) and by
  saved verification of a run whose retained captured bytes and digests were replaced and refreshed (`VERIFICATION_FAILED`), as is a retained source without the standard header.
- **Runtimes and retained evidence** (`runtime`): no/wrong/relative QPDF and MuPDF (run and verify) fault
  `INTERPRETER_NOT_FOUND`/`UNSUPPORTED_RUNTIME`; the documented environment fallback verifies; a receipt and
  submission naming a canary executable never ran it; each retained-diagnostic mutation is rejected by both the
  public route and the raw product verifier (the shared run-storage snapshot faults first for a tampered authored input).
- **Lifecycle** (`lifecycle`): timeout and cancellation before the first launch; verification deadlines expiring
  part-way (0.15/0.6/1.2 s) fault within the budget; deadline expiry during final host work faults;
  verification cancelled before launch and **in flight inside a hung native observer** faults and the process group
  is gone; a run whose observer hangs ends at its 6 s timeout (6.1 s) with failed evidence retained.
- **Boundaries** (`boundaries`): direct bound run, registry run, finite study (2 states), workflow reuse and
  same-path changed-byte invalidation, scheduler with 2 workers and a dependent artifact job (3 jobs, resumed all
  reused, post-verified), QPDF→QPDF chain (literal oracle on the second output) and **QPDF→MuPDF handoff**
  (MuPDF reviewed the verified published PDF through an artifact binding; PNG sizes 160×240 and 596×842 match the
  literal expectation).

Host: 50 `test_qpdf.py` tests pass; guidance audit 13 reviewed/0 pending/0 stale; scoped readiness admission 0 failures
(against the supervisor-generated reference and Help); the host-only Studio search acceptance passes 168/168, including the reviewed
`merge PDF` and `reorder PDF pages` cases that previously failed on the Studio adaptor surface.

## Corrections after independent review and integration checks

- **Aggregate source budget parity (confirmed defect).** A run refused sources over 32 MiB together or without a `%PDF-` header, but saved
  verification re-checked only 16 MiB per source, so retained captured bytes with refreshed digests verified. Both now call one
  `capture_policy` (`adaptor.py`); verification reports `VERIFICATION_FAILED` at `retained captured source <name>`. Host tests cover the exact
  32 MiB boundary and prove no native launch happens first; a mutation check (policy neutralised) makes them fail; the native probe above
  reproduces the supervisor's scenario. This is a resource-contract fix, not a historical-attestation claim.
- **Studio discovery.** The adaptor and operation keywords now include the phrases users type (`merge PDF`, `reorder PDF pages`, `extract PDF
  pages`, `rotate PDF pages`, and neighbours); the reviewed search cases are unchanged.
- **External references (review F1).** `/Ref` (reference XObjects) and `/OPI` stream-dictionary entries now refuse; resource names `/Ref` and `/OPI` do
  not. Native negatives use form XObjects carrying each.
- **Messages and documentation (F2–F8).** The direct-object `/Parent` refusal names its cause (message only; supported semantics are unchanged). The
  guide now states the repeated fresh-observation cost (2S+7 launches per run, 2S+6 per verification, repeated by the common runtime), exactly which
  run-stage evidence is retained, the 3600 s run timeout cap and its effect on studies, post-assembly failures for inconsistent page trees, the
  16-versus-32 reference bounds, concrete bounded-appearance examples, and that a page transparency group refuses. The `LOSSES` prose is unchanged:
  it is part of the route version's plan and summary identity, and a wording change would make earlier runs fail verification.
- **Not changed, with reason.** An indirect-reference-to-null `/Rotate` cannot be refused on the host: QPDF's JSON omits that key, so only the
  fresh observation, after assembly, catches the disagreement when a parent supplies a rotation. An earlier host guard for it was removed as
  unreachable.

## Defects found and corrected during implementation

An invalid-timeout path and the final-envelope fault code were tightened by unit tests; an inaccurate
documentation row (a PDF missing `startxref` is `INVALID_PDF_SOURCE`, not `PDF_REPAIRED`, because recovery
is suppressed) was corrected; qualification harness mistakes (clones nested at the wrong depth for the run's
relative schema store, publication paths not rebuilt in clones, a stale configuration hiding a missing runtime,
an unused declared source in a test graph, scheduler output layout) were fixed without relaxing any expectation.

## Limits

Linux x86-64 only. QPDF's checksum was verified; its GPG signature was not. No fuzzed or hostile corpus beyond
the named cases; real-world PDFs were not sampled and many (hyperlinked, tagged, form, layered) are refused by
design. Both observers use MuPDF's renderer, so the literal fixtures provide the separate oracle. Verification
shows the current published bytes satisfy the captured request within the bounded appearance, text and geometry
contract; it is not full semantic equivalence, accessibility, colour management or conformance validation, and not
historical attestation. A run directory keeps absolute receipt paths and a relative schema-store reference;
raw directory relocation is not qualified. Shared schema export rebases schema references, without automatically
rewriting absolute receipt paths. The supervisor visually inspected two synthetic handoff pages from the earlier
qualification; final native acceptance uses fresh literal-oracle and exact comparisons. No real-world corpus was reviewed.

## Supervisor integration — 18 October 2026

The shared workflow guidance was remapped by route identity, preserving existing explanations. References,
the ParaView documentation-only guide and packaged Help were regenerated and passed freshness checks.
All guidance, scoped admission and the public release gate passed. No native ParaView was invoked.

- Full host suite: **1,823 tests, 33 skipped, zero failures or errors**, 734.196 seconds. Python/runtime sources,
  unit tests and generated Help remained unchanged throughout the run. Two packaged Studio test files were
  repaired during it and checked in the separate Studio verification below; the exact source delta is retained.
- Full serial Studio suite: **399 tests, 396 passed, 3 existing skips, zero failures**, 260.699 seconds.
  The first run's seven failures were stale FreeCAD test assumptions: positional template selection and the older
  default Help guide. The repair selects the intended `solid-box` by ID and checks the accepted PartDesign guide,
  retaining operation Help and the older CAD workflow topic. Production UI and templates were unchanged.
- QPDF Studio: all four discovery phrases, operation/field Help, typed source/page editing, validation, Cancel and
  atomic Undo passed in the actual browser. All 168 search-acceptance cases passed.
- Independent Claude Fable review approved the core design and then the correction set. The supervisor independently
  repeated the original 34,603,029-byte source-budget reproduction: both run and saved verification now refuse
  before any native launch. The reviewer's policy mutation check demonstrated that the host regressions discriminate.
- Fresh full QPDF qualification passed all six phases, including the actual QPDF→MuPDF handoff; fresh MuPDF
  qualification also passed. The subsequent Studio test-only changes affect conservative source digests, so both
  common native kits were refreshed before registration. Product code and native semantics were unchanged.
- Registered source digests: QPDF `sha256:3527617afc02ccf110e24c274465338be218c17de0a4e4d5f8045e17312069e0`;
  MuPDF `sha256:839f3723d31da8b46f31f56ad0cdc0f10ed020de6af71df648ad94fcaab3acc9`.

Local evidence is retained under `evidence/programme-20261017/integration-openai-20261018/`: the two independent
reviews, original and corrected budget probes, owner corrections, Studio runs and `final-integration/` results.
Failed native fixtures, the initial failed Studio suite and an aborted incomplete Studio file-list invocation remain
available; none was relabelled as a pass. Other adaptors' earlier native receipts are historical after shared-source
changes unless separately refreshed; this acceptance makes no all-provider source-freshness claim.

Additional native review confirmed that some malformed direct-object parents carrying inherited values also fail
only after assembly, leaving an unsuccessful run without a receipt. This is the safe failure direction, not support
for arbitrary page-tree structure. Fixture detection of invisible text and a 0.005-point mark does not establish a
general minimum detectable feature size.

Latest-stable release confirmation used the official [QPDF 12.4.2 release](https://github.com/qpdf/qpdf/releases/tag/v12.4.2)
and [release notes](https://github.com/qpdf/qpdf/blob/main/manual/release-notes.rst), because the API endpoint was
unavailable through the browsing interface. Absorption is limited to the native behaviour qualified here.
