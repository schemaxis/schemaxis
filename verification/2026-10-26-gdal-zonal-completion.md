# GDAL zonalSummary completion note (2026-10-26)

Scope: new operation `zonalSummary` of the existing `schemaxis.gdal/1` route, its fields
(`zones`, `missing`, shared `source`/`epsg`/`units`/`nodata`/`lossPolicy`), the typed CSV and
JSON publications and the GDAL → Calc `readTypedCSV` handoff. The legacy `window` operation,
its worker (`native_worker.py`, unchanged so retained window receipts still verify), fixtures and
qualifier are not re-reviewed. This note records the author's checks; it is not an independent
review or acceptance, and the absorbed GDAL version stays 3.13.3.

Native basis: private conda-forge GDAL 3.13.3 (Python 3.12) and LibreOffice 26.8.1.1, no
system installation. Native algorithm: released `raster zonal-stats` through `gdal.Run`
(`stat=[count,min,max,sum,mean]`, `pixels=default`, `include_field=[zone]`, GeoJSON output); this
release has no Python wrapper class. Bulk transcripts stay in `evidence/` (not committed).

| Item | Result |
| --- | --- |
| registration | Same route and closed `operation` enum gains `zonalSummary`; `plan` keeps one root closed-key declaration over the union of both operations' fields plus an exact per-operation one, so the independent parser/schema parity test passes without borrowing schema keys. |
| schema | `oneOf` window/zonal branches with union root properties; generated schema/reference/Help regenerated. Zones: 1–16 `{id,x,y,width,height}`, closed items, booleans refused. |
| semantics | Host refusals before native work with stable codes and `$.zones[i]` locations: `INVALID_ZONE`, `ZONE_MISSING_VALUES`, `ZONE_SUM_UNRESOLVABLE`, `INVALID_RASTER_CONTENT` (asserted CRS/units/nodata), `RASTER_EXTENT_INVALID`. Tests: `tests/unit/test_gdal_zonal.py`. |
| native-mapping | `gdal.Run('raster','zonal-stats')` on trusted GeoJSON rectangles built from authored pixel indices and the source affine; fresh second process reopens `summary.geojson`/`zones.geojson` with OGR. |
| execution | Separate trusted worker `zonal_worker.py`; consumed inputs (source, zones, config, worker), submissions, stdout/stderr retained and bound; exact publication membership. |
| discovery | Capabilities entry, keywords (including `mean per zone`, `average per zone`) and six search cases (including a negative); natural sentence queries that share no curated term still find nothing, which is the existing keyword-matching behaviour. |
| guidance | Operation and all new field addresses, including `/oneOf` branches, written; `studio_guidance --check` passes. The operation and `docs/gdal.md` justify each of the eight CSV columns by what it measures (sample size, withheld pixels, measured fraction, spread, additive total, typical value); the Calc Summary needs are stated separately as a consumer property. Prose is the author's draft and still needs domain review; sum for non-additive quantities is the least settled judgement. |
| help | `docs/gdal.md#zonal-summaries`, regenerated reference and packaged Help. |
| examples | `gdal-zonal.json`, `gdal-zonal-temperature.json`, `gdal-zonal-invalid.json` (duplicate ID), two Studio templates, kit cases `zonal`, `zonal-geographic` and the edited variants `zonal-taller-north` (north rectangle grows a row) and `zonal-added-east` (a fifth zone is appended), all with hand-stated literal expectations. |
| tests | `test_gdal_zonal.py` (including a check that the published edit cases' literals equal an exhaustive stdlib pixel visit), updated Studio template test in `test_gdal.py`, parser parity. |
| qualification | `tools/qualify_gdal_zonal.py`: literals; 31 semantic mutants, each refreshed so every hash and receipt is consistent, then required to pass `publication_metadata.verify` before the adaptor verification must refuse with its exact stated code, full message and location (explicit constants, no fragment matching), plus a no-mutation refresh control that changes no retained byte and three no-refresh integrity controls and a tampered-metadata-companion control with their own exact faults; hostile inputs, native numeric probes (including an ordinary mixed-sign near-boundary zone, a partial-cancellation zone refused before any native process and native signed-zero publication); live cancel/timeout holds that record the owned process group while the victim is live and assert that it is gone after runner termination, before any safety-net cleanup; kit cases; Calc chains, including a changed zone and a changed crop window run as fresh workflows with hand-stated literal values (resume of a changed graph is refused; no same-directory invalidation claim). `tools/qualify_gdal_public.py` drives the same route through the public agent service: capability search, published context, draft authoring, baseline and edit cases, plan, execute, verify, paginated revision-bound snapshot inspection of the CSV, a refused missing policy, a wrong snapshot revision, a stale plan and an invalid plan, against hand-stated values; integer columns must be the exact canonical integer text and refusal codes and locations are asserted exactly. The workbook qualifier reports exact cell totals per format and combined against a hand count. No receipt is registered by this note. |
| maintenance | `assessment.json` intentionally untouched: its fingerprint is stale and the scores are not raised; `upstream.json` absorbed version unchanged. |

Independent oracle and bounds: the stdlib reader visits every included pixel; counts and
Float32/integer minimum/maximum are exact; native `sum` and `mean` are compared with the exact rational
sum of the stored values and accepted only within the derived allowances `(n-1)u/(1-(n-1)u)·Σ|x|`
(u = 2⁻⁵³) for the sum and `(that·(1+u)+u·|S|)/n` for the mean (which includes its final division),
never a fixed `1e-9`. Before native work a zone is refused (`ZONE_SUM_UNRESOLVABLE`) when either
allowance exceeds 2⁻²⁶ of the exact magnitude: a consistency threshold between native output and the host
oracle, not a scientific accuracy claim. The published sum is the correctly rounded exact sum and the
mean that sum divided by the count, so their own rounding is within `u` and `2u+u²` relative of the exact
values. Published zonal numbers never carry a signed zero; legacy window bytes are unchanged.

Limits: the SIGSTOP holds in the live timeout/cancel probes pause the real worker after it has
consumed its inputs; they do not prove a stop inside the GDAL library. No polygon, reprojection,
area weighting, MPI or solver claim. A zone refused as unresolvable has no partial publication. The
aggregate visit budget is 2 097 152 pixels: with up to 262 144 pixels per source, eight full-grid zones reach it
and nine exceed it. The CSV has no unit column. Calc evidence is LibreOffice 26.8.1.1
headless only. Remaining: independent review, parent integration of the shared test map and
assessment refresh, registered native receipt after acceptance.
