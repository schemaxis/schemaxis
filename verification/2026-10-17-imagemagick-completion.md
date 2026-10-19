# ImageMagick completion review — 17 October 2026

Initial `schemaxis.imagemagick/1` delivers exact PNG detail preparation and an
optional indexed comparison sheet. This is the distinct D05 programme assignment,
owned by GPT-6.1 Sol. It contains no CFD integration. Root reviewed the bounded
design and critical PNG/policy/oracle code; the final two requested corrections
are implemented and verified below.

## Native scope and independent evidence

The official latest release API identified **7.1.2-34**, published 14 October 2026,
on 17 October. The official GCC x86_64 AppImage was downloaded and extracted into
ignored evidence without installation or PATH changes. Its SHA-256 matched the
GitHub asset digest:
`6e9edfd35d5f30b57c27533afe003d6085faaf8607b207426f398d11751acf93`.
Observed runtime: ImageMagick 7.1.2-34 Q16-HDRI x86_64,
`c5d4ca8a0:20261014`, GCC 11.4. Exact asset URL, published digest and observation
are in `evidence/programme-20261017/imagemagick-runtime/provenance.json`.
Official [release](https://github.com/ImageMagick/ImageMagick/releases/tag/7.1.2-34)
and [latest-release endpoint](https://api.github.com/repos/ImageMagick/ImageMagick/releases/latest).

`tools/qualify_imagemagick.py` completed with `verified: true` in
`evidence/programme-20261017/imagemagick-native2/acceptance.json`; the corresponding
source-bound kit receipt there predates final shared generation. After root review
and regeneration, common native conformance reran unchanged science into
`imagemagick-native3/qualification.json` and was explicitly registered. Published
qualification context reports **source-current**, digest
`sha256:804c2f88ac6b273a39757fe816d8501e5957540bfb2e655cf9e795da107e5691`.
The initial empty receipt bundle used an incorrect protocol key; registration
refused it, the owning metadata was corrected, and the unchanged successful
native3 receipt then registered. This repair did not loosen qualification.
Four cases exercise baseline crop/magnification, changed crop/clockwise rotation,
encoded-sample alpha flatten, and an indexed sheet containing both RGB8 and RGBA8
sources. Expected rows are authored literal RGBA values from the synthetic 3x2
grid. All output pixels and channels are independently decoded and compared,
including RGB beneath alpha zero and exact rounding at alpha 64/128. Sheet
geometry is 11x6 with tiles at (1,1) and (6,1); 88 aggregate publication pixels.
The four acceptance cases do not prove arbitrary-image colour appearance.

The supervisor additionally generated a 257×131 RGBA source exercising every PNG
row filter and all 256 alpha levels, then ran a 183×91 crop, 2× magnification and
clockwise quarter turn in preserve and flatten modes. A separate literal coordinate
mapping and integer alpha calculation checked all **532,896 output channel values**
exactly across the two 182×366 native outputs. This larger sample check passed;
it establishes encoded-sample arithmetic, not colour appearance. Its retained
review is `evidence/programme-20261017/imagemagick-root-pixels/review.json`.

The final launcher also passed 14 hostile probes with refreshed ordinary hashes:
changed pixels/sheet/capture, generated recipe, policy and policy readback,
publication/evidence membership, runtime and submission; **equivalent opaque RGB
output**, **tagged RGBA output**, and **changed hidden zero-alpha RGB** are refused.
Native probes refused SVG, JPEG output, unlisted paths, indirect reads and HTTPS.
The pseudo-image coder returned unavailable under the minimal child environment;
that result is explicitly distinguished from a policy-denial observation.

The real scheduled workflow captured an image artifact from one ImageMagick job
into another, independently verified the result, reused both unchanged jobs and
reran both after a same-path source-byte change. A two-state finite study passed.
In-flight timeout and cancellation tests used a documented slow executable double
and confirmed the owned PID died; those tests qualify lifecycle, not image results.
Native kit checks separately cover ordinary timeout and pre-launch cancellation.

## Completion checklist

| Item | Result and retained evidence |
| --- | --- |
| registration | Active manifest has one document route, scheduled workflow/image handoffs, composition and byte-bound reusable inputs; one serial child at a time. No shared app-name dispatch branches. |
| schema | Complete typed declarations/literal schema cover every nested image, crop, RGB channel and sheet control; deterministic immutable plans, defaults, schema/planner agreement and exact invalid-ID fixture pass kit host conformance. Root generated authored/literal references and Help. All four ordinary native3 runs reference one shared schema `7e7a059983eb496e056dac6897e7ee9449fbe9fc9d2fda0019efd48b06c216a3` through normal schema snapshots; no adaptor-specific schema store was added. |
| semantics | Top-left integer crop, finite integer scale/quarter turns, distinct IDs, regular file/byte limits, supported PNG chunk/mode/colour declarations, combined input/output/sheet pixel budgets and unused-alpha-background rejection occur before native preparation. |
| native-mapping | Fixed trusted `magick` argument arrays map crop/+repage, sample, rotate, alpha remove and Copy composite; public CLI/PNG/security references are in readiness and the guide. Captured sources and canvas are read-only in the child policy. |
| execution | Fresh directory, total deadline, shared owned-process cancellation, CPU/address-space/file limits, PNG cache/thread limits, minimal child environment, no delegates/filters/other coders and exact permitted paths. Runtime and exact active policy are checked immediately after their prerequisite stages **before** any image preparation. Host regression verifies early refusal. |
| discovery | Curated contact-sheet/nearest-neighbour/crop and unsupported-vector cases cover multiword, synonym, ambiguous and negative queries across capability, adaptor selection, Add and Help. Capability matching and actual Node production search regression pass. |
| guidance | All 24 operation/schema records reviewed; no pending/stale records or missing sources. Nested fields explain pixels, defaults, ordering, file ownership, colour assumptions, hidden RGB and the non-linear-light blend limitation. `tools/studio_guidance.py --app imagemagick --check` passes. |
| help | Local guide and generated operation/schema reference, contextual Help, public API sources and stable recovery faults supplied. Admission passes after root generation. No external fetch occurs in discovery/admission. |
| examples | Editable baseline, changed crop/rotation, flatten, sheet, invalid ID and matching Studio starters. Literal fixture generator creates tagged RGB/RGBA8 grids; no AI image generation or external image assumptions. |
| tests | Seven owned unit tests pass: host conformance/search/guidance, immutable/default/closed recipe, all five PNG filters and RGB alpha, malformed/unsupported/decompression budget, literal transforms/layout/flatten, regular sources/byte identity, and runtime/policy prerequisite refusal. Native acceptance and tamper probes are distinct from these host tests. Existing behaviour is absent for this new provider; root owns wider framework regressions. |
| qualification | Implementation, documentation admission, local availability and source-bound native qualification remain separate. Fresh native2 results cover the exact observed release/four cases; final native3 receipt is registered after root generation/review and qualification context confirms source-current; structural admission remains an independent host-only report. |
| maintenance | Latest official version/provenance and bounded acceptance recipe retained. `upstream.json` explicitly uses manual checking because shared stable-version parsing rejects ImageMagick's hyphenated fourth numeric component. It preserves the exact official version rather than inventing a dotted tag. |

## Limits and justified optional exclusions

PNG input is limited to non-interlaced RGB/RGBA8 with sRGB provenance or an explicit
untagged `assume-srgb` decision; no palette/greyscale/16-bit, APNG, ICC, tRNS,
compressed metadata, SVG/PDF/URL/script inputs or arbitrary native options.
Publications are **untagged RGBA8 with only IHDR/IDAT/IEND**, enforced even after
receipt hashes are refreshed. Metadata and physical resolution are lost. Crop
loses outside samples, magnification replicates and quarter turns permute samples.
Flatten blends encoded sRGB channels, not linear light, and loses alpha. Preserve
retains hidden RGB. Sheet tiles copy complete RGBA samples; JSON IDs/index and
positions identify them, with no visual typography or font claims.

There are at most eight inputs, 8MiB each, 4096 pixels per side, 1,048,576 combined
source pixels and separately 1,048,576 total image publication pixels including
the sheet. No generic colour/format conversion, native inspection, MPI, temporal
batch API, persistent live editing or native project save is advertised; those
feature exclusions have scoped decisions in readiness. Generic source/property
editing, finite composition, workflows and byte-bound reuse remain supported.
Only the observed Linux x86_64 runtime is native-qualified; Windows/macOS and
other ImageMagick quantum/build versions have not been run.

Reproduce owned checks from the public repository with `PYTHONPATH=src`:

```sh
python3 -m unittest discover -s tests/unit -p test_imagemagick.py -v
python3 tools/studio_guidance.py --app imagemagick --check
python3 -m schemaxis readiness --app imagemagick --admission --check
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
python3 tools/qualify_imagemagick.py --imagemagick /absolute/magick \
  --output-directory evidence/fresh-imagemagick
```

Compact host/admission/search transcripts are retained under
`evidence/programme-20261017/imagemagick-*.log`. No commits, publishing, licence
changes or pre-existing data cleanup were performed.
