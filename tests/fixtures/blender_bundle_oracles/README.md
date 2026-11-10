# Independent bundle qualification expectations

These fixture-owned expectations do not import or consult the render planner,
layout, AOV, layer or bundle compilers. Native projects remain owner-built;
`projects.json` specifies three REQUIRED projects, not three qualified products.
C remains required when captured per-part projection is unavailable.

`oblique-panel-frame1.json` is directly executable against the retained oblique
128×128 frame1 plane: camera (5,0,3), horizontal sensor36/focal28, world normal
(1/2,0,sqrt(3)/2), plane through origin. EXR scanlines go downward. A ±2.5 pixel
footprint admits the explicit retained sampling/filter support; 2e-5 is an
absolute geometry/float32 error bound, not a scientific universal tolerance.
Depth must satisfy both optical-Z identity and independent ray-plane footprint;
position must lie on that plane AND project into the same footprint. Rotated
camera axes and world normal are independent. For frame12's plane through z=.5,
change only the literal offset to sqrt(3)/4, never derive it from decoded pixels.
Native owner must confirm its actual sampling/filter support fits this radius.

B must build an enclosure/window with two material slots, a suffixed authored
owner, a World and alternate layer overrides, then supply interior sample pixels
strictly away from silhouettes. Literal values .375/.25/.875/.75 are authored
AOV taps, not rendered Beauty expectations. Supply channel names explicitly.
Crypto names `panel`/`object` have fixed Murmur3 hashes b6f5bb0a/055ec73d;
`idBits` means the actual encoded uint32 pixel bits (apply the declared Crypto
exponent conversion manually for hashes requiring it). Bind complete manifests,
ordered ID/coverage pairs and independent known interior/boundary coverage.
`hello`/248bfa47 is a same-byte-length *valid* manifest replacement for panel.

Light sum checks require complete disjoint radiance contributions, including
World. Choose raw linear interior samples, fixed same-render integrator paths,
no denoising/display transform/clamp, and explicitly justify any stochastic
absolute tolerance with an independent bound. Sum RGB radiance, not coverage,
alpha or display values. Passing a sum alone does not establish group membership;
use separate native pointer/membership controls and literal zero/nonzero regions.

C must capture a nontrivial perforated housing, curved shaft and flange in nested
collections, instantiate twice, and exercise occurrence-local exclusion/holdout/
indirect-only/override. Declare camera, part transforms and sample regions before
rendering; independently project literal corners/interior test points and test
native reopened membership. Reuse of a single cube does not qualify this case.
Missing projection is REQUIRED OPEN, never an accepted exclusion.

CLI (from installed/source-qualified environment):

    python tools/blender_bundle_oracles.py output.exr expectations.json --report oracle.json

Tools also expose `mutate_none_sample(source,destination,channel,[x,y],value)` and
`mutate_manifest_member(source,destination,layer,old,new,new_hash)`. Mutations keep
byte count and preserve unrelated samples/chunks; owner must add actual native
format-validity controls and refreshed publication/source hashes. Tests use tiny
independent NONE EXR encodings plus retained native ZIP Crypto bytes; this does
not establish native renderer or public route qualification.
