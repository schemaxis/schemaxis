# EPUBCheck independent-review repair (2026-10-25, allocation 52, review 38)

Scope: the `epubcheck` adaptor only. It answers an independent read-only review (one medium and five low confirmed findings, three unconfirmed). It claims no rendering,
device, accessibility or legal certification, no human review and no source authentication, and registers nothing; `upstream.json` keeps `absorbedVersion` null.
The earlier acceptance (`2026-10-25-epubcheck-52.md`) and the offline repair (`2026-10-25-epubcheck-52-offline-repair.md`) are superseded where they disagree; their
launcher text and receipts no longer verify (the file-size cap and launcher text changed) and must be rerun. Nothing was accepted before this repair.

## Findings and what changed

* **M1 (medium)** The host gated XML by file extension, but EPUBCheck picks its parser from the declared media type and the container rootfile. Now the host (a) indexes
  `META-INF/container.xml` rootfiles and the package manifest items whose media type is XML (resolved safely to members, percent-encoded, dotted, fragment and query forms,
  never followed as URLs), and holds each of them, under any file name, to the strict UTF-8 / byte-order-marked UTF-16 profile plus the entity and catalogue-DOCTYPE gate;
  (b) holds every other member that contains `<!DOCTYPE`/`<!ENTITY` as ASCII/UTF-8, UTF-16LE or UTF-16BE to the same profile and refuses the same text in UTF-32. UTF-32, EBCDIC
  and declared unsupported encodings are refused, not bypassed. A container or package the host cannot parse is refused. The test that accepted an entity in `EPUB/data.bin` is flipped.
  Supported subset: documented in `docs/epubcheck.md`; it is a bounded index, not an EPUB reader.
* **L1** setup text states the one fixed Java setting and that caller `JAVA_TOOL_OPTIONS`/`JDK_JAVA_OPTIONS`/`_JAVA_OPTIONS` are not inherited. **L2** "14 of its 15" (one upstream typo left out).
  **L3** identity pinned to `5.4.0`; 5.4.1, 5.4.10, 5.5.0, 5.3.0, 5.4 and 5.4.0-rc1 are `UNSUPPORTED_RUNTIME`. **L4** the fresh check's own stage must show exactly the offline notice on
  stderr and an empty stdout before its report is parsed when it exits 0 (an exit 1 is refused anyway and still reports findings). **L5** a spine item with a null index is
  `EPUBCHECK_REPORT_INVALID`.
* **U1 confirmed** with the real Java: a 2048-byte cap (never a large file) gave exit 0, a truncated report of exactly cap+1 = 2049 bytes and no signal exit. The kernel file cap is now the
  reader budget plus one byte and a larger report is `NATIVE_RESOURCE_EXHAUSTED` before any JSON or diagnostic is read; a host fake that ignores `SIGXFSZ` shows the same for exits 0, 1 and 2.
* **U2** non-ASCII member names without the ZIP UTF-8 flag are refused early as `UNSUPPORTED_EPUB_FEATURE`. **U3** documented: heap size is the trusted launcher's own option; the host sets no memory limit
  and claims no OS sandbox.

## Native observations (direct controls through the official 5.4.0 CLI, bypassing the host; separate from the host refusals, which made zero native calls)

* `file:` DTD in a manifest-declared `c.txt` and `c.bin` (a marker file the test wrote in its own temporary directory): present and missing files give different message IDs (`HTM-004` against `HTM-004` + `PKG-008`).
* `jar:http://127.0.0.1:PORT/x.jar!/x.dtd`: the checker fetched `GET /x.jar` from the owned loopback listener **even with the fixed offline property** (the property only matches identifiers starting with `http`). `ftp://`: no request observed.
* The same publications through `adaptor.run` with a counting launcher: `UNSUPPORTED_EPUB_FEATURE`, zero native calls, zero loopback requests. No external or public endpoint was used.

## Evidence (new; old receipts retained, not reused)

* Host: `tests.unit.test_epubcheck` 56 tests OK (46 before + 10 new, `runs/host-final.log`); the first run had one stale-assertion failure and the first native run one regression (L4 ordering on a rejected swapped capture), both kept as `*-run1-superseded.log` and fixed.
* Native boundary: 12 tests OK (8 before + 4 new, `runs/native-boundary-final.log`; observations above printed in the log).
* Qualifier `tools/qualify_epubcheck.py` into the new `qualifier-run1` (PID 2191566, `verified: true`, EPUBCheck v5.4.0, started 08:13:06 after the last source edit; source hashes in `qualifier-start-source.sha256`): 118 native launches, all with the fixed
  property, none that inherited the poisoned parent options; file-size caps observed 65537 and 8388609 bytes (budget + 1), CPU 380 s, open files 1024; affinity `0-1` on a 20-CPU host; seven new host refusals (MIME-declared `.txt`/`.bin` file, jar and ftp DTDs, UTF-32,
  UTF-16 entity, binary marker, non-flagged name) started no native process; loopback network canary 0 connections; timeout (PID 2211584) and cancellation (PID 2211663) left no process; Pandoc 3.12.1 -> EPUBCheck workflow succeeded (9 members) and was reused on resume.
  Counts and PIDs describe this run only; the earlier 118-launch run (PID 2150385) is historical and had different caps.
* Scoped: readiness, completion, architecture and `test_pandoc_epub` 77 OK (help currency checks pass). A broader run that added `test_adaptor_kit` and `test_adaptor_runtime` had one error in the ffmpeg adaptor conformance (`extract-audio-invalid`),
  an adaptor with uncommitted changes of its own that this work did not touch (`runs/scoped-related.log`; not investigated here).

## Limits

* The offline property is not an operating-system network or file boundary; the host's refusal, not the property, keeps `file:`, `jar:` and `ftp:` away from the checker, only for members the index or marker rule can see. A member the package does not list and that carries no ASCII/UTF-16 marker is not seen.
* One platform (Linux x86-64), one Java (OpenJDK 25), one release (5.4.0), serial. Not run: the full suite, `release_gate.py`, generators and registration (master-owned). Zero human review, source authentication, device or accessibility certification.
