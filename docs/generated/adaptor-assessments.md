# Adaptor strength assessments

Generated from the existing registry and each adaptor’s `assessment.json`.
51 registered application providers expose 62 authorable routes; routes are not additional applications.

All scores are **subjective**, rounded to five percentage points. Breadth is relative to the **whole application**; abstraction is relative to the **named supported workflows**. High abstraction within a narrow slice does not imply broad application support.

These are editorial planning estimates, not native qualification, runtime availability or measured API ratios. A `current` record matches only the declared adaptor-source fingerprint scope. Read [the rubric and limitations](../adaptor-assessments.md) before comparing scores.

| Provider | Routes | Whole-application breadth | Supported-workflow abstraction | Estimate confidence (breadth / abstraction) | Date / status |
| --- | --- | --- | --- | --- | --- |
| `apachearrow` | 1 | 10% | 75% | medium / medium | 2026-10-26 / current |
| `aseprite` | 1 | 20% | 65% | medium / medium | 2026-10-25 / current |
| `blender` | 3 | 35% | 70% | low / medium | 2026-11-06 / current |
| `calc` | 1 | 10% | 80% | medium / medium | 2026-10-26 / current |
| `calculix` | 1 | 10% | 90% | medium / medium | 2026-11-03 / current |
| `cantera` | 1 | 10% | 75% | medium / medium | 2026-11-04 / current |
| `elmer` | 1 | 5% | 85% | medium / medium | 2026-11-04 / current |
| `epubcheck` | 1 | 50% | 70% | medium / medium | 2026-10-25 / current |
| `espeakng` | 1 | 10% | 65% | medium / medium | 2026-10-25 / current |
| `exiftool` | 1 | 25% | 70% | low / medium | 2026-10-27 / stale |
| `ffmpeg` | 1 | 15% | 75% | medium / medium | 2026-10-25 / stale |
| `flac` | 1 | 35% | 70% | medium / medium | 2026-10-25 / current |
| `freecad` | 6 | 25% | 75% | low / medium | 2026-11-06 / current |
| `gdal` | 1 | 5% | 65% | medium / medium | 2026-10-26 / current |
| `getdp` | 1 | 10% | 85% | medium / medium | 2026-11-03 / current |
| `gmsh` | 1 | 20% | 80% | medium / medium | 2026-11-10 / current |
| `gnuplot` | 1 | 20% | 70% | medium / medium | 2026-10-26 / current |
| `godot` | 1 | 10% | 55% | medium / medium | 2026-10-26 / current |
| `graphviz` | 1 | 30% | 65% | medium / medium | 2026-10-25 / current |
| `hdf5` | 1 | 75% | 70% | medium / medium | 2026-11-05 / current |
| `ifcopenshell` | 1 | 5% | 40% | low / low | 2026-10-26 / current |
| `imagej` | 1 | 5% | 80% | medium / medium | 2026-10-26 / current |
| `imagemagick` | 1 | 10% | 65% | medium / medium | 2026-10-25 / current |
| `infozip` | 1 | 15% | 60% | medium / medium | 2026-10-25 / current |
| `inkscape` | 1 | 10% | 80% | medium / medium | 2026-10-25 / current |
| `kicad` | 1 | 10% | 60% | medium / medium | 2026-10-25 / current |
| `meshio` | 1 | 10% | 60% | medium / medium | 2026-11-04 / current |
| `mupdf` | 1 | 20% | 65% | medium / medium | 2026-10-25 / current |
| `ngspice` | 1 | 15% | 80% | medium / medium | 2026-11-03 / current |
| `numpy` | 1 | 5% | 85% | medium / medium | 2026-10-25 / stale |
| `octave` | 1 | 10% | 70% | medium / medium | 2026-10-25 / current |
| `openscad` | 1 | 10% | 85% | medium / medium | 2026-10-25 / current |
| `opensees` | 1 | 10% | 90% | medium / medium | 2026-11-04 / current |
| `oracle` | 1 | 30% | 75% | medium / medium | 2026-11-03 / current |
| `pandoc` | 1 | 15% | 80% | medium / medium | 2026-10-25 / current |
| `paraview` | 1 | 50% | 50% | low / medium | 2026-10-28 / stale |
| `premiere` | 1 | 5% | 65% | low / low | 2026-10-25 / current |
| `prusaslicer` | 1 | 30% | 75% | medium / medium | 2026-10-25 / current |
| `pyproj` | 1 | 5% | 80% | medium / medium | 2026-10-25 / current |
| `qgis` | 1 | 20% | 75% | low / medium | 2026-10-25 / current |
| `qpdf` | 1 | 25% | 65% | medium / medium | 2026-10-25 / current |
| `r` | 1 | 5% | 85% | medium / medium | 2026-10-26 / current |
| `shotcut` | 1 | 10% | 60% | medium / medium | 2026-10-25 / current |
| `sox` | 1 | 25% | 75% | medium / medium | 2026-10-25 / current |
| `sqlite` | 1 | 15% | 75% | medium / medium | 2026-10-25 / current |
| `sympy` | 1 | 5% | 85% | medium / medium | 2026-10-25 / stale |
| `tesseract` | 1 | 10% | 60% | low / medium | 2026-10-25 / current |
| `webp` | 1 | 40% | 75% | medium / medium | 2026-10-25 / current |
| `whispercpp` | 5 | 25% | 80% | medium / medium | 2026-10-25 / current |
| `xarray` | 1 | 5% | 75% | low / medium | 2026-10-26 / current |
| `zstandard` | 1 | 55% | 65% | high / medium | 2026-11-05 / current |

## Scopes and interpretation

### apachearrow

Explicit typed nullable CSV table selection, renaming, widening and null replacement into independently checked Parquet and optional typed CSV publications.

**Whole-application denominator:** Typed arrays and tables, CSV/columnar interchange, datasets, compute, streaming and cross-language memory exchange.

**Breadth rationale:** Prepared tables can now publish an explicitly opted-in typed CSV alongside Parquet and the report, connecting selected rows to declared CSV consumers. This deepens bounded interchange; general datasets, streaming, memory exchange and most compute remain absent, so whole-application breadth stays at 10%.

**Abstraction rationale:** Declared schemas, predicates and publication intent hide native parsing, table operations and writer configuration. Users still choose physical types and compatible downstream contracts; the existing 75% estimate is retained within this bounded interchange family.

**Material limits:** Six flat scalar types and bounded CSV input; no general Parquet ingestion, nested types, metadata, units or dataset operations. Optional CSV preserves the closed lexical/null contract but carries no schema. Consumers must declare compatible types; a literal nonnull reserved null token cannot be represented. Spreadsheet consumers may support a stricter subset. Canonical floating-point text is an observed PyArrow 26.0.0 writer contract; sample probes and independent typed readback support this bounded implementation, not every future native writer. Subjective source-contract assessment, not an exhaustive API measurement. Verification confidence, native availability and source-bound qualification remain independent of both strength scores.

**Evidence:** [src/schemaxis/adaptors/apachearrow/adaptor.json](../../src/schemaxis/adaptors/apachearrow/adaptor.json), [src/schemaxis/adaptors/apachearrow/readiness.json](../../src/schemaxis/adaptors/apachearrow/readiness.json), [docs/apachearrow.md](../../docs/apachearrow.md), [verification/2026-10-25-apachearrow-35.md](../../verification/2026-10-25-apachearrow-35.md), [verification/2026-10-25-apachearrow-65.md](../../verification/2026-10-25-apachearrow-65.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app apachearrow`.

### aseprite

Bounded procedural RGBA sprites, timed frames, layer/cel placement and captured PNG import to editable sprites and sheets.

**Whole-application denominator:** Pixel drawing, layers/cels, animation and tags, palette/colour editing, image import and asset publication.

**Breadth rationale:** Cels, frames and publication connect several core sprite concepts, but drawing tools, rich blending, palette workflows and animation editing remain largely absent.

**Abstraction rationale:** Named sprites, layers, frames and tags hide Lua and organise reusable assets; users still specify many low-level drawing and placement details.

**Material limits:** Captured imports require the declared RGBA8 PNG subset, binary alpha and in-canvas replacement; no general blending, scaling or interactive editing. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/aseprite/adaptor.json](../../src/schemaxis/adaptors/aseprite/adaptor.json), [src/schemaxis/adaptors/aseprite/readiness.json](../../src/schemaxis/adaptors/aseprite/readiness.json), [docs/aseprite.md](../../docs/aseprite.md), [verification/2026-10-24-aseprite-allocation.md](../../verification/2026-10-24-aseprite-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app aseprite`.

### blender

Typed mesh/scene production and reusable inferred-pivot product presentation, editable procedural materials/motion/rigs and checked frame publications.

**Whole-application denominator:** Mesh and scene modelling, materials, lighting/cameras, rendering, animation, rigging, sculpting, simulation and compositing.

**Breadth rationale:** Scene production now spans editable assets/hierarchy, object/bone motion, rigs/skin, curated shader/procedural/compositor graphs, bounded rigid-body/cloth and evaluated exchange. Most families remain partial; broader linked-library/cache asset reuse, richer simulation/cache workflows, sculpt/paint/Grease Pencil and sequencing/tracking remain unfinished. This is an uncertain strategic breadth estimate, not a measured API percentage. Reusable role-bound action/NLA clips and relative/absolute morph authoring now extend animation, with native asset fidelity for ordinary action strips. The conservative whole-application estimate remains unchanged until broader missing families are addressed. Reusable typed shader, geometry and compositor group interfaces now include nested graphs and checked native parameter editing; the remaining strategic family map is unchanged. Selected native scene/layer collection carriers now preserve native ownership, nested instances and sharing; linked-library overrides and source render-layer transplantation remain unfinished. Typed scientific mesh fields and multiple named UV projection/unwrap/packing now extend texture/data workflows; sculpt/paint/baking/UDIM and richer topology remain required. The conservative whole-application estimate is unchanged. Typed Object/Collection resources and selected-asset-part compositions extend bounded procedural workflows; imported procedural topology remains incomplete. Finite mesh selections and ordered topology edits now support enclosure, bridge and halfspace workflows; broader mesh operators, topology data interpolation, sculpt and paint remain incomplete. No family-wide completion follows from these bounded cases. Editable classic multi-spline Bezier/NURBS controls, planar fills and section/taper dependencies extend modelling without closing broader curve editing, surfaces, hair or implicit modelling. Subjective scores remain unchanged. Typed Cycles/EEVEE/Workbench engine intent, display transforms and distinct material/object/mesh-attribute colours extend rendering; broader rendering, probe/cache, OCIO and pass/output families remain incomplete. Conservative subjective estimates remain unchanged. Bounded captured-image Workbench previews now separate display image and active UV from shader appearance; painting/baking/UDIM remain incomplete. Subjective estimates are unchanged. Named DATA surface layouts and exact-data Object palettes extend bounded face/spline/text materials and linked appearance. The subjective whole-application estimate remains unchanged; broader shader/paint/bake/UDIM and material animation remain required. Typed layered artist surfaces and shared image/UV/normal intent extend reusable material workflows without changing the conservative subjective breadth score; texture painting, baking, UDIM and additional shader families remain incomplete. Finite public render bundles add named view layers, CPU scientific EXR planes and Cryptomatte, managed PNG/EXR output, logical Material/World AOV taps and captured collection masks. Cycles Freestyle adds bounded technical lines. Explicit rigid-packed and cloth-packed/disk requests add freshly reconstructed all-frame cache verification. Whole Blender remains incomplete.

**Abstraction rationale:** Named scene resources, semantic channels and graph sockets compose reusable workflows, while inferred-pivot turntables lower product presentation into editable controls and verified outputs. Expert node/rig/physics controls still require native domain knowledge. Direct scene-production input removes authored DAG scaffolding, and complete packed native assets retain editable hierarchy, material and child motion. Motion roles decouple clips from object identities, explicit reference poses and normalized morph progress remove native slot/timing/Key spacing plumbing. Shared typed node interfaces remove native interface IDs, per-domain constructor plumbing and repeated graph definitions. Explicit scene/layer selection and inferred unambiguous choices replace manual append/reparent/flatten plumbing with a verified native asset carrier. Mesh-domain fields unify constant/dense/sparse data, canonical edge ordering and typed shader/procedural access; explicit copy/shared prototype ownership and semantic source-name selection prevent accidental per-instance/shared writes. Current-stage semantic selections and explicit data-loss/ownership policies replace operator selection-mode and mutable pre-edit witness plumbing for bounded mesh edits. Typed spline controls unify rational weights, tangent policies, named profile/taper dependencies and sampling budgets without authoring RNA paths or arbitrary execution. Engine-specific unions reject ineffective settings; independent display, shader, Object and attribute colours express technical presentation without RNA keys. Captured-source reconstruction separates input authority from editable output readbacks while reproducing authorised scene overlays. Independent typed display-image selection and closed pinned-file consumers avoid native paint-slot or file-reference plumbing. Logical material roles, disjoint semantic regions and separate DATA-layout/Object-palette ownership remove native slot-index and per-instance sharing plumbing while retaining editable materials and source-authoritative verification. Artist finish layers and local named sampler/channel roles compile reviewed native graphs; one stored UV transform can drive base/ORM/tangent normals without exposing native node/socket plumbing. Logical layer/owner/pass references, reusable owner-local taps and explicit cache consumers compose with existing authored scene intent; no native property dictionary or executable authoring escape is added.

**Material limits:** Important stable Blender families remain unfinished as listed in docs/blender-capabilities.md; no strategic completion or near-total API coverage is claimed. Most catalogues are curated subsets. Native node constructor/readback coverage does not prove every graph effect; physics replay is bounded serial acceptance without portable baked caches. Editorial estimates have low confidence and no exhaustive API denominator; native qualification and runtime availability remain separate axes. Typed mesh attributes and UV mapping broaden supported scene production; whole-Blender completion remains open, and independent pixel-gap checks cover the documented fixture/solver matrix rather than arbitrary UV polygons. Resource admission conservatively considers reachable pointer defaults/overrides; imported arbitrary node/cache/volume resources need broader reviewed bounds. Source numeric topology animation uses conservative key/Bezier envelopes; driven, layered/NLA or curve-modifier topology needs a reviewed explicit bound. Mesh editing is bounded deterministic geometry replay; general bevel/knife/dissolve/subdivide, unequal/open loop bridging and existing UV/custom-normal/weight/morph interpolation remain gaps. Curve/builtin-font source bounds include render resolution; richer spline/profile/taper and surface modelling still require broader authoring and native acceptance. Renderer verification is scoped to recorded cases; final integration and independent whole-adaptor review remain pending. Whole Blender remains incomplete. Texture painting/baking, broader material animation and MatCap flip intent/readback, captured custom OCIO/LUTs, EEVEE probe/cache authoring remain incomplete; finite named render layers/AOV/EXR bundles are now available under the declared source and decoding constraints. General verification does not independently rerender arbitrary images. Named surface material layouts are bounded to Mesh faces, classic splines and Unicode text-character ranges, with finite selector scan work and owner/element readback budgets. Grease Pencil materials, broader shader catalogues and paint/bake/UDIM remain incomplete. Independent integration acceptance is required. Fresh source reconstruction now binds imported material geometry inputs, including UV/colour selections, split normals, texture space, owned morph/Action channels and render-only modifier configuration. Geometry drivers, legacy Actions and texture/ORCO mesh overrides still require further typed contracts. This source-fidelity boundary is not arbitrary-image rerender equivalence or completed shader/PBR authoring. Reserved native selection flags are presentation only when unqueried. Finite reserved literal Attribute names bind fresh stored/evaluated flags regardless of the current query mode, because captured layered Actions can switch Object to Geometry on later frames. Retained captured meshes and Object/Collection procedural dependencies share conservative query propagation without changing persisted asset-fidelity/v2; this does not prove arbitrary-image rerender equivalence. Artist PBR has accepted scoped source, native, Studio and installed-package qualification; the three-feature closeout requires its own current combined integration gates. General shader-coordinate Jacobian correction, render-time bounds, SSS convergence oracles and whole-Blender completion are not claimed. Native UVsphere producer indices are now deterministic; older allocation-dependent packets can require a NEW trusted-input run. Exact source topology authority remains mandatory. CPU built-in OSL is qualified on the fixed runtime; OptiX OSL requires available supported hardware. Authored Script nodes, shader code and untyped RNA are unavailable. Fresh scene-render context reconstruction binds hidden bounce/optics/output settings and numeric Attribute RNA lookup candidates. This requires a configured fixed Blender runtime for public saved-scene verification, including a plain DAG without explicit materials; native context is not authorised by refreshed readbacks. Native Smart magnification is qualified; adaptive minification and portable mip-cache ownership remain OPEN. Large tiled-image probes alias with packed resources and native-generated unpacked texture caches; no area-filtering guarantee is claimed. Legacy Curve/Font render data and global saved time/camera markers/gravity are freshly reconstructed; non-mesh curve shape-key dependencies still need a reviewed mapping and are refused. This adds no curve-morph authoring coverage. Cycles 8-bit sRGB image sampling can lose substantial colour precision near zero alpha; encoded-byte colour fidelity is not guaranteed. EEVEE and Non-Color data use their distinct native paths. Native geometry drivers, including simple expressions that work in Blender library append, remain refused by the material-input dependency contract; bake supported Action channels before asset reuse. Classic Curve point/handle selection and hide flags remain conservative source inputs and can require a new capture after an otherwise presentation-only edit. These workflows remain required gaps, not exclusions. Scientific raw-plane identity is qualified on fixed CPU Cycles; general beauty PNG/EXR verification binds source and layout rather than arbitrary image equality. Generic AOV fields must avoid reserved Cycles names. Projected captures require the admitted finite local hierarchy; nested instances/deformers/drivers are refused. Freestyle uses the declared finite Cycles subset. Only complete-timeline rigid-packed and cloth-packed/disk caches are admitted; rigid-disk, inherited arbitrary baked caches, broader simulations, Grease Pencil Line Art, procedural skies and World volumes remain unsupported or unfinished.

**Evidence:** [src/schemaxis/adaptors/blender/adaptor.json](../../src/schemaxis/adaptors/blender/adaptor.json), [src/schemaxis/adaptors/blender/readiness.json](../../src/schemaxis/adaptors/blender/readiness.json), [docs/parallel-dispatch-and-blender.md](../../docs/parallel-dispatch-and-blender.md), [verification/2026-10-24-blender-allocation.md](../../verification/2026-10-24-blender-allocation.md), [docs/blender-production.md](../../docs/blender-production.md), [docs/blender-capabilities.md](../../docs/blender-capabilities.md), [verification/2026-11-04-blender-production.md](../../verification/2026-11-04-blender-production.md), [docs/blender-motion.md](../../docs/blender-motion.md), [verification/2026-11-04-blender-motion.md](../../verification/2026-11-04-blender-motion.md), [docs/blender-node-groups.md](../../docs/blender-node-groups.md), [verification/2026-11-04-blender-node-groups.md](../../verification/2026-11-04-blender-node-groups.md), [docs/blender-collection-assets.md](../../docs/blender-collection-assets.md), [verification/2026-11-04-blender-collections.md](../../verification/2026-11-04-blender-collections.md), [docs/blender-mesh-data.md](../../docs/blender-mesh-data.md), [verification/2026-11-04-blender-mesh-data.md](../../verification/2026-11-04-blender-mesh-data.md), [docs/blender-mesh-editing.md](../../docs/blender-mesh-editing.md), [verification/2026-11-04-blender-mesh-editing.md](../../verification/2026-11-04-blender-mesh-editing.md), [verification/2026-11-05-blender-curve-budget.md](../../verification/2026-11-05-blender-curve-budget.md), [docs/blender-splines.md](../../docs/blender-splines.md), [verification/2026-11-05-blender-splines.md](../../verification/2026-11-05-blender-splines.md), [docs/blender-rendering.md](../../docs/blender-rendering.md), [verification/2026-11-05-blender-rendering.md](../../verification/2026-11-05-blender-rendering.md), [docs/blender-image-preview.md](../../docs/blender-image-preview.md), [verification/2026-11-05-blender-image-preview.md](../../verification/2026-11-05-blender-image-preview.md), [docs/blender-material-assignments.md](../../docs/blender-material-assignments.md), [verification/2026-11-05-blender-material-assignments.md](../../verification/2026-11-05-blender-material-assignments.md), [docs/blender-surface-materials.md](../../docs/blender-surface-materials.md), [verification/2026-11-05-blender-surfaces.md](../../verification/2026-11-05-blender-surfaces.md), [docs/blender-render-bundles.md](../../docs/blender-render-bundles.md), [docs/blender-freestyle.md](../../docs/blender-freestyle.md), [docs/blender-simulation-caches.md](../../docs/blender-simulation-caches.md), [verification/2026-11-06-blender-feature-closeout.md](../../verification/2026-11-06-blender-feature-closeout.md).

Record version `2026-11-06.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app blender`.

### calc

Declared numeric or typed text/number tables, captured CSV with explicit column/null policy, verified editable workbook publication, numeric summaries and requirements, including a declared producer-file handoff.

**Whole-application denominator:** Workbook creation/editing, formulas, formatting/charts, data import/analysis, pivot tables and spreadsheet interaction.

**Breadth rationale:** Typed labelled rows and captured CSV now preserve identifiers, literal notes and declared missing measurements alongside the existing numeric summaries and requirements. This deepens the table-publication family; broad spreadsheet editing, formatting, charts, pivoting, formulas and automation remain absent, so the coarse whole-application estimate remains 10%.

**Abstraction rationale:** Table schemas, literal labels, missingness, summaries and requirements hide native conversion and recalculation. Authors still declare types, null policy and supported measurements; native workbook limits remain explicit. These additions retain the existing 80% estimate within this named workflow family.

**Material limits:** Bounded tables and fixed numeric summaries, not general workbook editing. Each numeric column needs at least two present values; empty text is refused, null becomes blank, and text never enters numeric summaries. Native workbook numbers allow documented decimal rounding and negative-zero normalisation. Use text for exact identifiers and integers above 2^53. No authored formulas, macros, dates, currency or unit inference. A generic file artifact is parsed against an explicit CSV header, types and null policy before native work; file kind alone does not establish compatible table contents. Subjective source-contract assessment, not an exhaustive API measurement. Native availability, actual runtime observations and source-bound qualification are separate facts.

**Evidence:** [src/schemaxis/adaptors/calc/adaptor.json](../../src/schemaxis/adaptors/calc/adaptor.json), [src/schemaxis/adaptors/calc/readiness.json](../../src/schemaxis/adaptors/calc/readiness.json), [docs/calc.md](../../docs/calc.md), [verification/2026-10-24-calc-allocation.md](../../verification/2026-10-24-calc-allocation.md), [verification/2026-10-25-calc-typed.md](../../verification/2026-10-25-calc-typed.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app calc`.

### calculix

Rectangular isotropic linear-elastic members assessed from dimensions, material, six end resultants, compatible restraint and measured serviceability limits.

**Whole-application denominator:** Finite-element geometry/mesh input, materials, loads/constraints, linear/nonlinear structural analysis, thermal analysis and result evaluation.

**Breadth rationale:** The supported member product now spans six signed end resultants, axial/biaxial bending/torsion, superposition, two compatible restraints and meaningful native measured requirements. It remains one straight solid rectangular section/material/static family within a much larger general multiphysics FEA application; no broad application-completion claim follows from deeper checks.

**Abstraction rationale:** Physical end-resultant and restraint intent drives consistent quadratic forces/couples, meshes, automatic refinement, independent axial/bending/torsional/equilibrium acceptance and measured translation/twist/interior sampled-stress decisions. Solver-deck construction and native processes are hidden within the bounded supported product; general structural assemblies and peak/failure decisions remain unsupported.

**Material limits:** Only one solid rectangular geometry/section and isotropic linear material/static-analysis family; arbitrary meshes/decks, general constraints/assemblies, nonlinearity, contact, buckling, dynamics and thermal analysis remain unsupported. Native proof is bounded to named cases and declared tolerances; continuous superpositions are not exhaustively qualified. Interior normal/von Mises measurements do not bound peak or certify yielding/fatigue. Subjective whole-application and supported-workflow editorial scores; neither is a native API ratio, runtime availability or source-bound qualification claim.

**Evidence:** [src/schemaxis/adaptors/calculix/adaptor.json](../../src/schemaxis/adaptors/calculix/adaptor.json), [src/schemaxis/adaptors/calculix/readiness.json](../../src/schemaxis/adaptors/calculix/readiness.json), [docs/calculix.md](../../docs/calculix.md), [verification/2026-11-03-calculix-six-resultants.md](../../verification/2026-11-03-calculix-six-resultants.md).

Record version `2026-11-03.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app calculix`.

### cantera

Hydrogen/oxygen ideal-gas property/equilibrium sweeps and closed reactor ignition/cooling histories with optional fixed-bath total conductance.

**Whole-application denominator:** Thermodynamic phases, chemical equilibrium, reaction kinetics, reactor networks, transport, flames and mechanism management.

**Breadth rationale:** Thermodynamics, equilibrium and closed-reactor kinetics with fixed-bath thermal exchange form useful connected workflows, but one mechanism and strict ideal-gas bounds still exclude much of Cantera.

**Abstraction rationale:** Physical state, held pressure/volume, total bath conductance, temperature and labelled checked energy outputs replace native network setup; users still choose species, sample times and solver tolerances.

**Material limits:** Ten-species h2o2 mechanism only; no carbon chemistry, condensed phases, transport, open or multiple-reactor networks, moving/radiating walls, finite baths, surfaces or flames. Editorial estimate with unchanged 10% breadth and 75% abstraction scores; no exhaustive native API denominator. Newly run native evidence qualifies only named thermal and retained baseline cases, separately from these subjective scores.

**Evidence:** [src/schemaxis/adaptors/cantera/adaptor.json](../../src/schemaxis/adaptors/cantera/adaptor.json), [src/schemaxis/adaptors/cantera/readiness.json](../../src/schemaxis/adaptors/cantera/readiness.json), [docs/cantera.md](../../docs/cantera.md), [verification/2026-10-24-cantera-allocation.md](../../verification/2026-10-24-cantera-allocation.md), [verification/2026-11-04-cantera-completion.md](../../verification/2026-11-04-cantera-completion.md).

Record version `2026-11-04.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app cantera`.

### elmer

Layered constant-area insulation and solid-heater conduction with source, end-condition and sampled-limit intent.

**Whole-application denominator:** General geometry/dimensions, solid thermal, mechanics, electromagnetics, acoustics, coupled fields, transient/nonlinear solutions, parallel/adaptive execution, result/restart and interactive workflows.

**Breadth rationale:** A useful complete layered steady solid-conduction family is integrated, including material/source/end alternatives and verified restart/result interpretation. Nearly all general geometry, physics, transient/nonlinear, coupling, parallel and interactive families remain excluded.

**Abstraction rationale:** Users author material resistance, heating and end conditions instead of native mesh/SIF syntax. The adaptor generates native models, retains full-precision measured temperatures, derives explicitly signed heat rates, checks exact conservation and enforces sampled criteria. Explicit mesh cells and sampled-only limitations remain user decisions.

**Material limits:** Serial perfectly contacting one-dimensional constant-property solids only; no general geometry, transient, radiation, nonlinear/coupled physics, CFD or MPI. Native VTU ASCII haseight-significant-digitnificant digits; full-precision native ASCII restart supplies tables and physics checks. Editorial estimates are not measured API percentages or native qualification. Limits concern nodes and midpoint flux; no mesh-convergence or continuum-envelope guarantee. Upstream patch identity is source provenance because the binary reports major.minor only.

**Evidence:** [src/schemaxis/adaptors/elmer/adaptor.json](../../src/schemaxis/adaptors/elmer/adaptor.json), [src/schemaxis/adaptors/elmer/readiness.json](../../src/schemaxis/adaptors/elmer/readiness.json), [docs/elmer.md](../../docs/elmer.md), [verification/2026-11-04-elmer-completion.md](../../verification/2026-11-04-elmer-completion.md), [verification/2026-11-04-native-evidence-types.md](../../verification/2026-11-04-native-evidence-types.md).

Record version `2026-11-04.3`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app elmer`.

### epubcheck

Strict zero-finding validation of one captured finished EPUB using the fixed default profile.

**Whole-application denominator:** EPUB package/document validation, profiles, severity and message configuration, archive/expanded-folder input and structured reporting.

**Breadth rationale:** The central package-validation workflow is present, but profile/custom-message handling, tolerant reporting and expanded inputs are excluded.

**Abstraction rationale:** A publication pass/fail goal and captured input replace Java flags and report parsing; the decision remains a fixed policy rather than adaptable editorial intent.

**Material limits:** Exactly the recorded supported EPUBCheck release and default profile; any warning fails; no repair, rendering, accessibility or legal certification. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/epubcheck/adaptor.json](../../src/schemaxis/adaptors/epubcheck/adaptor.json), [src/schemaxis/adaptors/epubcheck/readiness.json](../../src/schemaxis/adaptors/epubcheck/readiness.json), [docs/epubcheck.md](../../docs/epubcheck.md), [verification/2026-10-25-epubcheck-52.md](../../verification/2026-10-25-epubcheck-52.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app epubcheck`.

### espeakng

Short plain-text synthetic narration drafts with rate and four selected voices to canonical PCM16 WAV.

**Whole-application denominator:** Multilingual speech synthesis, voices, pronunciation/phonemes, prosody, SSML, output formats and dictionary/language development.

**Breadth rationale:** Creating speech is central, but most voices, prosody, pronunciation and markup capabilities are not exposed.

**Abstraction rationale:** Narration intent and a canonical reusable WAV hide synthesis plumbing; most expressive speech decisions are fixed or unavailable.

**Material limits:** Four closed voice choices and bounded plain text; fixed pitch/amplitude/output; no SSML or phoneme control and no intelligibility or human-quality guarantee. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/espeakng/adaptor.json](../../src/schemaxis/adaptors/espeakng/adaptor.json), [src/schemaxis/adaptors/espeakng/readiness.json](../../src/schemaxis/adaptors/espeakng/readiness.json), [docs/espeakng.md](../../docs/espeakng.md), [verification/2026-10-25-espeakng-57.md](../../verification/2026-10-25-espeakng-57.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app espeakng`.

### exiftool

Reading, auditing, comparing, editing, removing and minimising the metadata of a bounded set of photographs, and reconciling and correcting capture clocks, locating, setting and geotagging positions, through catalogue-field profiles, transfer groups and policies, a closed naming vocabulary, rule names, a named baseline, typed field edits, removal categories, device groups with declared true times, positions and tracks, with typed CSV handoff to a spreadsheet and produced images handed to later operations.

**Whole-application denominator:** Reading and writing of EXIF, XMP, IPTC, ICC, MakerNotes, GPS and many hundreds of file formats, composite and print-converted tags, sidecars, geotagging, time shifting, renaming and batch operations, structured and CSV output, configuration and extension.

**Breadth rationale:** Five-point rubric, whole-application denominator unchanged. Reading is a typed catalogue read by independent EXIF/GPS/IPTC/XMP decoders in JPEG, TIFF, DNG, PNG, WebP and HEIF files and XMP sidecars, with an optional complete native listing, audit and comparison, plus read-only clock reconciliation and typed position and height-reference reports. Writing covers new copies of the same container (JPEG, TIFF, DNG, PNG, WebP and the existing items of HEIF files): descriptive and rights fields, concrete removal categories and a rendering-preserving minimise, the time and location writes (capture-time correction, declared and track-interpolated positions with edition-aware altitude references), and now selected typed metadata carried from a photo or an XMP sidecar onto copies (descriptive, rights, rating, place, camera, lens, exposure with exact numerator and denominator pairs, device serials, a captured time and a position through the E3 writers), each with independent readback, byte-identical image data, a closed native diff and a source-versus-output proof. Beyond the copies, E4 exports portable XMP sidecars in a closed 29-property set (with an explicit altitude reference rule and stated coordinate quantisation), plans photo names from recorded capture facts and makes exact foldered byte copies. Full-block, MakerNote and unknown-tag transfer, editing or merging an existing sidecar, a naming template language, BigTIFF and maker raw containers, video, TIFF and DNG minimise, HEIF item creation and removal, MakerNote editing, extended or structured XMP, reverse geocoding and most of ExifTool remain outside this. The earlier 15 reflected the read family, the JPEG descriptive and removal writes and the time and location families; metadata transfer, sidecar export, naming and organising are further named families in the denominator, which moves the honest rounded value to 20 on the five-point scale, still below the rubric anchor of 25 (a few useful families with major areas missing) and not a claim of whole-application coverage. E5 adds TIFF, DNG, PNG, WebP and HEIF containers to the read family and to every writing operation (editing, removal with PNG and WebP minimise, capture-time and position writes, geotagging, transfer and sidecar application): each is located by a bounded reader, decoded by the shared readers and written as a new copy under an offset-free preservation proof, a shared readback and a closed native diff, with named refusals where native 13.55 or the structure cannot be protected (HEIF items are edited only when they exist and HEIF removal and minimise are refused; TIFF and DNG minimise is a named limit). That moves the honest rounded value to 25, the rubric anchor for a few useful families with major areas missing, and is not a claim of whole-application coverage.

**Abstraction rationale:** Authors state intent as catalogue profiles, field IDs, rule names and a baseline; the adaptor hides Perl invocation, tag and group naming, duplicate/instance keys, JSON number quirks, container location, charset and namespace handling, sidecar pairing, folder expansion with a complete manifest, presence-state classification, literal concordance and anchoring against a fixed native listing. Authors still decide which profiles matter, how to resolve disagreeing sources, whether recorded metadata is believable and what to do with privacy-relevant fields, and the closed catalogue limits what can be asked. For writing, authors state set, clear, add and remove of catalogue fields removal categories and minimise; the adaptor decides destinations, character sets, list joins, language handling, loss policy, native assignments and the three independent proofs, and never accepts a raw tag, option or expression. Confidence stays medium: native evidence is a bounded synthetic corpus. For the time and location workflows authors state devices, true times, shifts and offsets with a keep rule, positions with an explicit height reference and tracks with a gap limit; the adaptor hides time-tag families, sub-second and offset companions, rational coordinate storage, edition-dependent altitude rules, GPX parsing, interpolation and every native assignment, and it never accepts a raw tag, shift expression or geotag option. Authors still decide which clock is right (references are declarations), the group structure, the vertical reference, policies for stale companions and unplaceable photos, and the group and plan names are internal conveniences, so the score is unchanged at 65: more intent is expressed, but some decisions (group naming, assumed offsets, plan hand-off) remain manual. For the E4 workflows authors choose what is carried (closed groups or fields), what to do with existing, absent and ambiguous values, which time basis and source a name uses and what a missing fact means; the adaptor hides the typed snapshot, the catalogue views, native assignments, the sidecar property mapping and anchoring, the sanitiser and collision rules and the create-only copier, and never accepts a native tag, option, template or expression. Authors still decide whether recorded values are believable and which groups are appropriate to share (device serials and location are explicit), and the closed vocabularies limit what can be asked. Confidence stays medium: native evidence is a bounded synthetic corpus. The container family keeps the same intent-level operations, now for every operation: a container choice adds no native option, and its limits surface as stable refusal codes rather than native detail.

**Material limits:** Writes are new copies of the same container (JPEG, TIFF, DNG, PNG, WebP; HEIF only through Exif and XMP items that already exist) for descriptive, rights, removal, time, location, transfer and sidecar application. Items with trailing bytes, extended XMP, MPF, FlashPix, damaged metadata, an XMP value whose qualifiers a rewrite would drop, a paired sidecar or ExifTool warnings are refused per item; an unrecognised maker note blocks device-identity removal (minimise deletes it with the whole Exif block). JPEG, PNG and WebP minimise keeps only Orientation, YCbCrPositioning, ColorSpace and an allow-listed InteropIndex, refuses a capture with a Gamma tag or an XMP rendering value that disagrees with Exif, and lists every kept segment in its residual report; unknown application segments stay byte for byte. Proof N compares listings of the same engine that wrote the file and proves reproducibility, not independent truth; proof P is about bytes and says nothing about pixels or authenticity. Removal is for the listed categories in understood locations and is not anonymisation or privacy certification. No MWG compliance is claimed. JPEG (any coding process), TIFF, DNG, PNG, WebP, HEIF and XMP sidecars, catalogued fields only; every other tag, container (BigTIFF, maker raw, JPEG XL, GIF) and metadata family is unassessed. Metadata can be wrong and nothing certifies capture time, location, authorship or privacy; sources that disagree are reported, none preferred, and no MWG compliance is claimed. Duplicate source files are refused per item; two distinct files with identical bytes are reported by the audit, not deduplicated. A derived capturedUtc is published as derived even when its local-time input is only partially assessed, and compare treats a zero coordinate with opposite references as the same canonical value. Native evidence is bounded measurement of a small synthetic corpus: hand-literal qualifier cases, a public agent loop and a Calc folder-handoff/reuse check against ExifTool 13.55 with private fixtures. No kit receipt is registered, no independent acceptance is claimed and the parent gate decides any qualification label. Verification of a native listing needs a configured trusted ExifTool 13.55. Field coverage is uneven: all 40 catalogue fields have host-literal decoding tests, but modifiedLocal, lensMake and lensSerialNumber are read present from only one synthetic file, and XMP-sourced GPS, structured and extended XMP, MakerNotes, thumbnails and every container outside the six are unassessed. NATIVE_ANCHOR_MISMATCH against a real ExifTool is exercised by one deliberate same-size Make padding (ExifTool trims the trailing space that the independent reader keeps) in a verified partial set, plus retained-listing mutants and stage-emulated host tests; a file that repeats a GPS reference tag is a separate real native case (the field is ambiguous and ExifTool's copies are kept); no other real disagreement is known, and ordinary synthetic fixtures agree. Discovery matches every query token, so a long natural sentence can find nothing; curated short phrases are reviewed. A folder re-run re-executes every consumer of a re-run producer, even when the published bytes are unchanged. Subjective source-contract assessment rounded to five points; no exhaustive API denominator supports these percentages. Time and location: references, assumed offsets, positions, vertical references and track datums are declarations and are not verified; no time zone, daylight-saving rule, leap second, vertical datum conversion or place lookup exists; an interpolated position has no claimed accuracy; the GPS-only 2.4 altitude edition is an inference labelled as such and readers older than Exif 3.0 may not recognise the sea-level references; creating an Exif directory under an untouched height is refused rather than risking a change of its meaning; a sidecar altitude gap, exposure transfer between copies, renaming and reverse geocoding are not provided. Native evidence is a bounded private synthetic corpus run against ExifTool 13.55 (focused host, native, lifecycle, workflow and mutant tests); the global native and union gates and independent acceptance are separate and not claimed here. Transfer is selected typed values onto copies of JPEG, TIFF, DNG, PNG, WebP and HEIF items: no full-block, MakerNote or unknown-tag transfer, no XMP structures, no merge or edit of an existing sidecar, a destination that records an offset the source lacks or a different fraction precision for a captured time; an Exif block or ExifIFD is never created by a transfer. Names come from recorded capture facts with a closed vocabulary; organised copies exist only inside the run directory, and none of this is privacy or provenance certification. E5 containers: HEIF metadata items are never created (a conservative, named limit of native 13.55 observed on hand-built fixtures) and HEIF removal and minimise are refused; a HEIF edit that would leave an existing Exif or XMP item empty and an IPTC rebuild of a block with an opaque Photoshop tail (any container, any operation) are refused before native; TIFF and DNG minimise and thumbnails outside JPEG are not offered; a maker note that changed is accepted only when the relocation-aware comparison shows it equal (otherwise MAKERNOTE_CHANGED); items are bounded by 256 MiB (TIFF, DNG) or 64 MiB; BigTIFF, maker raw formats, JPEG XL and GIF are refused. Native evidence is hand-built synthetic fixtures against ExifTool 13.55; the independent family review and the global gates are separate and not claimed here.

**Evidence:** [src/schemaxis/adaptors/exiftool/adaptor.json](../../src/schemaxis/adaptors/exiftool/adaptor.json), [src/schemaxis/adaptors/exiftool/readiness.json](../../src/schemaxis/adaptors/exiftool/readiness.json), [src/schemaxis/adaptors/exiftool/fields.json](../../src/schemaxis/adaptors/exiftool/fields.json), [docs/exiftool.md](../../docs/exiftool.md), [verification/2026-10-26-exiftool-71.md](../../verification/2026-10-26-exiftool-71.md), [verification/2026-10-26-exiftool-workbench-74.md](../../verification/2026-10-26-exiftool-workbench-74.md), [tools/qualify_exiftool_workbench.py](../../tools/qualify_exiftool_workbench.py), [tools/qualify_exiftool_agent_loop.py](../../tools/qualify_exiftool_agent_loop.py), [tools/qualify_exiftool_folder_reuse.py](../../tools/qualify_exiftool_folder_reuse.py), [tests/unit/test_exiftool_workbench.py](../../tests/unit/test_exiftool_workbench.py), [src/schemaxis/adaptors/exiftool/writes.json](../../src/schemaxis/adaptors/exiftool/writes.json), [src/schemaxis/adaptors/exiftool/fields-2.json](../../src/schemaxis/adaptors/exiftool/fields-2.json), [tools/qualify_exiftool_write.py](../../tools/qualify_exiftool_write.py), [tests/unit/test_exiftool_write.py](../../tests/unit/test_exiftool_write.py), [tests/unit/test_exiftool_write_complete.py](../../tests/unit/test_exiftool_write_complete.py), [src/schemaxis/adaptors/exiftool/fields-3-additions.json](../../src/schemaxis/adaptors/exiftool/fields-3-additions.json), [src/schemaxis/adaptors/exiftool/writes-3.json](../../src/schemaxis/adaptors/exiftool/writes-3.json), [tools/qualify_exiftool_time_location.py](../../tools/qualify_exiftool_time_location.py), [tools/qualify_exiftool_time_location_loop.py](../../tools/qualify_exiftool_time_location_loop.py), [tests/unit/test_exiftool_e3_correct.py](../../tests/unit/test_exiftool_e3_correct.py), [tests/unit/test_exiftool_e3_place.py](../../tests/unit/test_exiftool_e3_place.py), [tests/unit/test_exiftool_e3_geotag.py](../../tests/unit/test_exiftool_e3_geotag.py), [tests/unit/test_exiftool_e3_lifecycle.py](../../tests/unit/test_exiftool_e3_lifecycle.py), [tests/unit/test_exiftool_e3_workflow.py](../../tests/unit/test_exiftool_e3_workflow.py), [verification/2026-10-26-exiftool-time-location-74.md](../../verification/2026-10-26-exiftool-time-location-74.md), [src/schemaxis/adaptors/exiftool/e4model.py](../../src/schemaxis/adaptors/exiftool/e4model.py), [src/schemaxis/adaptors/exiftool/e4copy.py](../../src/schemaxis/adaptors/exiftool/e4copy.py), [src/schemaxis/adaptors/exiftool/e4host.py](../../src/schemaxis/adaptors/exiftool/e4host.py), [src/schemaxis/adaptors/exiftool/xmpwrite.py](../../src/schemaxis/adaptors/exiftool/xmpwrite.py), [src/schemaxis/adaptors/exiftool/naming.py](../../src/schemaxis/adaptors/exiftool/naming.py), [tests/unit/test_exiftool_e4_naming.py](../../tests/unit/test_exiftool_e4_naming.py), [tests/unit/test_exiftool_e4_sidecar.py](../../tests/unit/test_exiftool_e4_sidecar.py), [tests/unit/test_exiftool_e4_transfer.py](../../tests/unit/test_exiftool_e4_transfer.py), [tests/unit/test_exiftool_e4_organise.py](../../tests/unit/test_exiftool_e4_organise.py), [tests/unit/test_exiftool_e4_lifecycle.py](../../tests/unit/test_exiftool_e4_lifecycle.py), [tests/unit/test_exiftool_e4_workflow.py](../../tests/unit/test_exiftool_e4_workflow.py), [tests/unit/test_exiftool_e4_surface.py](../../tests/unit/test_exiftool_e4_surface.py), [tools/qualify_exiftool_transfer_sidecar_naming.py](../../tools/qualify_exiftool_transfer_sidecar_naming.py), [tools/qualify_exiftool_transfer_sidecar_naming_loop.py](../../tools/qualify_exiftool_transfer_sidecar_naming_loop.py), [verification/2026-10-27-exiftool-copy-sidecar-naming-74.md](../../verification/2026-10-27-exiftool-copy-sidecar-naming-74.md), [docs/design/exiftool-metadata-workbench.md](../../docs/design/exiftool-metadata-workbench.md), [src/schemaxis/adaptors/exiftool/containerprofiles.json](../../src/schemaxis/adaptors/exiftool/containerprofiles.json), [tools/qualify_exiftool_containers.py](../../tools/qualify_exiftool_containers.py), [tools/qualify_exiftool_containers_loop.py](../../tools/qualify_exiftool_containers_loop.py), [tests/unit/test_exiftool_e5_positive.py](../../tests/unit/test_exiftool_e5_positive.py), [tests/unit/test_exiftool_e5_write.py](../../tests/unit/test_exiftool_e5_write.py), [tests/unit/test_exiftool_e5_lifecycle.py](../../tests/unit/test_exiftool_e5_lifecycle.py), [tests/unit/test_exiftool_e5_metadata_first.py](../../tests/unit/test_exiftool_e5_metadata_first.py), [tests/unit/test_exiftool_e5_surface.py](../../tests/unit/test_exiftool_e5_surface.py), [verification/2026-10-27-exiftool-containers-74.md](../../verification/2026-10-27-exiftool-containers-74.md), [tests/unit/test_exiftool_e5_ops.py](../../tests/unit/test_exiftool_e5_ops.py), [tests/unit/test_exiftool_e5_minimise.py](../../tests/unit/test_exiftool_e5_minimise.py), [tests/unit/test_exiftool_e5_matrix.py](../../tests/unit/test_exiftool_e5_matrix.py), [tests/unit/test_exiftool_e5_residual.py](../../tests/unit/test_exiftool_e5_residual.py), [tests/unit/test_exiftool_e5_ops_mutants.py](../../tests/unit/test_exiftool_e5_ops_mutants.py), [tests/unit/test_exiftool_e5_lifecycle_ops.py](../../tests/unit/test_exiftool_e5_lifecycle_ops.py), [tests/unit/test_exiftool_e5_workflow.py](../../tests/unit/test_exiftool_e5_workflow.py), [tests/unit/test_exiftool_e5_controls.py](../../tests/unit/test_exiftool_e5_controls.py), [tests/unit/test_exiftool_e5_completion.py](../../tests/unit/test_exiftool_e5_completion.py).

Record version `2026-10-27.3`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app exiftool`.

### ffmpeg

Bounded image/video frame publication, review-movie audio/caption muxing and selected AAC/PCM audio interchange.

**Whole-application denominator:** Media demux/decode, filtering, editing, encode/mux, audio processing, subtitles, streaming and broad format/device support.

**Breadth rationale:** Connected video, audio and caption publication has grown, but general filter graphs, broad codecs, editing and streaming remain absent.

**Abstraction rationale:** Deliverable dimensions, duration/error/byte budgets and review-movie intent replace long command lines, while exact stream/container policies still matter.

**Material limits:** Closed codecs, containers and bounded frame/audio contracts only; no arbitrary filters, streaming, audio mixing or general media editing; numeric error budgets are not perceptual quality. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/ffmpeg/adaptor.json](../../src/schemaxis/adaptors/ffmpeg/adaptor.json), [src/schemaxis/adaptors/ffmpeg/readiness.json](../../src/schemaxis/adaptors/ffmpeg/readiness.json), [docs/ffmpeg.md](../../docs/ffmpeg.md), [verification/2026-10-25-ffmpeg-audio-publish-56.md](../../verification/2026-10-25-ffmpeg-audio-publish-56.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app ffmpeg`.

### flac

PCM16 mono/stereo WAV lossless archive and canonical decode, optionally retaining three declared labels.

**Whole-application denominator:** Lossless audio encode/decode, sample formats/channels, compression choices, metadata, seeking and integrity testing.

**Breadth rationale:** The central lossless round trip is covered, but sample formats, channels, encoder controls and metadata operations are substantially restricted.

**Abstraction rationale:** Archive/decode intent and canonical downstream audio hide flags and integrity plumbing; the workflow remains a relatively direct encoding task.

**Material limits:** PCM16 native FLAC only; no Ogg, 24-bit, general tagging, pictures or seek-table control; consistency does not establish recording authenticity. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/flac/adaptor.json](../../src/schemaxis/adaptors/flac/adaptor.json), [src/schemaxis/adaptors/flac/readiness.json](../../src/schemaxis/adaptors/flac/readiness.json), [docs/flac.md](../../docs/flac.md), [verification/2026-10-25-flac-55.md](../../verification/2026-10-25-flac-55.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app flac`.

### freecad

Declared mechanical design, general named sketch relations, capsule slots, checked planar-face intent, per-Body feature histories, named length drivers, measured studies and fixed sourced assemblies.

**Whole-application denominator:** Parametric solid/sketch modelling, PartDesign, assemblies, CAD import/export, drawings, surfaces, CAM and domain workbenches.

**Breadth rationale:** Mechanical modelling now has a composable multi-Body foundation with named constrained geometry, frames/face attachments, successive additive/subtractive histories, datum rotation, Body dress-ups, patterns and lofts. The enclosure/lid workflow independently exercises native parameter propagation and useful geometry handoffs. The retained conservative subjective breadth score is not an API ratio: important surface/BRep, mechanisms, manufacturing and simulation families remain open. One typed CAD-to-static-elasticity bridge now adds independently checked material, mesh, geometric support/traction, native solver/result and editable lifecycle coverage; broader simulation physics remain open. Common native drilling now preserves one drill/recess definition across explicit, grid and pitch-circle fastening locations; this advances mechanical workflows without closing broad application families. Uniform native Skin shells add open cups/tubes and a shelled enclosure composition, without closing general surfaces/offsets or the other workbenches. Native sweeps with editable bend paths and attached flanges advance the mechanical family; broad3D paths, surface modelling and other workbenches remain unfinished. Technical drawing and prescribed constant-speed Revolute/Slider motion add useful checked deliverables; broader drawing, joint, loop, dynamics, BIM/Draft, surfaces, mesh/reverse engineering and analysis/CAM variants remain unfinished. Typed mould-release Draft now adds measured planar/cylindrical face intent and native shell/boss/Hole compositions; this advances one modelling family without closing the broad application inventory. Native Spreadsheet aliases and affine unitful length formulas now drive editable Body histories, with owner native edit/reopen, source-copy isolation and workflow proofs; independent review, integrated Help and package acceptance remain open, so the breadth score is unchanged. Checked closed-STL preparation supports faceted Part/refine/boolean workflows and checked imported stock can seed editable Bodies; broad mesh repair, decimation and scan reconstruction remain missing. The subjective breadth score is unchanged. Editable straight-edged Draft polygon profiles now compose native Part extrusion/booleans with full trusted source and save-state binding; broader Draft and current integrated acceptance remain open. The subjective score is unchanged. Imported-solid Body stock and explicit layouts have source-bound owner product, native edit/reopen, save/authority and independent held-out source/assembly/GUI/removal evidence. First/final seed-only stock now composes through an exact finite empty-inline-table policy, with full fresh payload binding and no geometry tolerance change. Exact integrated/package acceptance and broader application families remain open. Application-wide denominator and scores are unchanged. Named flat-tool CAM and geometric drilling-cycle intent are implementing with independently parsed controller state, per-tool depth-specific removal and whole trusted saved-Job reconstruction. Pointed drills, explicit tip/full-diameter depths and finite aboveBlank/evolvingStock physical-tool/holder policies now have source-bound owner native, GUI edit/reopen, authority and lifecycle proof. An optional reduced shank retains its complete native template/extension and real shoulder, with an independently reviewed copy/edit/reopen path. Full current product/integration/package gates remain open; exterior holding, other cutters, machine constraints and broad CAM strategies stay required unfinished breadth. Scores and the whole-application denominator are unchanged. Finite pure generation1 Pad/Pocket, selected-final-Body generation2 histories and admitted primitive/import seeds now retain complete typed source intent. Whole native source and assembly-copy reconstruction, bounded trusted SDK save states and retired-source reuse have source-bound owner evidence and independent source review. The portable public qualifier now has source-bound native and installed-package acceptance for this finite Body-history milestone. Explicit unseeded Body frames now have typed world-carrier selection, local assembly witnesses, WORLD named measurements, authoring examples and a public lifecycle qualifier. Current combined native/package qualification remains open. Whole-application scores and denominator are unchanged. Typed helical material modes, native world-frame named measures and original-geometry empirical closed-boundary diagnostics now compose in the integrated candidate. Isolated auxiliary conic lenses close two finite period/tangent availability classes while retaining original curves. This remains empirical numerical evidence, with unmodelled endpoint and three-dimensional closure gaps; combined integrated/package acceptance and broad modelling families remain open. Application-wide scores and denominator are unchanged.

**Abstraction rationale:** Common rectangle/circle/slot intent lowers to native constrained sketches. Planar-face intent resolves exact cardinality and preserves attachment links; explicit per-Body history prevents hidden branching. General geometry relations name semantic endpoints instead of native indices. Users still author ordered features, general constraints and topology-sensitive choices; broader mechanisms, CAM, analysis and modelling workflows remain incomplete. Static-solid FEM expresses material and geometric support/traction intent rather than mesh-node indices or solver cards. Drilling layout intent compiles native pitch/phase constraints and fixed expressions rather than authored geometry indices or duplicated diameter values. A shell expresses thickness once and opening-face intent without indices; a shared wall dimension propagates into attached bosses, drilling and a second Body lid. Bend radius/angle intent compiles solved construction geometry; one wall dimension controls nested sweep sections and flange bores, and persistent centre-of-mass attachments follow moving faces without user constraint indices. Named joint endpoint/duration intent compiles native angular/linear formulas and sampled rigid-tree trajectories; it does not require authored native object paths or Python. General prescribed mechanisms remain unfinished. Draft faces use exact-cardinality geometric predicates and an explicit same-Body neutral profile plane rather than native face numbers; optional datum pull axes and native history preserve editable intent. Named tool IDs and source-frame hole layouts lower into native controllers, geometric edge targets and finite drilling cycles, avoiding authored tool-library paths, native indices and raw NC. Independent replay uses the selected cutter footprint at each depth. Physical clearance intent separates cutting reach, actual shank geometry, ordered stepped holders and tip/full-diameter depth; it compiles native tools and complete motion checks without authored Python, native property paths or NC.

**Material limits:** Stable FreeCAD capability families remain unfinished; this accepted mechanical-design milestone is not whole-application completion. See docs/freecad-capabilities.md for specific remaining gaps. Editorial percentages are conservative subjective assessments, not tested API percentages. Native receipts and source identities separately establish qualified workflows; unrelated earlier live/assembly/import receipts retain their original scope. Native engineering tables currently cover bounded affine length formulas driving part dimensions. Angular/nonlinear/general-table and cross-document spreadsheet workflows remain missing; this foundation is not whole-application completion. STL preparation retains faceted geometry and native Part edits; it does not recover analytical surfaces, scan-fitting intent, colours or foreign Body/assembly feature histories from a mesh. Draft profiles currently cover straight closed boundaries and native Points/Placement edits; curves, dimensions, arrays, snapping, Body seeding and sourced-history copying remain unfinished. Portable typed Body captures compare whole reachable trusted SDK states under one 120-second verification budget; repeated states may conservatively refuse. Scheduled fresh verification currently repeats complete source closure four times. Explicit Body.frame support retains local feature/assembly coordinates and applies world layout once; current integrated qualification is separate from whole-application completion. Helical solid measures use bounded empirical completed-boundary diagnostics, not certified errors or physical mass. Conic/rational endpoint joins, three-dimensional rung/cap gaps and native/quadrature roundoff remain unmodelled; other unresolved conic configurations refuse. The authored turn bound does not guarantee numerical availability.

**Evidence:** [src/schemaxis/adaptors/freecad/adaptor.json](../../src/schemaxis/adaptors/freecad/adaptor.json), [src/schemaxis/adaptors/freecad/readiness.json](../../src/schemaxis/adaptors/freecad/readiness.json), [docs/freecad-part-design.md](../../docs/freecad-part-design.md), [verification/2026-10-24-freecad-allocation.md](../../verification/2026-10-24-freecad-allocation.md), [docs/freecad-assemblies.md](../../docs/freecad-assemblies.md), [verification/2026-10-18-freecad-assembly-sources.md](../../verification/2026-10-18-freecad-assembly-sources.md), [docs/freecad-capabilities.md](../../docs/freecad-capabilities.md), [verification/2026-11-04-freecad-completion.md](../../verification/2026-11-04-freecad-completion.md), [docs/freecad-histories.md](../../docs/freecad-histories.md), [verification/2026-11-04-freecad-histories.md](../../verification/2026-11-04-freecad-histories.md), [verification/2026-11-04-freecad-analysis.md](../../verification/2026-11-04-freecad-analysis.md), [verification/2026-11-04-freecad-drilling.md](../../verification/2026-11-04-freecad-drilling.md), [verification/2026-11-04-freecad-shells.md](../../verification/2026-11-04-freecad-shells.md), [verification/2026-11-04-freecad-sweeps.md](../../verification/2026-11-04-freecad-sweeps.md), [docs/freecad-mechanisms.md](../../docs/freecad-mechanisms.md), [verification/2026-11-04-freecad-mechanisms.md](../../verification/2026-11-04-freecad-mechanisms.md), [verification/2026-11-04-freecad-drawings.md](../../verification/2026-11-04-freecad-drawings.md), [verification/2026-11-04-freecad-draft.md](../../verification/2026-11-04-freecad-draft.md), [docs/freecad-spreadsheets.md](../../docs/freecad-spreadsheets.md), [verification/2026-11-05-freecad-spreadsheets.md](../../verification/2026-11-05-freecad-spreadsheets.md), [docs/freecad-mesh-preparation.md](../../docs/freecad-mesh-preparation.md), [verification/2026-11-05-freecad-mesh-preparation.md](../../verification/2026-11-05-freecad-mesh-preparation.md), [verification/2026-11-05-freecad-draft-profiles.md](../../verification/2026-11-05-freecad-draft-profiles.md), [docs/freecad-cam.md](../../docs/freecad-cam.md), [tools/qualify_freecad_cam_drilling.py](../../tools/qualify_freecad_cam_drilling.py), [verification/2026-11-05-freecad-cam-operation-names.md](../../verification/2026-11-05-freecad-cam-operation-names.md), [verification/2026-11-05-freecad-physical-cam.md](../../verification/2026-11-05-freecad-physical-cam.md), [tools/qualify_freecad_cam_physical.py](../../tools/qualify_freecad_cam_physical.py), [docs/freecad-body-history.md](../../docs/freecad-body-history.md), [tools/qualify_freecad_body_history.py](../../tools/qualify_freecad_body_history.py), [docs/freecad-measurements.md](../../docs/freecad-measurements.md), [docs/design/freecad-helical-precision.md](../../docs/design/freecad-helical-precision.md), [tools/qualify_freecad_completed_boundary.py](../../tools/qualify_freecad_completed_boundary.py), [docs/freecad-body-frames.md](../../docs/freecad-body-frames.md), [tools/qualify_freecad_body_frame.py](../../tools/qualify_freecad_body_frame.py).

Record version `2026-11-06.4`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app freecad`.

### gdal

Single-band north-up GeoTIFF windows and nearest-neighbour grid resizing, plus named grid-aligned rectangular-zone summaries with explicit CRS, value units and missing-data policy.

**Whole-application denominator:** Raster/vector formats and translation, georeferencing/reprojection, resampling, mosaics, analysis and dataset/metadata management.

**Breadth rationale:** Named grid-aligned zone summaries deepen bounded raster analysis alongside window preparation. General drivers, vector workflows, reprojection, mosaics and most analysis remain outside this integration, so the whole-application estimate remains 5%.

**Abstraction rationale:** Named zones and explicit missing-data intent hide GeoJSON construction, native aggregation, fresh readback and publication handling. Authors still choose pixel rectangles and sampling decisions and judge whether summing the values is meaningful. The existing 65% estimate is retained within these declared workflows.

**Material limits:** Bounded single-band classic GeoTIFFs in EPSG:4326/3857 only; no general vector polygons, reprojection, interpolation beyond nearest, masks, overviews or arbitrary driver/metadata handling. Zones are pixel-aligned rectangles in the current source grid and may overlap as independent summaries. Value sums are not area integrals, and angular pixels do not establish ground area or uncertainty. Every included pixel is visited by the independent source oracle. Sum/mean checks use an explicit roundoff allowance and refuse unresolved cancellation; this is numerical consistency, not scientific validity or acquisition-quality certification. Subjective source-contract assessment rounded to five points, with no exhaustive native API denominator. Native qualification, exact tested cases and runtime availability are separate readiness facts; this record does not register a native receipt.

**Evidence:** [src/schemaxis/adaptors/gdal/adaptor.json](../../src/schemaxis/adaptors/gdal/adaptor.json), [src/schemaxis/adaptors/gdal/readiness.json](../../src/schemaxis/adaptors/gdal/readiness.json), [docs/gdal.md](../../docs/gdal.md), [verification/2026-10-24-gdal-allocation.md](../../verification/2026-10-24-gdal-allocation.md), [verification/2026-10-26-gdal-zonal-completion.md](../../verification/2026-10-26-gdal-zonal-completion.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app gdal`.

### getdp

Layered constant-area steady thermal walls and electrical resistors with source, end-condition and sampled-limit intent.

**Whole-application denominator:** General 1D/2D/axisymmetric/3D formulations, scalar/vector/mixed fields, thermal/electrical/magnetic and coupled/circuit problems, steady/transient/harmonic/nonlinear solution and postprocessing.

**Breadth rationale:** Two useful steady scalar-conduction families are covered end to end, while general geometries, vector electromagnetics, transients, harmonic/nonlinear systems and coupling exclude most GetDP breadth.

**Abstraction rationale:** Layered material, generation and end-condition intent determines mesh/formulation and independently verified field, flux, conservation and sampled-limit decisions; users retain explicit cells and operation-dependent units.

**Material limits:** Serial constant-property perfectly contacting one-dimensional layers only. No arbitrary formulations/imported geometry, transient, nonlinear, radiation, harmonic, vector electromagnetic or coupled electrothermal systems. Editorial ordinal estimates, not measured API ratios or runtime/native qualification. Mesh-node field and element-midpoint flux limits do not certify unsampled extrema or all tolerance variants.

**Evidence:** [src/schemaxis/adaptors/getdp/adaptor.json](../../src/schemaxis/adaptors/getdp/adaptor.json), [src/schemaxis/adaptors/getdp/readiness.json](../../src/schemaxis/adaptors/getdp/readiness.json), [docs/getdp.md](../../docs/getdp.md), [verification/2026-11-03-getdp-completion.md](../../verification/2026-11-03-getdp-completion.md).

Record version `2026-11-03.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app getdp`.

### gmsh

One analytic primitive or STEP solid to verified linear tetrahedra with named planar and cylindrical (bore, shaft, sleeve) boundaries, discoverable CAD surfaces, explicit curved-cap error budgets, chord-deviation and quality goals, bounded refinement and adopted STEP inputs.

**Whole-application denominator:** Geometry construction/import, 1D/2D/3D and high-order meshing, physical groups, size fields, optimisation and mesh exchange.

**Breadth rationale:** Connected primitive construction (box, cylinder, annular single-solid cut and sphere), STEP, named planar and whole analytic cylindrical boundaries with an independently proven material side, two 3D methods and bounded quality/refinement workflows are useful. Most geometry, standalone surface/high-order/structured meshing, other curved-wall families, multi-domain and post-processing breadth remains outside this integration.

**Abstraction rationale:** Reusable typed geometric intent and analytic oracles feed one solid/mesh contract. Named walls with a stated material side, an independently measured chord-deviation requirement, a CAD surface inventory for authoring, named-boundary resolution, explicit cap loss budgets, method decisions and measured quality avoid native call ordering while retaining numerical meaning.

**Material limits:** One solid/volume; planar and cylinder groups share a limit of twelve; only world-axis analytic cylinders; linear tetrahedra only, bounded node/cell counts; no solver setup or MPI claim. Editorial estimate over the capability-family map and current contracts; no exhaustive native API denominator. The recorded sleeve, plate, refinement, adoption and primitive fixtures qualify only those serial cases. Qualification and local availability remain separate axes.

**Evidence:** [src/schemaxis/adaptors/gmsh/adaptor.json](../../src/schemaxis/adaptors/gmsh/adaptor.json), [src/schemaxis/adaptors/gmsh/readiness.json](../../src/schemaxis/adaptors/gmsh/readiness.json), [docs/gmsh.md](../../docs/gmsh.md), [verification/2026-10-24-gmsh-allocation.md](../../verification/2026-10-24-gmsh-allocation.md), [verification/2026-11-03-gmsh-primitives.md](../../verification/2026-11-03-gmsh-primitives.md), [verification/2026-11-10-gmsh-cylinders.md](../../verification/2026-11-10-gmsh-cylinders.md), [tools/qualify_gmsh_cylinders.py](../../tools/qualify_gmsh_cylinders.py).

Record version `2026-11-10.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app gmsh`.

### gnuplot

Named numeric CSV series with declared units, explicit ranges, symmetric y intervals or one supplied asymmetric range envelope to independently checked SVG/PNG.

**Whole-application denominator:** 2D/3D scientific plotting, plot types, functions, styling, axes, multiplots, terminals and interactive exploration.

**Breadth rationale:** Explicit asymmetric lower/upper envelopes and captured typed-CSV handoffs deepen the bounded 2D publication family. Most plot types, 3D, composition, functions, rich styling and interactive exploration remain absent, so the coarse whole-application estimate stays at 20%.

**Abstraction rationale:** Series, unit and supplied-bound intent hide plotting scripts and native filled-curve geometry. Authors still choose columns, ranges, compatible scales and the meaning of supplied bounds; the existing 70% estimate is retained within this bounded plotting family.

**Material limits:** One to four ordinary numeric series or one asymmetric envelope on linear axes, with bounded tables and ASCII labels. No missing values, general functions, multiplots, arbitrary plot commands or inference of quantiles/confidence/coverage. Every SVG bound vertex is checked. PNG verification samples interiors at each row and midpoint and exteriors where observable, requiring at least one across the plot; it is not full raster equivalence. Conservative pixel-clearance rules refuse some legitimate thin, steep or near-border envelopes. The legend swatch and label have checked relative geometry; their pair is only constrained to the visible key row. Other label lengths have not been separately qualified in the isolated band proof. A captured file or table artifact is still parsed against the explicit header, finite numeric rows, units and range contract; kind alone does not establish compatible CSV. Subjective source-contract assessment, not an exhaustive native API measurement. Native availability, observed runtimes and source-bound qualification remain independent of both strength scores.

**Evidence:** [src/schemaxis/adaptors/gnuplot/adaptor.json](../../src/schemaxis/adaptors/gnuplot/adaptor.json), [src/schemaxis/adaptors/gnuplot/readiness.json](../../src/schemaxis/adaptors/gnuplot/readiness.json), [docs/gnuplot.md](../../docs/gnuplot.md), [verification/2026-10-24-gnuplot-allocation.md](../../verification/2026-10-24-gnuplot-allocation.md), [verification/2026-10-26-gnuplot-range-envelope.md](../../verification/2026-10-26-gnuplot-range-envelope.md).

Record version `2026-10-26.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app gnuplot`.

### godot

Static 3D primitive/import scenes, materials, lights, cameras and transform groups, plus captured-sheet forward-tag AnimatedSprite3D resources with declared frame durations and bounded headless playback.

**Whole-application denominator:** 2D/3D scenes, rendering/materials, gameplay scripting, input/UI, animation, physics, audio and export/deployment.

**Breadth rationale:** Scene assembly now includes one captured-sheet timed sprite slice with editable resources and checked headless playback. Most game-engine functions, general animation, gameplay, UI, physics and deployment remain absent, so whole-application breadth stays at the coarse 10% estimate.

**Abstraction rationale:** Named groups, assets and captured animation tags hide project, PackedScene and SpriteFrames plumbing. Authors still describe scene primitives, local transforms and supported clip intent; the existing 55% estimate is retained within this scene-publication family.

**Material limits:** Bounded scenes, self-contained glTF and one supported sprite-sheet metadata family. No authored scripts, gameplay, physics, GUI animation editing, general animation state machines or deployment. Animation is headless forward-tag playback at the fixed 1 ms process tick with an independently derived boundary tolerance. Clips whose planned observations cannot distinguish adjacent frames are refused; this does not certify real-time pacing, rendering or other process rates. Captured Aseprite producer observations can come from an older runtime; they do not qualify the latest Aseprite release. Native qualification and host source-contract scores are separate. Subjective source-contract assessment, not an exhaustive native API measurement. Original isolated host argv and an explicit floating-point rounding term remain disclosed verification limits in the dated note.

**Evidence:** [src/schemaxis/adaptors/godot/adaptor.json](../../src/schemaxis/adaptors/godot/adaptor.json), [src/schemaxis/adaptors/godot/readiness.json](../../src/schemaxis/adaptors/godot/readiness.json), [docs/godot.md](../../docs/godot.md), [verification/2026-10-24-godot-allocation.md](../../verification/2026-10-24-godot-allocation.md), [verification/2026-10-26-godot-animated-sprite.md](../../verification/2026-10-26-godot-animated-sprite.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app godot`.

### graphviz

Named directed dependency/feedback graphs with automatic TB/LR layout and editable DOT/SVG.

**Whole-application denominator:** Graph description, directed/undirected layout engines, constraints, clusters/ranks, node/edge styling and output formats.

**Breadth rationale:** Automatic directed graph publication covers a core family, but other engines, clusters, rich constraints and presentation features remain excluded.

**Abstraction rationale:** Named dependencies and direction hide DOT generation and native execution; richer task semantics and layout objectives remain manual.

**Material limits:** Two to 200 nodes; unique nonself edges; no clusters, authored DOT, URLs, HTML labels or images. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/graphviz/adaptor.json](../../src/schemaxis/adaptors/graphviz/adaptor.json), [src/schemaxis/adaptors/graphviz/readiness.json](../../src/schemaxis/adaptors/graphviz/readiness.json), [docs/graphviz.md](../../docs/graphviz.md), [verification/2026-10-24-graphviz-allocation.md](../../verification/2026-10-24-graphviz-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app graphviz`.

### hdf5

Typed path-addressed HDF5 intent: objects, storage, scales, links, edits, extracts, expectations, mesh fields and SWMR series.

**Whole-application denominator:** Files/drivers/format bounds, groups and links, typed datasets and attributes, selections, chunking/filters/fill, resizing, dimension scales, references and committed types, virtual and external storage, inspection, editing/repacking, SWMR, parallel MPI-IO, remote drivers, filter plugins, low-level property tuning and interoperable mesh/table handoffs.

**Breadth rationale:** Eight operations cover creation, adoption, extraction (memory-bounded streaming, typed where row filters, chunk indexes and local MPI parallel reads), editing/repack (including compound field writes and copyChunks direct chunk copies), comparison, XDMF mesh/field series, SWMR acquisition and local MPI-IO writes, with typed access tuning (chunk cache, sieve buffer, alignment, metadata block, page buffer), null-dataspace datasets, large attributes in creation order and verified NumPy, meshio and xarray handoffs. Remote ros3/S3, third-party filter plugins and multi-node MPI are absent; MPI is local to one machine by the accepted v1 scope.

**Abstraction rationale:** Users declare paths, types, units, scales, selections and edits rather than h5py calls; defaults choose layouts, and the host locates faults and simulates edits. Users still choose element widths, chunk shapes and filter options, which is appropriate for HDF5 but remains native-level detail.

**Material limits:** MPI-IO (parallelWrite, parallel extraction) runs on one local machine only, qualified with Open MPI 4.1.7 and 2-3 ranks; multi-node correctness and scaling are future work (docs/design/hdf5-multinode-mpi-backlog.md). Remote drivers and filter plugins are unavailable. Values independently compared literally up to 1,048,576 elements per file; larger files rely on digests of the h5py readback for unedited data and on h5dump hyperslab reads of selected or written regions. Some facts (UTF-8 attribute encoding, LZF/scale-offset presence, region references, non-native fill values) are observable only by the h5py readback, not h5dump XML; null dataspaces are confirmed from h5dump DDL headers. Compound/vlen bases are one level deep; dimension scales are one-dimensional; CSV extracts carry enum codes and no type metadata; chunk indexes and copyChunks cover gzip/shuffle/Fletcher-32 single-file layouts.

**Evidence:** [src/schemaxis/adaptors/hdf5/adaptor.json](../../src/schemaxis/adaptors/hdf5/adaptor.json), [src/schemaxis/adaptors/hdf5/readiness.json](../../src/schemaxis/adaptors/hdf5/readiness.json), [docs/hdf5.md](../../docs/hdf5.md), [verification/2026-11-05-hdf5-completion.md](../../verification/2026-11-05-hdf5-completion.md).

Record version `2026-11-05.8`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app hdf5`.

### ifcopenshell

Bounded GUID-linked IfcWall property and quantity schedule with explicit precedence, missingness and units, handed to a typed workbook.

**Whole-application denominator:** IFC reading and writing across schemas, entity and property families, geometry processing, units and placement, validation, classification, cost and scheduling utilities and conversion tools.

**Breadth rationale:** One IFC4 wall schedule with a small property and quantity subset exercises a tiny part of the library. Geometry, other classes, schemas and authoring are outside the integration.

**Abstraction rationale:** Authors name property and quantity columns and policies and receive a verified typed schedule without writing native code. They still decide which quantities are meaningful, supply the exact set names and judge whether the stored values are right; the workflow is a hypothesis without demonstrated customer demand.

**Material limits:** One ASCII IFC4 file, plain IfcWall only, IfcPropertySingleValue and three plain-SI quantity kinds; no geometry, other classes, schema versions, materials, relationships or authoring. Numbers and #ids anywhere in the file are held to a declared lexical budget (40 mantissa digits, exponent magnitude 400, 10 id digits) and must be valid STEP INTEGER or REAL text; larger exact decimals are unsupported. Unselected entities and geometry are unassessed. Agreement between IfcOpenShell and the independent reader shows both read the same stated values; it does not show the model, its quantities or the schedule are right for the building. The workflow is a hypothesis without demonstrated customer demand. Subjective source-contract assessment; no exhaustive API denominator supports these percentages.

**Evidence:** [src/schemaxis/adaptors/ifcopenshell/adaptor.json](../../src/schemaxis/adaptors/ifcopenshell/adaptor.json), [src/schemaxis/adaptors/ifcopenshell/readiness.json](../../src/schemaxis/adaptors/ifcopenshell/readiness.json), [docs/ifcopenshell.md](../../docs/ifcopenshell.md), [verification/2026-10-26-ifcopenshell-wall-schedule.md](../../verification/2026-10-26-ifcopenshell-wall-schedule.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app ifcopenshell`.

### imagej

Calibrated grayscale threshold-particle measurements or repeated named rectangular-region measurements across labelled frames, with explicit frame times and a typed workbook handoff.

**Whole-application denominator:** Image import/processing, filtering, segmentation, measurement, colour/stacks, ROI management, plugins and scientific visualisation.

**Breadth rationale:** The existing particle pipeline now also supports repeated named rectangular regions across declared grayscale frames. Both remain bounded measurement workflows; general image processing, segmentation, plugins and scientific visualisation are absent, so the coarse whole-application estimate remains 5%.

**Abstraction rationale:** Calibration, threshold/connectivity, particle-size intent and named frame/region/time decisions hide Java and ImageJ measurement plumbing. Users still define rectangular regions and measurement assumptions; the existing 80% estimate is retained within this measurement family.

**Material limits:** Closed bounded grayscale TIFF/PGM inputs. Repeated regions have explicit rectangles, frame times and common calibration; this is not object tracking, registration, segmentation, ROI-set import, colour processing or Fiji/plugin automation. Pixel values, counts and geometric calibration are checked within the declared rectangle workflow. Authored calibration/time and biological meaning are not independently established by those checks; observed jar hashes establish consistency rather than publisher authenticity. Frame dimensions/depth, aggregate pixel/byte/visit budgets and source alias constraints are enforced. Fractional means and nonunit calibrated areas remain numeric observations, with no uncertainty or acquisition-quality certificate. Subjective source-contract assessment, not an exhaustive native API measurement. Verification confidence, runtime availability and source-bound qualification remain separate.

**Evidence:** [src/schemaxis/adaptors/imagej/adaptor.json](../../src/schemaxis/adaptors/imagej/adaptor.json), [src/schemaxis/adaptors/imagej/readiness.json](../../src/schemaxis/adaptors/imagej/readiness.json), [docs/imagej.md](../../docs/imagej.md), [verification/2026-10-24-imagej-allocation.md](../../verification/2026-10-24-imagej-allocation.md), [verification/2026-10-26-imagej-regions.md](../../verification/2026-10-26-imagej-regions.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app imagej`.

### imagemagick

Exact PNG crop, integer magnification, quarter-turn rotation and indexed contact sheets.

**Whole-application denominator:** Raster import/export, transformations, compositing, colour, effects, text/drawing, animation and batch image preparation.

**Breadth rationale:** Common asset preparation is present but most formats, transforms, effects, text and colour workflows are excluded.

**Abstraction rationale:** Asset and sheet intent replaces command sequences, though crop rectangles and integer transforms remain procedural choices.

**Material limits:** RGB/RGBA8 PNG subset with bounded pixels; no ICC, palettes, 16-bit, general resampling, arbitrary options or delegates. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/imagemagick/adaptor.json](../../src/schemaxis/adaptors/imagemagick/adaptor.json), [src/schemaxis/adaptors/imagemagick/readiness.json](../../src/schemaxis/adaptors/imagemagick/readiness.json), [docs/imagemagick.md](../../docs/imagemagick.md), [verification/2026-10-24-imagemagick-allocation.md](../../verification/2026-10-24-imagemagick-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app imagemagick`.

### infozip

Selected publication files to a flat deterministic stored ZIP with an unsigned inventory.

**Whole-application denominator:** ZIP creation/update/extraction, compression, member selection, directory metadata, archive maintenance and compatibility.

**Breadth rationale:** A portable publication bundle is useful, but compression, extraction, updates, directories and most archive management are not supported.

**Abstraction rationale:** Named publication membership and a portable inventory hide ZIP details; the operation remains a thin packaging workflow.

**Material limits:** One to sixteen flat stored files; no compression, ZIP64, encryption, directories or source metadata preservation; inventory is unsigned. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/infozip/adaptor.json](../../src/schemaxis/adaptors/infozip/adaptor.json), [src/schemaxis/adaptors/infozip/readiness.json](../../src/schemaxis/adaptors/infozip/readiness.json), [docs/infozip.md](../../docs/infozip.md), [verification/2026-10-25-infozip-60.md](../../verification/2026-10-25-infozip-60.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app infozip`.

### inkscape

Technical block diagrams and intent-driven directed flow diagrams with declared layout requirements.

**Whole-application denominator:** Vector drawing/editing, shapes/paths, text, styles, layout, diagrams, raster/vector import and export.

**Breadth rationale:** Technical diagram publication is a narrow slice of general illustration and SVG editing.

**Abstraction rationale:** Dependencies can determine ranked layout and connectors, while measured layout requirements express outcomes; explicit block diagrams still need coordinates.

**Material limits:** Bounded boxes/links and left-to-right routing; no general SVG import, typography, arbitrary styling or routing optimiser; connector crossings are unassessed. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/inkscape/adaptor.json](../../src/schemaxis/adaptors/inkscape/adaptor.json), [src/schemaxis/adaptors/inkscape/readiness.json](../../src/schemaxis/adaptors/inkscape/readiness.json), [docs/inkscape.md](../../docs/inkscape.md), [verification/2026-10-24-inkscape-allocation.md](../../verification/2026-10-24-inkscape-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app inkscape`.

### kicad

Read-only saved-board inspection, design-rule checking and Excellon drill publication.

**Whole-application denominator:** Schematic capture, PCB layout/routing, libraries, design checks, manufacturing outputs and electronics project management.

**Breadth rationale:** Useful manufacturing review covers only a small portion of the suite; schematic, board authoring and most fabrication outputs are absent.

**Abstraction rationale:** Board checks and drill intent hide command and readback plumbing, but remain close to native tools and require a finished design.

**Material limits:** Bounded existing boards and through-via/drill subset; no board authoring, zone refill, schematic parity, Gerbers or placement outputs. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/kicad/adaptor.json](../../src/schemaxis/adaptors/kicad/adaptor.json), [src/schemaxis/adaptors/kicad/readiness.json](../../src/schemaxis/adaptors/kicad/readiness.json), [docs/kicad.md](../../docs/kicad.md), [verification/2026-10-16-kicad-completion.md](../../verification/2026-10-16-kicad-completion.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app kicad`.

### meshio

Strict ASCII linear triangle/tetra/eight-node-hexahedron VTU and legacy VTK volume interchange with explicit units and exact ordered topology/field preservation.

**Whole-application denominator:** Mesh format interchange, mixed/high-order cell topology, point/cell data and sets, time-series and format-specific metadata.

**Breadth rationale:** Hexahedral CAE volumes strengthen static interchange, but only two ASCII formats and a small topology/data subset are authorable; groups/sets, solver formats and temporal families remain absent. Breadth remains 10%.

**Abstraction rationale:** Explicit units, strict preservation, independently integrated volumes and useful verified handoffs remove procedural reader/writer code; users still manage format selection, field units and mesh-quality assessment. Abstraction remains 60%.

**Material limits:** ASCII linear triangle/tetra/eight-node-hex subset only; Jacobian sampling is not global validity proof. No compressed/binary data, broad solver formats, groups/sets, high-order or unsupported metadata. Editorial planning estimate; bounded native acceptance covers literal affine/warped fixtures and named controls, not an exhaustive native API denominator. Query qualification/runtime separately.

**Evidence:** [src/schemaxis/adaptors/meshio/adaptor.json](../../src/schemaxis/adaptors/meshio/adaptor.json), [src/schemaxis/adaptors/meshio/readiness.json](../../src/schemaxis/adaptors/meshio/readiness.json), [docs/meshio.md](../../docs/meshio.md), [verification/2026-10-24-meshio-allocation.md](../../verification/2026-10-24-meshio-allocation.md), [docs/meshio-hexahedron.md](../../docs/meshio-hexahedron.md), [verification/2026-11-04-meshio-completion.md](../../verification/2026-11-04-meshio-completion.md).

Record version `2026-11-04.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app meshio`.

### mupdf

Selected passive PDF pages to rendered PNGs, UTF-8 text and page geometry for review.

**Whole-application denominator:** Document interpretation/rendering, text/search, page manipulation, annotations/forms, editing, conversion and supported document formats.

**Breadth rationale:** Core PDF viewing/extraction functions are connected, but document editing, interaction and non-PDF formats are largely absent.

**Abstraction rationale:** Ordered review pages and DPI hide native invocation/readback, while pagination and rendering choices remain explicit.

**Material limits:** Bounded unencrypted passive PDF pages only; no OCR, editing, authored scripts or general viewer interactions; extracted text follows native content order. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/mupdf/adaptor.json](../../src/schemaxis/adaptors/mupdf/adaptor.json), [src/schemaxis/adaptors/mupdf/readiness.json](../../src/schemaxis/adaptors/mupdf/readiness.json), [docs/mupdf.md](../../docs/mupdf.md), [verification/2026-10-24-mupdf-allocation.md](../../verification/2026-10-24-mupdf-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app mupdf`.

### ngspice

Declared ideal linear networks with sampled voltage/gain/phase/current/power/loading intent and explicit phasor conventions.

**Whole-application denominator:** Circuit definition, device models, DC/AC/transient and other analyses, nonlinear devices, behavioural modelling and result exploration.

**Breadth rationale:** DC/AC and first-order RC workflows now include useful frequency-grid and electrical characterisation decisions. General transient, nonlinear device/model, noise, distortion and scripting families still exclude most upstream SPICE breadth.

**Abstraction rationale:** Network topology, units, log-grid density, passive sign, RMS/peak convention and performance bounds express circuit intent without native control scripts or manual table calculations. Derived quantities retain their native-voltage/native-source-current basis.

**Material limits:** Bounded ideal linear elements and one RC transient family; no semiconductors or arbitrary models/netlists; sampled acceptance is not a continuous-envelope guarantee. Editorial estimate of workflow breadth and abstraction, not an exhaustive native API denominator. Fresh bounded native electrical cases are recorded separately; qualification freshness and local runtime availability remain independent.

**Evidence:** [src/schemaxis/adaptors/ngspice/adaptor.json](../../src/schemaxis/adaptors/ngspice/adaptor.json), [src/schemaxis/adaptors/ngspice/readiness.json](../../src/schemaxis/adaptors/ngspice/readiness.json), [docs/ngspice.md](../../docs/ngspice.md), [verification/2026-10-25-ngspice-36.md](../../verification/2026-10-25-ngspice-36.md), [verification/2026-11-03-ngspice-characterisation.md](../../verification/2026-11-03-ngspice-characterisation.md).

Record version `2026-11-03.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app ngspice`.

### numpy

Unit-aware principal components of correlated numeric measurement channels with variance/reconstruction requirements.

**Whole-application denominator:** N-dimensional arrays, indexing/broadcasting, numerical ufuncs, linear algebra, FFT, statistics, random sampling and data interchange.

**Breadth rationale:** One PCA workflow covers a very small fraction of a general numerical array library; no breadth is inferred from matrix sizes or checks.

**Abstraction rationale:** Channels, units, retention goals and reconstruction decisions replace eigensolver and subspace plumbing with analysis intent.

**Material limits:** Bounded real numeric tables and PCA only; no missing values, general array programming, arbitrary linalg/FFT/statistical operations or causal interpretation. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/numpy/adaptor.json](../../src/schemaxis/adaptors/numpy/adaptor.json), [src/schemaxis/adaptors/numpy/readiness.json](../../src/schemaxis/adaptors/numpy/readiness.json), [docs/numpy.md](../../docs/numpy.md), [verification/2026-10-24-numpy-allocation.md](../../verification/2026-10-24-numpy-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app numpy`.

### octave

Real-valued 1D tables, signal transforms, fitted trends, integration/derivatives and resampling.

**Whole-application denominator:** Matrix/numerical programming, linear algebra, signal processing, optimisation, statistics, plotting and packages.

**Breadth rationale:** Several useful 1D numerical operations exist, but matrix programming, plotting and most numerical families/packages are absent.

**Abstraction rationale:** Declared analyses and labelled tables hide Octave code, while users still compose algorithm choices and sampling constraints.

**Material limits:** Real-valued bounded 1D scope only; no complex values, missing data, plotting or authored functions; FFT has uniform power-of-two sampling limits. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/octave/adaptor.json](../../src/schemaxis/adaptors/octave/adaptor.json), [src/schemaxis/adaptors/octave/readiness.json](../../src/schemaxis/adaptors/octave/readiness.json), [docs/numerical-analysis.md](../../docs/numerical-analysis.md), [verification/2026-10-24-octave-allocation.md](../../verification/2026-10-24-octave-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app octave`.

### openscad

Dimensioned mounting plates with hole patterns and annular spacers to editable source and checked faceted solids.

**Whole-application denominator:** Scripted constructive geometry, 2D profiles/extrusion, transformations, parameterisation, imports and mesh publication.

**Breadth rationale:** Two fabrication part families are useful but do not expose general constructive geometry or the modelling language.

**Abstraction rationale:** Fabrication dimensions, clearances and hole-pattern intent replace CSG scripts and topology plumbing within these part families.

**Material limits:** Bounded plate/spacer geometry and translations only; faceted surfaces, constrained hole separation and tessellation; no authored OpenSCAD language. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/openscad/adaptor.json](../../src/schemaxis/adaptors/openscad/adaptor.json), [src/schemaxis/adaptors/openscad/readiness.json](../../src/schemaxis/adaptors/openscad/readiness.json), [docs/openscad.md](../../docs/openscad.md), [verification/2026-10-24-openscad-allocation.md](../../verification/2026-10-24-openscad-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app openscad`.

### opensees

Planar pin-jointed small-strain elastic truss serviceability from node/member/load/measurement intent.

**Whole-application denominator:** Geometry/constraints, truss/frame/shell/solid elements, elastic/inelastic materials, static/nonlinear/dynamic/seismic/geotechnical analysis, response evaluation and reliability.

**Breadth rationale:** A complete bounded general planar elastic truss product covers editable structural networks, redundant mixed stiffness, signed nodal load response and measured serviceability decisions. Most OpenSees element/material and nonlinear/dynamic/geotechnical families remain explicitly excluded.

**Abstraction rationale:** Users author engineering geometry, Cartesian restraints, E/area, signed loads and named measured limits. The adaptor supplies solver construction, numbering, linear solution, native readback, independent direct stiffness/equilibrium, reconstruction and CSV/assessment handoff. General design optimisation and code compliance remain excluded.

**Material limits:** Small supported subset of a much larger structural/geotechnical application; no frame/solid/3D, nonlinear, buckling, plastic, transient, seismic or safety-certification claim. Native acceptance covers named serial fixtures and observed pinned engine/package; it does not establish arbitrary structure safety, MPI or exhaustive continuous-domain correctness. Subjective editorial whole-application and declared-workflow scores, separate from native qualification and runtime availability.

**Evidence:** [src/schemaxis/adaptors/opensees/adaptor.json](../../src/schemaxis/adaptors/opensees/adaptor.json), [src/schemaxis/adaptors/opensees/readiness.json](../../src/schemaxis/adaptors/opensees/readiness.json), [docs/opensees.md](../../docs/opensees.md), [verification/2026-11-04-opensees-completion.md](../../verification/2026-11-04-opensees-completion.md), [verification/2026-11-04-native-evidence-types.md](../../verification/2026-11-04-native-evidence-types.md).

Record version `2026-11-04.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app opensees`.

### oracle

Declared typed tables to inspect, load, relational report and atomic mutation workflows with independent verification.

**Whole-application denominator:** Connection/session, dictionary, scalar types, table definitions, loading, selection, joins/set operations, aggregation/analytics, typed expressions, mutation, transactions, schema evolution, LOBs, JSON, PL/SQL routines, object/collection/XML types, vector, spatial/graph/text, AQ, notifications, performance/observability, Thin/Thick and authentication, administration, other Oracle products.

**Breadth rationale:** Useful partial coverage across relational tables, reports, transactions and bounded document storage: CLOB/BLOB and native JSON with typed scalar extraction now join the existing shared table contract. Existing-table mutation has snapshot, idempotency and precommit verification. Major Oracle families remain unimplemented; this is an editorial estimate, not an API ratio.

**Abstraction rationale:** Shared typed tables and named relations/conditions/steps express relational and bounded document intent without SQL, scripts, driver code or transaction replay logic. Users still choose schema, keys, joins, paths and business preconditions.

**Material limits:** The whole application includes 24 retained capability families; none is claimed exhaustively covered. Native acceptance is bounded to the recorded Thin driver and Free server; registration freshness is reported independently. Streaming and empty LOBs, NCLOB/BFILE, advanced SQL/JSON, schema evolution, PL/SQL, vector, spatial/graph/text, AQ and other specialist families remain unimplemented.

**Evidence:** [src/schemaxis/adaptors/oracle/adaptor.json](../../src/schemaxis/adaptors/oracle/adaptor.json), [src/schemaxis/adaptors/oracle/readiness.json](../../src/schemaxis/adaptors/oracle/readiness.json), [docs/oracle.md](../../docs/oracle.md), [docs/design/oracle-coverage.md](../../docs/design/oracle-coverage.md), [verification/2026-11-03-oracle-completion.md](../../verification/2026-11-03-oracle-completion.md).

Record version `2026-11-03.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app oracle`.

### pandoc

Structured sections/tables/images and pinned transcript blocks, with ordered author and description declarations, to HTML, DOCX and optional EPUB 3.

**Whole-application denominator:** Document parsing/writing across formats, structured documents, citations, mathematics, templates/styles, filters and publication metadata.

**Breadth rationale:** A coherent small-report pipeline spans HTML, DOCX and EPUB with checked author/description declarations, but broad readers, citations, maths, styling and document transformations remain absent. The additional metadata stays within a small publication slice, so the coarse whole-application estimate remains 15%.

**Abstraction rationale:** Report structure, transcript provenance and consistent publication metadata express intent without markup or writer commands; supported author/description choices remain bounded and style/editorial decisions remain restricted. Abstraction remains 80% within this explicitly expanded report slice.

**Material limits:** Closed bounded report model; no authored markup, templates, filters, bibliography or broad input formats; EPUBCheck is a separate workflow, not implicit certification. Authors and descriptions are declarations, not verified identity or review; fixed native reader behaviour is version-bound. Subjective review of current source contracts and bounded evidence, not an exhaustive native API measurement. Native results cover named cases; source-bound qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/pandoc/adaptor.json](../../src/schemaxis/adaptors/pandoc/adaptor.json), [src/schemaxis/adaptors/pandoc/readiness.json](../../src/schemaxis/adaptors/pandoc/readiness.json), [docs/pandoc.md](../../docs/pandoc.md), [verification/2026-10-25-whispercpp-54.md](../../verification/2026-10-25-whispercpp-54.md), [verification/2026-10-26-pandoc-62.md](../../verification/2026-10-26-pandoc-62.md).

Record version `2026-10-25.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app pandoc`.

### paraview

Curated scientific data pipelines and the typed generated native catalogue with publication and inspection.

**Whole-application denominator:** Scientific dataset readers/sources, filters, arrays/temporal analysis, representations, rendering, writers and parallel/interactive visualisation.

**Breadth rationale:** Fifty is the rubric's several-central-families-with-substantial-gaps judgement. A connected data-analysis loop is authorable across dataset ingest, geometric/field transforms, sampling/temporal analysis, camera/representation setup and checked data/image publication. These useful families span more than one isolated task; they are not weighted by the number of proxy bindings. Major parts of whole ParaView remain incomplete: interactive/client-server sessions and linked selections, full view/animation lifecycles, in-situ/remote workflows, specialised domains and outputs beyond the verified publication subsets. Uneven depth across these families makes this estimate low-confidence; generated constructor coverage neither establishes workflow completeness nor native qualification.

**Abstraction rationale:** Curated operations express domain tasks, but much generated catalogue authoring remains typed native properties; volume of bindings does not make intent abstraction uniformly high.

**Material limits:** Generated declarations do not establish every reader/domain on real data; no arbitrary Python or programmable filters; MPI and specialised readers need their own qualification. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/paraview/adaptor.json](../../src/schemaxis/adaptors/paraview/adaptor.json), [src/schemaxis/adaptors/paraview/readiness.json](../../src/schemaxis/adaptors/paraview/readiness.json), [docs/paraview-catalogue.md](../../docs/paraview-catalogue.md), [verification/2026-10-25-paraview-37.md](../../verification/2026-10-25-paraview-37.md), [src/schemaxis/adaptors/paraview/filters.py](../../src/schemaxis/adaptors/paraview/filters.py).

Record version `2026-10-28.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app paraview`.

### premiere

Read-only source identity and named multi-track frame-layout/coverage contracts.

**Whole-application denominator:** Media ingest, timeline editing, audio, effects/colour, titles/captions, rendering/export and collaborative project workflows.

**Breadth rationale:** Timeline inspection is a very narrow portion of an editor and does not author, render or export a movie.

**Abstraction rationale:** Named coverage requirements and exact layout decisions hide native tick/asynchrony handling, but users must build the project and declare detailed expected clips.

**Material limits:** Native qualification remains pending; host-tested contracts are not a demonstrated Premiere run. No native editing/export, audio, captions, effects, source-byte or rendered-content checks. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/premiere/adaptor.json](../../src/schemaxis/adaptors/premiere/adaptor.json), [src/schemaxis/adaptors/premiere/readiness.json](../../src/schemaxis/adaptors/premiere/readiness.json), [docs/premiere.md](../../docs/premiere.md), [verification/2026-10-17-premiere-completion.md](../../verification/2026-10-17-premiere-completion.md).

Record version `2026-10-25.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app premiere`.

### prusaslicer

One closed STL to bounded single-extruder FFF G-code with explicit profiles and layer/temperature/filament inspection.

**Whole-application denominator:** Mesh preparation/placement, printer/material/print profiles, slicing, supports, modifiers, multi-material workflows, preview and printer integration.

**Breadth rationale:** The central slice-to-G-code workflow is present, but advanced support/modifier/material and printer integration features are missing.

**Abstraction rationale:** A print profile and independently interpreted layer/filament deliverables hide CLI/G-code plumbing, while many machine/material decisions remain explicit.

**Material limits:** No supports, variable layers, custom/postprocessed G-code, printer upload or physical print/safety claim; one extruder and generic Marlin 2 profile. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/prusaslicer/adaptor.json](../../src/schemaxis/adaptors/prusaslicer/adaptor.json), [src/schemaxis/adaptors/prusaslicer/readiness.json](../../src/schemaxis/adaptors/prusaslicer/readiness.json), [docs/prusaslicer.md](../../docs/prusaslicer.md), [verification/2026-10-24-prusaslicer-allocation.md](../../verification/2026-10-24-prusaslicer-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app prusaslicer`.

### pyproj

Continuous WGS84 ellipsoidal route stationing with labelled leg/station tables and GeoJSON.

**Whole-application denominator:** CRS representation, coordinate/vertical transformations, geodesics, grids, projections and operation/database discovery.

**Breadth rationale:** One geodesic stationing task uses little of the CRS/projection/transformation library.

**Abstraction rationale:** Route spacing, endpoint policy and physical distances express survey intent without geodesic loop/interpolation code.

**Material limits:** WGS84 geographic routes in the declared latitude/length domain only; no antimeridian, general CRS transforms, vertical datums or grid selection. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/pyproj/adaptor.json](../../src/schemaxis/adaptors/pyproj/adaptor.json), [src/schemaxis/adaptors/pyproj/readiness.json](../../src/schemaxis/adaptors/pyproj/readiness.json), [docs/pyproj.md](../../docs/pyproj.md), [verification/2026-10-24-pyproj-allocation.md](../../verification/2026-10-24-pyproj-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app pyproj`.

### qgis

Bounded 2D vector reprojection/buffering/clipping, polygon centroids, typed selection and grouped attribute summaries.

**Whole-application denominator:** Vector/raster data management, CRS, geometry processing, analysis, styling/maps, editing, databases and plugins.

**Breadth rationale:** Several connected vector analysis and table workflows are useful, but raster analysis, cartography, broad editing and plugin capabilities are missing.

**Abstraction rationale:** Metric geometry intent, typed selections, grouped quantities and explicit requirements remove many native steps; CRS and geometry choices still need expertise.

**Material limits:** Bounded 2D GeoJSON/GeoPackage scope; annotation-only units, regenerated feature IDs and restricted aggregates; previews are not georeferenced rasters. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/qgis/adaptor.json](../../src/schemaxis/adaptors/qgis/adaptor.json), [src/schemaxis/adaptors/qgis/readiness.json](../../src/schemaxis/adaptors/qgis/readiness.json), [docs/qgis.md](../../docs/qgis.md), [verification/2026-10-24-qgis-allocation.md](../../verification/2026-10-24-qgis-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app qgis`.

### qpdf

Ordered PDF review packets with repeated source pages and clockwise quarter-turn rotations.

**Whole-application denominator:** PDF page assembly, inspection/repair, object/stream transformation, encryption, optimisation and structural metadata management.

**Breadth rationale:** Page assembly is a central useful family, but object transformation, encryption, repair and optimisation remain out of scope.

**Abstraction rationale:** Named sources and ordered page selections avoid native command details; publication structure and page choice remain mostly manual.

**Material limits:** Captured unencrypted passive PDFs only; forms, signatures, layers, tags, annotations/actions and unsupported transparency are refused, not preserved. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/qpdf/adaptor.json](../../src/schemaxis/adaptors/qpdf/adaptor.json), [src/schemaxis/adaptors/qpdf/readiness.json](../../src/schemaxis/adaptors/qpdf/readiness.json), [docs/qpdf.md](../../docs/qpdf.md), [verification/2026-10-24-qpdf-allocation.md](../../verification/2026-10-24-qpdf-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app qpdf`.

### r

Full-rank numeric OLS calibration with held-out predictions, coefficient uncertainty, named requirements and declared new-observation mean-response confidence or individual prediction intervals.

**Whole-application denominator:** Statistical programming, data manipulation, model families/inference, visualisation, time series and extensible packages.

**Breadth rationale:** Explicit new-observation confidence and prediction intervals deepen the existing OLS calibration family. General statistical programming, data manipulation, other models and plotting remain absent, so the whole-application estimate remains 5%.

**Abstraction rationale:** Predictor units, calibration and inference intent, held-out acceptance requirements and explicit interval meaning hide formulas, fitting, reopen and interval plumbing. Users retain responsibility for the regression assumptions and scope; the existing 85% estimate remains within this OLS workflow family.

**Material limits:** Small full-rank numeric OLS with explicit predictors; no categorical/missing data, interactions, weights, arbitrary formulas or general R programs. Intervals rely on the stated linear, independent, normal and homoscedastic error assumptions. Mean-response confidence and individual future-observation intervals have different meanings. Neither establishes model validity, causality, future generalisation or empirical coverage; extrapolation is labelled rather than certified. Rows whose interval types cannot be distinguished within the actual verification allowance are refused before native work. Eight-predictor interval tables exceed the bounded Gnuplot consumer column limit. Subjective source-contract assessment, not an exhaustive native API measurement. Live lifecycle evidence is stage bounded, with no claim about the instruction position inside predict.lm; qualification and runtime availability remain separate.

**Evidence:** [src/schemaxis/adaptors/r/adaptor.json](../../src/schemaxis/adaptors/r/adaptor.json), [src/schemaxis/adaptors/r/readiness.json](../../src/schemaxis/adaptors/r/readiness.json), [docs/r.md](../../docs/r.md), [verification/2026-10-24-r-allocation.md](../../verification/2026-10-24-r-allocation.md), [verification/2026-10-26-r-prediction.md](../../verification/2026-10-26-r-prediction.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app r`.

### shotcut

Explicit source trims, order and repetitions to one editable silent timeline and FFV1 render.

**Whole-application denominator:** Timeline/media editing, multi-track composition, audio, transitions, effects, colour, captions and export.

**Breadth rationale:** Basic timeline assembly is useful, but the majority of a full editor remains inaccessible.

**Abstraction rationale:** Named assets and frame ranges hide MLT setup and rendering, but the user still describes individual cuts and order.

**Material limits:** One contiguous silent track; no gaps, transitions, audio, subtitles, scaling or rotation; bounded sources and frames. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/shotcut/adaptor.json](../../src/schemaxis/adaptors/shotcut/adaptor.json), [src/schemaxis/adaptors/shotcut/readiness.json](../../src/schemaxis/adaptors/shotcut/readiness.json), [docs/shotcut.md](../../docs/shotcut.md), [verification/2026-10-24-shotcut-allocation.md](../../verification/2026-10-24-shotcut-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app shotcut`.

### sox

Frame-accurate PCM16 excerpt assembly/fades, speech conformance, explicit peak normalisation and two-track gain/placement mixing with a declared duration policy.

**Whole-application denominator:** Audio format conversion, resampling/channel handling, editing/assembly, mixing, filtering/effects, level processing and devices.

**Breadth rationale:** Connected audio preparation now includes a bounded two-track narration/background overlay alongside assembly, speech conformance and peak normalisation. Broad formats, arbitrary effects, general multitrack work and device workflows remain absent; narrow PCM16 and frame bounds keep this within the existing coarse 25% whole-application estimate.

**Abstraction rationale:** Clip placement, speech-input conformance, target peak levels and two-track composition hide native effect chains. Authors still choose exact sample placements, gains and restricted duration policies; the estimate remains 75% within this named bounded slice.

**Material limits:** Bounded PCM16 files only; mix span is at most 262144 frames (about 5.5 seconds at 48 kHz), so full-length podcast mixing is outside this slice. No more than two simultaneous tracks, crossfade, arbitrary effects, loudness/RMS/true-peak goals or sound-device interaction. Subjective review of source contracts and bounded evidence, not an exhaustive native API measurement. Named native cases and source-bound qualification are separate from these strength estimates.

**Evidence:** [src/schemaxis/adaptors/sox/adaptor.json](../../src/schemaxis/adaptors/sox/adaptor.json), [src/schemaxis/adaptors/sox/readiness.json](../../src/schemaxis/adaptors/sox/readiness.json), [docs/sox.md](../../docs/sox.md), [verification/2026-10-25-sox-58.md](../../verification/2026-10-25-sox-58.md), [verification/2026-10-26-sox-mix.md](../../verification/2026-10-26-sox-mix.md).

Record version `2026-10-25.2`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app sox`.

### sqlite

Fresh typed related tables to one foreign-key join/filter/group summary and database publication.

**Whole-application denominator:** Relational schema/queries, transactions, updates, indexes, constraints, existing databases and engine management.

**Breadth rationale:** Useful relational preparation and aggregation cover a limited slice of a general SQL engine; updates and existing database work are absent.

**Abstraction rationale:** Typed tables, relations and grouped measures replace authored SQL, while users still select keys and closed relational operations.

**Material limits:** One to four bounded fresh tables, one FK inner join and SUM/COUNT filter subset; no existing databases, arbitrary SQL, transactions or extensions. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/sqlite/adaptor.json](../../src/schemaxis/adaptors/sqlite/adaptor.json), [src/schemaxis/adaptors/sqlite/readiness.json](../../src/schemaxis/adaptors/sqlite/readiness.json), [docs/sqlite.md](../../docs/sqlite.md), [verification/2026-10-24-sqlite-allocation.md](../../verification/2026-10-24-sqlite-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app sqlite`.

### sympy

Exact rational univariate real-root isolation with multiplicities and rational-width goals.

**Whole-application denominator:** Symbolic expressions, simplification, algebra/equations, calculus, matrices, discrete mathematics, geometry and code generation.

**Breadth rationale:** One polynomial task covers a very small part of symbolic mathematics; symbolic calculus and broader solving are absent.

**Abstraction rationale:** A polynomial and interval-width goal hide isolation algorithms and exact-arithmetic certificates with task-level outputs.

**Material limits:** Degree 1-12 rational polynomials only; bounded coefficients/width, no complex roots, multivariate systems or arbitrary symbolic expressions. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/sympy/adaptor.json](../../src/schemaxis/adaptors/sympy/adaptor.json), [src/schemaxis/adaptors/sympy/readiness.json](../../src/schemaxis/adaptors/sympy/readiness.json), [docs/sympy.md](../../docs/sympy.md), [verification/2026-10-24-sympy-allocation.md](../../verification/2026-10-24-sympy-allocation.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app sympy`.

### tesseract

Bounded one-page OCR into explicitly unreviewed text, word boxes and native confidence, with captured image/model inputs and optional declared origin bound to pixels.

**Whole-application denominator:** Image and page recognition, layout and segmentation choices, languages and models, structured document outputs, configuration and vocabulary, orientation and script detection, and model training and evaluation.

**Breadth rationale:** A single English-model page recognition path provides useful text and word boxes, but most language, layout, output-format, configuration and training capabilities remain outside the integration. The estimate concerns the whole application rather than recognition accuracy on its small qualification corpus.

**Abstraction rationale:** A recognition operation produces an inspectable review trail and hides subprocess configuration and TSV parsing. Authors still supply a pinned model file, choose a native-derived segmentation mode and compose document rendering or later correction themselves; the interface does not decide whether recognised words are correct.

**Material limits:** One opaque RGB8 non-interlaced PNG and one explicitly pinned LSTM model, exposed as English; the model's language content is not established by its filename or hash. The interface has two segmentation modes and bounded image/model sizes; no general PDF, multipage, layout, handwriting, correction or training workflow. Native confidence is uncalibrated, output is a machine draft, and pixel consistency does not certify text truth or human review. Native availability and source-bound qualification remain separate readiness facts. Subjective source-contract assessment rounded to five points; no exhaustive API denominator or recognition-accuracy measurement supports these percentages.

**Evidence:** [src/schemaxis/adaptors/tesseract/adaptor.json](../../src/schemaxis/adaptors/tesseract/adaptor.json), [src/schemaxis/adaptors/tesseract/readiness.json](../../src/schemaxis/adaptors/tesseract/readiness.json), [docs/tesseract.md](../../docs/tesseract.md), [verification/2026-10-25-tesseract-63.md](../../verification/2026-10-25-tesseract-63.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app tesseract`.

### webp

Bounded lossless PNG/WebP round trip and opaque lossy encoding with numeric error/byte requirements.

**Whole-application denominator:** Static/animated WebP encoding and decoding, alpha/colour, quality/compression controls, metadata and container operations.

**Breadth rationale:** Core static encode/decode families are covered, but animation, broad container/metadata and encoder controls are absent.

**Abstraction rationale:** Lossless preservation or explicit error/size goals express web-asset intent; quality choices and numeric rather than perceptual criteria remain user decisions.

**Material limits:** Closed PNG/static simple WebP subsets; lossy is opaque only; no animation/metadata/colour management or perceptual quality guarantee. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/webp/adaptor.json](../../src/schemaxis/adaptors/webp/adaptor.json), [src/schemaxis/adaptors/webp/readiness.json](../../src/schemaxis/adaptors/webp/readiness.json), [docs/webp.md](../../docs/webp.md), [verification/2026-10-25-webp-51.md](../../verification/2026-10-25-webp-51.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app webp`.

### whispercpp

Bounded speech transcription to draft timed text, explicit human correction versions and host-only caption line layout.

**Whole-application denominator:** Local speech recognition, language/translation, segmentation/timing, decoding controls, streaming, VAD and model/runtime choices.

**Breadth rationale:** Offline transcription and cue-length targets cover a central family; translation, language detection, VAD, diarisation and streaming are absent. Host editorial routes improve the chain without increasing native API breadth.

**Abstraction rationale:** Draft/review provenance, per-cue correction ledgers and explicit caption-layout goals express connected editorial work; accuracy and review remain human decisions.

**Material limits:** CPU PCM16 mono 16 kHz bounded transcription; accuracy is not certified. Correction/caption routes launch no recogniser and have no native qualification; Unicode code-point layout is not readability certification. Editorial estimate from current contracts, guidance and completion evidence; no exhaustive native API denominator or new native acceptance was measured for this assessment. Qualification and runtime availability must be queried separately.

**Evidence:** [src/schemaxis/adaptors/whispercpp/adaptor.json](../../src/schemaxis/adaptors/whispercpp/adaptor.json), [src/schemaxis/adaptors/whispercpp/readiness.json](../../src/schemaxis/adaptors/whispercpp/readiness.json), [docs/whispercpp.md](../../docs/whispercpp.md), [verification/2026-10-25-whispercpp-32.md](../../verification/2026-10-25-whispercpp-32.md), [verification/2026-10-25-whispercpp-38.md](../../verification/2026-10-25-whispercpp-38.md), [verification/2026-10-25-whispercpp-45.md](../../verification/2026-10-25-whispercpp-45.md), [verification/2026-10-25-whispercpp-54.md](../../verification/2026-10-25-whispercpp-54.md), [verification/2026-10-25-whispercpp-59.md](../../verification/2026-10-25-whispercpp-59.md).

Record version `2026-10-25.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app whispercpp`.

### xarray

Bounded local classic-NetCDF measurement-cube selection into a one-axis unweighted mean profile with declared variable, layout/unit assertions, coordinate ranges, missing-data policy and numeric plotting handoff.

**Whole-application denominator:** Labelled arrays and datasets, indexing and selection, named-dimension arithmetic and reduction, alignment and merging, grouping/resampling/rolling, coordinate and calendar handling, storage backends, lazy/distributed execution and scientific inspection.

**Breadth rationale:** One classic-NetCDF variable can be selected by named numeric coordinate ranges and reduced to an unweighted mean profile. Most labelled-array operations, dataset combinations, scientific metadata conventions and storage/execution backends remain outside this integration; a coarse 5% whole-application estimate reflects that narrow breadth.

**Abstraction rationale:** Authors declare coordinates, selection, retained dimension and missingness rather than write array code or native serialization. Independent finite-array checks and a typed profile publication support reuse, but users still supply storage-order and unit assertions, choose the missing policy and arrange scientifically appropriate weighting or plotting outside the supported slice.

**Material limits:** One bounded CDF-1 classic-NetCDF cube and one variable with strictly increasing numeric coordinates; selected retained profiles have at most 2048 points. No general CF/calendar, packed values, NetCDF4/HDF5, Zarr, remote or Dask workflow. The reduction is an unweighted mean with explicit skip, propagate or refuse policy and conditioning refusal. No inferred units, alignment, interpolation, measurement uncertainty or scientific-validity certification. Dimension-list order is a deliberate storage-layout assertion, although reduction uses named dimensions. A plotting consumer has its own row, finite-value, header and unit contract; artifact kind alone does not establish compatibility. Subjective source-contract estimates rounded to five points, not exhaustive API measurements. Native runtime availability and source-bound qualification remain separate facts.

**Evidence:** [src/schemaxis/adaptors/xarray/adaptor.json](../../src/schemaxis/adaptors/xarray/adaptor.json), [src/schemaxis/adaptors/xarray/readiness.json](../../src/schemaxis/adaptors/xarray/readiness.json), [docs/xarray.md](../../docs/xarray.md), [verification/2026-10-25-xarray-completion.md](../../verification/2026-10-25-xarray-completion.md).

Record version `2026-10-26.1`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app xarray`.

### zstandard

Captured content, reusable dictionaries, earlier snapshots and checked compressed streams.

**Whole-application denominator:** Compression controls, compatibility codecs, streaming and frames, dictionaries, reference deltas, inspection and performance selection.

**Breadth rationale:** Twelve typed tasks cover the reviewed bounded stable CLI inventory, including all five codecs, finite streaming and frames, advanced matching/scheduling/adaptive controls, trained/raw dictionaries, deltas, benchmarks and recursive/named file sets. Source-bound native, full host/Studio and clean installed-product acceptance pass. The existing conservative editorial score is retained; it is not an API ratio or acceptance gate.

**Abstraction rationale:** Task-level intents hide CLI process and provenance boilerplate while expert compression overrides remain available.

**Material limits:** Accepted stable CLI content scope, with documented resource caps; library ABI/application embedding and unbounded persistent pipe service are separate product boundaries. No public release is claimed. Adaptive content and frame policy are verified, but the historical native level schedule cannot be reconstructed. Recorded profile wall time is observational; later verification proves content and size, not historical timing. File sets retain relative names and bytes; filesystem permissions, ownership and timestamps are not archived.

**Evidence:** [src/schemaxis/adaptors/zstandard/adaptor.json](../../src/schemaxis/adaptors/zstandard/adaptor.json), [src/schemaxis/adaptors/zstandard/readiness.json](../../src/schemaxis/adaptors/zstandard/readiness.json), [docs/zstandard.md](../../docs/zstandard.md), [verification/2026-11-05-zstandard.md](../../verification/2026-11-05-zstandard.md).

Record version `2026-11-05.5`; rubric `schemaxis.strength-rubric/1`. Query: `schemaxis assessments --app zstandard`.
