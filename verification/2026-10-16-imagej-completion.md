# ImageJ particle measurement completion review (2026-10-16)

**Architect closeout:** shared reference/Help generation, catalogue and workflow
guidance integration, admission checks, the full host suite and final native
qualification are complete. A fresh receipt is registered against the final
source. See the [integration verification](2026-10-16-architecture-integration.md).
The implementation-agent handoff below records its earlier state; its pending
central-integration items are now resolved. Application scope limits remain.

Scope: the new `schemaxis.imagej/1` route with one operation, `analyzeParticles`,
and every field: `image`, `calibration.{pixelWidth,pixelHeight,unit}`,
`threshold.{lower,upper}`, `connectivity`, `includeHoles`, `excludeEdges`,
`minimumArea` and `maximumArea`. No other adaptor was changed.

## Runtime selection

- **Runtime:** ImageJ 1.x `ij.jar`, version **1.54t**. This is the first
  entry of the release list read by Help > Update ImageJ
  (`https://wsr.imagej.net/jars/list.txt`), published on 2026-05-16, and the
  latest stable release on 2026-10-16. Later entries in the
  [release notes](https://imagej.net/ij/source/release-notes.html), such as
  1.54u8, are daily builds.
- **Launch:** OpenJDK 21 runs a fixed Java source program through the JDK
  source-file launcher (JEP 330), headless, with a private
  `user.home`/plugins/temporary folder.
- **Why not a macro:** plain ImageJ 1.x macro `open()` calls `IJ.init()`,
  which builds AWT menus and throws `HeadlessException` under
  `java.awt.headless=true`. This was observed on 1.54t.
- **Fiji:** Fiji's launcher and plugins are not the qualified runtime. Fiji
  bundles the same ImageJ 1.x core, but using a Fiji `ij-1.54*.jar` is
  unqualified.
- **Native defect found:** on 1.54t, constructing `ParticleAnalyzer` with
  `FOUR_CONNECTED` but without `INCLUDE_HOLES` returns empty particles with
  NaN measurements. The constructor sets its forced `INCLUDE_HOLES` on a local
  copy after storing the options. The fixed program therefore sets both flags,
  and the planner rejects `four` with `includeHoles: false`
  (`UNSUPPORTED_OPTION`).

## Checklist results

| ID | Result |
| --- | --- |
| registration | `adaptor.json` declares the route (`workflow`, `scheduled`, `compose`; `timeBatches`/MPI false) and the hooks `query`, `reusableInputs` and `resources`. Java is the `imagej` executable; `ij.jar` comes through `runOptions.jar` from the `imagejJar` location. The CLI flags are `--imagej` and `--imagej-jar`. The registry discovers the manifest with no app-name branches. Feature decisions are in `readiness.json`. |
| schema | Closed object schema with exact bounds. The unit, connectivity and boolean controls are explicit, defaults are typed and `maximumArea` is optional. Host conformance checks schema/planner agreement across 3 valid and 6 invalid examples, rejects an undeclared root field, plans 6 distinct acceptance cases and checks the typed defaults. |
| semantics | The planner rejects a relative path or control characters, an unsupported extension, `lower > upper`, `four` without holes, and an area window with no whole pixel count. Before native launch it also rejects malformed/compressed/multi-page/signed/colour images, size limits, `upper` above the bit depth, full-range thresholds and `NO_PARTICLES`. Each fault has an exact code and location; tests assert both. |
| native-mapping | Public API only: `PGM_Reader.openFile`, `Opener.openTiff`, a fresh `Calibration` (pixelWidth/pixelHeight/unit), `ImageProcessor.setThreshold(lower, upper, NO_LUT_UPDATE)`, and `ParticleAnalyzer(options, AREA\|MEAN\|MIN_MAX\|CENTROID\|RECT, rt, minPx, maxPx)` with `SHOW_ROI_MASKS`, `FOUR_CONNECTED`, `INCLUDE_HOLES` and `EXCLUDE_EDGE_PARTICLES`. Readback covers version, dimensions, depth, plane count, inverted LUT, density calibration, calibration, unit codepoints, threshold, option flags, pixel bounds and the consumed-input SHA-256. Losses are listed in the plan, the summary and `readiness.json`. |
| execution | One deadline covers `java -version`, the analyse stage and a fresh reopen stage. Shared owned-process cancellation is checked before each stage and before publication. The run retains the authored input, plan, input copy, fixed program, runtime record, logs, readbacks, native/reopened tables, count mask, publications and failure `result.json`. Verification is independent (see the guide). |
| discovery | Application and operation purpose, curated keywords (Analyze Particles, Fiji, blob counting, grain/pore/particle size, count particles, measure area, connected components, segmentation…) and semantics. `search-cases.json` covers all four kinds and all four surfaces. "measure area" is classed as ambiguous because it may mean calibrated area or pixel count; both are published, and other adaptors' area measurements may also match under global scope (no ranking claim). Negative cases: "frequency response" and "tetrahedral mesh". |
| guidance | `guidance.json` has 17 records (the operation plus 16 field addresses), all `reviewed`, with units, defaults, examples, pitfalls and local sources. `tools/studio_guidance.py --app imagej --check` reports 0 pending and 0 stale. Domain review of the scientific wording is still welcome (see open items). |
| help | `docs/imagej.md` covers runtime, document, threshold, connectivity, calibration, outputs, verification, fixtures, handoff, faults, limits, maintenance and public API links. Generated reference and packaged Help were produced and checked only in an isolated checkout copy. Central regeneration in the shared tree is deferred to the architect. |
| examples | `examples/schemaxis/imagej-particles.json` (baseline), `-filled.json` (variant), `-16bit.json` and `imagej-to-calc.json`. Studio offers 2 templates and 5 snippets with filled host plans and unfilled placeholder rejection. Fixtures are the original synthetic targets in `examples/schemaxis/fixtures/imagej/`, made of analytic rectangles (not experimental data). `tools/qualify_imagej_fixtures.py --check` reproduces their bytes. |
| tests | `tests/unit/test_imagej_admission.py` has 15 tests. They cover host conformance, fixture reproducibility, bounds and exact faults, the pixel window, the analytic reference model, complementary-connectivity hole filling, decoder rejections and fixed commands. They also cover runtime identities, missing runtime and false success, and verifier falsification through an offline native double (tampered labels, values, readbacks, program, input and summary, with refreshed digests). |
| qualification | Native conformance passed: 6 cases, 10 integrity probes each, timeout and pre-launch cancellation (see "Native acceptance" below). The receipt is **not** registered: central Help regeneration changes the source digest. The parent must rerun and record it with the commands below. Until then, qualification stays unrecorded. |
| maintenance | `upstream.json` uses `policy: latest-stable` with a manual source check and an explicit reason. The shared numeric release parser cannot read the letter-suffixed `1.54t`. `absorbedVersion` is 1.54t, set only after native acceptance passed in the shared checkout. |

## Native acceptance

Runtime: ImageJ 1.54t `ij.jar` (2642337 bytes, SHA-256 `bd05a0bb…710e`) with
OpenJDK 21.0.12.1, Linux x86-64, serial execution. Cases (literal analytic
expectations in `readiness.json`):

| Case | Expected and observed |
| --- | --- |
| `baseline-8bit` | 8 particles; 347 px = 86.75 µm²; L-shape centroid (4.3333, 13.8333) µm; ring 108 px; island 4 px; diagonal pair 18 px. |
| `filled-edges-size` | 5 particles; ring 144 px with mean 130.8333, min 20, max 230; rejected edge 1, size 1; 89.5 µm². |
| `four-connected` | 8 particles; corner-touching squares split into 9 + 9 px; 94.75 µm². |
| `inclusive-threshold-boundary` | Lower bound 180 keeps the 180-valued square; 6 particles; 59.5 µm². |
| `anisotropic-millimetres` | 0.25 × 0.5 mm pixels; 43.375 mm²; column `area_mm2`. |
| `sixteen-bit-boundary` | Big-endian two-strip 16-bit TIFF; lower bound 18000; 6 particles; 59.5 µm². |

The shared kit also confirmed `RUNNER_TIMED_OUT` and `RUNNER_CANCELLED`. In
addition, `tools/qualify_imagej.py` showed the following:

- A corrupted count mask, native table or reopened table is rejected even when
  its digest is refreshed.
- The Calc `readCSV` handoff preserves the unit-bearing columns in µm and mm,
  and all jobs are reused on resume.
- Changing the image bytes at the same path prevents reuse.
- The public agent protocol ran the baseline and millimetre cases and rejected
  the invalid example with its exact fault.

Commands (paths are placeholders):

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_imagej_admission -q
PYTHONPATH=src python3 tools/studio_guidance.py --app imagej --check
PYTHONPATH=src python3 tools/qualify_imagej_fixtures.py --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.imagej/1 --output-directory evidence/imagej-host
PYTHONPATH=src python3 tools/qualify_imagej.py --output-directory evidence/imagej-native \
  --java /path/to/java --jar /path/to/ij.jar --calc /path/to/soffice
# After central Help regeneration, with a private configuration holding
# imagej=/path/to/java and imagejJar=/path/to/ij.jar:
SCHEMAXIS_CONFIG=/path/to/private.json PYTHONPATH=src python3 -m schemaxis adaptor conform \
  schemaxis.imagej/1 --native --output-directory evidence/imagej-native-final
PYTHONPATH=src python3 -m schemaxis adaptor record evidence/imagej-native-final/qualification.json
```

## Integration review

The Studio starters now expose both threshold bounds for 8- and 16-bit images.
Previously their lower-bound forms allowed 16-bit intensities while the upper
bound was fixed at 255. Both templates now bind a 18000–65535 window correctly
against the 16-bit fixture; the focused admission suite passes all 16 tests.

## Open items and limits

- **Shared integration:** central regeneration of `docs/generated` and packaged
  Studio Help (`schemaxis reference`, `tools/generate_studio_help.py`) is
  needed. Then rerun native conformance and `adaptor record` (receipts go stale
  when Help changes).
- **Shared grammar:** `schemaxis configure` records only executables, so
  `imagejJar` has to be added to the private configuration by hand or passed
  with `--imagej-jar`. The shared release parser does not accept ImageJ's
  letter-suffixed versions.
- **Scope:** one plane and a manual inclusive threshold. No automatic
  thresholds, perimeter or shape descriptors, colour or stacks, and no Fiji
  plugins. Synthetic targets establish the declared semantics only. They make
  no claim about segmentation quality on experimental images.
- **Unqualified:** an R consumer of the particle table, other ImageJ 1.54
  releases, Fiji-bundled jars, non-Linux hosts and Java versions other than 21.
- **Domain review:** a domain reviewer should confirm the guide's wording on
  calibration practice and threshold choice.
