# Architecture integration — 16 October 2026

Integrated three new application adaptors, two extended adaptors, optional
ParaView schema grouping/storage, and the shared discovery, guidance, examples
and Help surfaces. The application catalogue now contains 20 providers.
Changes are uncommitted; no package release or website deployment was performed.

## Delivered application scope

| Application | Supported addition | Final native runtime | Conformance cases |
| --- | --- | --- | ---: |
| [KiCad](../docs/kicad.md) | Inspect existing two-layer boards, check design rules and export independently checked Excellon drill hits | 10.0.7 | 4 |
| [ImageJ](../docs/imagej.md) | Threshold and measure particles in one calibrated 8/16-bit image plane, with independent pixel/component checks | 1.54t, Java 21.0.12.1 | 6 |
| [PrusaSlicer](../docs/prusaslicer.md) | Slice one closed STL using an explicit generic Marlin 2 FFF profile; replay G-code and compare native settings/geometry | 2.9.6, locally built CLI-only | 3 |
| [Cantera](../docs/cantera.md) | Constant-pressure/constant-volume adiabatic reactor histories for the pinned hydrogen mechanism, checked against an independent integrator | 3.2.0 | 10 |
| [R](../docs/r.md) | Classical least-squares coefficient standard errors, tests and confidence intervals under explicit model assumptions | 4.6.1 | 6 |

These are bounded serial qualifications. KiCad does not author boards or qualify
all native DRC rules. ImageJ does not expose arbitrary macros or batch imaging.
PrusaSlicer does not control printers or establish physical print quality; its
geometry checks do not prove complete toolpath shape equivalence. Cantera does
not support arbitrary reaction mechanisms. R does not establish model validity,
causality or robust inference. See each guide and completion note for limits.

## Integrated verification

- The combined host suite passed: **1,556 tests in 480.047 seconds, 32 skipped**.
  Skips retain their optional/native requirements; native checks below ran
  separately. After the final Help-generation fix described below, all **25
  completion and qualification-kit regression tests** passed again, including
  the new receipt/source-identity regression.
- Studio Help and search passed **57/57** checks. All five application guidance audits
  and admission checks passed. Shared workflow guidance was remapped by route
  identity after provider insertion; a regression guards against index drift.
- Generated reference, ParaView operation guide and packaged Studio Help passed
  their freshness checks. The Help package contains 976 topics plus its index.
- Fresh native conformance passed **29 cases, 338 integrity probes and 10
  timeout/cancellation probes** across the five applications above.
- All five application-specific qualifiers passed separately, including
  independent analytic cases, forged-output rejection, requirements and reuse
  checks, and the declared ImageJ/Cantera/R-to-Calc handoffs.
- Each final receipt was registered only after shared generation and compared
  with the actual final source digest. All five report `source-current`.
  Public receipt copies replace only workstation executable locations with
  `<configured-runtime>`; unmodified receipts remain in ignored local evidence.
- A clean wheel build passed resource and privacy audits: all 977 Help files
  and all five registered receipts match source bytes. An extracted wheel under
  `python3 -I -S`, outside the checkout, discovers all 20 applications, exports
  the five affected schemas and creates the six-member ParaView bundle without
  importing optional/native modules. Release scans of public files (including
  untracked additions) and the wheel found no unallowlisted private material.

Independent review found and resolved numerical, parsing and evidence gaps:
PrusaSlicer native-info rounding for small inch-authored solids; incomplete STL
input rejection; Cantera empty/malformed trajectory acceptance; KiCad ambiguous
connectivity, bounded file access and native-stage evidence binding; and ImageJ
16-bit Studio template bounds. Verification was not relaxed to accept failures.

The final packaging check also exposed a circular dependency: Help copied linked
qualification receipts, whose source digests included those Help copies.
Generation now keeps receipt references without embedding their changing contents.
It still rejects missing linked receipts and packages ordinary linked JSON. A
regression proves that changing a receipt leaves Help and source identity stable.
All five native conformance and application qualifier runs were repeated after
this correction; no source-digest fields were rewritten to manufacture freshness.

Bulk logs and retained outputs are under ignored
`evidence/architect-20261016/final/`. Key files are `host-suite.log`,
`studio-search.log`, `native-summary.json`, `qualification-status.json`,
`source-digests.json`, the five `*-native/qualification.json` receipts and five
`*-qualifier.log` transcripts. Registered portable records live in each owning
adaptor's `qualification.json`.

Reproduction entry points (use configured runtimes and new output directories):

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
PYTHONPATH=src python3 -m schemaxis reference --check
PYTHONPATH=src python3 tools/generate_studio_help.py --check
PYTHONPATH=src python3 -m schemaxis readiness --app APP --admission --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.APP/1 \
  --native --timeout 300 --wall-timeout 600 --output-directory NEW_DIR
```

Application qualifier commands and installation requirements are in the five
dated completion notes and guides. Native receipt timestamps are in UTC; this
note uses the local session date.

## ParaView and retained storage

The selected grouping is **common, readers, filters, rendering and writers**,
with a complete document entry point. Existing standalone exports are preserved.
The optional content-addressed snapshot store retains exact bytes and verifies
relative references, hashes and relocation. Ten identical actual schema captures
used 4,080,622 bytes instead of 40,774,020 bytes: **90.0% less storage**.
Grouping itself adds a little total storage; its benefit is smaller category
entry points. See the [measured schema/storage review](2026-10-16-paraview-schema-storage.md).

No native ParaView run was performed. Historical evidence was not migrated or
deleted. The read-only audit also found substantial exact duplication in runtime
archives and plans; this implementation does not deduplicate those automatically.

## Qualification boundaries

Only the five changed application routes received fresh native qualification.
Older records remain historical evidence and may be stale because shared source
changed. A catalogue count of retained native runs is not a claim that every
route is qualified against the current source, platform or installed runtime.
The five `source-current` results above are for the integrated checkout. A
standalone wheel retains the receipts but omits checkout-only fixture/test
context used by the conservative source fingerprint; it does not inherit that
checkout freshness result. Qualify the actual deployment and runtime separately.

The historical repository's source was not edited. Earlier cross-application
checks launched an existing LibreOffice installation whose bootstrap changed two
cache-directory timestamps without changing retained file contents. Final Calc
checks used private runtime copies in the active repository's ignored evidence.

The separate website uses recovered real output images, identifies the historical
orbit's date and input contract, and distinguishes recorded native evidence from
current-source qualification. No synthetic scientific output was substituted.
Private commercial analysis and ownership/licensing discussions remain outside
the public repository; no project licence change was made.
