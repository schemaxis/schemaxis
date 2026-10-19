# SoX sample-frame assembly completion review

Route: `schemaxis.sox/1`, initial `assemble` document. Scope is canonical PCM16
mono/stereo excerpts, integer frame cuts, linear amplitude gain and nonoverlapping
linear edge fades, then ordered concatenation. No arbitrary effects, scripts,
compressed formats, resampling, mixing or crossfades. Host discovery/planning use
Python 3.10+ standard library only; native SoX runs in tracked isolated processes.

## Checklist review

| Item | Result and retained evidence |
| --- | --- |
| registration | Manifest declares the document route, serial runtime family 14.4.2, CLI location, workflow/composition and source-byte resource hooks. Unsupported optional features have explicit scope decisions. |
| schema | Typed nested clip declarations, literal schema and common authored-reference schema agree on five valid examples and schema-valid fade-overlap rejection. Common host conformance checks deterministic immutable plans, defaults and closed root fields. |
| semantics | Absolute local WAV sources, positive integral half-open frame cuts, nonoverlapping fades, common rate/channels, pre-fade clipping refusal, whole-job byte/sample/frame budgets and regular-file bounds are enforced before native audio processing. Exact faults and locations have host coverage. |
| native-mapping | Official SoX 14.4.2 `trim STARTs COUNTs`, linear `vol`, `fade t INs COUNTs OUTs`, `--combine concatenate`, `-D` and serial execution are mapped through trusted argument arrays. Native version is checked before processing clips. Frames remove time-rounding ambiguity. |
| execution | Captures, plans, launchers, stage inputs, submission/stdout/stderr, clips and output WAV are bound and retained. One deadline covers capture through verification; CPU/address-space/file limits and shared cancellation bound native processes. Independent RIFF/wave/struct reopening checks every sample and exact integer concatenation. |
| discovery | Curated audio-assembly, Sound eXchange, join-recordings, ambiguous trim and negative OCR cases cover capability/Add/selection/Help surfaces. Actual CLI search finds `operation/sox/assemble`. Phrases describe bounded assembly rather than broad audio mastering. |
| guidance | All 12 records are reviewed: operation plus every root/nested field. Text explains frame/channel conventions, gain ratio, omission, fade endpoint behaviour, source ownership and common errors; no pending or stale records. |
| help | Local `docs/sox.md` covers scope, native prerequisites, timing, metadata uncertainty, errors, workflow limits and official public references. Root owns regenerated operation reference, packaged contextual Help and Studio search regression. |
| examples | Mono sequence, stereo sequence, changed stereo, literal eight-frame endpoints and 4000-frame stereo extrema case; editable Studio mono/stereo starters. Deterministic fixture provenance is documented beside WAVs. Semantic overlap example remains schema-valid. |
| tests | Nine own host tests pass; common host conformance, guidance audit, readiness admission and real capability search pass. Native common cases and extra acceptance tests are recorded below. |
| qualification | Native qualification applies only to named PCM16 cases and the observed SoX 14.4.2 build. Discovery availability and source-current receipt status remain separate axes. Conservative shared-source digests can become stale after another adaptor's generated Help changes. |
| maintenance | Latest stable official SourceForge release is 14.4.2, released 22 February 2015, rechecked 17 October 2026. Absorption is recorded only after bounded host/native acceptance; `upstream.json` retains repair/acceptance obligations. |

Optional native inspection, MPI, time batches, live editing, native project save
and general conversion are unsupported. The route has no graph/node ports or
interactive application state. WAV file artifacts still must satisfy the PCM16
contract when handed between workflows; a `file` kind alone proves no compatibility.

## Independent sample basis

Five common native cases check 37540 scalar samples: mono sequence 1536 frames at
16000 Hz; stereo sequence 7000 frames and changed sequence 6998 frames at 48000 Hz;
eight literal mono frames at 8000 Hz; and 4000 stereo frames at 11025 Hz with
signed PCM16 extrema, ramps, impulses and touching 2000-frame fades. Per-clip
analytic sample error is at most 0.5001 PCM16 LSB: one nearest-integer output
quantisation contributes at most 0.5, and two internal PCM32 effect truncations
contribute less than 2/65536. Concatenation has zero extra tolerance. Observed
maximum is 0.5000000000004547 LSB, consistent with floating arithmetic at the tie.

The literal endpoint output is
`[0,-6000,12000,-12000,12000,-9000,6000,-3000]`. The stereo extrema case starts
with scalar values `[0,0,-12,0]` and retains `[32767,-32768]` at touching fade
frame 2000. The final fade frame retains `1/N`; a zero endpoint after the clip
is not silently invented. The qualifier uses its own wave/struct reader and
analytic loop; it never uses SoX to manufacture expected audio.

A local native build uses the official SoX 14.4.2 source archive. Its SHA256 is
`81a6956d4330e75b5827316e44ae381e6f1e8928003c6aa45896da9041ea149c`.
Native runtime is reported portably as `SoX v14.4.2` after raw executable identity
has been checked. No system installation or PATH change is needed for qualification.

## Lifecycle and limits

Meaningful rejection probes refresh ordinary artifact/evidence hashes before
reverification: changed final/processed/captured samples, invalid RIFF size,
duplicate data chunk, forged summary, native command, runtime, publication and
missing/extra evidence. Source bounds, fade overlap and gain clipping fail before
native clip processing. Same-path source-byte changes invalidate reuse; verified
WAV artifacts cross a normal two-job handoff.

An individual native run reopens from its captures after original source removal.
The current scheduled workflow verifier additionally rechecks original source
hashes, so workflow verification and reuse still depend on current original
files. This is recorded as a shared framework limitation; the adaptor does not
bypass it. No arbitrary native-run relocation claim follows from shared schema
export portability. Metadata retention/stripping is outside this contract; this
route is not an anonymisation tool.

Final full acceptance passed and registered a native receipt in
`src/schemaxis/adaptors/sox/qualification.json`. Bulk results are retained under
ignored `evidence/programme-20261017/sox-native-final/`: `acceptance.json` records
all five native cases, 37540 independently checked scalar samples, 14 rejection
probes, workflow reuse/invalidation, native WAV handoff, capture reopening,
two-state composition and in-flight timeout/cancellation. Lifecycle wrappers are
deterministic process-control checks and are never counted as native audio cases.

Ten additional native jobs checked sample rates 8000, 11025, 12345, 16000, 22050,
32000, 44100, 48000, 96000 and 192000 Hz, each with a touching faded excerpt and a
single-frame cut ending exactly at the source boundary. These check 170 more
scalar samples and exact frame/rate preservation; they do not claim exhaustive
coverage of every integer rate. All extrema, endpoint, bounds, process termination
and ordinary-hash-refreshed semantic tamper assertions passed.

Commands run successfully:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_sox.py -q
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.sox/1 --output-directory evidence/programme-20261017/sox-host-final
PYTHONPATH=src python3 tools/studio_guidance.py --app sox --check
PYTHONPATH=src python3 -m schemaxis readiness --app sox --admission --check
PYTHONPATH=src python3 -m schemaxis capabilities search 'audio assembly' --scope app/sox
PYTHONPATH=src python3 tools/qualify_sox.py --sox /absolute/path/to/sox --output-directory evidence/programme-20261017/sox-native-final --register
```

Production Studio search regression passed all 116 tests, including the five SoX
search cases and each Add operation's packaged contextual Help. Final readiness
admission passed. After the Help generation epoch changed the conservative digest,
a fresh five-case common native conformance run passed and was registered from
`evidence/programme-20261017/sox-integrated-common/qualification.json`; the separate
settled sample/tamper/rate/lifecycle suite was not needlessly repeated.

Root integration owns the remaining shared generated-output drift: read-only
`reference --check` reports `modules.json`/`modules.md`, and packaged Help `--check`
reports one changed/missing and three extra files. These are shared generation
results, not an altered SoX sample expectation. Root has the exact diagnostics. Further shared-source generation may make
the conservative native receipt stale without changing these established sample
results; refresh the common bounded native conformance/register after that freeze.
No commits, publishing, system installation, licence edits or PATH changes were
performed by this assignment.
