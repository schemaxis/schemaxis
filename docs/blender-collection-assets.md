# Blender selected native scene assets

A packed `.blend` asset now preserves native collection ownership and collection
instances. Select its `scene` and `viewLayer` under `production.assets`. Empty
selectors infer a value only when there is exactly one choice; ambiguous sources
require names. Ordinary single-scene/single-layer projects keep automatic reuse.
A scene-less plain object library retains the object route; a scene-less library
with collection dependencies requires a scene carrier before reuse.

```json
{
  "id": "assembly",
  "file": "assembly.blend",
  "format": "blend",
  "sourceUnits": "millimetres",
  "scene": "Assembly",
  "viewLayer": "Main",
  "location": [20, 30, 0]
}
```

The selected layer becomes an owned collection carrier, instanced by the named
asset root. Objects retain native parents, shared object data, multiple collection
memberships, nested collection instances, instance offsets, material slot links
and animation dependencies. Hierarchy is editable after saving. A collection is
copied only when a selected layer excludes one of its descendants; unaffected
collection IDs and their resource references stay shared. Projection aliases and
excluded paths are recorded. Direct branch exclusion does not erase that
collection when an included instance independently references it.

Only the dependency closure enters the packed output. Source scenes and unrelated
imported IDs are removed after an admitted finite dependency proof. A local
constraint/parent/node resource can remain a captured non-visible object dependency
without being inserted as visible geometry. Needed zero-user dependencies receive
native save retention because object parent/constraint references can be weak
users and native append clears source retention flags. Linked libraries, recursive collection
instances, unsupported object/modifier/node classes and external or stateful cache
dependencies remain explicit refusals. Ownership is bounded to 1,024 collections,
4,096 visible source objects and 64 nested collection levels, plus the existing
two-million-record/64MiB fidelity budget.

Consumer production owns the renderer, world, active camera, render passes, frame
rate and output timeline. Source action frame indices are retained; source FPS
and range are recorded without implicit retiming. View-layer material overrides,
holdout, indirect-only and local viewport hiding require a separate compositing
or visibility conversion and are refused. Data-level object/collection visibility
flags remain native settings. Geometry publications use evaluated depsgraph
instances; rendering additionally applies native render visibility. This is an
asset handoff, not a source scene/render-layer transplant or a general asset-browser
or linked-library override system.

Source member observations describe source object state. Aggregate asset root
observations and exports measure actual placed occurrences, including nested
instances and outer carrier transforms. No flattening is used in the editable
project; exchange formats intentionally bake the selected evaluated frame.
Fresh verification checks collection membership, sharing identities, link policies,
instance references/offsets, source selection, material slots and complete admitted
Action/NLA dependencies, alongside existing topology/UV/rig/shader fidelity.

`tools/qualify_blender_collections.py` generates a small native fixture and checks
selected/excluded layers, multiply linked shared objects, nested collection
instances, offsets, animation, placement, physical volume, rendering and another
packed-project reuse. Its independent native oracle inspects the saved IDs and
actual depsgraph occurrences. `tools/qualify_blender_collection_tamper.py` changes
current native bytes and refreshes receipt hashes before exercising verification.
