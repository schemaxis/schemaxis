# Info-ZIP publication bundle

Use `schemaxis.infozip/1` to hand over a set of finished publication files — a caption file, a transcript,
an audio recording, a report, an image — as **one portable ZIP** under file names that you choose. One
operation:

- `bundle` packages **one to sixteen individually selected files** into `bundle.zip` (stored, no
  compression) and adds a host-written `manifest.json` inventory.

It publishes `bundle.zip` (kind `file`) and `bundle-summary.json` (kind `text`), and proves the archive by
reading every byte of it back with an independent host reader. Product judgement (not demonstrated demand):
captions, transcripts, audio and report assets are verified one at a time today, and a single verified
package is a convenient handoff.

**This is not case preservation.** The core [storage preservation](storage-management.md) action exports
whole cases (authored input, evidence, logs, schema and history stores) so they can be restored. `bundle`
packages only the files you list, under names you choose, so a workflow can deliver them. It never adds run
directories, receipts or logs, and leaving those out is a scope choice, not privacy sanitisation. Use storage
preservation when you need a restorable case.

## Setup

A run needs one Info-ZIP **Zip 3.0** `zip` executable: `--infozip` (or `schemaxis configure infozip`, or
`SCHEMAXIS_INFOZIP`). The `PATH` is never searched and a receipt never supplies an executable. A missing,
relative-path or non-3.0 executable is a fault, never a skipped check. `zip -v` must report
`This is Zip 3.0 (...), by Info-ZIP.`; other releases need upstream acceptance first. **Verification needs no
native program**: `schemaxis verify OUTPUT` checks the archive and every byte with the host reader (see
[Verification contract](#verification-contract)). Discovery and planning need only Python 3.10+ and perform no
file input or output.

```json
{
  "version": "schemaxis.infozip/1",
  "operation": "bundle",
  "files": [
    {"name": "report.txt", "source": "/absolute/path/to/report.txt"},
    {"name": "captions.srt", "source": "/absolute/path/to/captions.srt"}
  ]
}
```

```sh
schemaxis run examples/schemaxis/infozip-baseline.json --infozip /absolute/path/to/zip --output-directory evidence/bundle
schemaxis verify evidence/bundle
```

## What the fields mean

| Field | Meaning |
| --- | --- |
| `version` | `schemaxis.infozip/1`; the document contract, not the Info-ZIP release. |
| `operation` | `bundle`. |
| `files` | One to sixteen entries, archived in this order (`manifest.json` is always last). |
| `files[].name` | The member name in the ZIP: a flat lowercase ASCII name — a letter, then letters, digits, `_` or `-` (48 characters at most) — and exactly one extension from `txt`, `json`, `srt`, `vtt`, `wav`, `flac`, `m4a`, `png`, `html`, `docx`, `epub`, `pdf`. A Windows reserved device basename followed by the dot (`con`, `prn`, `aux`, `nul`, `com1`–`com9`, `lpt1`–`lpt9`, as in `nul.json`) is refused, in the schema pattern and by the archive reader too; `console.txt` or `com0.txt` stay valid. |
| `files[].source` | An absolute local regular file whose bytes become the member. A verified `file`, `text` or `image` artifact from an earlier workflow step can be bound here. |

The extension of a source is not compared with the member name, and the bytes are never interpreted: a file
named `x.png` is stored whether or not it is a PNG.

## Supported subset and refusals

Each file is at most 32 MiB and the selected files total at most 64 MiB (empty files are allowed). The
archive adds only a fixed overhead for headers and `manifest.json`.

| Input or situation | Result |
| --- | --- |
| Name outside the grammar, reserved `manifest.json`, duplicate name | `INVALID_INFOZIP_NAME` at `$.files[n].name` |
| Relative path, URL, prefix or NUL in a source, or a missing, symlinked, directory, FIFO, device or other non-regular source | `INVALID_INFOZIP_SOURCE` (path form at planning; the filesystem checks happen at run, before any native process starts) |
| Source changed while the bundle was created | `INVALID_INFOZIP_SOURCE`; sources are read again after the native stage |
| A file over 32 MiB or selected files over 64 MiB in total | `INFOZIP_BUDGET` |
| More than sixteen files, no files, unknown keys, wrong types | `INVALID_ARGUMENT`, `UNKNOWN_ARGUMENT` or `INVALID_DOCUMENT` from the shared validator |
| The archive is not the canonical stored ZIP (prefix, suffix, comment, gap, overlap, extra field, ZIP64, data descriptor, compression, encryption, header/CRC/size disagreement, wrong names or order) | `INVALID_INFOZIP_ARCHIVE` at run; `VERIFICATION_FAILED` (with the cause) at verification |
| `zip` is not Zip 3.0 | `UNSUPPORTED_RUNTIME` |
| Executable absent, relative or not executable | `INTERPRETER_NOT_FOUND` |
| Output directory already exists | `OUTPUT_EXISTS` |
| Native failure, timeout, cancellation | `NATIVE_EXECUTION_FAILED`, `RUNNER_TIMED_OUT`, `RUNNER_CANCELLED` |
| Retained JSON with duplicate keys, `NaN`/`Infinity`, excess depth or a changed type (`true` to `1`, `66` to `66.0`) | `VERIFICATION_FAILED` |

A failed run publishes no `bundle.zip`, summary or receipt and records a `failed` result. After a failure that follows
the native stage, an unverified `pack/bundle.zip` can remain in the run's `pack/` directory, and a timeout or
cancellation can leave `zip`'s temporary files there; neither is a published or verified artifact.

Refused by design: directories, globs, recursive input, symbolic links, devices and FIFOs; archive extraction;
encryption; compression flags; ZIP64; self-extracting archives; authored native options.

## What is published

- `bundle.zip`: the members in authored order, then `manifest.json`. Every member is stored (method 0), carries
  the fixed time 1980-01-01 00:00:00 and regular mode 0600, and has no extra field, comment or data descriptor.
  Original workstation paths, timestamps and permissions are not published.
- `bundle-summary.json` (`schemaxis.infozip.summary/1`): archive size and SHA-256, and for each member its
  name, byte count, SHA-256, CRC-32 and archive offsets, plus the `manifest.json` record and the readback record.
- `manifest.json` (`schemaxis.infozip.manifest/1`) inside the archive: members in order with `name`, `bytes` and
  `sha256`, and a statement that it is an **unsigned inventory**. It lists every member except itself and
  carries no self-hash: a recursive self-hash is impossible and a signature is not claimed.

## Native mapping

The native tool is Info-ZIP `zip` 3.0 ([project page](https://infozip.sourceforge.net/Zip.html),
[source downloads](https://sourceforge.net/projects/infozip/files/Zip%203.x%20(latest)/3.0/)). Zip 3.0 is the latest
3.x release (public release date 7 July 2008; the `zip -v` banner of distribution builds reads July 5th 2008). The
generic "latest file" shown by SourceForge for the project is the separate UnZip beta, not a Zip release.

Fixed argument arrays, no shell, no authored flags:

```text
zip -v
zip -X -0 -q bundle.zip <member names in authored order> manifest.json
```

`-X` excludes extra file attributes, `-0` stores without compression and `-q` keeps the stage silent. The host
stages each captured file in a private `pack/` directory with mode 0600 and modification time 315532800
(1980-01-01 UTC), and the native process runs with the working directory `pack/` and the explicit environment
`LANG=C`, `LC_ALL=C`, `TZ=UTC`, which makes the DOS timestamps constant.

Environment and process honesty: the small Python launcher inherits its caller's environment, and `execve`
then gives the native `zip` **only** those three variables, so `ZIPOPT`, `UNZIPOPT`, `HOME` and `TMPDIR` never
reach it. The launcher writes `<stage>-process.json` (its process id, which `execve` keeps for the native
`zip`, and the argument array) just before it replaces itself; the Python supervisor, timeout runner and any
cgroup limits outside the process are not the native process. The launcher also applies per-process limits:
address space 2 GiB, CPU 180 s, output file size (archive bound plus 1 MiB), 64 open files. The shared runner
enforces the wall-clock timeout and cancellation and owns the stdout/stderr logs; the quiet bundle stage must
log nothing, and a log over 1 MiB is refused.

## Verification contract

The decision is native-free. The host reads the complete retained `bundle.zip` with a strict stored-ZIP
physical reader and with the standard `zipfile` module as a second reader, and compares:

- the end-of-central-directory record, which must end the file exactly (no comment, suffix, ZIP64 or second disk);
- the central directory, which must fill the space between the members and that record exactly;
- every local and central header (version, flags 0, method 0, fixed time, no extra field or comment, mode 0600,
  names, sizes and CRC-32 agreeing), with members tiling the file from offset 0 with no prefix, gap or overlap;
- every member byte against the **captured copy** retained in `pack/`, and `manifest.json` against the inventory the
  host regenerates from those captures;
- the receipt is a closed object holding exactly `artifacts`, `evidence`, `executables` and `runtime`; an added
  `signed`, `verified` or `signature` claim is refused;
- the summary, capture record, receipt membership, evidence digests, and the recorded native recipe (exact
  launcher text, argument array, input bindings, process record, exit code, silent logs), none of which is
  re-executed. A receipt never supplies an executable and the recorded path is only provenance.

Verification does not read the original source files, so it still works after they have moved; the captures
bind the bundle. Retained JSON is read strictly and compared by typed canonical form, and result claims are
regenerated from the observation rather than trusted. A coherent rewrite of the archive **and** all unsigned
captures and claims produces a valid new archive: this is integrity against accident and inconsistency, not
signed authenticity.

## Workflows

`files[].source` accepts verified `file`, `text` and `image` artifacts, so publications of earlier steps bind
directly. [infozip-speech-workflow.json](../examples/schemaxis/infozip-speech-workflow.json) narrates text with
eSpeak NG, archives the WAV as FLAC and bundles the FLAC, both JSON summaries and a literal caption file. The text
and captions in the examples are illustrative synthetic drafts: no human has reviewed them.

## Limits and not claimed

- Contents are opaque. No media format, quality, accessibility, security, privacy or recognition accuracy
  is checked, and nothing is sanitised, redacted or listened to.
- Storage is stored-only: no compression, ratio or size-saving claim; the ZIP is slightly larger than its contents.
- The manifest and archive are unsigned; no identity, origin or tamper-proof claim is made.
- No MPI, no time batching, no live session; one serial native process per stage.
- Absorbed upstream version is not advanced until the bounded native acceptance in
  `tools/qualify_infozip.py` has passed on the integrated source.
