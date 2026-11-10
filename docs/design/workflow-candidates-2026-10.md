# Workflow candidate roadmap — October 2026

Assessed 25 October 2026 against core commit `8d4677c27f883e70e5ee38b0a44242df5450e197`.
The baseline has **41 application provider manifests**. Provider counts and
authorable route counts are different; the [delivery index](../generated/adaptor-delivery.md)
identifies routes. This document proposes future work, not delivered capabilities.
Every proposed application chain below includes at least one unimplemented link.
Existing guides identify what can already run; a proposed chain is not qualification.

The selection starts with repeatable user work, then weighs the semantic gap,
completion of existing application chains, independent verification and maintenance
cost. Priorities are product judgements. **No demonstrated customer demand was found
in the inspected material**; all sixteen entries are product hypotheses, each with
a proposed validation experiment. Official APIs establish technical possibilities,
not willingness to adopt or pay. No customer contact was performed.

P0 means a strong next bounded implementation brief after source/runtime checks;
P1 means a following wave after its contract/dependency decision; P2 means resolve
feasibility or domain-validation questions before committing implementation. These
are recommendations, not reservations, schedules or delivery promises. One coherent
workflow can require several capabilities; splitting fields, reviews or provisioning
into artificial delivery counts does not improve the product.

Research used current official documentation and existing adaptor source/guides.
No native runtime was provisioned, probed or executed for this roadmap. Installation
access, current-version support and native qualification remain implementation
questions. Linked live documentation may describe a beta or development version;
select the latest stable runtime explicitly and read its actual method-level API.
Fetch limitations are called out where they affected the evidence.

All proposals preserve dependency-free host discovery/planning, isolated native
processes, closed authored contracts, structured faults, conceptual Studio guidance,
source capture, independent result checks and explicit information-loss policies.
A successful native process or matching file hash alone is insufficient. Review,
changed-input cases and relevant negative controls are part of acceptance. The
public scope includes general geometry, meshing and scientific visualisation;
CFD solver execution and CFD-specific setup remain separately maintained integration
work and are excluded from this selection. Local result tables are ordinary public
workflow artifacts; integrated cross-case intelligence is outside this roadmap.

## Prioritised overview

| Rank | Candidate workflow | Industry | Investment | Priority |
| --- | --- | --- | --- | --- |
| 1 | [Narration with a background recording](#wf01) | Education and media production | Strengthen SoX | P0 |
| 2 | [Scanned-page OCR with a review trail](#wf02) | Archives and document operations | Create Tesseract adaptor | P0 |
| 3 | [Raster measurements by field or study zone](#wf03) | Agriculture and environmental monitoring | Strengthen GDAL | P0 |
| 4 | [Labelled measurement and inventory workbooks](#wf04) | Manufacturing quality and operations reporting | Strengthen Calc | P0 |
| 5 | [Checked PCB fabrication package](#wf05) | Electronics manufacturing | Strengthen KiCad with one coherent fabrication contract | P1 |
| 6 | [Named-dimension environmental dataset reduction](#wf06) | Climate and earth-science research | Create xarray adaptor with one pinned NetCDF backend | P1 |
| 7 | [IFC component quantity and property schedule](#wf07) | Architecture and construction | Create IfcOpenShell provider | P1 |
| 8 | [Comparable measurements across image timepoints](#wf08) | Microscopy and materials characterisation | Strengthen ImageJ | P1 |
| 9 | [Editable timed sprites in a game scene](#wf09) | Games and interactive learning | Strengthen Godot with explicit Aseprite handoff | P1 |
| 10 | [Consistent report and EPUB publication identity](#wf10) | Technical publishing and education | Strengthen Pandoc | P1 |
| 11 | [Scan-to-reference deviation report](#wf11) | Surveying and industrial metrology | Create CloudCompare provider | P2 |
| 12 | [Prediction intervals for calibration reports](#wf12) | Laboratory calibration and quality analytics | Strengthen R | P2 |
| 13 | [Mechanical response design study](#wf13) | Mechatronics and controls education | Create OpenModelica provider for mechanical systems only in this proposal | P2 |
| 14 | [Field-photo provenance and publication preparation](#wf14) | Field engineering and digital collections | Explore new ExifTool provider plus strengthening existing raster adaptors | P2 |
| 15 | [Reproducible research-volume segmentation](#wf15) | Research imaging and materials tomography | Create 3D Slicer adaptor | P2 |
| 16 | [Molecular structure exchange with explicit losses](#wf16) | Chemistry research and education | Explore a new Open Babel provider after obtaining a chemist-reviewed narrow feature set | P2 |

## Candidate contracts

Each experiment below would test the product hypothesis; it has not been conducted.

<a id="wf01"></a>

### 1. Narration with a background recording (P0)

**Industry/user:** Education and media production — Course producer or small podcast team.

**Workflow and pain:** Overlay a reviewed narration take and a background recording at declared sample offsets and gains, then publish the checked mix. Sequential clip editing cannot express simultaneous tracks; manual re-editing makes revisions difficult to reproduce.

**Inputs:** Two captured compatible PCM16 WAV files; integer frame offsets, gains and explicit output-length policy. **Useful outputs:** PCM16 mix, exact source-to-output timeline and clipping/headroom report.

**Proposed chain:** eSpeak NG or captured recording → SoX overlay → FLAC or FFmpeg review package.

**Schemaxis value:** Declare audible composition intent once and keep every sample tied to the source takes across revisions.

**Existing coverage and gap:** [SoX](../sox.md) already assembles excerpts, conforms speech and normalises sample peaks; [FFmpeg](../ffmpeg.md) already creates archival review muxes. No SoX operation overlays simultaneous sources. Automatic ducking, perceived loudness and browser MP4 remain separate scopes.

**Investment and feasibility:** Strengthen SoX; no new provider. High for a fixed two-input same-rate/channel slice. Unequal lengths, negative gains, overflow, offsets and SoX implicit gain require explicit decisions.

**Upstream evidence:** SoX documents input combination, but the official manual and source-manual URLs were inaccessible during this review. Re-read the released source manual and probe actual mix rounding before implementation. [SoX official manual (fetch unsuccessful)](https://sox.sourceforge.net/sox.html).

**Verification approach:** Independent sample-by-sample integer/fraction oracle; fresh native decode; changed offset/gain/length, silence, exact clipping-boundary and swapped-input controls.

**Why consider it next:** Completes an existing audio-to-publication chain with a mathematically inspectable new composition operation.

**Demand-validation experiment:** Ask a producer to rebuild one narration/background revision from the declaration and measure editing time and correction count.

<a id="wf02"></a>

### 2. Scanned-page OCR with a review trail (P0)

**Industry/user:** Archives and document operations — Archivist or back-office document reviewer.

**Workflow and pain:** Rasterise selected scanned pages, recognise words and publish text with page-linked word boxes and review flags. Embedded-text extraction yields nothing on image-only scans; plain OCR text loses the location of uncertain readings.

**Inputs:** Captured bounded page PNGs, explicit language/model and segmentation mode; optional originating PDF page identity. **Useful outputs:** Text, bounded word table with page boxes and native confidence, and an inspectable review report.

**Proposed chain:** MuPDF selected-page rendering → Tesseract → Pandoc review document; later explicit reviewed corrections.

**Schemaxis value:** Keep recognised text connected to source pixels and mark machine output for review rather than claiming the words are correct.

**Existing coverage and gap:** [MuPDF](../mupdf.md) renders pages and extracts embedded text; [Pandoc](../pandoc.md) publishes reports. Neither recognises words from page pixels. OCR inference, model provenance, word-coordinate contract and review handoff are absent.

**Investment and feasibility:** Create Tesseract adaptor; reuse existing page rendering/report adaptors. High for one plain image and one pinned language model. Model/engine provenance and page-segmentation defaults must be explicit.

**Upstream evidence:** Official tessdoc exposes text and TSV output including word boxes and confidence, with explicit engine/language choices. [Tesseract command-line usage](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

**Verification approach:** Independently validate boxes, hierarchy, coordinates, text/TSV agreement and model/source hashes. Use synthetic text for bounded accuracy observations, changed word/DPI and corrupted-output probes; do not certify arbitrary OCR accuracy.

**Why consider it next:** Adds document ingestion semantics that cannot be supplied by another PDF conversion wrapper.

**Demand-validation experiment:** Review a small representative scan set and record correction effort, missed fields and usefulness of page-linked uncertainty.

<a id="wf03"></a>

### 3. Raster measurements by field or study zone (P0)

**Industry/user:** Agriculture and environmental monitoring — Agronomist or environmental GIS analyst.

**Workflow and pain:** Summarise a captured measurement raster within declared zones and compare each zone with explicit requirements. Raster subsets and vector maps leave the analyst manually counting valid pixels and reconciling no-data and boundary conventions.

**Inputs:** Supported same-CRS single-band GeoTIFF, named grid-aligned rectangular zones initially, units, no-data policy and selected statistics. **Useful outputs:** Zone-labelled count/min/max/sum/mean table, coverage and no-data observations, and report-ready evidence.

**Proposed chain:** GDAL raster window + declared study zones → GDAL zonal summary → Calc/Pandoc.

**Schemaxis value:** Make pixel inclusion and missing-data treatment part of the authored decision instead of hidden GIS defaults.

**Existing coverage and gap:** [GDAL](../gdal.md) extracts/resizes same-CRS raster windows; [QGIS](../qgis.md) processes vector geometry. The Schemaxis GDAL adaptor does not currently reproject. No raster-to-zone aggregation or verified zone-table handoff.

**Investment and feasibility:** Strengthen GDAL. General polygon input and QGIS handoff follow only after the rectangular contract is accepted. High for aligned rectangles; medium for polygons. Official zonal-stats is available from GDAL 3.12; fractional overlap has an additional GEOS version requirement.

**Upstream evidence:** The official zonal-stats command supports vector/raster zones and explicit inclusion methods; it does not reproject inputs. Start without implicit resampling, fractional weighting or reprojection. [GDAL raster zonal-stats](https://gdal.org/en/stable/programs/gdal_raster_zonal_stats.html).

**Verification approach:** Enumerate every included pixel with an independent host oracle; verify all sums/counts, units/CRS/no-data, changed zone and sentinel, empty/all-missing zones and boundary controls.

**Why consider it next:** Connects two established spatial domains to a practical analytical deliverable with a strong finite oracle.

**Demand-validation experiment:** Have an analyst compare a real field-summary task against their current GIS procedure and inspect boundary/no-data disagreements.

<a id="wf04"></a>

### 4. Labelled measurement and inventory workbooks (P0)

**Industry/user:** Manufacturing quality and operations reporting — Quality engineer or operations analyst.

**Workflow and pain:** Publish typed rows with sample/part identifiers, optional measurements and safe literal notes into editable workbooks. Numeric-only tables force users to maintain labels and missing-value explanations in separate files.

**Inputs:** Explicit text/numeric column schema, bounded rows and an explicit null-to-blank policy; no authored formulas. **Useful outputs:** ODS/XLSX tables with exact identifiers and measurements plus a typed semantic round-trip summary.

**Proposed chain:** Apache Arrow typed table or declared captured CSV → Calc → Pandoc report.

**Schemaxis value:** Preserve identifiers and missingness through the same verified publication as the measurements.

**Existing coverage and gap:** [Apache Arrow](../apachearrow.md) supports Unicode/nullable typed interchange; [Calc](../calc.md) only accepts finite numeric table cells. Text cells, mixed column types and a declared missingness interchange contract in Calc. Existing native validation must remain unchanged for numeric-only documents.

**Investment and feasibility:** Strengthen Calc; do not introduce another spreadsheet provider. High for text and finite numbers, medium for nulls. UNO data arrays accept doubles/strings; distinguish blank, empty string, zero and formulas explicitly.

**Upstream evidence:** LibreOffice XCellRangeData supports double/string arrays; use explicit text cell APIs where needed to prevent formula interpretation. [LibreOffice XCellRangeData](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1sheet_1_1XCellRangeData.html); [LibreOffice XCell](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1table_1_1XCell.html).

**Verification approach:** Fresh native reopen plus independent OOXML/ODF inspection; preserve leading zeros, Unicode, formula-looking text, empty strings and numeric cells. Changed identifiers and null policy must alter the semantic result.

**Why consider it next:** Removes a handoff barrier shared by microscopy, BIM, component inventory and field measurements.

**Demand-validation experiment:** Recreate a labelled quality report and check whether a reviewer can reconcile every row to its source without a sidecar spreadsheet.

<a id="wf05"></a>

### 5. Checked PCB fabrication package (P1)

**Industry/user:** Electronics manufacturing — PCB designer preparing a prototype order.

**Workflow and pain:** From a saved board, apply declared DRC acceptance and publish a coherent selected-layer Gerber/drill package with a manifest. A successful plot command can still omit a copper/mask/outline layer or use inconsistent drill origin and units.

**Inputs:** Captured supported two-layer board, closed layer policy, units/origin and declared DRC tolerances. **Useful outputs:** Gerbers, Excellon drills and a cross-checked layer/geometry/origin manifest ready for human fabrication review.

**Proposed chain:** KiCad board checks → KiCad fabrication export → Info-ZIP package → MuPDF/Pandoc review where applicable.

**Schemaxis value:** Express package completeness and geometry requirements rather than forward plot flags.

**Existing coverage and gap:** [KiCad](../kicad.md) already inspects boards, runs DRC and exports independently checked drills; [Info-ZIP](../infozip.md) packages declared files. Gerber geometry and cross-file fabrication completeness. Schematic/BOM/placement parity is separate and must not be implied.

**Investment and feasibility:** Strengthen KiCad with one coherent fabrication contract. Medium: public CLI is mature, but independent Gerber apertures/regions and polarity semantics are substantial work. Begin with a supported board/primitive subset and reject the rest.

**Upstream evidence:** KiCad 10 CLI documents Gerber, drill, position, BOM and netlist exports. Only Gerber plus existing drills are proposed in the first slice. [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html).

**Verification approach:** Independent board-to-Gerber primitive geometry, selected-layer identity, outline/bounds, drill alignment and fresh native readback; omit/swap/mirror layers and alter origin in negative controls.

**Why consider it next:** Adds an actual manufacturing deliverable beyond isolated exports, with completeness that a user can inspect.

**Demand-validation experiment:** Ask a designer to compare one package against the board and their usual fabrication checklist; no ordering or machine control.

<a id="wf06"></a>

### 6. Named-dimension environmental dataset reduction (P1)

**Industry/user:** Climate and earth-science research — Researcher analysing gridded observations.

**Workflow and pain:** Select named coordinates/time ranges from one local dataset, apply explicit missing-data reductions and publish a smaller dataset and numeric summary. Flattened CSV loses coordinate identity, calendars, masks and variable units; repeating analysis requires remembering positional slicing.

**Inputs:** Bounded local NetCDF dataset; declared variables, dimensions, coordinate ranges, units and reduction/missingness policy. **Useful outputs:** Reduced NetCDF with retained coordinates/attributes and labelled numeric tables for plotting/reporting.

**Proposed chain:** xarray dataset selection/reduction → Gnuplot/Calc → Pandoc; ParaView handoff only after format qualification.

**Schemaxis value:** Author scientific dimensions and decisions while retaining the exact coordinate/mask provenance.

**Existing coverage and gap:** [NumPy](../numpy.md) covers table PCA, [GDAL](../gdal.md) spatial rasters, and [Apache Arrow](../apachearrow.md) tables; no named multidimensional dataset provider is registered. Coordinate-aware multidimensional IO, explicit reduction semantics and calendar/encoding preservation.

**Investment and feasibility:** Create xarray adaptor with one pinned NetCDF backend; avoid adding it to the host. Medium: library and backend are accessible, but calendars, scale/offset, compression and coordinate alignment need a narrow first contract. Begin with simple monotonic coordinates and one calendar.

**Upstream evidence:** Official xarray docs expose named-dimension computation and explicit IO engine selection; different backends have materially different capabilities. [xarray computation](https://docs.xarray.dev/en/stable/user-guide/computation.html); [xarray IO](https://docs.xarray.dev/en/stable/user-guide/io.html).

**Verification approach:** Synthetic analytic data cube with permuted dimension order, missing cells, coordinate labels and changed selection. Independently compute every reduction, reopen output and reject unsupported calendars/encoding.

**Why consider it next:** Adds a durable data model rather than duplicating numeric array arithmetic.

**Demand-validation experiment:** Reproduce one researcher-defined subset/reduction and measure how often positional/metadata mistakes are caught.

<a id="wf07"></a>

### 7. IFC component quantity and property schedule (P1)

**Industry/user:** Architecture and construction — BIM coordinator or quantity surveyor.

**Workflow and pain:** Select components by declared IFC class and publish GUID-linked property/quantity schedules with explicit units and missing-property flags. Geometry export discards the object identity and inherited property context needed to reconcile a schedule to the building model.

**Inputs:** Captured bounded IFC model, supported schema, class selection, exact property/quantity names and unit policy. **Useful outputs:** GUID-linked typed schedule, missing/ambiguous-property report and schema/unit provenance.

**Proposed chain:** IfcOpenShell → Apache Arrow typed table → Calc/Pandoc after explicit format handoff.

**Schemaxis value:** Preserve BIM meaning and identity instead of reducing every building model to triangles.

**Existing coverage and gap:** [Blender](../parallel-dispatch-and-blender.md) and [FreeCAD](../freecad-part-design.md) cover general geometry; neither is an IFC property schedule provider. IFC identity, class, property/type inheritance, project units and quantity semantics.

**Investment and feasibility:** Create IfcOpenShell provider. Bonsai is a possible user interface, not another provider count for the same first workflow. Medium for property schedules without geometry. Begin with one schema and explicit occurrence-vs-type precedence; missing quantities are absent, not zero or inferred geometry.

**Upstream evidence:** IfcOpenShell public utilities expose property/quantity retrieval and unit handling. Use a closed selector contract rather than arbitrary selector expressions. [IfcOpenShell examples](https://docs.ifcopenshell.org/ifcopenshell-python/code_examples.html); [IfcOpenShell property utilities](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html); [IfcOpenShell unit utilities](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/unit/index.html).

**Verification approach:** Original small IFC fixtures with known GUIDs, inherited/overridden properties, duplicate names and non-SI units; independent supported STEP-entity/property graph checks plus fresh native reopen.

**Why consider it next:** Establishes a new industry semantic boundary with little overlap with existing CAD wrappers.

**Demand-validation experiment:** Compare a bounded schedule against a coordinator-reviewed model and record missing/ambiguous properties before attempting computed quantities.

<a id="wf08"></a>

### 8. Comparable measurements across image timepoints (P1)

**Industry/user:** Microscopy and materials characterisation — Lab researcher measuring repeated fields of view.

**Workflow and pain:** Apply the same declared rectangular regions and calibration to a bounded image series, publishing per-region/per-frame measurements. Manual repeated measurement invites region drift, inconsistent calibration and ambiguous timepoint labels.

**Inputs:** Captured ordered grayscale planes, sample/frame identifiers, shared calibration, explicit time values and named rectangular regions. **Useful outputs:** Labelled region/timepoint measurement table, region overlays and calibration/source provenance.

**Proposed chain:** ImageJ region/series measurement → Calc or R → Gnuplot/Pandoc.

**Schemaxis value:** Express repeated measurement intent while preserving which pixels and timepoint produced each number.

**Existing coverage and gap:** [ImageJ](../imagej.md) independently checks calibrated single-plane threshold particles; no regions, image batches or series are declared. Region selection, shared-region reuse, series identity and direct intensity statistics. No registration/tracking or biological inference is proposed.

**Investment and feasibility:** Strengthen ImageJ; batch orchestration alone is insufficient unless the shared region/calibration contract is verified. Medium: use public ImagePlus/ImageProcessor/ImageStatistics APIs and bounded plane inputs; avoid GUI RoiManager assumptions in a headless runtime.

**Upstream evidence:** ImageJ documents image stacks and ROI management; implementation must use supported headless measurement methods rather than invoke menu macros. [ImageJ ImageStack API](https://imagej.net/ij/developer/api/ij/ij/ImageStack.html); [ImageJ ROI manager API](https://imagej.net/ij/developer/api/ij/ij/plugin/frame/RoiManager.html).

**Verification approach:** Independent every-pixel region statistics on analytic intensity ramps with changed region/time/calibration, rectangular pixel spacing, out-of-range region and unequal image-size controls.

**Why consider it next:** Builds on an existing strong oracle while adding a repeatable lab workflow rather than another threshold option.

**Demand-validation experiment:** Ask a researcher to repeat one analysis after a region edit and check time saved and whether every point remains traceable.

<a id="wf09"></a>

### 9. Editable timed sprites in a game scene (P1)

**Industry/user:** Games and interactive learning — Technical artist or indie developer.

**Workflow and pain:** Carry verified sprite frames and timing into a saved Godot animation resource and place it in a reusable scene group. A sprite sheet or rendered preview loses its authored per-frame timing when manually reconstructed in the game editor.

**Inputs:** Captured supported PNG frames/sheet, declared frame rectangles, durations, animation names, looping policy and scene placement. **Useful outputs:** Editable Godot project and SpriteFrames resource with exact frame/timing readback and a bounded playback observation.

**Proposed chain:** Aseprite animation publication → Godot AnimatedSprite3D/SpriteFrames → saved scene.

**Schemaxis value:** Preserve artist intent through the application handoff rather than merely importing a texture.

**Existing coverage and gap:** [Aseprite](../aseprite.md) publishes timed animation assets; [Godot](../godot.md) supports static sprites, hierarchy and reusable groups, but explicitly excludes animation. Animation resource creation, duration mapping, loop semantics and actual state sampling.

**Investment and feasibility:** Strengthen Godot with explicit Aseprite handoff; reuse the existing Aseprite provider. Medium: public resource APIs are available. Keep a single animation family and distinguish relative frame durations from seconds and playback speed.

**Upstream evidence:** Godot SpriteFrames exposes frame textures/durations, animation speed and loop mode, with native readback methods. [Godot SpriteFrames](https://docs.godotengine.org/en/stable/classes/class_spriteframes.html).

**Verification approach:** Independent frame-rectangle pixel checks, exact duration conversion and fresh saved-resource reopen; changed ordering/duration, boundary-time playback and invalid rectangle controls.

**Why consider it next:** Connects two established creative tools through editable meaning, extending beyond another export format.

**Demand-validation experiment:** Have an artist change an Aseprite frame duration and confirm that the reopened Godot resource and bounded playback agree.

<a id="wf10"></a>

### 10. Consistent report and EPUB publication identity (P1)

**Industry/user:** Technical publishing and education — Report author or independent publisher.

**Workflow and pain:** Publish the same bounded authorship, description and language declarations across report formats and verify each format mapping. Document identity is currently rebuilt manually; format-specific metadata can diverge from visible title/description.

**Inputs:** Existing structured report plus bounded author list, description and explicit language; user declarations are not verified identity. **Useful outputs:** HTML/DOCX and optional EPUB with declared metadata and a cross-format mapping/loss report.

**Proposed chain:** Measured results or reviewed transcript → Pandoc → EPUBCheck for EPUB structural validation.

**Schemaxis value:** Keep publication identity in one declaration and make unsupported or omitted metadata visible.

**Existing coverage and gap:** [Pandoc](../pandoc.md) publishes reports/transcripts and EPUB with title/language; author/description fields are not authorable. [EPUBCheck](../epubcheck.md) validates EPUB structure. A coherent author/description metadata contract and independent mapping across all selected formats.

**Investment and feasibility:** Strengthen Pandoc; bundle related identity fields into one meaningful workflow allocation. High for a bounded plain-text metadata model, with medium mapping complexity because formats represent authors/description differently.

**Upstream evidence:** Pandoc documents metadata and multiple output writers; its manual explicitly warns that conversion can lose format details. [Pandoc manual](https://pandoc.org/MANUAL.html).

**Verification approach:** Inspect HTML metadata, DOCX core properties and EPUB OPF independently, including Unicode/multiple authors, absent-field legacy behaviour, changed description and forged-property controls.

**Why consider it next:** Retains the useful older publishing candidate while giving it an honest semantic/loss boundary.

**Demand-validation experiment:** Ask an author to compare visible and embedded identity in three formats and determine which fields their readers/distributors actually need.

<a id="wf11"></a>

### 11. Scan-to-reference deviation report (P2)

**Industry/user:** Surveying and industrial metrology — Survey analyst or inspection engineer.

**Workflow and pain:** Apply a declared rigid transform to a bounded point cloud and measure unsigned distance to a captured reference mesh. Manual alignment settings and hidden global coordinate shifts make deviation reports difficult to reproduce.

**Inputs:** Bounded points/reference triangles, units, explicit rigid transform and distance/statistic requirements. **Useful outputs:** Transformed cloud, point-labelled distances, coverage observations and a reproducible deviation summary.

**Proposed chain:** FreeCAD/meshio reference geometry → CloudCompare → ParaView/Gnuplot/Pandoc.

**Schemaxis value:** Separate known transformation and measurement from uncertain registration, retaining coordinate/unit meaning.

**Existing coverage and gap:** [FreeCAD](../freecad-part-design.md), [meshio](../meshio.md) and ParaView support geometry/interchange/visualisation, but no CloudCompare measurement provider is registered. Point-cloud distance measurement with controlled global-shift and numeric interpretation.

**Investment and feasibility:** Create CloudCompare provider; defer automatic ICP and accuracy certification. Medium-to-low: CLI is documented, but Qt/plugin/runtime and output-field semantics need probing. The live command wiki describes a beta; resolve stable command support explicitly.

**Upstream evidence:** CloudCompare documents ordered CLI state changes and global shifts. Never silently select the live wiki beta as a stable runtime. [CloudCompare command-line mode](https://www.cloudcompare.org/doc/wiki/index.php/Command_line_mode).

**Verification approach:** Planes/boxes with analytic distances and known transforms; independent point-triangle distance checks, shifted coordinates, changed transform, empty overlap and unit/mirror controls.

**Why consider it next:** Adds a new inspection result, provided the bounded geometry oracle and stable runtime can be demonstrated.

**Demand-validation experiment:** Use one synthetic calibration case and one reviewer-supplied noncritical scan to learn whether a fixed-transform report is useful before attempting registration.

<a id="wf12"></a>

### 12. Prediction intervals for calibration reports (P2)

**Industry/user:** Laboratory calibration and quality analytics — Test engineer or applied statistician.

**Workflow and pain:** Fit the existing additive linear model, predict declared new observations and publish mean-response confidence intervals separately from individual prediction intervals. A fitted curve or coefficient interval is easily mistaken for uncertainty around a future measurement.

**Inputs:** Captured training/new numeric tables, explicit interval type/level and stated independent constant-variance normal-error model assumptions. **Useful outputs:** Labelled predictions and bounds, model diagnostics/assumptions and a report suitable for statistical review.

**Proposed chain:** Measurement table → R → Gnuplot interval plot → Calc/Pandoc.

**Schemaxis value:** Make the uncertainty question explicit and preserve the distinction between fitted means and future observations.

**Existing coverage and gap:** [R](../r.md) supports additive numeric regression, held-out predictions and coefficient inference; prediction intervals are absent. New-observation interval semantics and independently verified leverage/residual-variance calculation.

**Investment and feasibility:** Strengthen R; do not add a statistics provider or imply automatic model suitability. Medium: native predict.lm provides both interval types; numerical conditioning, residual degrees of freedom and unsupported rank deficiency require explicit refusal/indeterminate decisions.

**Upstream evidence:** Official R predict.lm documents confidence/prediction intervals, future-observation variance and rank-deficient prediction constraints. The linked R-patched manual can include changes beyond a selected stable runtime; confirm its version-specific method before implementation. [R predict.lm](https://stat.ethz.ch/R-manual/R-patched/library/stats/html/predict.lm.html).

**Verification approach:** Independent QR/leverage and Student-t calculations with analytic small examples, changed newdata/level, zero residual degrees of freedom, extrapolation observations and tampered bounds.

**Why consider it next:** Adds a distinct decision-relevant output rather than merely exposing another native option.

**Demand-validation experiment:** Have a statistician review a calibration report and judge whether interval assumptions and distinctions prevent interpretation errors.

<a id="wf13"></a>

### 13. Mechanical response design study (P2)

**Industry/user:** Mechatronics and controls education — Mechanical/control engineer or instructor.

**Workflow and pain:** Compare a bounded family of mass-spring-damper responses under declared initial conditions and forcing, retaining editable models. Ad hoc scripts leave model equations, parameter units and sampled acceptance criteria disconnected from saved simulation results.

**Inputs:** Positive mass/stiffness, nonnegative damping, initial state/forcing and explicit time grid/requirements. **Useful outputs:** Editable Modelica model, sampled displacement/velocity/energy tables and analytic comparison report.

**Proposed chain:** OpenModelica → Gnuplot/Calc → Pandoc.

**Schemaxis value:** Describe a physical experiment and requirements while retaining both the model and verified response.

**Existing coverage and gap:** [Octave](../numerical-analysis.md), [SymPy](../sympy.md) and [ngspice](../ngspice.md) cover other numerical/electrical slices; no Modelica model provider exists. Native Modelica model generation, parameter provenance and physical-state result mapping.

**Investment and feasibility:** Create OpenModelica provider for mechanical systems only in this proposal. Medium-to-low: compiler/runtime and library versions are larger integration costs. Pin a stable release and trusted fixed model; no authored arbitrary Modelica.

**Upstream evidence:** OpenModelica documents model compilation/simulation scripting; the latest API page is a development build, so stable-release API compatibility must be checked separately. [OpenModelica scripting API](https://openmodelica.org/doc/OpenModelicaUsersGuide/latest/scripting_api.html); [OpenModelica stable downloads](https://openmodelica.org/download/download-windows/).

**Verification approach:** Independent under/critical/overdamped solutions, zero-force energy balance and time-grid checks; changed damping/mass and invalid physical parameters, plus model/result tampering.

**Why consider it next:** A credible entry to multi-domain systems if an analytic first family can sustain complete native acceptance.

**Demand-validation experiment:** Use an instructor-reviewed exercise to assess whether editable model plus verified response adds value beyond the existing numerical tools.

<a id="wf14"></a>

### 14. Field-photo provenance and publication preparation (P2)

**Industry/user:** Field engineering and digital collections — Field investigator or collection manager.

**Workflow and pain:** Inspect a captured photo set, reconcile declared orientation/time/location metadata, and prepare publication copies with an explicit metadata policy. Photo filenames and embedded metadata diverge; resizing or decoding can silently change orientation or lose source context.

**Inputs:** Bounded supported JPEG/PNG files, explicit metadata allowlist, coordinate/timezone policy and publication size/colour requirements. **Useful outputs:** Source-linked metadata inventory, orientation-correct previews and publication copies with documented retained/removed fields.

**Proposed chain:** ExifTool inspection → explicit JPEG decode/orientation → ImageMagick/WebP → Pandoc; optional GIS handoff after qualification.

**Schemaxis value:** Tie every derivative to a source and an explicit metadata/visual policy without claiming complete anonymisation.

**Existing coverage and gap:** [ImageMagick](../imagemagick.md) offers bounded PNG preparation; [WebP](../webp.md) encodes supported raster inputs. Neither provides a complete photo-metadata/JPEG input contract. Metadata interpretation, JPEG source decode, orientation handling and publication downscale; this is a staged workflow, not one field-sized allocation.

**Investment and feasibility:** Explore new ExifTool provider plus strengthening existing raster adaptors; first accept read-only inventory before derivative editing. Medium for selected EXIF tags; lower for universal metadata removal, which is not proposed. Official manual opens returned 403; primary FAQ/examples were discoverable but require method-level follow-up.

**Upstream evidence:** ExifTool official material describes metadata read/write, JSON output and GPS/orientation tags. Fetch limitations prevent a full option-level API review here. [ExifTool FAQ](https://exiftool.org/faq.html); [ExifTool examples](https://github.com/exiftool/exiftool/blob/master/html/examples.html); [ExifTool manual (fetch unsuccessful)](https://exiftool.org/exiftool_pod.html).

**Verification approach:** Independent EXIF fixture parser and image-pixel oracle; changed orientation/timezone/GPS, missing/duplicate tags and retained-source checks. Metadata policy reports only inspected fields/formats.

**Why consider it next:** Turns the older resize/JPEG ideas into an actual collection workflow, pending demand and decode-policy evidence.

**Demand-validation experiment:** Inspect a collection manager-approved non-sensitive sample and identify which metadata and sizes their real publication process needs.

<a id="wf15"></a>

### 15. Reproducible research-volume segmentation (P2)

**Industry/user:** Research imaging and materials tomography — Research imaging scientist.

**Workflow and pain:** Threshold a calibrated synthetic or research volume into a named labelmap, measure its volume and export a reviewable surface. Image-by-image thresholds cannot preserve 3D spacing/orientation or show which voxels a derived surface represents.

**Inputs:** Bounded simple volume with explicit spacing/origin/direction, scalar threshold and segment identity. **Useful outputs:** Saved editable segmentation, labelmap, voxel-derived measurements and surface with declared meshing losses.

**Proposed chain:** 3D Slicer → meshio/Blender/ParaView → Pandoc research report.

**Schemaxis value:** Preserve voxel/physical-coordinate meaning through a segmentation-to-geometry handoff.

**Existing coverage and gap:** [ImageJ](../imagej.md) supports one grayscale plane; general geometry adaptors do not provide volume segmentation semantics. 3D calibrated volume ingestion, segmentation identity and labelmap/surface coordinate contract.

**Investment and feasibility:** Create 3D Slicer adaptor; start with synthetic research data, without DICOM ingestion or clinical validation. Low-to-medium: large application/runtime and possible display dependencies. Constrain input storage and threshold effect before surface algorithms or extensions.

**Upstream evidence:** Official Slicer script examples expose segmentation effects and labelmap export; labelmaps and segmentations use different identity representations. The linked latest documentation tracks development and must be checked against the selected stable Slicer release. [Slicer segmentation scripting](https://slicer.readthedocs.io/en/latest/developer_guide/script_repository/segmentations.html).

**Verification approach:** Independent voxel membership and physical-volume oracle on boxes/spheres; changed spacing/direction/threshold, exact labelmap readback and bounded surface geometry checks with explicit tolerance.

**Why consider it next:** Offers a distinct 3D measurement workflow if runtime feasibility is established; not a claim of medical suitability.

**Demand-validation experiment:** Ask an imaging researcher to review synthetic-volume coordinate preservation before testing any real dataset.

<a id="wf16"></a>

### 16. Molecular structure exchange with explicit losses (P2)

**Industry/user:** Chemistry research and education — Chemist curating a small molecule collection.

**Workflow and pain:** Convert a bounded structure set while checking molecular identity, charges and declared stereochemical/coordinate losses. A format conversion can look successful while silently dropping charge, bond order, stereochemistry or coordinates.

**Inputs:** Captured supported SDF/MOL records with explicit atom/bond features and output-format/loss policy. **Useful outputs:** Converted structure file plus record-by-record formula/charge/bond identity and loss report.

**Proposed chain:** Open Babel → typed molecular inventory through Apache Arrow → Calc/Pandoc; no assumed Cantera mechanism handoff.

**Schemaxis value:** Turn format conversion into an explicit chemical-information preservation decision.

**Existing coverage and gap:** [Cantera](../cantera.md) models a bounded reaction mechanism, not general molecular structure interchange; no Open Babel provider is registered. Molecular structure parsing, identity/feature preservation and honest format-specific loss handling.

**Investment and feasibility:** Explore a new Open Babel provider after obtaining a chemist-reviewed narrow feature set. Medium for simple neutral achiral structures; lower for aromaticity/stereochemistry. Explicitly restrict unsupported features rather than claiming formula equality establishes identity.

**Upstream evidence:** Open Babel documents structure conversion and notes that conversion does not automatically generate coordinates; its stereochemistry documentation describes limited supported classes. [Open Babel command-line conversion](https://openbabel.org/docs/Command-line_tools/babel.html); [Open Babel stereochemistry](https://openbabel.org/docs/Stereochemistry/stereo.html).

**Verification approach:** Independent bounded atom/bond graph and charge checks, record identity under allowed reordering, changed bond/charge and unsupported stereo controls; formula/count alone is insufficient.

**Why consider it next:** Adds a new scientific data domain with a clear preservation contract, but needs domain review before priority rises.

**Demand-validation experiment:** Have a chemist supply and review a small positive/negative corpus and judge the value of the explicit loss report.

## Reassessment of previous roadmap ideas

The [older public catalogue](adaptor-candidates.md) remains historical design
material. This dated workflow assessment supersedes its ordering for these
proposals; its early provider inventory and CFD execution row are not the current
public programme. The [17 October assessment](adaptor-programme-assessment-2026-10.md)
is also a historical baseline, not a current inventory or demand study.

- **Older public application catalogue: Historical starting map, not current inventory.** Its 2026-10-16 list predates the current 41-provider baseline. Names already present are strengthening opportunities only after checking current operations.
- **SoX two-track mix: Retain as WF01 P0.** Exact source confirms no simultaneous mix; bounded mathematical verification and downstream audio consumers exist.
- **Pandoc authorship/description: Retain as WF10 P1.** Coherent identity contract across formats; no separate allocation for each field.
- **H.264/AAC MP4 publication mux: Defer pending timing/codec feasibility.** Potentially useful but AAC priming/edit lists, duration and independently decoded fidelity need a sound contract. Current FFV1/PCM/SubRip archival review is not a browser-publication promise.
- **ImageMagick shrink-to-fit and JPEG publication: Fold into WF14 photo workflow feasibility.** Do not add thin conversion wrappers solely to increase provider or allocation counts. Orientation, colour, source provenance and actual publication requirements determine useful scope.
- **eSpeak pacing or FLAC metadata: Do not redispatch existing capability.** Current source already includes rateWpm and title/artist/description respectively. Reinspect the latest source before any future change.
- **Bonsai and IfcOpenShell: One first BIM provider/workflow, WF07.** A UI and its underlying semantic engine do not justify duplicate provider counts for the same capability.
- **Gazebo, DWSIM and SuiteSparse: Retain as later feasibility topics, outside first sixteen.** Large simulation/physics or backend verification costs; no demonstrated user workflow supplied here that outweighs the selected connected gaps. This is prioritisation, not a claim of unavailability.
- **DICOM ingestion and Aliza: Defer.** Research segmentation can begin with synthetic simple volumes. DICOM grouping/affine/scaling and supported Aliza automation/edition need separate evidence.
- **CFD solver execution and CFD-specific setup: Excluded from public roadmap selection.** Belong in separately maintained integrations. General geometry, meshing and scientific visualisation remain public eligible.


The next selection should recheck the actual source and runtime, choose the
smallest connected slice that delivers a useful result, and write explicit
acceptance criteria before implementation. A weak or unavailable runtime should
change the proposed slice or its readiness label; it should not inflate coverage,
verification confidence or demand claims. Reassess priorities after user evidence
or accepted capabilities change the gaps.
