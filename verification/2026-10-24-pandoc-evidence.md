# Pandoc hostile retained-evidence review — 24 October 2026

Scope: the existing `schemaxis.pandoc/1` report route's later, independent
verification of retained artifacts (`schemaxis verify`), and the native launch
boundary. No new report fields, operations or routes. Earlier route review:
[2026-10-17-pandoc-completion.md](2026-10-17-pandoc-completion.md).

## Audit workflow

An untrusted-input report is planned, its PNG is captured, Pandoc runs in isolated
per-stage launchers (version, API probe, HTML, DOCX, fresh DOCX readback), and the
retained directory is later reopened by `verify` with ordinary receipt/publication
hashes. The weak point is a directory whose bytes and hashes were rewritten
together (hashes refreshed), so only the independent inspectors protect the reader.

## Gaps reproduced and fixed

Each was reproduced against a real native run directory with refreshed hashes
(`probe-hostile-before` in the evidence directory) and has a regression in
`tests/unit/test_pandoc_evidence.py`. The tests fail on the pre-change source.

| Gap | Fix |
| --- | --- |
| Text or elements outside `<body>`, text in `<head>`/`<header>`/table containers, comments and processing instructions passed HTML verification although browsers display them | HTML must be exactly `html`→`head`,`body` with whitespace-only text in structural containers, reviewed child elements, no comments/PI/odd declarations, balanced closing and bounded nesting |
| DOCX package members and relationships were unchecked beyond `word/document.xml` (macros, embedded objects, custom XML, headers/footers, hidden text in footnotes, external relationships outside `document.xml.rels`, unreviewed relationship types) | Reviewed Pandoc writer part allowlist, per-`.rels` external/type checks, text-free auxiliary parts, header/footer references refused, encrypted/unsupported compression refused |
| Raw `RecursionError`, `RuntimeError` (encrypted member), `zlib.error`, `OverflowError` escaped `verify` | Retained JSON is strict (no duplicate keys, non-finite constants or deep nesting); any other inspection exception becomes `VERIFICATION_FAILED` |
| Undeclared files in the output directory and unreferenced extracted `reopened/` media verified successfully | Directory and extracted-media membership are checked against declared publications/evidence |
| Distribution Pandoc without embedded data files failed the DOCX stage as a generic `RUNNER_FAILED` | Specific structured `UNSUPPORTED_NATIVE_BUILD` with recovery; the sandbox is never relaxed |
| A concurrent `mkdir` race raised an unstructured `FileExistsError` | `OUTPUT_EXISTS` |

Checklist items touched: execution, tests, qualification, help (fault recovery in
the guide and readiness recovery text), maintenance (`upstream.json` acceptance
note). Registration, schema, semantics, discovery, guidance and examples are
unchanged. The qualifier (`tools/qualify_pandoc.py`) gained refreshed-hash probes
for these cases; they ran against the shimmed 3.7.0.2 run (below) but not yet in
a full official-binary qualification.

## Native observations (all newly run, 24 October 2026)

The only local Pandoc is the distribution package **3.7.0.2**; the route is
absorbed and qualified for the official **3.12.1** binary, which is unchanged.

- `schemaxis run … --pandoc /usr/bin/pandoc` stops at the DOCX stage: the
  distribution build cannot find `data/docx/[Content_Types].xml` under `--sandbox`
  (HTML stage passes). It now reports `UNSUPPORTED_NATIVE_BUILD`. **No unmodified
  3.7.0.2 baseline/variant passes, and none is claimed.**
- The unmodified verifier also rejects 3.7.0.2 HTML (stylesheet fingerprint and
  extra `role`/`aria-label` image attributes) and DOCX (body-level bookmarks): the
  route fails closed on output of an unreviewed Pandoc release.
- For verifier probes only, a test shim dropped `--sandbox`, removed those
  attributes/bookmarks and swapped the stylesheet fingerprint in-process. With it,
  real Pandoc 3.7.0.2 produced baseline and variant reports that the
  registry-bound `verify` accepted, and nine refreshed-hash tamper cases through
  the public verifier (altered cell, text after body, comment, extra file, extra
  media, deep readback, altered launcher, relative executable, replaced captured
  image) and all qualifier negative probes were rejected with structured
  `VERIFICATION_FAILED`. These are **not qualification** of any runtime and do not
  show that the sandboxed route works on 3.7.0.2.

## Official 3.12.1 acceptance (newly run, unregistered)

An isolated official Pandoc 3.12.1 Linux binary (SHA-256
`10a980df73e7fea52904375d4de731c4ed61fd1c45fa0900facd2a5972ff0ee1`, release archive
digest verified by the integration owner) ran the unmodified
`tools/qualify_pandoc.py`, no shim, without `--register`. The first integration
run passed native baseline/variant and every hostile case but failed
`workflow.verify`: the new membership check rejected the framework-owned
`job.json` the workflow coordinator adds to each attempt directory. That was a real
regression from this change. `job.json` is now an allowed framework member (it must
be a regular, non-symlink file) with a host regression. The rerun passed: baseline
and variant verified on `pandoc 3.12.1`, 21 refreshed-hash probes (including the
new HTML, DOCX, membership, deep JSON and duplicate-key cases) all rejected with
`VERIFICATION_FAILED`, timeout and pre-launch cancellation, workflow unchanged
reuse and changed-image invalidation with `workflow.verify`, and a two-state
finite study. `schemaxis verify` on the retained baseline also verifies. This
bounded serial result shows the tightened HTML/DOCX shapes accept 3.12.1 output
for these cases only; the registered receipt in `qualification.json` is still the
old, source-stale one until the integration owner re-registers.

## Limits and open work

- Parts or HTML structure emitted by other Pandoc releases fail closed until
  reviewed; only the cases above were observed on 3.12.1. The registered receipt is
  source-bound and is now stale until re-registered (`--register`).
- The shared `schema_store.verify_run` reads `authored.json` with plain
  `json.loads`; a pathologically nested `authored.json` still raises a raw
  `RecursionError` in the public bound `verify` before this adaptor runs. This is
  shared code outside this adaptor's ownership.
- Launchers hash each stage input and then exec Pandoc, which reopens it by path;
  an actor with write access to the live run directory during execution could swap
  bytes in between. Receipts are audit evidence, not signed attestations.
- No change to scientific or layout claims: no exact page layout, PDF,
  accessibility or colour-management certification.

## Commands run

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_pandoc*.py' -q   # 15 tests OK
PYTHONPATH=src python3 tools/studio_guidance.py --app pandoc --check               # 26 reviewed, 0 pending
PYTHONPATH=src python3 -m schemaxis readiness --app pandoc --admission --check
PYTHONPATH=src python3 -m unittest tests.unit.test_compatibility tests.unit.test_captured_inputs -q
PYTHONPATH=src python3 tools/qualify_pandoc.py --pandoc /absolute/isolated/pandoc-3.12.1 --output-directory evidence/pandoc-native   # passed, unregistered
```

Shared generated references and packaged Help, final suite and native
re-registration are left to the integration owner.

## Supervisor native and shared-parser integration

Fresh unmodified official Pandoc 3.12.1 baseline, variant, hostile-content, timeout,
cancellation and workflow/resume acceptance passed after the worker's changes.
The archive digest matched the official upstream release metadata. No sandbox
shim, stylesheet replacement or altered inspector was used for that acceptance.
An initial native workflow check exposed a membership regression for the
coordinator's `job.json`; the exact framework member is now accepted as a regular
file, with a regression. Unknown metadata-sidecar names are refused.

The shared retained-schema boundary also converts parser and schema-keyword walk
recursion failures into `INVALID_SCHEMA_SNAPSHOT`. Regressions exercise the actual
Python 3.10 parser and a schema that parses onPython 3.14 but previously leaked from
the recursive keyword walk. Deep malformed parent metadata no longer aborts
schema capture. Four focused regressions pass on both interpreters.
