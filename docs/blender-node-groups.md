# Reusable typed Blender node groups

Shader materials and groups share a budget of 8,192 distinct nodes, including
managed preview helpers. Each group instance also counts its recursively expanded
contents: material roots together may contain at most 8,192 expanded node
occurrences, with at most 32 nested groups. Reusing one definition twice counts
its expansion twice. Unused definitions must remain within the same per-group
expansion and depth limits. This bounds graph allocation and expansion, rather
than treating a short declaration as evidence of inexpensive shader compilation.
Authored graphs are checked before native launch; captured native shader graphs
receive the same checks during dependency admission, before rendering. Native
file loading and rendering still run within the bounded application process.
The scene shares one native budget across active DAG materials, authored shader
definitions and every captured asset. Repeated snapshots cannot reset it. Only
the same actual native Material or group ID shares its allocation; separately
appended copies count separately. Inactive DAG material declarations are not
allocated and are omitted from the active DAG portion of the budget.

`production.nodeGroups` declares named reusable shader, geometry and compositor
functions. Each definition has a `family`, ordered `inputs` and `outputs`, reviewed
`nodes` and typed `links`. A graph instantiates it with `kind:"group"`, `group`
and socket `values`; socket IDs belong to the declared interface rather than
native property paths. Definitions can reference later definitions. Admission
orders dependencies and refuses recursive groups and cross-domain references.

[The connected example](../examples/schemaxis/blender-node-groups.json) uses one
PBR shader group, a geometry group nested twice to lift a housing, and a reusable
compositor exposure group. The native project retains interfaces, defaults,
bounds, group instances and shared node trees. Editing the outer lift parameter
changes both nested transformations. A saved edit can become a new captured
native-asset input for another production; the original workflow contract stays
bound to its original parameters.

The same interface descriptors drive admission, default assignment, native socket
construction and persisted readback. All domains support number, integer, boolean,
vector and RGBA colour. Shader groups add shader links. Geometry groups add
geometry links, strings, Euler rotations, matrix links and named object,
collection, image and material resources. Compositor groups add image fields,
strings, Euler rotations, matrix links and named object resources. An image field
in the compositor uses a colour socket; a geometry image socket carries a named
packed image resource. These domains remain distinct during semantic validation.

Literal sockets have a typed default. Number and integer sockets also have
`minimum` and `maximum`; these bound instance values as well as the saved native
interface. Integers have a conservative million-unit bound. Number limits must
remain within finite native float storage. Defaults must fit the declared bounds.
Vectors and rotations have three components; RGBA colours have four. Shader,
geometry, compositor image and matrix sockets are link-only: their interface has
no authored literal default and must be connected at each group instance and
inside reusable outputs. Resource sockets accept a declared resource ID or
an empty string for no resource. Resource existence is checked before execution.
Socket `description` supplies editable conceptual help in the native project.

Inside a group, `input` exposes its declared input sockets and `output` receives
its declared output sockets. Standard constructors keep the existing reviewed
catalogue and typed property/value rules. A `group` node gets its exact value
fields from the referenced interface. Static JSON schemas describe the possible
literal shapes; semantic admission resolves dynamic user-defined socket names and
checks their exact types and resources. No authored constructor or property path
can select arbitrary native code.

Geometry expansion is checked recursively through nested group instances before
evaluation. Topology counts remain bounded literals; linking a group parameter
into subdivision, primitive resolution or similar allocation controls is refused.
Each evaluated binding retains the conservative two-million-vertex budget.

Fresh native verification, including ordinary DAG material scenes without a
production envelope, requires a configured Blender executable and reconstructs
the expected shader state before opening the submitted project. It checks
interface membership/order/type/defaults/bounds,
resource pointers, field modes, exact instance bindings, node types/values,
muting and links, plus evaluated geometry and published files. Acceptance covers
all 29 admitted domain/type combinations, literal nested deformation, compositor
pixel changes, a native parameter edit adopted into another production, and
refreshed-hash mutation refusal for both authored and reused projects.

The legacy typed `readGltf` DAG reader retains imported material trees. Mesh
material lists, Object slot ownership, data sharing and face assignments are
checked against fresh construction from the captured original, including derived
DAG outputs and typed production instances. The same boundary covers native
STL/PLY readers and CSV curves; these constructors do not acquire an arbitrary
property interface. Local imported shader classes use the reviewed captured
dependency reader, including owner-qualified embedded trees and packed image
payloads. Unsupported dependencies refuse explicitly. Material evidence is
bounded to two million items and 64 MiB, and imported DAG materials share the
scene shader expansion budget with authored graphs and production assets.

Fresh reconstruction also binds material geometry inputs: stored and evaluated
positions, topology, UV maps and their active/render selections, colour attribute
selections, other nonselection attributes, sharp/smooth flags, split corner
normals, vertex weights, texture space, object colour and world transforms.
Tangents derive from the bound geometry, normals and UVs at the fixed runtime.
Renderer-only modifier flags and subdivision levels are checked even when their
viewport result is unchanged; graph inputs and referenced native ID targets
remain bound to their source. Declared image resources retain their separate
packed/external image policy. This is source fidelity, not a general render
comparison of a saved project.

Relative shape keys and their owned layered Actions retain source coordinates,
channels and interpolation. Temporary evaluated mesh keys are results rather
than dependency authority. Geometry drivers, legacy Actions and texture/ORCO
mesh overrides require a further typed dependency contract and refuse explicitly.
Native editor selection attributes are presentation state unless an admitted
material queries them. Requested reserved Boolean selection fields are bound
from stored and evaluated geometry, including retained asset members and
Object/Collection geometry-resource dependencies. Queries propagate
conservatively through all resource alternatives rather than relying on the
current viewport branch. These fresh checks preserve the retained
asset-fidelity/v2 layout. Arbitrary custom attributes remain bound material
inputs.

An Attribute node's reserved literal name is bound even when its saved query
mode is Object or Instancer: a captured layered Action can switch the mode to
Geometry on a later frame. This conservative rule also follows Object/Collection
resources and does not use the saved frame to discard future material inputs.
Selection edits remain presentation changes when no admitted material names
the reserved attribute.

Interface panels, dynamic menus, bundles/closures, font/sound socket resources,
custom interface field policies and matrix literal construction remain open.
Existing node catalogues remain curated; interface support does not imply every
upstream node constructor is implemented. Packed native asset reuse preserves
used shader/geometry group dependencies. Collection handles now also have
finite native ownership through
[selected scene/layer carriers](blender-collection-assets.md). Asset-browser library management and unrelated unused group-library
import remain open. These limits remain on the whole-application capability map.

The incoming-material acceptance command is
`tools/qualify_blender_imported_materials.py --blender <executable> --output <new-directory>`.
It uses independent packed-texture colour expectations, multi-import and derived
mesh compositions, refreshed native hashes/publication metadata and rewritten
readbacks. Unlit appearance and source retention of textured anisotropy and
absorption use the fixed runtime's finite native classes. Physical anisotropy,
transmission and volume artist workflows remain on the broader material roadmap.
Portable source reuse requires explicit adoption of the original self-contained
glTF input before removing its workstation precursor; retain the adopted snapshot.
