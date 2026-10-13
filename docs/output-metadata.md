# Output metadata

Published artifacts now carry a versioned `<filename>.metadata.json` companion.
`publication-metadata.json` commits the ordered membership and companion hashes
for an execution. Companions do not consume workflow artifact indices. Native
receipts retain their existing shapes and independent scientific verification.

The `schemaxis.artifact-metadata/1` contract contains the artifact basename,
kind and SHA-256; byte size; observed dimensions/counts when available; and a
spatial record. Spatial state is `known`, `unknown` or `notApplicable`. Unknown
units and placement remain explicit rather than inventing physical coordinates.
PNG pixel dimensions are read from the image header. Parallel dataset members
have their own companions; the entry point also records member hashes, sizes
and total bundle bytes. Existing native verification checks completeness of the
underlying multi-file dataset.

Delimited tables report physical records (including any header) and observed
column counts. Header presence remains unknown unless supplied by the adaptor;
logical data rows are reported only when observed. Bounds and transforms carry
their ordering and coordinate conventions so consumers can interpret them across
applications.

ParaView image companions include camera observations and four ordered world
coordinates: top-left, top-right, bottom-right and bottom-left image edges.
For a single, native planar, non-crinkle Slice, these are the image-edge ray
intersections with the observed slice plane. Rows increase downward. Orthographic
and perspective projections are supported when the plane intersects every ray
in front of the perspective camera. These coordinates describe the viewport
mapping; overlays, background and pixels without slice geometry are not surface
samples. Multiple visible objects and other renders describe the camera focal
plane only: they do not claim to recover surface depth. Camera vectors and units
are retained separately. Unsupported or degenerate projections remain unknown.

Ordinary registered runs, direct bound adaptor runs, analytic visits, workflows
and scheduled workflow batches share finalisation. FreeCAD live saves/images,
console snapshots, retained ParaView MVP exports and node-inspection observations
also produce companions. Other native outputs supply existing observed size and
unit fields; richer application-specific spatial observations can be added using
an explicit `spatial` artifact field.

Finalisation stages all companions before replacing them, then commits the
membership manifest last. Missing commit evidence means publication is incomplete;
this is not a filesystem-level atomic transaction across multiple files.
Verification checks membership, every companion hash, output hashes/sizes and
reconstructed metadata. It never regenerates missing or modified metadata.
A run cannot report verified success at the shared boundary before finalisation.
Older receipts without companions require explicit migration or rerunning; there
is no implicit verification bypass.

Metadata is deliberately exempt from producing further companions. Internal
runtime packages, locks, progress logs and temporary staging files are execution
infrastructure rather than published artifacts. Adding or updating authored input
schemas does not require duplicating this metadata format.

Agent resource records include the companion and membership-manifest paths and
digests. `inspect_resource_metadata(resource_id, ...)` returns bounded structured
metadata after checking the artifact, receipt, companion and manifest. Modifying
any of these blocks resource reuse. Workflow studies collect their aggregate
publications without changing artifact indices.
