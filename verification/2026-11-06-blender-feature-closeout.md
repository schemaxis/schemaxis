# Blender: finite render bundles, Freestyle and simulation caches

The recorded baseline is Blender 5.2.3 LTS (`e13b728c6880`). These are finite
production-route additions; whole Blender and broader PBR coverage remain
incomplete. No package release or version change is implied.

## Qualified behaviour

- The analysis example writes the named `sx_temperature` field as 300, with
  independently derived oblique-plane positions, world normals and optical-axis
  depth at three pixels in each of two frames. Crypto IDs use independent
  MurmurHash3 values, ordered coverage ranks and explicit complete manifests.
- The artist example separates face roughness .375/.75 from a .25 layer override,
  writes World tags .125/.875 at actual background pixels, and conserves linear
  beauty radiance across the declared disjoint light groups.
- The assembly example reuses two captured three-part native projects. Exclusion,
  holdout and indirect-only rules target original collection paths. Literal ray
  intersections and matte IDs distinguish all six parts in two frames; fresh
  native checks retain exact local vertices/faces and shared Material identity.
  Transparent film is explicit where an empty-background alpha mask is wanted.
- Scientific verification reconstructs trusted intent before opening a submitted
  project. Complete valid EXR mutants with refreshed artifact/publication hashes
  fail raw-plane or semantic-manifest comparison before candidate open. A separate
  native selected-pass decoder admits the baseline and both mutant file formats.
- Native layer and World edits with both complete actual readback witnesses and
  hashes replaced still fail fresh source authority. Saved managed writers retain
  relative paths. Adopted source reuse survives whole producer retirement through
  the public workflow boundary, including verified resume and exact restoration.
- Public Cycles Freestyle checks cover an occluded plate, hidden dash intervals,
  line position/width, a curved two-material boundary, exclusions, saved edits and
  fresh reopen. Two analytic visits also retain identical decoded pixels.
- Explicit rigid-packed, cloth-packed and cloth-disk requests are independently
  rebuilt and checked at every frame, including scrambled fresh-process sampling.
  Physics edits and coforged witnesses fail source guards; disk edits/corruption
  fail whole-folder checks before opening submitted native state. Captured image
  retirement/resume, actual active-bake cancellation/deadline and fresh recovery
  are recorded separately from generic pre-launch cancellation.
- Native RGB/RGBA PNG output has independent 8/16-bit header and decoded semantic
  controls. This establishes the supported encoding profile, not arbitrary
  encoded-colour or beauty-image equivalence.

## Repairs and confidence boundaries

A generic field called `temperature` collided with the fixed Cycles builtin and
rendered zero despite a correct native mesh field. Generic AOV taps now refuse
all standard-name collisions; renaming field and source together preserves the
logical pass name. A missing field must be present on every effective owner,
including clamped polygon material slots and converted geometry. Converted
instance schemas use stable original Object identities rather than borrowed
iterator pointers. Independent source review and fixed-runtime controls cover
these source-authority boundaries; earlier failing receipts remain failures.

Scientific data identity is restricted to the declared fixed CPU Cycles profile.
General beauty images retain source/layout verification rather than arbitrary
rerender equality. Cache support is limited to the three named modes and a full
declared timeline. Rigid-disk and arbitrary inherited baked assets remain refused.
Projected sources retain a finite local hierarchy; unsupported dependencies do not
silently flatten. Grease Pencil Line Art, procedural skies, World volumes and
broader simulation/cache families are not delivered by this checkpoint.

## Reproduction

Run the following through the workspace's bounded runner with a configured fixed
Blender executable:

- `tools/qualify_blender_render_bundles.py` and its lifecycle companion.
- `tools/qualify_blender_freestyle.py` and its lifecycle companion.
- `tools/qualify_blender_caches.py` across its three published examples.

The source-owned records distinguish the functional runtime, test-only changes,
documentation/metadata changes, and exact installed integrated acceptance. Final
combined host, Studio, package and installed-native gates are separate from the
individual native controls above.
