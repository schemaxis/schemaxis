# pyproj route chainage

`schemaxis.pyproj/1` provides one operation, `routeStations`. It stations an ordered route of
WGS84 longitude/latitude waypoints at true ellipsoidal (geodesic) distances, continuously across
the turning points. It publishes labelled station and leg tables, station and route GeoJSON, a
host-owned summary and an independent verification record.

Typical uses are desk-study and planning chainage for long linear assets that cross UTM or MTM
zones, length limits for a route, and loop or transect closure checks.

It is **not** survey stakeout or measurement. No datum, CRS, epoch, height or geoid
transformation is applied. No survey, measured-position, physical or regulatory accuracy is
claimed.

## What routeStations does

1. Captures the waypoint CSV bytes and parses them strictly to binary64 values.
2. Refuses every conclusive domain problem on the host, before any native process starts.
3. Runs isolated pyproj 3.8.0 / PROJ 9.9.0 in two stages:
   - **compute:** `Geod.inv` for each leg and for a requested endpoint gap, then `Geod.fwd` for
     each fixed station;
   - **readback:** the worker reopens its publications and checks native self-consistency.
4. Re-evaluates every leg, station, consecutive step and requested gap with an independent
   standard-library oracle, then decides any requirements on the host.

Only a run whose requirements are met (or that declares none) is an accepted deliverable.

## Runtime, public API and maintenance

The native runtime is exactly **pyproj 3.8.0 with PROJ 9.9.0 on Python 3.12.15**, POSIX, one
thread. Configure it as an absolute isolated interpreter with `--pyproj` (or
`schemaxis configure pyproj /absolute/env/bin/python`). The host never imports pyproj.

The worker enforces the following:
- PROJ network access is disabled through `PROJ_NETWORK=OFF` and
  `pyproj.network.set_network_enabled(False)`, and the setting is read back.
- HOME, XDG and PROJ user directories point to an empty run-private directory, which
  verification requires to remain empty.
- `Geod(ellps='WGS84')` must read back `a = 6378137` and `f = 1/298.257223563`.

Other pyproj or PROJ builds are refused (`UNSUPPORTED_GEOD_RUNTIME`).

Public API sources:
- [pyproj Geod](https://pyproj4.github.io/pyproj/stable/api/geod.html)
- [pyproj network](https://pyproj4.github.io/pyproj/stable/api/network.html)
- [pyproj history](https://pyproj4.github.io/pyproj/stable/history.html)
- [PROJ geodesic calculations](https://proj.org/en/stable/geodesic.html)
- Karney (2013), [Algorithms for geodesics](https://doi.org/10.1007/s00190-012-0578-z)
- [RFC 7946 GeoJSON](https://www.rfc-editor.org/rfc/rfc7946)

`src/schemaxis/adaptors/pyproj/upstream.json` records the absorbed version. A new release
needs its own bounded native acceptance with `tools/qualify_pyproj.py`.

## Start with the Winnipeg route

`examples/schemaxis/pyproj-winnipeg-route.json` stations Winnipeg City Hall → Selkirk →
Lockport every 1 km and requires a total length of at most 50 km. Replace the CSV path, then
run:

```sh
schemaxis run examples/schemaxis/pyproj-winnipeg-route.json --output-directory runs/route --pyproj /absolute/env/bin/python
schemaxis verify runs/route
```

The route has 2 legs (33,092.27 m and 7,416.65 m) and 43 rows. The total is 40,508.917 m with a
numerical band of about 2 µm, and the requirement is `met`. Stations continue across the leg
boundary: the station at 35 km lies 1,907.73 m into leg 2.

Other examples:
- `pyproj-winnipeg-loop.json` closes a triangle back to its first waypoint.
- `pyproj-equator.json` checks exact equatorial arcs: the length is a × Δλ and the azimuth is
  exactly 90°.

## Waypoint CSV and coordinates

The source is an absolute local `.csv` of at most 1 MiB with 2–500 waypoints in route order.

- **Header:** exactly `lon_deg,lat_deg` or `name,lon_deg,lat_deg`. Longitude comes first, and a
  latitude-first header is refused, never guessed.
- **Cells:** plain decimal numbers. Spaces, `nan`, `inf`, separators and blank lines are refused
  with their line.
- **Names:** use ASCII letters, digits, spaces and `._()+/-`, at most 40 characters.
- **Coordinates:** the captured decimal text is retained, but all arithmetic uses its correctly
  rounded binary64 values, not exact decimal arithmetic.

`ellipsoid` must be `WGS84` and `coordinateOrder` must be `lonLat`. A sphere or other ellipsoid
is never substituted.

Consecutive waypoints must differ. A route whose last waypoint repeats its first is refused as
ambiguous: declare `closed: true` and omit the repeat.

## Supported domain

- Every point of every leg stays within |latitude| ≤ 75°. This covers the waypoints and the
  Clairaut vertex when the azimuth passes ±90°.
- No leg crosses or touches the antimeridian: longitudes lie strictly inside (−180, 180), and a
  leg with |Δλ| ≥ 180° is refused.
- Legs are 0.01 m to 5000 km and the total is at most 20,000 km.
- At most 10,000 rows are published; spacing is 0.1 m to 1000 km.

The host refuses only when the outcome is certain. It uses a chord lower bound and a
meridian-plus-parallel upper bound. The native worker then refuses the exact remaining cases,
and the host accepts a native domain refusal only after the independent oracle reproduces it.

## Chainage, stations and merging

- **Chainage:** chainage at waypoint *i*+1 is `math.fsum` of the native leg lengths, a correctly
  rounded prefix sum.
- **Fixed stations:** a station lies at chainage `k × spacing_m` (k = 0, 1, …) while strictly
  below the route end.
- **Waypoints and merging:** every waypoint is a row. A waypoint becomes a single
  `waypoint+station` row (kind 3) only when its chainage equals `k × spacing_m` **bitwise**.
  There is no tolerance merge.
- **Final row and interval:** the final row is the last waypoint. `finalInterval_m` is the
  distance from the last fixed station to the end.
- **Row leg and offset:** each row belongs to its outgoing leg (the final row to the last leg),
  and `offset_m` is the chainage minus the leg start.
- **Positions:** waypoint rows republish the captured binary64 coordinates exactly. Station rows
  come from `Geod.fwd`.
- **Azimuths:** degrees clockwise from geodetic north, in [0, 360). Station rows carry the
  forward azimuth at the station. The leg table publishes the start azimuth, the end azimuth
  (direction of travel) and the back azimuth (end → start = end − 180°).
- **Deflection:** deflection at an interior waypoint is clockwise-positive. A closed route also
  reports a closure deflection.
- **Labels:** `km+mmm.mmm`, rounded to the millimetre. **Numeric chainage is authoritative.**

**Consequence of exact merging (worked example).**

- **The setup:** leg 1 of the Winnipeg route is 33,092.269933878 m. With
  `spacing_m = 11030.756644625997`, the third station lands at 33,092.26993387799 m, one
  binary64 step below the waypoint's chainage.
- **One ulp below:** the publication contains a station row and then a waypoint row about
  7.3e-12 m apart. Both carry the label `33+092.270`, and `finalInterval_m` is 7.276e-12 m. The
  summary reports `presentation.adjacentRowsWithIdenticalLabels = 1`.
- **One ulp above:** no third station is created, and the final interval is almost a full
  spacing.
- **Exact multiple:** with `spacing_m = L/2` the final row is kind 3 and `finalInterval_m` is 0.

## Outputs

| File | Kind | Content |
|---|---|---|
| `stations.csv` | table | `row,chainage_m,lon_deg,lat_deg,leg,offset_m,azimuth_deg,kind,waypoint`. Integer index columns; kind 1 station, 2 waypoint, 3 both; waypoint 0 when the row is not a waypoint. |
| `legs.csv` | table | `leg,from_waypoint,to_waypoint,length_m,start_chainage_m,end_chainage_m,azimuth_start_deg,azimuth_end_deg,back_azimuth_deg` |
| `stations.geojson` | geospatialVector | RFC 7946 Points with label, chainage, leg, offset, azimuth, kind, waypoint, name and deflection. There is no `crs` member. |
| `route.geojson` | geospatialVector | One LineString per leg through its published rows. Segments between vertices are straight in longitude/latitude, **not geodesic**. |
| `route-summary.json` | text | Host decision, total length, `lengthNumericalBand_m`, `finalInterval_m`, endpoint gap and `endpointGapNumericalBand_m` (null unless requested), presentation, deflections, numerical model, host-contract consumer notes and losses. |
| `route-verification.json` | text | Bindings (source, parsed waypoints, plan, configuration, native files, runtime observation, interpreter path digest, implementation, summary), oracle evidence, agreement and adequacy ratios, and the decision. The interpreter path digest is provenance only (see [Saved verification, export and reuse](#saved-verification-export-and-reuse)). |

## Requirements and acceptance

- `requirements.totalLength_m` takes `minimum` and/or `maximum` metres.
- `requirements.endpointGap_m` takes `maximum` metres and applies to open routes only.

The host decides each requirement against a numerical band:
- **met:** the whole interval value ± band satisfies the bound;
- **unmet:** the whole interval violates it;
- **indeterminate:** anything else; the state is never forced.

The bands are:
- total length: Σ τ(leg) + u·L;
- endpoint gap: τ(gap).

An unmet or indeterminate requirement still writes and retains all evidence. However, the run
fails with `ROUTE_REQUIREMENT_NOT_MET` or `ROUTE_REQUIREMENT_INDETERMINATE` at the requirement's
location, saved verification reproduces that fault, and workflows cannot consume the run.
Native output never carries a requirement state; the host recomputes the decision on every
verification.

## Endpoint gap

The endpoint gap is the geodesic from the last waypoint back to the first. It is computed only
when `endpointGap_m` is requested; otherwise it is published as `null`.

It must lie inside the same domain as a leg: at most 5000 km, no antimeridian crossing or
touching, and the whole geodesic within the latitude band. Otherwise the run is refused with
`ENDPOINT_GAP_OUTSIDE_DOMAIN` at `$.requirements.endpointGap_m` **before any numerical
comparison**. The refusal comes from the host (conclusive bounds), the native exact check, or
saved verification (the oracle's qualified cap and vertex).

There is no 1 cm minimum: near-coincident gaps resolve, and a bound inside the band is reported
as indeterminate.

## Numerical model and independent verification

- **Implementations:** PROJ (GeographicLib algorithms) and the verifier are separate
  implementations of the same auxiliary-sphere theory. The verifier evaluates the exact integrals
  by Gauss–Legendre quadrature and solves direct and inverse problems by Newton iteration.
- **Anchors:** the verifier is anchored by formulation-independent checks: exact equatorial
  arcs, meridian arcs by quadrature over geodetic latitude, and an RK4 integration of the
  geodesic equation on the ellipsoid surface (`anchors.py`).
- **Sub-millimetre regime:** separations under 1 mm use a local-metric regime with a stated
  curvature term. It agrees with the Newton evaluation to a few nanometres at the switch.

**Tolerance and adequacy.** The tolerance is τ(s) = 1 µm + 1e-12·s. Station positions are
allowed 2τ(leg) and consecutive steps 4τ(leg). Before any agreement check, every independent
evaluation must resolve to τ/10 at its own distance scale:

| Evaluation | Error budget | Must not exceed |
|---|---|---|
| Leg inverse | inverse error | τ(leg)/10 |
| Endpoint-gap inverse | inverse error | τ(gap)/10 |
| Station forward | direct residual + rounding estimate at the offset + leg inverse error propagated to the station | τ(leg)/10 |
| Consecutive inverse | inverse error | τ(step)/10 |

If any evaluation fails this adequacy rule, the whole run fails with
`VERIFICATION_INDETERMINATE`, even when no requirement is declared.

**What the agreement means.** It is numerical agreement only. It is conditional on parsed
binary64 coordinates, the qualified local shortest geodesic and the stated floating-point/libm
rounding model (about one ulp). The curvature and rounding allowances are engineering
estimates, not certified intervals. Native readback is self-consistency only, never independent
proof.

## Saved verification, export and reuse

`schemaxis verify` recomputes the whole host record and requires it to be bitwise equal to the
retained `route-summary.json` and `route-verification.json`. It also checks the following:
- the captured source and its identity;
- the trusted worker bytes and the exact relative command `python -I -B native-worker.py STAGE`;
- consumed-input and evidence digests;
- the native runtime observation;
- the empty private home;
- portable publication membership.

Re-verification is qualified on the producing host and libm. Recorded receipt paths and native
commands are not rewritten. A canonical schema-aware export (`export_run`), or a re-export of
that export, verifies through the normal `schemaxis verify` path from the retained capture after
the original CSV has been physically removed or changed. This was exercised for single runs, a
scheduled workflow and a common study. Cross-host or cross-libm re-verification is **not
qualified**.

The source bytes (`reusableInputs`) participate in reuse identity, so same-path edits or
removal invalidate new runs and reuse.

The `retainedInputs` hook is a lookup of complete saved-input provenance, used by the framework
**after** ordinary native verification has succeeded. It returns the original path and SHA-256
only after checking three things: the retained capture matches the effective document, the
retained bytes match, and the host record's source binding matches. It never rereads the
original. It does **not** re-verify the host record itself, so it is not a standalone
authenticator: call it only after `schemaxis verify` (or the framework's equivalent) has
succeeded on the same run.

**What the provenance bindings prove, and what they do not:**

- **Interpreter path digest:** `executablePathDigest` in `route-verification.json` is the
  SHA-256 of the interpreter **path string**. It is provenance only. It does not attest the
  executable's contents, or that a historical process ran that file.
- **Runtime evidence:** the runtime evidence is the exact runtime observation written by the
  trusted worker and required on every verification (pyproj 3.8.0, PROJ 9.9.0, Python 3.12.15,
  WGS84 `a` and `f`, network disabled), together with the trusted worker bytes and the exact
  relative command. These are bounded consistency checks on retained evidence, not
  cryptographic proof of what executed.
- **Implementation binding:** saved verification requires the digests of the five
  implementation modules (`adaptor.py`, `contract.py`, `geodesy.py`, `verifier.py`,
  `native_worker.py`) to equal the current code exactly. Any later edit to those files,
  including a comment-only change, makes every older run fail saved verification ("pyproj
  adaptor implementation changed"), and the run must be repeated with the current code. This is
  intended: retained results are only re-verified by the code that produced them.

If a workflow's `result.json` and `job.json` input hashes are both forged to claim different
source bytes, saved verification fails ("job input hashes differ from verified retained
inputs"). On resume, such an attempt is not reused: a fresh attempt captures the current bytes,
and the source path, effective document and handoffs stay identical.

## Workflows and consumers

Publications hand off by index: 0 `stations.csv`, 1 `legs.csv`, 2 `stations.geojson`,
3 `route.geojson`, 4 `route-summary.json`, 5 `route-verification.json`. See
`pyproj-qgis-workflow.json` (route GeoJSON into QGIS `readVector`) and
`pyproj-calc-workflow.json` (stations into Calc `readCSV`).

These consumer handoffs are checked against the host contracts only; this adaptor's
qualification does not run native QGIS or LibreOffice. Note the consumer limits:
- Calc `readCSV` needs at least two rows, so a single-leg `legs.csv` is refused.
- Gnuplot plots chainage profiles of at most 2,048 rows. It does not draw lon/lat maps, because
  its x values must strictly increase.

## Faults and recovery

| Code | Location | Recovery |
|---|---|---|
| `INVALID_ROUTE_CSV`, `ROUTE_WAYPOINT_LIMIT`, `ROUTE_FILE_LIMIT`, `ROUTE_COINCIDENT_WAYPOINTS` | CSV line | Fix the capture as described |
| `UNSUPPORTED_GEOGRAPHY` | CSV line or `leg i` | Keep within the band; split at the antimeridian |
| `UNSUPPORTED_ELLIPSOID`, `INVALID_ARGUMENT`, `INVALID_REQUIREMENT`, `REQUIREMENT_NOT_APPLICABLE` | document field | Correct the declaration |
| `ROUTE_CLOSURE_AMBIGUOUS` | `$.source` | Omit the repeated first waypoint; set `closed` |
| `ROUTE_LEG_TOO_LONG`, `ROUTE_LEG_TOO_SHORT`, `ROUTE_LATITUDE_EXCURSION`, `ROUTE_TOTAL_TOO_LONG`, `ROUTE_ROW_LIMIT` | `leg i`, `$`, `$.spacing_m` | Add or merge waypoints, split, or increase spacing |
| `ENDPOINT_GAP_OUTSIDE_DOMAIN` | `$.requirements.endpointGap_m` | Remove the gap requirement or add the closing path as legs |
| `VERIFICATION_INDETERMINATE` | evaluation | Agreement cannot be established; nothing is accepted |
| `GEODESIC_VERIFICATION_FAILED`, `VERIFICATION_FAILED` | evaluation or file | Native output disagrees or evidence was altered; rerun |
| `ROUTE_REQUIREMENT_NOT_MET`, `ROUTE_REQUIREMENT_INDETERMINATE` | requirement | Evidence retained; not an accepted deliverable |
| `UNSUPPORTED_GEOD_RUNTIME`, `INTERPRETER_NOT_FOUND` | runtime | Configure exactly pyproj 3.8.0 / PROJ 9.9.0 |

## Limits

- Only the WGS84 ellipsoid, longitude-first input and the bounded domain above are supported.
  There is no polar, antimeridian, cross-track or chainage-origin support.
- GeoJSON lines are not geodesic between vertices.
- Bands and adequacy budgets are conditional engineering estimates.
- Saved verification is same-host only.
- Consumer evidence is host-contract only.
