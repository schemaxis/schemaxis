# Candidate adaptors, conversion and workflow templates

Updated: 2026-10-10. Status: design direction and candidate backlog.

This document records the design discussion about broadening Schemaxis beyond
its current application coverage. Candidate operations, converters and templates
below are proposals unless explicitly linked to existing implementation. Their
presence here does not advertise an executable capability or promise delivery.

## Direction

Prefer free or inexpensive tools, documented automation interfaces, inspectable
outputs and useful connections to existing adaptors. Retain the existing ability
to post-process compatible OpenFOAM-format case data; CFD case preparation and
solver execution are a separate future track.

Select additions by the useful workflows they enable. Each new adaptor should
ship with one bounded, verified workflow and an editable JSON starting point.
Build reusable operations underneath those workflows so users can assemble
different pipelines. A library or command-line utility can be a provider even
when it has no desktop interface.

Current coverage includes ParaView, Blender, FreeCAD, Godot, Aseprite, FFmpeg, Inkscape, Shotcut,
QGIS, Gmsh, CalculiX, Cantera, ngspice, Octave, R and Calc, plus experimental
Premiere sequence inspection. These are bounded adaptors, not complete coverage
of the applications. See the [README](../../README.md),
[adaptor contract](../adaptors.md) and [CFD guide](../cfd-guide.md).

## Candidate catalogue

Priority labels are recommendations, not scheduled commitments:

- **Near:** a strong candidate for a bounded feasibility investigation next.
- **Next:** valuable expansion after the first connections are established.
- **Explore:** retain on the map; resolve automation or demand questions first.

The linked upstream projects are sources for their native capabilities. Proposed
Schemaxis slices and priorities are design judgments. Free/open-source availability
does not by itself establish redistribution terms or integration readiness.

| Area | Candidate | Priority | Proposed first slice and useful connection |
| --- | --- | --- | --- |
| Meshing | [Gmsh](https://gmsh.info/doc/texinfo/) | Qualified first slice | [FreeCAD STEP → Gmsh → ParaView](../gmsh.md): one solid, linear tetrahedra, authored volume, planar face and remainder groups with verified MSH/VTU. Arbitrary/nonplanar selection, high-order meshes and solver setup remain candidates. |
| Structural analysis | [CalculiX](https://calculix.de/) | Qualified first slice | [Rectangular elastic cantilevers](../calculix.md) with explicit SI material/load intent, separate axial/transverse refinement, native force/moment equilibrium, beam-theory and interior stress checks. [Stress tables into Calc](../beam-workbook.md) are qualified; general geometry, imported Gmsh groups and ParaView handoffs remain candidates. |
| Circuits | [ngspice](https://ngspice.sourceforge.io/) | Qualified first slice | [Declared DC networks, AC RLC responses and first-order RC transients](../ngspice.md), independent nodal/analytic checks, named sampled voltage/gain requirements and numeric tables into Calc. KiCad import, nonlinear models, general transients and continuous/all-tolerance guarantees remain candidates. |
| PCB design | [KiCad](https://www.kicad.org/about/kicad/) | Next | Inspect an existing board, run supported checks and export manufacturing/mechanical artifacts; investigate authoring separately. |
| Medical imaging | [3D Slicer](https://www.slicer.org/) | Near | Import a volume, apply a bounded segmentation, measure and export surfaces; connect to Blender and later meshing. Initial scope is research workflows. |
| DICOM inspection | [Aliza](https://www.aliza-dicom-viewer.com/software/aliza-ms-dicom-viewer) | Explore | Inspect series, metadata and views. Establish supported automation, edition and price before choosing an adaptor boundary. |
| Scientific imaging | [Fiji/ImageJ](https://imagej.net/software/fiji/) | Near | Threshold and measure particles in a calibrated image; export measurements to Calc or later R. Useful across biology and materials research. |
| Fabrication | [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer) | Near | Slice geometry with a declared printer/material profile; publish G-code and estimates. Physical printer control is a separate capability. |
| Architecture and construction | [Bonsai](https://bonsaibim.org/) | Next | Inspect IFC components and quantities, then bounded model edits and drawings; investigate reuse of the Blender runtime without losing IFC semantics. |
| System dynamics and controls | [OpenModelica](https://openmodelica.org/) | Next | Parameterise a known model, simulate and compare response curves; later introduce connected mechanical/electrical/thermal systems. |
| Robotics | [Gazebo](https://gazebosim.org/libs/sim/) | Next | Load a declared world/robot, run a bounded scenario and inspect sensor/state outputs. |
| Process engineering | [DWSIM](https://dwsim.org/) | Next | Parameterise a small flowsheet and publish stream/equipment results; independently check selected mass and energy balances. |
| Reaction chemistry | [Cantera](https://cantera.org/stable/examples/python/index.html) | Qualified first slice | [Ideal-gas h2o2 thermodynamic and TP/HP equilibrium sweeps](../cantera.md), independently checked properties, composition and conservation; numeric tables into Calc. Homogeneous reactor time histories and broader mechanisms remain candidates. |
| Sparse numerical computing | [SuiteSparse](https://github.com/DrTimothyAldenDavis/SuiteSparse) | Next | Import a sparse matrix and right-hand side, solve with an explicitly selected compatible backend and publish residual diagnostics. |
| Surveying and inspection | [CloudCompare](https://www.cloudcompare.org/presentation.html) | Next | Register scans and measure cloud-to-cloud or cloud-to-mesh distances; connect with QGIS and CAD. |
| Technical illustration | [Inkscape](https://inkscape.org/acerca-de/) | Qualified first slice | [Named technical diagrams](../inkscape.md), editable SVG, native geometry/text-fit checks and measured PNG publication. General imported-document editing and arbitrary routing remain candidates. |
| Video editing | [Shotcut](https://www.shotcut.org/) | Bounded native slice | [Named assets and frame-range timelines](../shotcut.md), editable MLT projects, native engine reload/render and independent decoded-frame comparisons. GUI edit roundtrips, audio, transitions and colour management remain candidates. |
| Commercial video editing | [Adobe Premiere Pro](https://developer.adobe.com/premiere-pro/uxp/) | Native environment needed | [Experimental read-only sequence inspection](../premiere.md) and its UXP companion check declared timing, profile and clip-placement requirements. Windows/macOS native acceptance is still required; editing/export remain candidates. |
| Statistics | [R](https://www.r-project.org/about.html) | Qualified first slice | [Bounded numeric additive regression](../r.md), independent QR checks, fresh native-model readback, named training/held-out requirements and a numeric-table handoff to Calc. Categorical terms, inference, plots and arbitrary packages/formulas remain candidates. |
| Audio | [Audacity](https://www.audacityteam.org/) | Explore | Investigate repeatable processing and editable audio projects; complement existing FFmpeg media outputs. |
| Molecular modelling | [Avogadro](https://avogadro.cc/) | Explore | Investigate molecule construction, inspection and exports; distinguish molecular structure from reaction/process simulation. |
| CFD execution | OpenFOAM | Explore | Bounded case setup, meshing and solver execution before integrated ParaView publication; select and qualify a specific distribution/release when there is a concrete execution workflow. |

## Cantera and SuiteSparse

Cantera complements DWSIM: its chemistry, thermodynamics and transport capabilities
support reaction-focused studies, whereas the proposed DWSIM slice concerns plant
flowsheets and equipment. Cantera's documented examples include reactor networks
and one-dimensional flames, which provide meaningful acceptance cases.

The first thermodynamic and TP/HP equilibrium slice is qualified; next consider a homogeneous
reactor or explicitly qualified additional mechanisms. Retain mechanism files and hashes, phase/species identities, composition
basis, units, initial conditions and solver tolerances. Define any ignition-delay
criterion explicitly. Check conservation and reference cases; process completion
alone does not validate the chemistry. Flame-speed studies can follow. Exporting
Cantera data does not imply that a CFD solver accepts the mechanism or physical model:
that would require a separate, qualified translation.

SuiteSparse is a collection of sparse numerical libraries, not a desktop app or
one universal solver. Its packages include UMFPACK for sparse LU, CHOLMOD for
sparse Cholesky and SPQR for sparse QR. Treat it as an optional native numerical
provider; assess reuse through an existing numerical runtime before introducing
a dedicated worker. Record the actual selected package/backend in either case.

A first slice should accept bounded Matrix Market data and explicit matrix
properties, solve a suitable system and publish the solution plus a normalised
residual. Distinguish general square, positive-definite and least-squares problems;
reject unsupported types and singular failures clearly. Bound dimensions/nonzeros
and possible factorisation memory; preserve sparse storage. A small residual is
not proof of accuracy for an ill-conditioned system. Do not add arbitrary native
calls to authored JSON or make SuiteSparse a dependency of host-side planning.

## CFD: explicit provider boundaries

Separate three capabilities in discovery, templates and qualification:

1. **Prepare:** create/edit a case through the matching GUI/API or other supported
   provider interface, then save and reopen it.
2. **Execute:** mesh and solve through the selected runtime, retaining resource,
   restart, termination and convergence evidence.
3. **Post-process:** read completed case data and publish measurements/visuals.

Today, Schemaxis ships the post-processing capability through ParaView. Preparation
and execution providers can be supplied as separately installed
[adaptor packages](../adaptor-development.md); do not label a combined
preparation-to-ParaView execution chain runnable until each stage is qualified.

Keep solver-specific settings in their provider implementation. Share
application-independent case/artifact contracts where evidence supports them; never
assume two OpenFOAM-derived distributions have identical dictionaries, models or
executable names.
Retain provider and version in the provenance. Do not silently substitute a
different solver when a licence or runtime is unavailable. Decide whether solver
execution needs a separate adaptor after investigating its interface, without
renaming or duplicating the current preparation adaptor prematurely.

## Conversion is a first-class workflow capability

Build a common conversion contract and a growing catalogue of specific, typed
converters. Add likely useful conversions to this backlog immediately; implement
them when a named producer/consumer workflow gives them an acceptance case. Avoid
promising arbitrary format-to-format conversion.

| Data family | Candidate implementation | Initial conversions or transformations to investigate |
| --- | --- | --- |
| Tables | Existing bounded Octave/Calc paths; a small table provider if justified | CSV/TSV and typed JSON tables; explicit column selection, renaming, units and missing-value rules. Extend beyond today's finite numeric CSV contract deliberately. |
| Larger typed tables | [Apache Arrow](https://arrow.apache.org/docs/python/parquet.html) | Selected CSV/Parquet/Arrow exchanges; preserve types, nulls and timestamps without forcing data into numeric-only CSV. |
| Multidimensional scientific data | [xarray and its I/O backends](https://docs.xarray.dev/en/stable/user-guide/io.html) | Selected NetCDF/Zarr datasets, preserving named dimensions, coordinates, units and masks. Define the dataset schema; a container format alone is not a semantic contract. |
| Scientific meshes | [meshio](https://github.com/nschloe/meshio), native Gmsh/VTK readers and writers | Gmsh MSH to VTU for inspection; selected solver mesh formats with node/cell sets and physical-group mappings. |
| CAD and surfaces | Existing FreeCAD/Blender/ParaView exporters | STEP to tessellated STL/PLY; explicit units, tolerances, normals and axes. Tessellation does not preserve an editable CAD feature tree. |
| Geographic data | [GDAL/OGR](https://gdal.org/en/stable/programs/index.html), QGIS | GeoTIFF reprojection/resampling; GeoJSON/GeoPackage exchange with explicit CRS and attributes. |
| Raster images | [ImageMagick](https://imagemagick.org/), native scientific-image tools | PNG/TIFF/JPEG variants with declared bit depth, colour space and compression; retain a separate scientific-volume contract. |
| Medical volumes | [dcm2niix](https://github.com/rordenlab/dcm2niix), 3D Slicer | Supported DICOM series to NIfTI plus sidecars; volume-to-surface extraction as a distinct processing operation. |
| Sparse matrices | SuiteSparse worker or qualified numerical runtime | Matrix Market to a supported sparse in-memory representation and back; explicit shape, symmetry, scalar type and indexing. |
| Media | Extend existing FFmpeg support | Image sequences and selected audio/video transcodes; retain frame rate/order, timestamps and codec-loss declarations. |
| Chemistry | Cantera-supported import/export tools | Selected mechanism import and result-table publication; enumerate supported species/reaction semantics before claiming compatibility. |
| Documents | [Pandoc](https://pandoc.org/) | Markdown/HTML and selected document exchanges for workflow reports; declare layout and feature losses. |

Each qualified conversion must declare:

- Input/output kinds, format versions, required fields and supported subsets.
- Units, coordinate frames/CRS, array association, shape and precision as relevant.
- Which metadata, topology, identifiers, time information and sidecars survive.
- Exact, tolerance-bounded or intentionally lossy behaviour. Required information
  loss must be rejected unless the workflow explicitly permits that loss.
- Fresh-read verification against the source or a suitable independent reference,
  plus hashes and provenance for every constituent artifact.

Renaming a file is not conversion. Interpolation, coordinate transformation and
surface extraction alter meaning and must appear as explicit operations. Do not
infer units from STL, treat point/cell data as interchangeable, or assume DICOM
conversion is anonymisation. Reader success alone does not demonstrate fidelity.

Keep converter-specific code in its owning adaptor. The shared framework should
handle contracts, discovery and artifact bookkeeping. Native libraries stay in
isolated workers; host discovery and planning retain no third-party dependencies.
Reuse existing declared capabilities where suitable instead of calling another
adaptor's internal utility code.

## Maintained JSON workflow templates

Yes: templates should be a maintained part of the product. They give humans and
agents useful starting points, make adaptor priorities concrete and provide
repeatable acceptance cases. They should remain editable compositions of reusable
operations, rather than becoming a separate execution language.

Use the current authored document contracts and `schemaxis.workflow/1` where all
members support it. Use `$document`, `$expr` and declared functions only in routes
that support them; use `$artifact` for supported inter-operation handoffs. The
workflow envelope already accepts shared dimensions, definitions, settings and
bounded finite analytics. Parameter metadata belongs in the separate
[workflow-template manifest](workflow-templates/template-contract.md), rather than
arbitrary workflow fields. See the [input reference](../json-input.md).

Each template bundle should contain:

- A goal, intended audience, required adaptors and explicit readiness status.
- Editable JSON with a small documented input surface: files, dimensions, fields,
  units, selections and scientifically meaningful parameters. Keep runtime paths
  in private configuration and input path configuration clearly documented.
- Redistributable small input fixtures, expected output artifacts and example
  results; distinguish a demonstration fixture from a user's production case.
- Preconditions and assumptions: coordinate directions, field meanings, physical
  models, supported data sizes and required licences where applicable.
- An independent acceptance check and retained version/qualification evidence.
  Validate planning and bounded native execution before advertising readiness.
- A quick-start explanation of what to change and what success means, including
  restart/reuse boundaries and known information loss at each handoff.

Keep three states explicit: **candidate** (design only), **experimental**
(implemented but incompletely qualified), and **qualified** (bounded evidence on
named runtime versions and fixtures). Qualification of a template does not certify
all user inputs or the validity of an underlying physical model.

### Initial template catalogue

| User goal | Starting point or proposed chain | Current standing |
| --- | --- | --- |
| Publish results from an existing CFD case | [CFD post-processing examples](../../examples/cfd-postprocess/README.md): completed case to ParaView slices, streamlines and measurements | Existing examples and bounded evidence; promote a documented parameterised starter. Does not run CFD. |
| Design and present a part | [CAD workflows](../cad-and-mesh-workflows.md): FreeCAD to ParaView/Blender | Existing bounded examples; curate as reusable templates. |
| Analyse a sampled signal | [Octave to Calc](../../examples/schemaxis/analysis/octave-to-calc.json) | Existing bounded workflow; use as the numerical-template baseline. |
| Prepare, run and report a CFD case | Case preparation to mesh/solve to ParaView | Candidate complete chain; preparation, execution and handoff providers remain to be qualified. |
| Predict bracket deflection | FreeCAD to Gmsh to CalculiX to ParaView | CAD → mesh → ParaView and named planar face groups are [qualified](../gmsh.md). A separate [generated rectangular beam](../calculix.md) is qualified; arbitrary brackets and CAD/Gmsh solver handoffs remain candidates. |
| Check a beam's serviceability | [CalculiX to Calc](../beam-workbook.md) | Qualified bounded cantilever and interior stress summary; producer/consumer requirements and reuse are checked independently. |
| Assess a numeric calibration model | [R regression and Calc](../r.md) | Qualified finite numeric linear models with independent coefficients/predictions and held-out requirements; no inference or generalisation claim. |
| Compare a circuit response | ngspice to Calc; later KiCad project linkage | Qualified bounded DC, AC RLC and first-order RC cases with analytic checks and workbook readback; KiCad remains a candidate. |
| Study ignition or equilibrium | Cantera to result tables to Calc; optional later R analysis | Candidate; retain mechanism and declared event/conservation checks. |
| Solve a sparse system | Matrix Market and right-hand side to SuiteSparse to solution/diagnostics | Candidate; begin with known-solution fixtures. |
| Measure an image batch | Fiji to tables to Calc or later R | Candidate; use calibrated fixtures with independently known measurements. |
| Extract a research anatomical model | 3D Slicer to surface to Blender | Candidate; retain physical coordinates and segmentation provenance. |
| Prepare a part for printing | FreeCAD/Blender to PrusaSlicer | Candidate; bounded printer/profile and G-code verification, without physical machine control. |
| Compare scanned and designed geometry | CloudCompare with reference geometry from FreeCAD | Candidate; verify registration and distance metrics on known offsets. |

Do not manufacture runnable-looking JSON for unavailable operations. Candidate
chains stay here until their schemas and handoffs exist. Publish working bundles
under `examples/`, link them from capability metadata where supported, and later
add a searchable template catalogue when enough bundles justify it. A new template
installation command or manifest schema is not part of the current implementation.

## Selection and delivery sequence

For each candidate record the concrete user problem, first input/output contract,
automation interface, installation/cost, named maintainer, verification approach,
native version and evidence status. Check the latest stable upstream at implementation
time. Avoid wrapping a whole API before the first workflow works.

Recommended sequence:

1. Curate existing CFD post-processing, CAD and numerical examples into the template
   convention; inventory the conversions already available.
2. Gmsh named planar faces, Cantera thermodynamic/TP/HP tables and ngspice
   linear-circuit tables, including AC inductors and RLC resonance, now have qualified
   handoffs. Next consider a Cantera homogeneous reactor, broader circuit
   capabilities, or extending the generated CalculiX beam to a separately qualified
   imported mesh with explicit Gmsh groups. Deliver one independently verified capability at a time.
3. Qualify CFD case preparation and bounded execution as a separate track; keep
   any licence requirements out of unrelated workflows.
4. Expand into 3D Slicer, Fiji and fabrication; introduce SuiteSparse when a direct
   sparse-solve workflow justifies its backend and artifact contracts.
5. Reprioritise the remaining catalogue from real use and maintenance cost.

This is sequencing guidance, not a commitment to implement every candidate.

## Licensed applications

Keep the free/inexpensive entry path. Where a workflow needs a licensed
application, state the prerequisite clearly. Distinguish installation, API
availability, licence availability and qualification. Preserve authored workflows,
completed artifacts and receipts when a licence is unavailable, and explain which
new executions need one.
