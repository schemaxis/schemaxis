# Blender selected collection asset acceptance

Native scene reuse now owns a selected Scene/ViewLayer collection carrier, with
explicit selectors when either choice is ambiguous. It preserves native parents,
multiple object memberships, shared Mesh/Collection identities, nested instances,
collection offsets, exclusions and local object dependencies. It also checks
object material-slot overrides and collection link policies. Source scenes and
unrelated IDs are pruned after a complete admitted dependency proof. Ordinary
single-choice scenes and scene-less plain object libraries retain automatic use.

Fresh Blender 5.2.3 acceptance checks five cube occurrences and 40mm³ volume in the
selected layer, six and 48mm³ in the inclusive layer, deep layer projection, root
placement/rotation, source instance offsets, coordinate-unit conversion, distinct
instance mesh shapes, repeated packed-file reuse with the same public asset ID,
a non-visible dependency with that same name, and native editing adopted as a new
source. An independent saved-file oracle checks actual native ID sharing, parent
links, material and Action, non-visible constraint target, preserved collection
link policy, pruned excluded objects and five physical depsgraph occurrences at
three frames. Selected source render settings remain consumer-owned.

The asset regression exposed a native instance lifetime error: storing evaluated
instance objects until after depsgraph iteration made distinct objects alias the
last transient object. A skinned box was consequently measured/exported as its
unskinned copy. The resolver now yields each live instance; consumers read or copy
mesh data before the iterator advances. Actual 5.2.3 probes showed the reused RNA
pointer/name changing across instances, and the repair restores frame 6 z bounds
[0,2] for the skinned source and aggregate z[-1,2]. The distinct-height collection
fixture catches this independently. The upstream
[instance lifetime warning](https://developer.blender.org/docs/release_notes/2.80/python_api/scene_and_object_api/)
provides historical API context; qualification here uses actual 5.2.3 behaviour.

Current-byte native attacks refresh the saved artifact hash before verification.
They exercise object/child collection membership, shared data and collection
identities, offsets, unused collection link policy, full Action curves, object
material overrides, mesh coordinates, non-visible target coordinates, source
selection and excluded-path metadata. Both the initial native carrier and another
packed reuse are attacked. Finite unsupported boundaries include ambiguous or
unknown selections, scene-less collection libraries, source layer material
overrides, holdout, indirect-only and local viewport hiding. Linked libraries,
source scene transplantation, general asset-browser management and unsupported
cache/dependency classes remain unfinished application families.

Reproduce with `tools/qualify_blender_collections.py` and
`tools/qualify_blender_collection_tamper.py`, under the resource envelope and an
explicit trusted Blender runtime. Private manifests identify the frozen source
and exact newly run evidence separately from older milestones.

The trusted tamper harness first verifies each complete baseline, then isolates
the provider's full current-byte verifier from companion metadata, whose hashes
still describe that baseline. An unchanged native open/save with a refreshed
receipt hash must pass the exact same native entry used by attacks. Rejections
must identify a fresh native readback guard; a generic verification fault or
framework metadata rejection cannot satisfy the attack. This audit also caught
and corrected an initially ineffective exclusion mutation in the reused scene.
Product verification still includes schema, source, artifact and companion checks.
