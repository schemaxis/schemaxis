# IfcOpenShell IFC4 wall schedule completion note (2026-10-26)

Scope: the new adaptor `ifcopenshell`, route `schemaxis.ifcopenshell/1`, operation
`scheduleWalls`, and the one appended workflow Studio record for its document
alternative. Candidate WF07 is a product hypothesis; no customer demand has been
demonstrated. The review covers this first slice only (plain `IfcWall`, ASCII IFC4,
`IfcPropertySingleValue`, length/area/volume quantities in plain SI units) and does not
re-review other adaptors. Generated references, packaged Help, the generated
assessment index and the workflow schema index are derived artifacts: they were
regenerated in this isolated candidate with the ordinary generators so it can be
reviewed complete, and the integrating parent regenerates them again after the union. `absorbedVersion` stays `null`
until the parent accepts the native evidence.

Native basis: IfcOpenShell 0.9.0.post1 (latest stable PyPI release checked 26 October
2026) in a private virtual environment; wheel identity comes from the pip install
report, with no publisher attestation. Verified behaviour of this release: plain SI
prefixes scale area and volume by the squared and cubed prefix (probed for MILLI), and
`get_pset(..., prop, should_inherit=True)` returns the whole type set when the
occurrence lacks the property, so the worker uses explicit non-inheriting lookups.

| ID | Result |
| --- | --- |
| registration | `adaptor.json` registers one route, runtime family `0.9.0.post1`, hooks `query`, `reusableInputs`, `resources`, `--ifcopenshell` option; no framework app-name branches (test asserts it). |
| schema | Closed document: source, class (IfcWall only), 2-6 typed columns, missing, inheritance, zeroQuantity; cross-field rules (property vs quantity members, duplicates, reserved names, type inheritance needs a property) with exact `INVALID_COLUMN` faults. |
| semantics | Independent stdlib STEP reader (`step.py`): bounded tokenizer, closed selected subgraph, exact Fraction conversion rounded once to binary64; refusals before any native process for schema, escapes, comments, complex entities, duplicate ids/GUIDs/sets/properties, dangling selected references (unselected cycles and dangling references are unassessed), ambiguous types and units, unsupported units/entities/properties, type mismatch, empty/negative/zero values. |
| native-mapping | `worker.py` uses `ifcopenshell.open`, `by_type(include_subtypes=False)`, `util.element.get_pset(should_inherit=False)`, `get_type`, `util.unit.calculate_unit_scale`; API URLs in `readiness.json`. Losses listed in `docs/ifcopenshell.md`. No geometry, selectors or code. |
| execution | Trusted launchers bind inputs by hash and fix the environment and caps; extract and fresh-reopen stages; tables must be byte-identical and agree with the host oracle; offline `verify` rebuilds publications and launches nothing. Live SIGSTOP-held native interpreter cancelled and timed out (qualifier). |
| discovery | `search-cases.json` (synonym, multiword and two negative cases) and `capabilities.py` curated terms. |
| guidance | `guidance.json`: operation and all 20 route fields written with sources; author-written and not independently domain-reviewed by a BIM specialist. Workflow record appended at its registry-derived position. |
| help | Local guide `docs/ifcopenshell.md`, packaged into Studio Help by `tools/generate_studio_help.py`; reference, Help, assessment parity, `studio.help` admission and the node search acceptance pass on this candidate. |
| examples | Studio baseline and variant, four runnable examples, four invalid examples, original synthetic fixtures with a deterministic generator (`tools/author_ifcopenshell_fixtures.py --check`). |
| tests | `tests/unit/test_ifcopenshell.py` host tests; native qualifier `tools/qualify_ifcopenshell.py` with literal expectations, pre-native controls, fully refreshed semantic mutants, live lifecycle, Calc typed handoff with independent ODF/OOXML readback, and shared conformance cases. The public-protocol loop (author, edit, plan, run, verify, inspect through resources) is part of the qualifier. Not done: new Studio browser UI tests. |
| qualification | Receipt produced by the shared kit in the allocation evidence only; nothing is registered here, so the route is not recorded as native-qualified in this tree. |
| maintenance | `upstream.json` (latest-stable, `absorbedVersion: null`), `assessment.json` dated 2026-10-26 with source fingerprint, low-confidence subjective scores (coverage 5, abstraction 40). |

Post-review repair (2026-10-26): the first independent review found that the host STEP reader built an exact
fraction for every numeric token (so a 12-byte `1.E30000000` consumed minutes of CPU before any native process
and ahead of the run deadline) and crashed on tokens over Python's 4300-digit limit (reported as a native
failure). The reader now applies a declared lexical budget to every number and `#id` in the file before any
conversion (40 mantissa digits, exponent magnitude 400 in at most 4 digits, 10 id digits; `STEP_RESOURCE_LIMIT` with
bounded facts), builds exact fractions only for selected values, requires Part 21 INTEGER or REAL syntax, and labels
an unexpected host failure before any native launch `HOST_EXECUTION_FAILED`. Retained native `scales`, `typeGuid`
and property `raw` values are now compared with the independent walk (strict cell types), the identity pins the
`util/element.py` and `util/unit.py` hashes of the qualified release, a property-only schedule works without project
units, and the number representation and the Calc magnitude limit are documented. The native evidence for this
tree is only the repaired-source run recorded in the allocation evidence; earlier native runs are not carried over.
The second independent review accepted that repair with five P3 follow-ups.

Recovery (2026-10-26) closes those follow-ups without changing the numeric guards or the native comparison:
- Keyword and type names from the file are bounded in structured faults (whole up to 64 characters, otherwise a
  48-character prefix and the true length as `nameCharacters`; the entity reference or offset is an observed field, not
  the location); a host test covers eight placements with 5,000-character names and an ordinary 45-character class name.
- The recorded parse cost is corrected: a near-2MiB worst case measured by the reviewer took about 1.7 s and 100 MB
  (not the 0.35 s quoted for 1MB). It is a measurement, not a guarantee.
- Host numeric capacity (`IfcInteger` to 2^53, ids to 10 digits, any finite binary64) is documented as not
  native-qualified at the extremes; the run refuses as `NATIVE_DISAGREES` if the library disagrees, and published
  values come from the host walk.
- The property-only schedule with `UnitsInContext $` now has fresh native evidence: the qualifier runs it directly
  (literal CSV, native scales `{}`, type GUIDs and raw cells compared with hand-stated literals) and through the
  public protocol (hand-stated CSV and JSON literals). It replaces the exploratory run that was moved after it was made.

Follow-up (2026-10-26) closes the three optional P3 items of the recovery review without changing the numeric guards, any
successful path or the native comparison: the `prefix` and `name` enumerations of a refused project unit go through the
same bounded name helper (the unit type and the fault location are kept); the documentation no longer calls the
reference or offset the fault location; the host test expects the literal 48-character prefix, and a new host test covers
the wrong-argument-count message.

Not qualified: IfcOpenShell behaviour at the numeric extremes, other classes of whole-building use (geometry,
relationships, materials, other schemas), and any quantity accuracy or geometry validity.

Unresolved: independent Opus review of the repaired source; parent regeneration of reference, Help,
assessment index and workflow schema after the union; parent-side native freshness and
registration; shared browser checks of the Studio template, insert, undo and Help.
