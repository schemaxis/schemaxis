# EPUBCheck offline and encoding repair (2026-10-25, allocation 52 maintenance)

> Superseded in part by `2026-10-25-epubcheck-52-review38-repair.md`: the XML gate is no longer extension-only, the identity is pinned to 5.4.0 and the file-size cap is the budget plus one byte, so the launcher text and the counts below describe an earlier build.

Scope: the `epubcheck` adaptor only. This repair closes two gaps found by inspecting the official EPUBCheck 5.4.0 source after the first acceptance
(`verification/2026-10-25-epubcheck-52.md`, superseded where it disagrees). It claims no rendering, device, accessibility or legal certification, no human
review and no source authentication. No qualification receipt is registered and `upstream.json` keeps `absorbedVersion` null.

## Findings

* `DefaultResolver.java` at tag v5.4.0 (SHA-256 `ee940cd22f1b5b38d95f098668068f07c96bebfe49e3a45a09b3e844cf29a104`, lines 75-107): EPUB 3 resolves no external
  entity; for EPUB 2 a `SYSTEM` identifier outside its catalogue returns `null`, so the XML parser fetches it, unless the system property
  `epubcheck.offline` is `true` and the identifier starts with `http`, in which case an empty entity is returned. `XMLParser.java`
  (SHA-256 `a91212d1d241fd42660cfc0785c52ac59c3ead517d1fcbc43bd1917259cfcb9a`) switches external general and parameter entities off only inside a block that ignores
  failure. The first host preflight allowed W3C, DAISY and IDPF `http` prefixes broadly, so an unknown EPUB 2 DTD under such a prefix could reach the online fallback.
* The first XML scan decoded UTF-16 heuristically and did not cover UTF-32 or unknown declared encodings.

## Change

* Every native stage (identity probe, check, fresh check in `verify`) starts through the trusted launcher with a minimal environment: `LANG`, `LC_ALL` and
  `JAVA_TOOL_OPTIONS=-Depubcheck.offline=true`. The caller's `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS` and `_JAVA_OPTIONS` are not inherited; nothing is authorable. The
  JVM notice `Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true` is the only stderr the host accepts from a quiet check stage and is required from the identity probe
  (otherwise `UNSUPPORTED_RUNTIME`). The shared runtime wrapper, global environment and installation are unchanged. Retained directories and receipts from before this
  change do not verify and must be rerun.
* The host accepts a `DOCTYPE` `SYSTEM` identifier only if it equals an entry of the exact EPUBCheck catalogue (15 identifiers, including `about:legacy-compat`);
  everything else is `UNSUPPORTED_EPUB_FEATURE`. XML members must be strictly decodable UTF-8 (optional mark) or UTF-16 with a byte-order mark; UTF-32/UCS-4, UTF-16 without a
  mark, NUL characters, malformed bytes and any other declared encoding are refused.
* The old claim "native.network none" is replaced by the scoped statement in `docs/epubcheck.md` (not an operating-system network boundary).

## Evidence (all new; the first acceptance in `52-epubcheck/native-acceptance` is unchanged)

* Source audit and direct native controls with the official CLI against a loopback listener: unknown EPUB 2 DTD without the property: 1 request (`GET /canary.dtd`, `HTM-004`); with the
  property: 0 requests; same `DOCTYPE` in EPUB 3: 0 requests; catalogue DTD: 0 requests, exit 0. Evidence: `repair-epubcheck-offline/canary-run2` (an earlier `canary-run1` failed because of a
  relative output path and is kept, not a valid control). A `file:` DTD probe under the fixed property (`filedtd-run1`): an existing malformed file gave `RSC-016` and a missing one `PKG-008`, so the
  checker did read it: the property does not make `file:` identifiers safe, which is why the host refuses every non-catalogue `SYSTEM` identifier.
* Host: `tests.unit.test_epubcheck` 46 tests OK (39 earlier + 7 new), `host-final.log`. Native boundary: 8 tests OK (5 earlier + 3 new), the positive control observed the fetch and was not skipped,
  `native-boundary-final.log`. Both in `quota2-a-repair-epubcheck-offline-continuation/runs`; earlier runs in `repair-epubcheck-offline/runs`.
* Native acceptance, `tools/qualify_epubcheck.py` into the new folder `repair-epubcheck-offline/qualifier-run1` (qualifier PID 2150385, `verified: true`, EPUBCheck v5.4.0): 118 native launches
  (59 identity, 59 check; the wrapper execs Java, so the logged PID is the Java process), all with the fixed property and none that inherited the poisoned parent JDK or underscore options;
  valid and rich books accepted with zero findings; four defective books rejected with the expected identifiers (`OPF-049`, `RSC-005` x2, `RSC-011`; `RSC-007`, `RSC-016`; `OPF-053`; `OPF-014`, `RSC-006`);
  two Pandoc-generated EPUBs accepted; five forged assessments or captures refused with `VERIFICATION_FAILED`; twelve host refusals started no native process; remote-resource canary 0 connections;
  DTD controls as above; timeout (`RUNNER_TIMED_OUT`, PID 2155254) and cancellation (`RUNNER_CANCELLED`, PID 2155275) left no surviving process; Pandoc -> EPUBCheck workflow succeeded (9 members) and
  was reused on resume; CLI `schemaxis verify` without a launcher `INTERPRETER_NOT_FOUND`, with it verified.
* The qualifier ran detached (started 06:44:58 local, after the last source and qualifier edit; `adaptor.py` and `tools/qualify_epubcheck.py` were not changed afterwards) and completed on its own
  at 06:50:31, writing `acceptance.json`. The first worker had been ended by its time bound (exit 143, 06:48:40) while it was still running and before its FINAL, so this note and the checks below were
  completed by the resumed worker, which reran the host and native-boundary suites on the unchanged source; the qualifier was not rerun.

## Limits

* The property covers the `DefaultResolver` HTTP fallback of EPUBCheck 5.4.0 on this Java. It is not an operating-system network boundary, a launcher could ignore it, and other network paths in Java or
  the checker are not covered. The loopback controls probe the checker; the host refuses such a publication, so they do not show that the platform admits a loopback DTD.
* Hardware: the machine has 20 CPUs and the qualifier ran with affinity 0-19; the adaptor's two-CPU cap is observed separately (`Cpus_allowed_list` 0-1 in every native process). Observed limits in
  the native processes: CPU time 380 s, file size 65536 bytes (identity) and 8388608 bytes (check), open files 1024.
* One platform (Linux x86-64), one Java (OpenJDK 25), one EPUBCheck release (5.4.0), serial. No Windows/macOS launcher, other release, non-default profile, expanded EPUB or MPI.
* Not run: the full host suite, `release_gate.py`, generator checks and registration, which belong to the master integration. Zero human review, source authentication, device or accessibility certification.
