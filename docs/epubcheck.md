# EPUBCheck publication standards check

Use `schemaxis.epubcheck/1` to check **one finished EPUB** with the official
[W3C EPUBCheck](https://www.w3.org/publishing/epubcheck/) tool before it is handed over. One operation:

- `validate` captures a local `.epub`, preflights the ZIP container, runs EPUBCheck with a fixed
  policy of **zero fatal, error and warning messages**, and publishes the native JSON assessment
  (`assessment.json`) and a host summary (`epubcheck-summary.json`) only when the checker accepts the
  publication. A fresh second check of the held bytes must agree.

It is a standards check after a conversion, not a converter, editor or repair tool. Product judgement
(not demonstrated demand): a Pandoc EPUB report already proves that its own package and content are
consistent; a separate, official standards checker is independent evidence for the same hand-over.

## Setup

A run needs one **trusted EPUBCheck 5.4 launcher**: `--epubcheck` (or `schemaxis configure epubcheck`, or
`SCHEMAXIS_EPUBCHECK`). The official distribution is a JAR with a sibling `lib` directory that needs Java, so
the launcher is a fixed executable that you provide and trust, for example a two-line shell script that
`exec`s an absolute Java path with the official `epubcheck.jar` (the JAR's `lib` directory must sit
beside it) and any memory flag you want. Schemaxis never accepts a Java path, JAR, code or checker flags
from authored input. The launcher is started with a minimal environment: `LANG`, `LC_ALL` and exactly one
Java setting, the fixed `JAVA_TOOL_OPTIONS=-Depubcheck.offline=true` (see the offline policy below). The
caller's own `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS` and `_JAVA_OPTIONS` are not inherited, and there is no
`PATH` or user variable, so use absolute paths inside it. Schemaxis limits it to two CPUs, a CPU-time cap, an
output-size cap and the run deadline. It sets no host memory limit: the Java heap bound is whatever your
trusted launcher configures (for example `-Xmx256m`), so that choice, not Schemaxis, bounds memory, and it
is not an operating-system sandbox.

Verification needs the **same trusted launcher**: `schemaxis verify OUTPUT` takes only the directory, so
it finds the launcher from `SCHEMAXIS_EPUBCHECK` or a stored `epubcheck` location in the git-ignored
private configuration (`{"version": 1, "locations": {"epubcheck": "/path/to/launcher"}}` in
`.schemaxis.local.json`, or the file named by `SCHEMAXIS_CONFIG`). The `PATH` is never searched and a
receipt never supplies an executable. A missing, relative-path or other-than-5.4.0 launcher is a fault, never a
skipped check. Discovery and planning need only Python 3.10+.

```json
{
  "version": "schemaxis.epubcheck/1",
  "operation": "validate",
  "source": "/absolute/path/to/publication.epub"
}
```

```sh
schemaxis plan check.json
schemaxis run check.json --output-directory output/check --epubcheck /path/to/launcher
SCHEMAXIS_EPUBCHECK=/path/to/launcher schemaxis verify output/check
```

## What the fields mean

- `version`: always `schemaxis.epubcheck/1`; it names this document contract, not the EPUBCheck release.
- `operation`: always `validate`.
- `source`: one absolute local `.epub` file, or a verified file artifact bound from an earlier workflow step
  (the EPUB published by a Pandoc `report` is artifact index 3 of that run). The bytes are captured before
  the checker runs, and the captured copy, not the original path, is what is checked and verified.

There are no other fields. Java, JAR paths, profiles, modes, plugins, message-severity files, suppressions
and checker flags cannot be authored.

## Supported subset and refusals

The host refuses these before any native process starts (each with its own fault code and the
member or limit involved):

| Condition | Fault |
| --- | --- |
| relative path, URL, directory, non-`.epub` name, symlink or non-regular file | `INVALID_EPUB_SOURCE` |
| not a ZIP, truncated or corrupt ZIP, member that does not expand to its declared size | `INVALID_EPUB_ARCHIVE` |
| absolute, traversing, backslash, control-character, duplicate or case-colliding names; symlink or special members | `UNSAFE_EPUB_ARCHIVE` |
| encrypted ZIP members, compression other than stored/deflated, non-ASCII member names without the ZIP UTF-8 flag, XML members (by extension or by the role the package declares for them) that are not strictly decodable UTF-8 or byte-order-marked UTF-16, XML entity declarations, internal DTD subsets, or a `DOCTYPE` whose `SYSTEM` identifier is not in the EPUBCheck DTD catalogue, in any member that carries such text (see below) | `UNSUPPORTED_EPUB_FEATURE` |
| over 32 MiB, 2000 members, 64 MiB uncompressed, 32 MiB for one member, or a member expanding more than 200 times (above 256 KiB) | `EPUB_BUDGET` |

Expanded (unzipped) EPUB folders and single OPF, XHTML, SVG or navigation files are not supported. The
host does not read EPUB content semantically: whether the publication conforms is decided by EPUBCheck.

### XML text profile and DTD catalogue

EPUBCheck chooses its XML parser from the media type the package declares, not from the file extension, so the
host does not rely on extensions alone. Before any native process starts it holds these members to the profile
below:

1. members whose names end in `.xhtml`, `.html`, `.htm`, `.opf`, `.xml`, `.ncx`, `.svg`, `.smil` or `.xsl`;
2. the XML documents the package itself names, **whatever their file name**: the `rootfile` entries of
   `META-INF/container.xml` (the package document, even under a nonstandard name) and every package `manifest`
   `item` whose declared `media-type` is XML (`application/xhtml+xml`, `text/html`, `application/xml`, `text/xml`,
   `application/x-dtbncx+xml`, `application/x-dtbook+xml`, `application/smil+xml`, `image/svg+xml`,
   `application/oebps-package+xml`, `text/x-oeb1-document` or any `+xml` type). The container and package
   documents are held to the profile before the host parses them, `href` values are resolved only to members
   inside the container (percent-encoded, dotted, fragment and query forms included; URLs are never
   followed), and a container or package the host cannot parse as XML is refused as unsupported rather than
   skipped. A container with no `META-INF/container.xml` has nothing to index and is left to the checker;
3. a backstop that does not depend on the index finding a name: every other member (images, fonts, scripts, style
   sheets, `.txt`, `.bin`, no extension) **whose first bytes look like XML** is held to the same profile. That is a
   UTF-32/UCS-4 byte-order mark or `<` pattern in any byte order (including the mixed 2143 and 3412 orders), the
   EBCDIC signature of the text `<?xm` (`4c 6f a7 94`, the same in every EBCDIC code page), or a `<?xml` prefix with or
   without a UTF-8 byte-order mark (matched in any case, conservatively). The strict decoding below then refuses UCS-4,
   EBCDIC and any declared encoding other than UTF-8, so a member is not handed to the checker as, for example, an
   ASCII `<?xml ... encoding="IBM037"?>` declaration followed by EBCDIC text. Any other member that **contains** the
   text `<!DOCTYPE` or `<!ENTITY` in any case as ASCII/UTF-8, UTF-16LE or UTF-16BE is held to the profile too; the same
   text encoded as UTF-32 is refused as unsupported, never ignored. A binary file that happens to start like XML or
   to contain such a marker is therefore refused too. A valid UTF-8 `<?xml version="1.0"?>` document under a binary
   name is still accepted.

The host also refuses a backslash or a control character (C0 characters including tab, CR and LF, and DEL; XML
character references are decoded first, so `&#9;` counts) in a rootfile `full-path` or in the `href` of a manifest item
declared as XML, and a ZIP member name that contains a NUL byte (CPython keeps the part before the NUL, Java does not),
as `UNSUPPORTED_EPUB_FEATURE` and `UNSAFE_EPUB_ARCHIVE` respectively. Path resolution (the host) and URL resolution
(the checker) could disagree about those names, so the host does not index them; it does not implement a general URL
parser. The unique package names of all rootfile entries are collected first and each package is read, decoded and
parsed once, so a container with thousands of repeated `rootfile` elements costs no more than one with a single entry.

The profile decodes a member strictly as UTF-8 (optional byte-order mark) or UTF-16 with a byte-order mark and
refuses anything else: UTF-32 and UCS-4 (with or without a mark), EBCDIC and other undeclared encodings (they are
not valid UTF-8 text), UTF-16 without a mark, NUL characters, malformed byte sequences and any `encoding`
declaration other than `UTF-8` (or `UTF-16` under a UTF-16 mark). The EPUB standard allows only UTF-8 (and UTF-16 for
some XML documents), but a book that breaks this now fails at the host rather than as a checker verdict. The decoded
text is then refused if it contains `<!ENTITY`, an internal DTD subset or a `DOCTYPE` that is not either plain, or
`PUBLIC`/`SYSTEM` with a `SYSTEM` identifier that is exactly one of the 14 of its 15 `http` identifiers EPUBCheck
5.4.0 resolves from its own jar (the keys of `DefaultResolver.SYSTEM_ID_MAP` for OEB 1.2, OPF 2.0, XHTML 1.0 and
1.1, SVG 1.1, DTBook and NCX, minus its three bare Saxon names; the 15th key is an upstream typo, left out, so only
more is refused) or `about:legacy-compat`. Earlier builds allowed any URL under w3.org, daisy.org, idpf.org and
openebook.org, which could reach the checker's online fetch fallback; those other URLs are now refused.

This is a bounded host index, not an EPUB reader: it reads only the container, the package manifest and the bytes
of members, never content semantics. Its supported subset is the profile above. It is not a claim to know every
encoding the checker's XML parser could detect (the parser hands encodings it does not treat as UTF-8 to Xerces's own
detection): the host refuses the signatures it recognises in item 3, whether or not the index lists the member, and
it has not demonstrated an actual bypass of the index in the checker. Whether the checker resolves a manifest `href`
differently from the host's path resolution was not established either (the OCF and URL sources were not available);
the narrow reference rule above removes the ambiguous characters rather than model the checker. None of this is an
operating-system file or network boundary.

Non-ASCII member names must carry the ZIP UTF-8 flag. Without it the host (CP437) and the checker (UTF-8) would
read different names, so such an archive is refused up front as unsupported instead of failing later as an
unusable native report.

## What is published

On acceptance: `assessment.json` (the native EPUBCheck JSON report, byte for byte) and
`epubcheck-summary.json` (source size and SHA-256, member counts, checker identity and counts, publication
facts such as title, identifier, language and EPUB version, one row per file, and the assessment hash).
The run directory also keeps the captured `captured.epub`, the exact launchers, input bindings, stage
logs and the verification receipt.

On rejection nothing is published. The run fails with `EPUBCHECK_REJECTED`, which carries the first
findings (message ID, severity, path, line and text) and the counts, and the complete native report stays
in the run directory as `rejected-assessment.json` evidence. Such a directory cannot be verified as a
publication.

## Native mapping

The only native invocation is the configured launcher with the fixed argument array
`captured.epub --json assessment.json --failonwarnings --quiet --maxOfEachMessage unlimited --locale en`
(plus `--version` for the identity probe). `--failonwarnings` makes EPUBCheck exit `1` for any warning or
error; exit `0` means no fatal, error or warning message. Exit `1` is a checker verdict only when it comes
with a closed-valid report whose counts agree; exit `1` without such a report (for example a Java loader
failure) is a runtime fault. The check stage's output is capped at the report budget plus one byte by the kernel; the JVM
ignores the file-size signal, so a report that hits the cap is a short write with a normal exit, and a report file
larger than the budget is classified as `NATIVE_RESOURCE_EXHAUSTED` before any JSON or diagnostic is read (the
fixed 8 MiB budget is proved on a deliberately small cap with the real Java, never with a large file). Native sources, retained here by upstream release and API links:
[EPUBCheck 5.4.0](https://github.com/w3c/epubcheck/releases/tag/v5.4.0) and the
[project documentation](https://www.w3.org/publishing/epubcheck/). EPUBCheck reports remote resources as
findings and has no option for fetching them; the qualifier probes this with a loopback listener (see the
verification note).

### Fixed offline policy

Every native stage (the identity probe, the check and the fresh check of verification) starts through a
trusted launcher script that runs the configured EPUBCheck launcher in a minimal environment: `LANG`,
`LC_ALL` and `JAVA_TOOL_OPTIONS=-Depubcheck.offline=true`. The caller's `JAVA_TOOL_OPTIONS`,
`JDK_JAVA_OPTIONS` and `_JAVA_OPTIONS` are not inherited and nothing is authorable.

`epubcheck.offline` is read by the official `DefaultResolver` (source inspected at tag v5.4.0): EPUB 3
documents resolve no external entity; for EPUB 2 a `SYSTEM` identifier in its catalogue is served from the
jar; any other identifier returns `null`, so the XML parser fetches it, "as this has been the default
forever", unless the property is `true` and the identifier starts with `http`, in which case an empty entity
is returned. A direct probe with the official CLI against an EPUB 2 whose document names an unknown DTD on a
loopback listener observed one request without the property and none with it (the checker still reports
`HTM-004`); the same probe produced no request for the same `DOCTYPE` in an EPUB 3 or for a catalogue DTD.
The qualifier and a native boundary test repeat that control; the host refuses such a publication, so this
probes the checker and does not show that the platform admits a loopback DTD. The same direct controls with the
document named `c.txt` or `c.bin` and declared as XML in the manifest show that the checker parses by media type
and reads a `file:` DTD (a present and a missing file in the test's own temporary directory give different
message IDs); and that a `jar:http://` identifier on the loopback listener is fetched **even with the property
set** (one request, asserted from the loopback server's own record; the test skips with a stated reason, rather than
passes, in a run where no request is seen), because the property only matches identifiers that start with `http`; a
`ftp:` identifier made no observed request in that run. Those are observations of the checker taken directly; through the adaptor the same
publications are refused by the host with zero native calls.

The JVM acknowledges the variable on stderr with `Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true`.
The identity probe must show exactly that line (otherwise the run is refused as `UNSUPPORTED_RUNTIME`, for
example when a launcher drops the environment or the Java is not HotSpot-style), and verification accepts
exactly that line, and nothing else, as the stderr of a quiet check stage. This is the only native output
the host accepts.

What this is not: it is not an operating-system network boundary (a launcher could ignore the variable, and
the host cannot prove otherwise beyond the notice), it covers the `DefaultResolver` HTTP fallback and not
other network paths in Java or in the checker (`jar:http:` is one, observed), and it does not make `file:`
identifiers safe: under the fixed property the checker still read a local `file:` DTD in a direct probe, which is
why the host refuses every `SYSTEM` identifier outside the catalogue in every member it holds to the XML profile. The shared runtime wrapper, global environment and installation
are not modified; the launcher text changed, so retained directories from before this policy no longer
verify and must be rerun.

## Verification contract

`schemaxis verify` (and the end of every `run`) judges the published assessment from first principles:

1. The retained `captured.epub` is read once and held; the host preflight must still accept it, and the
   capture record must match its bytes.
2. The trusted launcher, discovered now from configuration (never from the receipt), runs on a private copy
   of exactly those bytes. It must exit `0` with zero fatal, error and warning messages.
3. The native JSON is parsed strictly (UTF-8, no duplicate keys, no NaN/Infinity, no bool-as-count) against a
   closed typed schema: messages must agree with the counters, the checker version with the observed
   identity, and the report items with the container files (names, compressed and uncompressed sizes,
   compression method, spine indices).
4. Every field of the fresh assessment must equal the retained published `assessment.json`. Only
   `checker.checkDate` and `checker.elapsedTime` are excluded, because they differ between runs.
5. The summary is recomputed and compared, and the receipt membership, evidence hashes, launchers, input
   bindings, submissions and stage logs (exactly the fixed offline notice on stderr, nothing else) must match.
   The same exact stderr and empty stdout are required of the fresh check's own stage, before its report is parsed, whenever that check exits `0`; an exit `1` is refused anyway and reports its findings. The captured bytes are re-read at the end to
   detect a concurrent change.

Refreshing hashes after tampering does not help: a forged assessment, summary, count or claim still
differs from the fresh native result, and a changed captured EPUB is re-checked as a new publication. The
capture is a writable, unauthenticated copy, not signed history. Faults stay distinct: input invalid
(`INVALID_EPUB_*`, `UNSAFE_EPUB_ARCHIVE`, `UNSUPPORTED_EPUB_FEATURE`, `EPUB_BUDGET`), launcher not configured
(`INTERPRETER_NOT_FOUND`), wrong release (`UNSUPPORTED_RUNTIME`), launcher unusable (`NATIVE_UNAVAILABLE`),
resource exhausted (`NATIVE_RESOURCE_EXHAUSTED`), timeout or cancellation (`RUNNER_TIMED_OUT`,
`RUNNER_CANCELLED`), checker verdict (`EPUBCHECK_REJECTED`), unusable native report
(`EPUBCHECK_REPORT_INVALID`), other native failure (`NATIVE_EXECUTION_FAILED`) and changed evidence
(`VERIFICATION_FAILED`).

## Workflows

A verified file artifact (for example `{"$artifact": "report", "index": 3}` for the EPUB of a Pandoc report
that enabled `epub`) can be the `source`; see `examples/schemaxis/epubcheck-workflow.json`. Unchanged
captured bytes reuse the earlier result; a changed file at the same path does not.

## Limits and not claimed

- Zero findings is a scoped result from the one audited EPUBCheck 5.4.0 release; the catalogue, the offline property and the host rules were established for 5.4.0 only, and a later patch release is refused (`UNSUPPORTED_RUNTIME`) until it is re-audited. It does not certify rendering on any
  reading system or device, accessibility conformance, legal or publisher-specific requirements, or the
  authenticity of the book.
- Only the default profile, English messages and this fixed policy run. The EPUBCheck message list is the
  upstream project's; informational and usage-level messages do not reject but are listed in the summary.
- No MPI, no other EPUBCheck release, no Windows or macOS launcher and no expanded EPUB input has been
  qualified. Java and the JAR are trusted installation content, not authored input.
- Customer demand is unproven; this adaptor is a product judgement that a separate official check
  strengthens a publishing hand-over more than another export option would.
