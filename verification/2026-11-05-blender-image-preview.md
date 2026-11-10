# Blender captured-image previews

Owner qualification targets Blender 5.2.3 LTS, build `e13b728c6880`, provider
execution commit `a115d280b392d39059d838abc1b3c465815f0cbe`. Source fingerprint is
`sha256:f1f53fd15b538bab63cd7c629d09f80b8ad6341042a2e5eaabcededb0ec9f960`;
runtime archive SHA256 is
`d78ecc32b1fabd8902ee08cb1174ed96fcc35511c7133878c5170c2b818590c4`.
Binary SHA256 is
`b8b07a190fb25db76aae6de08dbc6c2b3d64e22e82bed6ba90de9545859f3431`.
Independent integration acceptance remains pending. Whole Blender and broader
painting/rendering families remain incomplete; subjective scores are unchanged.

The current core proof passed fifteen independent pixel cases. Distinct images
and different active/render UV maps produce known quadrant permutations. Explicit
no-image and missing-UV choices use the material swatch. Non-Color images follow
independently calculated linear-to-sRGB conversion. All four alpha interpretations
have zero/one-alpha controls, and fractional linear samples distinguish straight
RGB from premultiplied RGB/alpha. JPEG pixels agree with a separate Pillow decoder,
a qualification-only dependency. A Cycles shader remains independent of its
Workbench preview; a materially different two-panel composition retains distinct
images, UV choices and scientific fields. Interior RGBA samples agree within one
encoded byte, without widening the tolerance for fractional alpha or JPEG.

The lifecycle proof passed twelve refreshed-hash native mutations and an identical
unchanged-save positive: preview image/flags/active node, helper projection/link,
alpha and colour-space interpretation, packed payload, both UV selectors and
retention of an unused declared image. It also passed:

- Original image removal, packed native reopen without that original, receipt
  refusal while absent, restoration and changed-original refusal.
- A deliberate native preview edit saved separately, adopted through the actual
  captured-input API, consumed by a workflow with independently expected changed
  pixels, then reused only after fresh verification on resume.
- A changed captured-asset preview flag with refreshed native hash and replaced
  submitted fidelity. The provider verifier refuses it against fresh captured-source
  reconstruction. This isolates native authority from the separate outer
  publication-metadata guard; stale outer metadata acceptance is not claimed.
- Public missing-image refusal and recovery in a new output directory,
  pre-dispatch cancellation, a short native deadline with incomplete results, and
  a filled Studio starter producing the known source-image colours.

Affected regressions passed at the identical source fingerprint/archive: assets
eight, node groups five, motion five, collections ten with eight refusals, and
geometry-resource assets eight. The eight asset constructors from `a115d28` were
reused only after source/archive/qualifier checks; all eight received fresh current
native verification. A legacy node-group fixture contained an invalid IDAT CRC,
confirmed independently and by native libpng. Tool-only commit
`8405ca7146a29fd5f8aa14d5e4f76d6572d814ca` corrects that checksum; provider bytes
and archive remain unchanged. The repaired fixture passes all twenty-nine
interface-type mappings. A collections report-filename harness error and an
omitted trusted runtime configuration were retained separately from successful
native phases; only the remaining tail was rerun.

Host preflight passed 153 native-enabled Blender tests with zero skips, including
public capture/refusal and schema/consumer controls. All three routes admit pinned
single files only at declared image/asset, supported mesh/CSV reader and saved-scene
positions. Wrong fields/readers/kinds, malformed containers, noncanonical/Unicode/
oversized indices and changed pinned bytes refuse. A required Studio image path
remains an honest unfilled marker with no invented default. Twenty new conceptual
records are reviewed; two image-file records are deliberately updated for bounds
and file picking. Other records and operation guidance are preserved. Guidance has
6259 reviewed and 246 reference records, none pending or stale. Search and private
Help generation/check pass, with 1528 topics from 691 files. The actual Studio
browser passes preview selection, image interpretation, real host folder selection
and renderer texture choice.

Evidence retains earlier orphan-image loss, incorrect ChannelPacked oracle,
missing captured-input policy, malformed fixture and harness failures as separate
epochs. Current proof, inputs, projects, outputs, source/runtime and qualifier
hashes, receipts, logs and restore mappings were copied and rehashed. Shared
generated Help, exact integrated full suites, installed package acceptance and
independent master acceptance remain integration gates. Source-only peer review of
captured-file policy found no actionable bypass; it does not imply independent
native or whole-adaptor acceptance.

General verification checks bounded PNG decoding, resource bytes and declared
native state. It does not independently rerender arbitrary images. PNG/JPEG have
early dimension admission; other native codecs receive post-load pixel admission,
not a universal predecode memory guarantee. Painting, baking, UDIM,
multiview/sequences, multi-slot/per-face authoring and broader rendering remain
open. See the [guide](../docs/blender-image-preview.md) for authoring and recovery.
