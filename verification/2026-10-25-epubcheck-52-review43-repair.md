# EPUBCheck independent-review repair 43 (2026-10-25, allocation 52)

Scope: the `epubcheck` adaptor only. It answers the second independent review (one residual medium finding M1, one finding M2, two low findings). It claims no rendering, device,
accessibility or legal certification, no human review and no source authentication, is not an operating-system network or filesystem sandbox, and registers nothing;
`upstream.json` keeps `absorbedVersion` null. Where it disagrees with `2026-10-25-epubcheck-52-review38-repair.md`, this note wins.

## Findings and what changed

* **M1 residual (encoding backstop).** The host backstop for a member it did not index as XML no longer depends on finding a `<!DOCTYPE`/`<!ENTITY` marker in a known encoding.
  A member whose first octets are an XML encoding signature the host recognises is held to the strict XML profile whatever its name or declared media type: any UCS-4/UTF-32 byte-order
  mark or `<` pattern (including the mixed 2143 and 3412 byte orders), the EBCDIC `<?xm` signature `4c6fa794`, or an ASCII-compatible `<?xml` prefix with or without a UTF-8 byte-order mark
  (any case). The profile refuses UCS-4, EBCDIC and any declared encoding other than UTF-8 (or UTF-16 under a UTF-16 mark). The host does not claim to know every encoding the native
  parser could detect; it refuses what it recognises and states the rest as not covered. No native URI-resolution bypass was demonstrated.
* **M1 residual (index).** References the host cannot resolve unambiguously are refused as `UNSUPPORTED_EPUB_FEATURE` before Java starts: a backslash, a C0 control character (tab, CR, LF),
  DEL, including decoded character references, in a container rootfile `full-path` or an XML manifest `href`. This is a narrow refusal list, not a WHATWG URL parser.
* **M2.** Package names from all container rootfiles are collected and de-duplicated before any package is parsed; each unique package is parsed at most once, so 1000 duplicate
  rootfiles no longer repeat the decompression, regular-expression and tree parse. A host test counts `scan_xml` calls for the duplicate case (constant, not wall-clock).
  Run, verify and reusable-input paths share the one bounded preflight.
* **Low 1.** A raw ZIP member name containing NUL (`info.orig_filename != info.filename`) is refused as `UNSAFE_EPUB_ARCHIVE` before the index, with a raw NUL fixture.
* **Low 2.** The direct `jar:http` loopback control asserts the observed `GET /x.jar` (the real checker did fetch it without the host refusal) instead of relying on the printed log.
  `upstream.json` scopes the runtime exactly to 5.4.0 and the new media-type, jar and encoding controls; fault messages say 5.4.0.
* Unchanged and still closed: L1-L5 and U1-U3 of review 38, the output file-size cap (budget+1), exact stderr, closed report and fresh native policy.

## Evidence

Source frozen before the final qualifier (six files, hashes in `qualifier-start-source.sha256`); the frozen source is byte-identical to the source that passed these runs.

| Check | Result |
|---|---|
| `tests.unit.test_epubcheck` (host, serial) | 60 tests OK (resume52, 142.6 s) on the identical source hashes |
| `tests.unit.test_epubcheck_native_boundary` (real EPUBCheck 5.4.0, owned temporary files and loopback only) | 13 tests OK (228.4 s) on the identical source hashes; `jar-http` observed `GET /x.jar HTTP/1.1` and asserted |
| the four new host tests against the pre-repair source | 4 tests run, 49 sub-case failures (NUL name 1, ambiguous references 11, duplicate rootfiles 1, unlisted-XML encodings 36) |
| `tools/qualify_epubcheck.py` fresh run (serial, official EPUBCheck 5.4.0 and official Pandoc 3.12.1) | exit 0, `verified` true, 118 native launches, all with the one fixed offline property, none inheriting the poisoned `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS` or `_JAVA_OPTIONS`; 26 host refusals, none started native code |
| two retained Pandoc 3.12.1 transcript EPUBs (`cross-deletion-timecode-epub/{partial,all}`) | 9 members each, 0 findings |
| Pandoc 3.12.1 -> EPUBCheck workflow (artifact index 3) | succeeded, 9 members, fully reused on resume |

## Limits

* Not an operating-system network or filesystem sandbox; the fixed offline property and the host refusals are controls, not isolation. Direct native controls read only owned temporary files and loopback.
* The host profile is a bounded index plus a signature backstop, not a general XML or WHATWG URL reader; an encoding or reference form it does not recognise is not covered.
* Real PIDs, argv and exit codes of every native process are in the qualifier report; the reviewed transcript EPUBs prove the checker accepted them, not that a reading system renders them.
* No qualification receipt is registered; the source-bound record stays pending until shared integration.
