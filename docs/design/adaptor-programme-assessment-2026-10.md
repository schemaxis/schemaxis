# Adaptor programme assessment — October 2026

Assessment date: 17 October 2026. This is the initial Task C selection and Task D
candidate decision record, not a delivery or qualification announcement. The
baseline is the 20 application providers in the working tree at the start of the
programme (`main`, starting commit `fe31946`, including existing uncommitted work).
Implementation by other programme workers can make this baseline historical.

**Historical assessment:** the [current scored assessment service](../adaptor-assessments.md)
and [generated inventory](../generated/adaptor-assessments.md) supersede the
non-percentage policy and inventory below. This dated record is preserved.

## Scope and method

The comparison separates three questions:

1. **Useful API/workflow coverage:** does the adaptor expose the connected native
   capabilities needed for the stated user goal, including inputs, meaningful
   changes, native persistence and usable outputs? The relevant scope is defined
   in the table; an entire application API is not an achievable denominator.
2. **Conceptual abstraction:** can an author state a purpose, structure and
   requirements, or must the author assemble native primitives and supply most
   domain reasoning? Direct CLI-like controls can be appropriate for a direct
   transformation tool. A graph is not automatically a better abstraction.
3. **Verification/confidence:** what evidence independently checks the result,
   what was actually exercised, and how confidently can this assessment describe
   it? Availability and qualification are separate from capability strength.

No coverage percentages, operation-count scores or application popularity scores
are used. “Narrow” concerns breadth of useful workflows; it does not mean that a
bounded scientific workflow is poorly implemented. “Strong within slice” is not
an assertion of general native API coverage. Selection is a comparative design
judgement with ties, using both primary dimensions and practical workflow gaps.

Read sources include the [completion checklist](../adaptor-completion.md),
[adaptor boundary contract](../adaptors.md), [strengthening acceptance
bar](adaptor-strengthening-2026-10.md), [candidate roadmap](adaptor-candidates.md),
all 20 manifests and readiness contexts, corresponding declarations/planners,
representative native mapping/verifiers and tests, registered qualification
receipts, and the [16 October integration record](../../verification/2026-10-16-architecture-integration.md).
Representative retained KiCad output was inspected: its independently derived
30 × 20 mm outline, six holes, diameter/plating groups and publication manifest
illustrate a semantic check beyond process exit. Retained FFmpeg, Godot, Aseprite,
QGIS and Cantera receipt cases were inspected for their expectations and integrity
probes. Historical results are not newly executed checks.

Every current application is eligible for assessment. ParaView is assessed only
as a general scientific visualisation application; existing format compatibility
is preserved. No CFD solver or CFD-specific application suite is selected. The
roadmap's excluded CFD execution row is explicitly disregarded.

## Existing applications: separate assessment axes

“Recorded native” below means a bounded receipt or dated qualification record
exists. Source freshness must be recomputed after integration; the existence of
`qualification.json` does not establish that today's source is qualified. The
five integration routes noted as newly checked on 16 October have stronger recent
evidence, but shared changes can invalidate that freshness too. No native run was
started as part of this inventory.

| Application and relevant workflow/API scope | Useful API/workflow coverage at baseline | Conceptual abstraction | Verification evidence and assessment confidence |
| --- | --- | --- | --- |
| Aseprite — editable sprite assets, layers/cels, timed animation and imported raster assets; [official Lua API](https://www.aseprite.org/api/) | Narrow authoring slice: new RGB sprites, normal layers, integer shapes, palette, frames and tags; sheets publish well, but existing-image import/edit is absent. | Mostly a linear native mutation recipe. Layer/frame/tag names help, but pixels/rectangles/circles leave asset preparation to the author. Selected for strengthening. | Fresh native reopen plus independent integer raster/compositing model and sheet timing; recorded 1.3.17.2 cases. High confidence in the declared boundary; broad sprite modes/effects unassessed. [Code](../../src/schemaxis/adaptors/aseprite/adaptor.py), [guide](../aseprite.md). |
| Blender — scripted geometry/material/modifier scenes, import/export, repeat renders; [official Python API](https://docs.blender.org/api/current/) | Relatively connected slice: primitives/profiles, meshes and modifiers, material/camera/light scenes, saved-scene render groups and geometry handoffs. Rigging, animation and general Blender editing remain outside it. | Declarative geometry dependencies and explicit scenes/resources; prepare/render separation expresses repeated publication intent. Some options remain native-like. | Native snapshots, bounds/material/render readback and saved scenes; bounded historical qualification. High implementation confidence, medium upstream-comparison confidence because the live API page failed to fetch in this review. [Operations](../../src/schemaxis/adaptors/blender/operations.py), [extended mapping](../../src/schemaxis/adaptors/blender/extended_native.py). |
| Calc — numeric result workbooks, recalculation, summary formulas and interchange; [SpreadsheetDocument API](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1sheet_1_1SpreadsheetDocument.html) | Narrow numeric-only table/workbook slice, with CSV import, summary workbooks and ODS/XLSX round trips. Strings, styles, arbitrary formulas and general editing are absent. | Strong within numerical reporting: named cell limits and weighted reconciliations make the intended decision explicit. | Independent formulas/caches/data in both formats, native recalc/reopen and failure requirements. Historical native receipt. High confidence within finite numeric tables. [Workbook](../../src/schemaxis/adaptors/calc/workbook.py), [requirements](../../src/schemaxis/adaptors/calc/requirements.py), [guide](../calc.md). |
| CalculiX — structural beam response, refinement and acceptance; [official solver manual](https://www.dhondt.de/ccx_2.23.pdf) | Very narrow application breadth: one rectangular isotropic small-strain cantilever family. Yet the complete bounded workflow includes mesh generation, solve, two refinement directions, measurement and decision. | Strong domain intent: geometry/material/load/requirements derive native decks; users need not author elements and constraints. | Independent beam theory, force/moment equilibrium, interior stress and fresh exact-deck execution; recorded native cases. High confidence in this family; no general FEA claim. [Beam implementation](../../src/schemaxis/adaptors/calculix/beam.py), [guide](../calculix.md). |
| Cantera — thermodynamic states, equilibrium and closed homogeneous reactors; [Python module reference](https://cantera.org/stable/python/index.html) | Connected but intentionally mechanism-specific: frozen states, TP/HP equilibrium and constant-pressure/volume adiabatic histories. General mechanisms, transport, walls/inlets and flames are absent. | Strong state/experiment vocabulary, units, composition basis, sampled histories and explicit ignition-delay criterion. | Pinned mechanism, independent thermodynamics/kinetics/conservation and integrator; fresh integration qualification reported for 3.2.0. High confidence within the named hydrogen mechanism. [Thermo](../../src/schemaxis/adaptors/cantera/thermo.py), [kinetics](../../src/schemaxis/adaptors/cantera/kinetics.py), [guide](../cantera.md). |
| FFmpeg — prepare, transform and publish inspectable timed media; [official CLI reference](https://ffmpeg.org/ffmpeg.html) | Narrow inputs: PNG sequences and sprite sheets to H.264/FFV1. No existing-video source processing or audio; central media preparation workflows therefore stop at the adaptor boundary. | Good direct conversion interface and deliverable policy for dimensions/timing/bytes/error. No need to force a general operation graph; input workflow coverage is the weakness. Selected. | Full native decode against captured source RGB, probe/timing readback, independent policy and tamper checks. Recorded FFmpeg 9.0.2 cases; no audio evidence. High confidence. [Implementation](../../src/schemaxis/adaptors/ffmpeg/adaptor.py), [deliverable verification](../../verification/2026-10-10-ffmpeg-deliverables.md). |
| FreeCAD — parametric single-solid construction, finishing, measurements and assemblies; [public API](https://freecad.github.io/API/) | Connected modelling subset: primitives/booleans, profiles and sketch features, selection-based finishing, measurements/design study, STEP/STL/FCStd and a separate assembly route. General workbenches and sketch constraints are not claimed. | Relatively strong: dependency graph, geometric edge intent/cardinality, measured targets and explicit assembly relations go beyond raw Part calls. | Independent geometry, analytic selections/measurements and native reopen; historical per-route receipts. High implementation confidence; upstream Doxygen landing content is sparse, so medium confidence in exhaustive API comparison. [Features](../../src/schemaxis/adaptors/freecad/features.py), [sketches](../../src/schemaxis/adaptors/freecad/sketch_features.py), [assemblies](../../src/schemaxis/adaptors/freecad/assembly.py). |
| Gmsh — solid-to-volume mesh with meaningful groups and quality requirements; [official API manual](https://gmsh.info/doc/texinfo/) | Narrow one-solid linear tetrahedral meshing, but includes STEP/box sources, planar named groups, boundary sizing, quality and bounded refinement. High order/multiple solids/general face selection absent. | Strong within slice: named boundaries, resolution rules and explicit quality/target decisions, rather than authored entity tags. | Independent mesh topology, positive cell volumes, CAD volume agreement and quality; native recorded 4.15.2 cases. High confidence. [Mesh](../../src/schemaxis/adaptors/gmsh/mesh.py), [quality](../../src/schemaxis/adaptors/gmsh/quality.py), [guide](../gmsh.md). |
| Godot — editable scene composition, reusable object groups/resources and runtime publication; [Node3D](https://docs.godotengine.org/en/stable/classes/class_node3d.html) | Static flat scenes: primitive/imported meshes, material, lights, camera and sprites, with additional transformed primitives/lights in code. No authored parent hierarchy or reusable groups, animation or physics scenario. | Native scene-node recipe with explicit typed links, but no way to express a component group moved as one unit. Selected. | Fresh PackedScene reopen, ownership/local primitive/material/light/camera readback, independent transforms/bounds; recorded 4.7.2 native cases. Graphical preview qualification is distinct. High confidence; guide omits some extra code declarations, so code governs. [Planner](../../src/schemaxis/adaptors/godot/adaptor.py), [native scripts](../../src/schemaxis/adaptors/godot/scripts.py), [guide](../godot.md). |
| ImageJ — calibrated threshold segmentation and particle measurement; [public Java API](https://imagej.net/ij/developer/api/) | Narrow single-plane 8/16-bit workflow, but covers threshold, connectivity/holes/edge/area rules, measured particles and numeric handoff. Stacks/plugins/general segmentation absent. | Strong measurement intent and calibration; the author states how particles are defined rather than writes a macro. | Independent pixels/components/measurements, native ResultsTable and image state; recent 1.54t integration cases including 16-bit/negative probes. High implementation confidence; live API page retrieval failed, so method-level upstream review is incomplete. [Program](../../src/schemaxis/adaptors/imagej/program.py), [image checks](../../src/schemaxis/adaptors/imagej/images.py), [guide](../imagej.md). |
| Inkscape — editable technical diagrams and measured publication; [CLI documentation](https://inkscape.org/doc/inkscape-man.html) | Bounded block/dependency diagrams, native text extent queries and PNG/SVG export; no general imported-SVG editing. | Strong diagram intent: `flowDiagram` derives DAG ranks/lanes, with named boxes/links and explicit fit/layout failure. | Independent geometry/layout, native text bounds and raster checks; historical 1.4.4 evidence. High code confidence, medium live-document review confidence (403 from upstream manual). [Layout](../../src/schemaxis/adaptors/inkscape/layout.py), [guide](../inkscape.md). |
| KiCad — inspect/check/manufacture existing boards; [official CLI](https://docs.kicad.org/10.0/en/cli/cli.html) | Bounded two-layer board inspection, DRC and Excellon drill output; no board authoring, Gerber or schematic/netlist link. Narrow but connected fabrication check. | Useful manufacturing decisions from declared limits with geometry/DRC observations, rather than opaque command forwarding. | Independent board geometry/holes versus native stats/drills and selected DRC predictions; recent 10.0.7 integration cases. High confidence; not all DRC rules independently certified. [Board](../../src/schemaxis/adaptors/kicad/board.py), [drill](../../src/schemaxis/adaptors/kicad/drill.py), [guide](../kicad.md). |
| ngspice — declared linear circuit frequency/DC/step studies; [official manual](https://ngspice.sourceforge.io/docs/ngspice-html-manual/manual.xhtml) | Connected ideal linear DC, AC RLC and first-order RC transient studies. Nonlinear devices/models and general transient networks absent. | Strong circuit/response intent with named voltage/gain limits; native netlist generated. Finite-sample claims are explicit. | Independent nodal/analytic references, native values and worst-sample margins; recorded ngspice 47 cases. High implementation confidence, medium live-document confidence because full manual fetch failed. [Circuit](../../src/schemaxis/adaptors/ngspice/circuit.py), [performance](../../src/schemaxis/adaptors/ngspice/performance.py), [guide](../ngspice.md). |
| Octave — real sampled-signal analysis and numeric table handoffs; [official manual](https://docs.octave.org/latest/) | Connected bounded 1D data derivation, integration/differentiation, interpolation, FFT and fitted trends. No arbitrary language/program execution, complex/missing data or plots. | Useful named analysis dependencies, but units and most goal/acceptance choices remain with author. A legitimate next strengthening candidate after this tranche. | Independent arithmetic/reference implementation, intermediate/native tables, historical native receipts. High confidence in bounded signal slice. [Worker](../../src/schemaxis/adaptors/octave/worker.py), [independent reference](../../src/schemaxis/adaptors/octave/reference.py). |
| ParaView — general scientific reader/filter/render/export pipelines; [official simple API](https://www.paraview.org/paraview-docs/latest/python/paraview.simple.html) | Broadest extensible catalogue plus curated operations, arrays/times/geometry/measurement publication. Generated bindings do not mean every specialised filter/reader is qualified. | Strong declarative pipeline expresses dependencies, explicit associations/time/loss policies. Domain requirements still need authored meaning. | Native geometry/array/XML and bounded reduction checks; historical serial/MPI scopes differ. No native invocation in this assessment. High confidence in architecture, medium confidence for arbitrary generated operation correctness. [Filters](../../src/schemaxis/adaptors/paraview/filters.py), [catalogue](../../src/schemaxis/adaptors/paraview/catalogue.py). |
| Premiere Pro — sequence inspection, editing intent and durable project observations; [official UXP API](https://developer.adobe.com/premiere-pro/uxp/) | Very narrow: read-only existing one-track silent contiguous sequence contract. No editing/export, gapped/multiple video tracks or audio. The weakness is the missing workflows, regardless of runtime availability. | Clear declarative timing/source requirements for the existing inspection slice, but all sequence construction is external. Selected for bounded inspection expansion; do not imply editor parity. | Real companion exercised with Node contract doubles, nonce/hash/exact ticks and stale observations tested; no native qualification or registered receipt. High confidence in host-only boundary; native behaviour confidence explicitly low. [Companion](../../src/schemaxis/adaptors/premiere/uxp/observer.js), [tests](../../tests/unit/test_premiere.py), [guide](../premiere.md). |
| PrusaSlicer — explicit FFF model/profile to inspectable G-code; [upstream CLI source](https://github.com/prusa3d/PrusaSlicer/tree/master/src/CLI) | Bounded one-part, one-extruder generic Marlin profile, infill/layers/material settings and measured output. Supports/presets/printer control absent. | Strong fabrication intent and requirements; avoids raw flags/custom G-code. | Independent STL/G-code replay, layer/envelope/temp/filament evidence; recent native 2.9.6 integration cases. High confidence in bounded profile; no physical print-quality claim. [Profile](../../src/schemaxis/adaptors/prusaslicer/profile.py), [replay](../../src/schemaxis/adaptors/prusaslicer/gcode.py), [guide](../prusaslicer.md). |
| QGIS — derive useful vector GIS results with attributes and explicit CRS; [PyQGIS cookbook](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/) | Narrow vector chain: read, reproject, metric buffer, rectangle clip, centroid; lacks attribute selection/group summaries and spatial analytical decisions. No raster support. | A dependency graph of native geometric operations. CRS/loss rules help, but the author supplies most feature-selection/summary intent. Selected. | Native build versus fresh reopen of geometries/attributes/project, captured sources and hashes; historical 3.34.4 cases. High confidence in declared scope; independent domain expectations are shallower than the recent measurement adaptors. [Planner](../../src/schemaxis/adaptors/qgis/adaptor.py), [worker](../../src/schemaxis/adaptors/qgis/native_worker.py), [guide](../qgis.md). |
| R — calibrated numeric linear modelling and interpretable fit/inference decisions; [stats::lm](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/lm.html) | Narrow numeric additive unweighted regression, held-out predictions and classical coefficient inference. No arbitrary formulas/packages, categorical terms or prediction intervals. | Strong modelling intent, explicit assumptions, meaningful named fit/prediction/interval requirements. | Independent scaled QR/conditioning/distribution checks, fresh RDS reopen; recent 4.6.1 integration cases. High confidence in bounded regression; no causal/generalisation claim. [Worker](../../src/schemaxis/adaptors/r/worker.py), [reference](../../src/schemaxis/adaptors/r/reference.py), [guide](../r.md). |
| Shotcut — editable multi-source frame-range editorial assembly; [MLT documentation](https://www.mltframework.org/docs/) | Narrow silent one-track cuts, but multiple named captured sources, trim/reorder/repeat, portable editable project and native render form a connected workflow. Audio/transitions/multitrack absent. | Clear editorial range/asset intent; less manual than a chain of raw MLT producer/playlist commands. | Original/reloaded native renders, every decoded frame versus source selection and precise timing/profile evidence; historical native MLT/FFmpeg cases. High confidence within silent cuts. [Implementation](../../src/schemaxis/adaptors/shotcut/adaptor.py), [guide](../shotcut.md). |

## Five strengthening assignments

The selected five are **Premiere, Godot, Aseprite, QGIS and FFmpeg**. Premiere has
the thinnest connected workflow coverage; Godot and Aseprite expose useful native
primitives but omit central composition/input concepts; QGIS lacks attribute
analytical intent; FFmpeg has good deliverable abstraction but a restricted input
family. Their gaps impede useful asset and result pipelines. This is not a claim
that their existing verifiers are weaker than all others.

Calc, CalculiX and ImageJ also have deliberately narrow breadth. They rank above
this tranche on domain abstraction and end-to-end decision completeness, not by
pretending they cover their full native APIs. Octave and Shotcut are close
follow-on candidates. The alternatives and rationale make the unavoidable
judgement in “weakest” explicit.

Each responsible worker owns its adaptor, focused examples/tests/guide,
capabilities/guidance/readiness and a dated completion review. Shared registry,
reference generation and integration belong to the programme supervisor. Read
`adaptor-completion.md` first; maintain optional-feature decisions and complete
all checklist items for the changed slice. New native changes require a fresh
baseline and changed-input native case where the runtime exists, hostile/misleading
evidence probes, cancellation/timeout retention, authored/effective binding and
workflow reuse checks. Host tests must never be described as native checks.

| Assignment | Bounded useful improvement brief | Required result/evidence | Complexity and routing |
| --- | --- | --- | --- |
| Godot | Add named transform groups and parent links for bounded static object assemblies. Define local position/rotation/scale and parent-before-child or explicit acyclic ordering; preserve existing flat documents. Exclude animation and physics. | Native PackedScene save/reopen must preserve parent identity and owner. Independently compute composed transforms and world bounds for a rotated/scaled nested assembly; test orphan/cycle/type rejection, changed ancestor transform, forged hierarchy/readback and legacy flat scene. | Complex transform/ownership semantics: Astra high design/review, Sol implementation. Official Node3D/Node/PackedScene semantics govern; do not merely compare two identical native receipts. |
| Aseprite | Import bounded captured PNG imagery into a named cel/layer/frame with explicit placement and colour/alpha limits; optionally derive an animation from declared repeated image placements only if the import contract is complete. Preserve procedural operations. | Independent decoded source pixels and compositing must match fresh-reopened editable cel, preview and sheet. Retain capture/digests, handle transparent pixels, reject clipping/unsupported PNG/colour modes; altered input, frame duration, cel and metadata must fail. | Moderate input/pixel contract; Sol high, stronger review if alpha/blending scope expands. Closed API: Image, Sprite, Cel; no authored Lua. |
| QGIS | Add bounded attribute selection plus grouped numeric summaries/explicit feature requirements. Choose literal typed comparisons and named aggregate columns instead of arbitrary expressions; preserve CRS and captured original attributes. Avoid broad spatial joins until their semantics are separately designed. | Independent small GeoJSON fixture checks selection/null/type treatment, group membership, sums/counts and requirements; native table/GeoPackage/project reload. Changed threshold/group variant and invalid fields/types/CRS fail clearly; no runtime absence used as ranking evidence. | Moderate; Sol high, Astra review if extending to geometry overlays/CRS transformations beyond current slice. Use QgsFeature/QgsFields/typed provider APIs. |
| FFmpeg | Add existing silent video input to bounded frame-range publication, or explicit PCM audio publication/muxing after choosing one complete workflow. Prefer a native-verified bounded source-video transform if that integrates cleanly with existing frame verification; do not add arbitrary filter strings. | Capture full source and decoded reference; explicit timebase/selection/loss policy; independently compare every selected output frame or PCM sample and stream metadata, including changed trim, unsupported timestamps/rates and forged evidence. Keep image/sheet regression cases. | Moderate; Sol high with review of timestamp and stream-selection semantics. Direct declarative options are appropriate. |
| Premiere | Expand read-only inspection to declared named track/range layout with explicit timeline positions/gaps and track identity, or equally substantive documented UXP sequence requirements. Preserve exact tick strings, stable observation binding and unsupported-state checks. Avoid unverified native editing/export promises. | Actual companion source exercised by meaningful host doubles with multiple tracks/gaps, changed source/track/timing and concurrent/stale observations; exact plan/response/retained-evidence tests. Native acceptance requires an actual supported Windows/macOS Premiere environment and remains pending otherwise. | Complex state/asynchrony/versioned API: Astra design/review. Sol can implement bounded verified host plumbing. Missing native runtime is a verification limitation; native-qualified status must remain false. |

Worker scopes may be narrowed or changed for demonstrated native constraints, but
must still add a substantive user workflow and retain their explicit acceptance
criteria. Existing successful records should not be rewritten to simulate freshness.

## Expansion queue and initial ten

The following applications/libraries were all absent from the baseline manifests.
They are distinct engines/providers, not aliases, version variants or plugins
counted as extra applications. Public libraries are eligible native providers
under the existing roadmap. Each new provider must run its optional dependencies
in a separate process and preserve dependency-free host planning/discovery.

Ordering favours useful new output/data domains, independently inspectable native
results, API suitability and bounded installation effort. Overlap is stated so
that breadth does not become the goal by itself. The first ten are selected;
remaining entries are the continuing queue. Machine-specific probes and full
worker briefs are retained only in ignored programme evidence. No runtime was
installed during this assessment.

| Rank | Candidate / proposed first workflow | Value and overlap | Complexity, installation and maintenance constraint |
| --- | --- | --- | --- |
| 1 | [Pandoc](https://pandoc.org/MANUAL.html): structured report sections/tables/local images to HTML and DOCX, semantic AST readback | New document reporting from existing results; complements Calc | Moderate. Portable binary; format-loss policy and AST versioning matter. |
| 2 | [Gnuplot](https://gnuplot.sourceforge.net/docs_6.0/Gnuplot_6.pdf): named numeric series/error bars with units/ranges to SVG/PNG | Plot publication beyond Octave analysis/Calc tables | Moderate. Headless terminals/font availability; generate trusted commands, not authored scripts. |
| 3 | [SQLite](https://www.sqlite.org/cli.html): typed table import, declared joins/group summaries to a new database and exports | Durable relational result collections; distinct from numeric CSV | Moderate. Isolated engine/CLI; nulls, constraints, stable ordering and engine version must be explicit. |
| 4 | [MuPDF](https://mupdf.readthedocs.io/en/latest/tools/mutool-draw.html): selected captured PDF pages to images/text with page geometry | Adds document ingestion/rendering; complements Pandoc | Moderate. Native binary; AGPL/commercial terms need ordinary review; no runtime redistribution assumed. |
| 5 | [ImageMagick](https://imagemagick.org/command-line-processing/): bounded crop/resize/rotation/contact-sheet raster assets | Broader raster preparation than sprite editing | Moderate. Portable binary/source; closed operator set, codec/delegate/resource policy. |
| 6 | [SoX](https://sourceforge.net/p/sox/code/ci/master/tree/sox.1): PCM trim/concatenate/gain/fade with clipping requirements | Adds audio assets to currently silent media workflows | Moderate. Isolated source build; exact sample units, quantisation/dither policy and component licences. |
| 7 | [Graphviz](https://www.graphviz.org/docs/outputs/plain/): named graph/cluster/rank layout to editable DOT/SVG/PNG | Overlaps Inkscape dependency diagrams; adds native graph/cluster layouts | Moderate. Layout/font plugins; native geometry must be assessed, not inferred from SVG existence. |
| 8 | [meshio](https://github.com/nschloe/meshio): selected linear mesh interchange preserving arrays/sets or rejecting loss | Extends Gmsh-specific export; independent format engine | Complex. Isolated NumPy/meshio; cell order/set/association semantics and maintenance burden. |
| 9 | [GDAL](https://gdal.org/en/stable/programs/gdalwarp.html): explicit raster grids/CRS/no-data/resampling to GeoTIFF | Raster capability distinct from current QGIS vector route | Complex. Isolated GDAL/PROJ/data; grids, axis order, driver/version dependencies. |
| 10 | [OpenSCAD](https://openscad.org/documentation.html): parameterised enclosure/plate/hole pattern to editable SCAD/STL | Overlaps FreeCAD CSG; adds native fabrication recipe workflow | Complex. Portable/source runtime with CGAL/Qt; constructive topology/tessellation must be independently checked. |
| 11 | [QPDF](https://qpdf.readthedocs.io/en/stable/cli.html): selected/reordered merged PDF pages | Structural document assembly complements MuPDF rendering | Moderate. Native binary; page identity/content/metadata semantics. |
| 12 | [Apache Arrow](https://arrow.apache.org/docs/python/parquet.html): typed nullable CSV/Parquet exchange | Avoids numeric-only CSV limits | Complex. Isolated wheel; schema/null/timezone compatibility, not just read success. |
| 13 | [xarray](https://docs.xarray.dev/en/stable/user-guide/io.html): named-dimension subset/reduction to NetCDF | New multidimensional scientific dataset model | Complex. Isolated backends; dimensions/coordinates/units/masks and codec provenance. |
| 14 | [CloudCompare](https://www.cloudcompare.org/doc/wiki/index.php/Command_line_mode): known rigid registration and cloud distances | New metrology scope; complements CAD/GIS | Complex. Large native/Qt dependencies; convergence and distance meaning require analytic fixtures. |
| 15 | [IfcOpenShell](https://docs.ifcopenshell.org/ifcopenshell-python.html): IFC selection and GUID-linked property/quantity schedule | BIM semantics absent from current CAD route; Bonsai would not count separately | Complex. Isolated geometry/schema engine; unit/property inheritance and schema versions. |
| 16 | [3D Slicer](https://slicer.readthedocs.io/en/latest/developer_guide/python_faq.html): synthetic calibrated volume threshold to labelmap/surface | Adds 3D volume segmentation beyond ImageJ's plane analysis | Complex. Large runtime and possible offscreen display; research fixtures, no clinical validation claim. |
| 17 | [Tesseract](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html): clean page OCR to text/word boxes/confidence | OCR differs from extracting embedded PDF text | Moderate. Binary plus language models; observed accuracy is fixture-specific. |
| 18 | [ExifTool](https://exiftool.org/exiftool_pod.html): captured metadata inspection/selected-tag removal on copies | Adds provenance/privacy preparation without changing pixels | Moderate. Perl script runtime; format-specific tag meaning and original preservation. |
| 19 | [Open Babel](https://openbabel.org/docs/Command-line_tools/babel.html): bounded molecule interchange/formula checks | Molecular structure domain distinct from reaction histories | Complex. Isolated chemistry engine; stereochemistry/charge/format-loss qualification. |
| 20 | [dcm2niix](https://github.com/rordenlab/dcm2niix): synthetic DICOM series to NIfTI/sidecars | Volume conversion complements segmentation | Complex. Native binary; affine/scaling/series grouping checked independently; no anonymisation assumption. |
| 21 | [OpenModelica](https://openmodelica.org/doc/OpenModelicaUsersGuide/latest/scripting_api.html): fixed mass-spring-damper response | Distinct non-fluid system dynamics; excludes CFD and fluid application slices | Complex. Compiler/library dependencies; analytic response/energy/time sampling and portability. |
| 22 | [SuiteSparse](https://github.com/DrTimothyAldenDavis/SuiteSparse): explicit sparse backend SPD solve | Numerical provider overlapping Octave, with explicit sparse semantics | Complex. Per-package licences/builds; residual alone cannot establish accuracy for ill-conditioned systems. |

Audacity remains a future feasibility topic rather than an initial choice because
SoX offers a smaller deterministic audio-processing boundary. Aliza remains
unselected pending a documented supported automation boundary/edition. DWSIM and
Gazebo are deferred for larger runtime/state/physics verification costs. Neither
native absence nor application popularity alone determines those priorities.

## Initial-batch native acceptance briefs

Common delivery: one responsible agent per application, all completion-checklist
materials, a realistic editable starting document, meaningful rejected input,
closed validation and located faults, independent baseline/changed-input native
cases, bounded resources and failure retention, tamper/misleading-result probes,
workflow handoff/reuse where declared, upstream record and precise qualification
limits. New native runtimes belong in ignored evidence; never change a user's
PATH or existing installations. The supervisor integrates shared generated
references/Help and verifies packaging after the wave.

- **Pandoc:** constrain a structured authored report model to headings, text,
  simple tables and local images. Fresh native DOCX-to-AST readback and independent
  OOXML/HTML checks must preserve order, cell text, heading levels and media
  relationships. Reject features beyond the loss policy. Latest official release
  source reviewed reports [3.12.1 on 7 October 2026](https://pandoc.org/releases.html);
  older available binaries do not satisfy latest-stable qualification.
- **Gnuplot:** explicitly select series columns, labels/units, ranges/log policy
  and error bars; independently check expected point coordinates and series data
  in native SVG/plot output, visible labels and PNG dimensions. Change data/range
  and exercise invalid log values. Terminal/font behaviour is part of the runtime.
  Official downloads identify stable major 6.0; resolve the current patch first.
- **SQLite:** generate a new database from captured typed tables and closed
  relational operations, never arbitrary SQL. A fresh read-only connection plus
  independent row-by-row join/group arithmetic must check results, key constraints,
  type/null semantics and ordering. Prohibit extension loading and writes to
  source databases. Python's native SQLite binding is an execution option only;
  its engine version must meet the recorded target, not inherit a Python version.
- **MuPDF:** use captured bounded unencrypted PDFs with explicit pages, rotation,
  crop and DPI; inspect page boxes and text as well as raster geometry. Synthetic
  coloured/text pages provide independent region/text expectations. Changed DPI
  and page order must produce correspondingly changed results. Installed older
  runtimes are feasibility evidence only; resolve current official release.
- **ImageMagick:** constrain raster formats/operators, dimensions and delegate
  access. Verify synthetic colour-grid pixels exactly for lossless crop/integer
  rotate/nearest resize/contact sheets; state alpha/colour-depth policy. Native
  identify and full decode must match independent pixel expectations. No arbitrary
  option strings or delegates. Resolve stable version from official distribution.
- **SoX:** PCM WAV only initially, explicit sample-index ranges, channels,
  concatenation, gain/fade and peak/clipping requirements. An independent host WAV
  reader reconstructs each expected sample and quantisation tolerance; native
  information and fresh decode cross-check frames/rate/channels. Declare whether
  dither is disabled or supported. No sound-device interaction or arbitrary effects.
- **Graphviz:** bounded named nodes/edges/clusters and rank/orientation constraints,
  generate escaped DOT. Parse native `plain` geometry and independently check
  identity, bounds and declared rank/order constraints, then SVG labels and raster
  content. A changed cluster/rank case must exercise more than file hashes. This
  is native graph layout, not another count for the existing Inkscape adaptor.
- **meshio:** select exact input/output formats and linear cell types first.
  Fresh readback and independent parsers must compare points/connectivity,
  point/cell arrays, associations and named-set mappings modulo explicitly allowed
  ordering. Reject any unsupported loss, mixed cells or tags; test altered arrays
  and negative/degenerate cells. Official releases list
  [v5.3.5](https://github.com/nschloe/meshio/releases); recheck when installing.
- **GDAL:** one captured single-band GeoTIFF, explicit target CRS, extent,
  dimensions/resolution, no-data and resampling. Independently compute analytic
  grid values for identity/nearest cases; verify target grid/affine/axis/CRS and
  meaningful reprojection bounds via native fresh readback. Record PROJ data/grid
  dependencies. Stable documentation currently identifies
  [3.13.3](https://gdal.org/en/stable/); resolve current bugfix before installation.
- **OpenSCAD:** author fabrication intent (plate/enclosure, hole pattern, wall and
  clearance dimensions) and generate trusted SCAD. Independently check mesh
  closure/orientation, bounds, volume and hole geometry, not triangle counts only.
  Re-render the retained editable SCAD; change hole/size parameters and reject
  impossible wall/overlap cases. Select an official stable release explicitly;
  development snapshots must not silently substitute for stable.

Pandoc, Gnuplot, SQLite, MuPDF, ImageMagick, SoX and Graphviz suit Sol at high
reasoning with focussed review. meshio, GDAL and OpenSCAD require Astra design and
independent semantic/geometry review, with Sol implementation pieces if useful.
Luna is suitable for narrow extraction/checklist support, not ownership of these
complete state/format contracts. Actual model availability and quota handling
remain the supervisor's responsibility.

## Evidence and review limits

Local ignored programme evidence contains the machine-readable ranked queue,
read-only command/module probes, version observations and durable checkpoint.
Installed native availability was probed without installation or PATH changes;
absence from PATH is not proof an application is absent from the entire machine.
Only the probed search scope is known. No existing app was penalised for absence.
No serial, graphical, MPI or native qualification is claimed from these probes.

Primary official documents were opened on the assessment date. Some endpoints
returned access/fetch errors (notably Blender, ImageJ, Inkscape, the ngspice manual,
and some candidate documentation). Their URLs identify the intended sources;
those failed reads are explicitly not successful method-level API validation.
Existing code/guides and reachable official indices support the bounded
assessment; each implementation worker must read the method-level public API it
uses and resolve latest stable release/data/format constraints before claiming
native qualification. Newer official API docs do not retroactively qualify an
older recorded runtime.

This inventory does not run the complete host suite, recertify retained outputs,
install runtimes or implement any adaptor. Those are separate programme tasks.
