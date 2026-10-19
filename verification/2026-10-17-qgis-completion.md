# QGIS attribute workflow completion

This slice adds typed `selectAttributes` with inclusive feature-count requirements
and `summariseAttributes` count/nonNullCount/sum/mean side tables. Selection keeps
surviving geometry, CRS and original attributes; summary keeps the incoming vector
unchanged and publishes typed JSON, CSV and a separate no-geometry GeoPackage
loaded into the saved project. The original one-layer vector GeoPackage handoff
remains available. Unique nonempty string semantic IDs trace every member; storage
`fid` is excluded. Groups use nullable string keys, deterministic null-first order
and sorted member IDs. Units are explicit annotations without conversion.

Count includes every member; nonNullCount counts numeric nonnull values. Sum/mean
ignore null and return null for an all-null group. Boolean is not numeric. Sum uses
`math.fsum`, and mean divides by nonNullCount; outputs are binary64, with rounding
and finite overflow limitations rather than exact decimal accounting guarantees.

Official sources checked on 17 October 2026 identify **4.2.3** as latest stable:
[release identity](https://qgis.org/version.txt),
[installation and Qt6 transition](https://qgis.org/resources/installation-guide/).
The newly executed runtime is QGIS **4.2.3-Belém do Pará**, Qt **6.11.2**, Python
3.12 from isolated community conda-forge packages. Package URLs/hashes and bootstrap
provenance are retained locally. Optional PDAL HDF/icebridge plugins report a
missing HDF C++ library; those plugins and all raster/point-cloud routes are outside
this OGR vector/table qualification. No system installation or PATH change occurred.
The historical QGIS 3.34.4 evidence remains historical; the new implementation uses
one compatible QGIS 3/4 API path, with fresh acceptance on 4.2.3 only.

| Checklist item | Result and bounded evidence |
| --- | --- |
| registration | Existing `schemaxis.qgis/1` route, process isolation and vector input/handoff preserved; summary table side products declared. Optional feature decisions retained. No native imports in host discovery/planning. |
| schema | Closed typed predicate/aggregate objects, bounded arrays, named source/output fields, literal values, defaults and explicit count requirements; authored value resolution precedes validation. Host schema/default/determinism conformance passes. |
| semantics | Strict number/string/Boolean comparisons, null exclusions, AND, numeric ordering, ID uniqueness, case-insensitive output-column uniqueness, forbidden storage IDs, group type, explicit units and overflow rejection. Exact field/type/count fault locations retained. |
| native-mapping | Public QgsFeature attribute/geometry, QgsFields, QgsVectorDataProvider field/feature insertion and QgsVectorFileWriter APIs; each summary table is independently reopened and included in fresh project readback. Public API links are in the guide/development metadata. |
| execution | Native build and fresh project reopen on 4.2.3; CSV/JSON/actual SQLite table content checked offline. Captured source hashes, worker/helper files, submission logs, artifact membership and common schema references retained. Timeout and post-submission cancellation retain failed results. |
| discovery | Curated attribute-filter, feature-selection, regional-total and group-summary terms; ambiguous attributes and negative raster-elevation cases. Actual CLI capability/admission and all 89 production Studio search tests pass. |
| guidance | 88 reviewed field/operation records and 16 retained attributed references; zero pending/stale records. Every nested predicate/aggregate field describes meaning, units, omission, valid choices and mistakes. Binary64 limitations are explicit. |
| help | Local guide and public method links updated; shared supervisor generates references/contextual Help. Readiness verifies every operation has packaged Help; final generation freshness is part of supervisor integration. |
| examples | Editable baseline, strict-boundary variant, rejected typed literal, local nine-feature fixture and filled/unfilled Studio asset-summary starter. Twelve dedicated host tests exercise these contracts and independent arithmetic. |
| tests | 12 dedicated host tests pass; existing media/geospatial suite passes 30 tests with one explicit unrelated native prerequisite skip. Host conformance covers six old/new native recipes. Independent native tool passes baseline, strict/lower thresholds, grouping/source variants, native negatives, misleading evidence, cancellation/timeout and workflow reuse/invalidation. |
| qualification | Fresh source-bound common native conformance passed six old/new cases plus timeout/pre-launch cancellation after the shared source freeze and was registered. Native assertions remain limited to named fixtures and runtime, never exhaustive GIS qualification. |
| maintenance | Latest stable target resolved from official QGIS source. Absorbed version advances only after host and fresh native acceptance; exact recipe, runtime/provenance and limitations retained in upstream metadata. |

The independent fixture oracle selects **b,c,e,g,h,i** for score >=20 and **e**
for >20. Null-key e totals 2 kW; empty-string-key i totals 3 kW; group `empty`
contains h with count 1/nonNullCount 0 and null sum/mean. Northern b/g has count 2,
nonNullCount 1, sum/mean 6 kW. Lowering the threshold to >=10 yields northern
members a,b,f,g: count 4, nonNullCount 3, sum 7 kW and mean 7/3 kW (absolute and
relative tolerance 1e-12). Changed grouping checks singleton membership and all
arithmetic; changed source load changes north to 10 kW. Every surviving point's
literal source coordinate and full attributes are checked against fresh native
readback, beyond file hashes or feature counts.

Native rejection covers missing fields, declared-type mismatch, duplicate IDs,
mixed numeric/text data, numeric grouping, unexpected feature counts and an
invalid explicit EPSG CRS. That CRS probe exposed an OGR fallback: invalid
EPSG:999999 originally logged errors but became EPSG:4326. The reader now
independently resolves an explicitly named GeoJSON CRS and requires the provider
to preserve it. GeoJSON without a CRS retains its format-defined EPSG:4326 default.
A second discovered regression padded both map axes when only one was degenerate,
which could hide collinear features; padding now preserves the nondegenerate axis.
Both failed development runs are retained, followed by passing cases.

Refreshed ordinary metadata/evidence digests cannot hide false selected member
IDs, false means, all-null totals changed to zero or changed captured attributes.
The timeout probe uses an actual submitted process with a 0.001 second budget.
Cancellation waits for owned process submission; it does not claim QGIS
initialisation completed. A real scheduled vector handoff reopens the producer's
one-layer GeoPackage, reuses unchanged jobs, and creates new immutable attempts
for both jobs after source modification while retaining the old attempts.

The geometry trust boundary is explicit: native build reads captured source
geometry and copies each selected QgsGeometry; a distinct native process reopens
the saved project and compares complete output WKB, attributes, CRS and tables.
The independent point oracle checks source coordinates against that reopened
native observation. Offline verification independently reads captured attributes
and SQLite table data and replays selections/summary arithmetic; its geometry
comparison uses retained native WKB snapshots. It cannot authenticate a coordinated
forgery of all native geometry observations. Successful process exit, matching
snapshots, hashes or offline checks alone are never described as new native proof.

Local bulk evidence: `evidence/programme-20261017/qgis-attributes-final/report.json`,
`qgis-search-studio.log`, `qgis-host-2/qualification.json`, `qgis-final-native/qualification.json`, `qgis-legacy-buffer-native`, `qgis-readiness.log` and
`runtimes/qgis/provenance.json`. The native recipe is:

```sh
PYTHONPATH=src python3 tools/qualify_qgis_attributes.py \
  --qgis /absolute/configured-qgis-python --output-directory /fresh/attribute-evidence
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.qgis/1 \
  --native --executable /absolute/configured-qgis-python --output-directory /fresh/native-kit
```

No MPI, GUI reverse synchronisation, arbitrary expression/SQL/Python execution,
spatial joins, numeric/Boolean grouping, raster/point-cloud processing or exact
decimal aggregation is added. Existing unsupported optional features remain
explicit in readiness metadata. Shared schema retention uses the common runtime
boundary and creates no separate adaptor-owned store.

Final native kit registration passed against source digest
`sha256:64dae156e55a8b1557c230011926cccd50d079f505821c7add8f86a19c5602e1`.
Its six cases retain existing import/reprojection/clip/projected-centroid behaviour
and the attribute baseline/strict boundary. A separate fresh legacy buffer/clip
run confirmed EPSG:3857, the east source name and exact 2500 square-metre area.
AbsorbedVersion advanced to 4.2.3 only after these host/native checks passed.
