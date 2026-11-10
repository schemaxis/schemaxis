# Output metadata

See [Descriptive output filenames](output-filenames.md) for ParaView publication
names, run-wide indices and the viewer's filename-property filters.

Published artifacts now carry a versioned `<filename>.metadata.json` companion.
`publication-metadata.json` commits the ordered membership and companion hashes
for an execution. Companions do not consume workflow artifact indices. Native
receipts retain their existing shapes and independent scientific verification.
The name `publication-metadata.json` is reserved for this shared manifest in every
run and nested run directory; unrelated files with that name are refused.

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
intersections with the observed slice plane. A native Slice with multiple planes
or a nonzero `SliceOffsetValues` is conservatively treated as a camera image;
its base plane is not assumed to contain the rendered cut. Rows increase downward. Orthographic
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

## Fields for independent viewers

The filename suffix is a discovery hint. Consumers must check that `version`
equals `schemaxis.artifact-metadata/1`, `artifact.file` matches the sibling's
basename and `artifact.sha256` matches its contents before trusting the placement.
Another application's `.metadata.json` file is not Schemaxis metadata merely
because its suffix matches. A standalone consumer can use a companion without
the run manifest; it must describe this as a checked companion, rather than claim
that the whole execution passed Schemaxis verification.

Producers can supply these optional artifact descriptor fields to
`publish_artifacts(directory, artifacts)`. They are retained in the version 1
companion and included in normal metadata verification:

```json
{
  "group": "Pressure slices",
  "sequence": {"id": "pressure-x", "axis": "x", "value": 2.5, "units": "m"},
  "overview": {"file": "../domain.png"}
}
```

`group` is a nonempty display group name. `sequence.id` identifies one ordered
series within the group; `axis` is `x`, `y`, `z` or `time`, and `value` is the
finite observed coordinate or timestamp. Units are optional and never inferred.
Series with different cameras, scalar fields, appearances or other varying
parameters should have distinct IDs. One `sequence` describes one series; it does
not encode a general multidimensional grid. `viewTime`, identity indices and
spatial planes remain available for richer grouping by consumers.

`overview.file` is a relative POSIX path from the artifact's directory. It is a
presentation reference, not proof of the overview's contents or spatial frame.
The overview should have its own companion when published. Consumers must resolve
the path inside their selected data roots and refuse references that escape them;
URLs, absolute paths and Windows paths are not producer hints. Parent references
allow a shared overview above per-series directories. Finalisation does not
require the optional overview to exist or manufacture its metadata.

The publisher copies these hints only when a producer explicitly supplies them.
It does not interpret filename pieces, axis names, timestamps or an image's
camera direction as scientific sequence declarations. Older companions remain
valid without the hints. A viewer may offer filename-based grouping separately
and identify that grouping as inferred.

For image placement, honour `spatial.state`, `mapping`, `frame`, `units`,
`cornerOrder`, `pixelOrigin` and `rowDirection`. The four `corners` are outer pixel
edges in the stated frame, not pixel-centre samples. Use the recorded `plane`
and corners to texture the image in 3D only when `mapping` is
`pixel-edge-rays-to-slice-plane`. A `camera-focal-plane` image can be displayed as
a camera card but does not establish a CFD slice. Read `boundsOrder` whenever
using bounds: producers can use different orderings. Do not combine `unknown`
units or unrelated frames by assuming a shared physical scale. Background and
legend pixels must not be presented as measured values on the slice.
