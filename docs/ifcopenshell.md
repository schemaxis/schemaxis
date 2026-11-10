# IfcOpenShell IFC4 wall schedule

The `ifcopenshell` adaptor schedules the **plain `IfcWall` occurrences of one small
ASCII IFC4 file**: one row per wall, linked by `GlobalId`, with the property-set values
and quantities you name, an explicit origin for every cell (occurrence, type or
missing) and project SI units converted to metres, square metres and cubic metres.
It publishes an editable typed CSV and a metadata-rich JSON schedule. It is a draft
for BIM coordination review: it does not compute or validate geometry, certify a
model, check compliance, safety or cost, or validate the whole IFC file.

This workflow is a product hypothesis (a BIM coordinator reconciling captured IFC
identities with declared properties and quantities); no customer demand has been
demonstrated. The first slice is deliberately one coherent family: `IfcWall`.

## Operation `scheduleWalls`

```json
{
  "version": "schemaxis.ifcopenshell/1",
  "operation": "scheduleWalls",
  "source": {"path": "/abs/model.ifc"},
  "class": "IfcWall",
  "columns": [
    {"name": "Fire rating", "source": "property", "set": "Pset_WallCommon", "property": "FireRating", "valueType": "text"},
    {"name": "Length (m)", "source": "quantity", "set": "Qto_WallBaseQuantities", "quantityName": "Length", "quantity": "length"}
  ],
  "missing": "null",
  "inheritance": "occurrence-overrides-type",
  "zeroQuantity": "accept"
}
```

Every field is explained in Studio guidance; the essentials:

- **`source`**: an absolute local `.ifc` path (optionally pinned by SHA-256). The file
  is captured into the run; all later checks use the captured copy, so the schedule
  stays verifiable offline when the original is gone.
- **`columns`** (2 to 6): each is a `property` (an `IfcPropertySingleValue` in an
  `IfcPropertySet`, `valueType` text, number or boolean) or a `quantity` (an
  `IfcQuantityLength`, `Area` or `Volume` in an occurrence `IfcElementQuantity`).
  Names are exact. There are no selector expressions, code or geometry options.
- **`missing`**: `refuse` stops with the wall `GlobalId` and column named; `null`
  publishes an empty typed cell with origin `missing`. A missing value is never zero.
- **`inheritance`**: `occurrence-only` never reads the wall type;
  `occurrence-overrides-type` reads the wall type's property set only when the
  occurrence has no such property. Quantities are never inherited.
- **`zeroQuantity`**: `accept` or `refuse` a stored zero. Negative quantities and
  empty text are always refused.

## Outputs

`ifc-schedule.csv` (kind `table`) is the canonical typed CSV: header `GUID`, `Name`,
then your columns; text and labels are always quoted (so `0123`, `+note` and `=x`
stay literal), numbers use the shortest round-trip decimal, and a missing value is
the bare null token `\N`. Rows are sorted by `GlobalId` ascending. `Name` is nullable
literal text and never an identity. `ifc-schedule.json` (kind `text`) carries the
source hash and schema, selection and policies, units, column declarations, every cell
with its origin, counts of unassessed entity classes, the runtime identity and the
review statement. Calc `readTypedCSV` can bind the CSV directly: declare the same
columns, set `nullToken` to `\N`, and note that Calc requires at least two present
values in every number column.

## Scope and losses

- ASCII STEP only, at most 2MiB, 4096 entities, 256 characters per string, 64 walls
  (at least 2). `FILE_SCHEMA` must be exactly `IFC4`; IFC2X3, IFC4X3 and multiple
  schemas are refused. Backslash/Unicode escapes (`\X2\`), comments and complex
  entities are refused before any native process runs. The "256 strings" budget is
  read here as 256 characters per string, with at most 8192 strings in total.
- Numeric budget, checked from the token text before any integer, fraction or power is
  built and applied to **every** number in the file (header, unselected and selected
  alike): at most 40 mantissa digits (leading zeros count), an exponent of at most 4
  digits and magnitude 400, and `#` ids of at most 10 digits. Values are never
  truncated or coerced; an over-budget token is refused as `STEP_RESOURCE_LIMIT` with
  its character count, a 16-character prefix and its offset, not the whole token. Every
  finite binary64 value, including subnormals, fits inside the budget; very long exact
  decimals (more than 40 digits) and exponents beyond 400 are unsupported by design. A
  token inside the budget that binary64 cannot hold is still `NUMBER_RANGE`.
- Parse cost is bounded by the file and token budgets, not proven: the reader has no
  mid-parse cancellation check. An independent review measured one worst-case file near
  the 2MiB cap (about 970,000 small integer tokens) at roughly 1.7 s and 100 MB of
  memory on one machine; an earlier 0.35 s figure for a 1MB file understated it. These
  are measurements of one file on one machine, not a guarantee.
- Host numeric capacity is not native capacity. The host reader accepts `IfcInteger`
  exactly up to 2^53, `#` ids of up to 10 digits (above 2^32) and any finite binary64
  real. Whether IfcOpenShell returns such extreme values unchanged has **not** been
  qualified; the native evidence uses ordinary values. If the native library disagrees
  at an extreme, the run refuses as `NATIVE_DISAGREES` after the native step, and the
  published values are always those of the independent host walk of the source. The
  strict host guards and the native scale, type and raw comparison were not loosened
  to match the native side.
- A keyword or type name taken from the file is repeated in a fault whole up to 64
  characters (every IFC4 class name fits); a longer name appears as its first 48
  characters and its true length (`nameCharacters`). The fault location stays the
  entity, `header` or `data`; the entity reference or the byte offset of the
  duplicate header keyword is an observed field of the fault, not its location. The
  `prefix` and `name` enumerations of a refused project unit are bounded the same way
  (`prefixCharacters` and `nameCharacters` give the true lengths), and the fault keeps
  the unit type and its location. The published JSON still lists unassessed entity
  classes by their names, unshortened.
- Number syntax follows Part 21: an INTEGER is digits; a REAL has a decimal point and an
  optional upper-case `E` exponent. `25E2`, `1.e5` and `1E5` are `STEP_SYNTAX`. Quantity
  values and `IfcReal` must be REALs (`2500.`), and `IfcInteger` must be an integer;
  `2500` as a quantity is a `TYPE_MISMATCH`. Whether IfcOpenShell would accept the
  non-STEP forms was not tested, so they are refused rather than normalised.
- Numbers publish as shortest round-trip binary64 text: an `IfcInteger` 7 appears as
  `7.0` (integers up to 2^53 are exact), and `1.E16` as `1e+16`. The IFC schedule
  accepts any finite binary64, but Calc `readTypedCSV` refuses numbers beyond +/-1e100
  (`INVALID_TABLE`); a workflow must check magnitude before the Calc step.
- Project units are needed only for quantity columns. A property-only schedule works with
  `UnitsInContext` set to `$`; a quantity column then refuses as `UNIT_MISSING`. A
  reference that is present but undefined is `DANGLING_REFERENCE`.
- Selected class is plain `IfcWall`. `IfcWallStandardCase` and `IfcWallElementedCase`
  are refused instead of silently included. Every other entity is counted and stays
  **unassessed**, as do geometry, representations, placement, materials, layers,
  classifications and all unselected properties and quantities.
- Properties: `IfcLabel`, `IfcText`, `IfcIdentifier` (text); `IfcReal`, `IfcInteger`
  (unitless numbers); `IfcBoolean` (published as text `true`/`false`). Lists,
  enumerations, bounded, table and complex properties, null values and properties
  with their own `Unit` are refused when selected.
- Units: the project must declare a plain `IfcSIUnit` for each quantity kind used
  (metre, square metre, cubic metre) with no prefix or `MILLI`, `CENTI`, `DECI`,
  `KILO`. Conversion-based, context-dependent, derived, missing and ambiguous units
  and per-quantity `Unit` overrides are refused. The value is the exact source
  decimal times a power of ten (prefix exponent times the dimension power), rounded
  once to binary64. Area and volume use the squared and cubed prefix.
- Duplicate entity ids, dangling **selected** references (references outside the selected
  subgraph, including unselected cycles and dangling references, are not assessed), duplicate `GlobalId`, duplicate
  property-set or property names, more than one type relation, a type that is not an
  `IfcWallType` and type mismatches are refused before any native process runs.

## How it is checked

IfcOpenShell 0.9.0.post1 runs in its own interpreter in two fresh processes (extract
and reopen); both raw tables must be byte-identical. A standard-library STEP
tokenizer and a walk of only the selected subgraph produce the expected GUIDs, names,
origins, values and conversions independently; they are never read from the native
output. Any disagreement stops with `NATIVE_DISAGREES` and the exact row and cell.
The published files are rebuilt from the host-checked values. Notably, the native
inherited lookup `get_pset(..., prop, should_inherit=True)` can return a whole type
property set when the occurrence lacks the property, so the worker uses explicit
non-inheriting lookups per object and the host applies precedence itself.
Every retained native field is bound to the independent walk: wall and type
`GlobalId`s, the unit scales (the same unit types, each within two ulps of the exact
SI prefix power), and for each cell its origin, `raw` source value with a strict cell type
(`False` is not `0`, an `IfcInteger` is not a real) and the converted value.
Offline `verify` reopens the retained evidence and launches no native process. An
unexpected host failure before any native launch is `HOST_EXECUTION_FAILED`, never a
native failure.

The native identity records and pins (by SHA-256, for the qualified 0.9.0.post1 release)
the pure-Python `util/element.py` and `util/unit.py` modules that implement the lookups
and scales, and records the compiled wrapper hash; the worker compares the identity
before and after the extraction. This is not a publisher attestation: the compiled
wrapper and other package files and dependencies are recorded or unpinned, no mesh or
geometry code is used, and no claim is made about them.

The native qualifier (`tools/qualify_ifcopenshell.py`) states every expected value as a
hand-written literal and matches each expected fault by its exact code, message and
location. Each mutant first refreshes every ordinary binding, stage input, receipt and
the publication metadata, and the qualifier checks that `publication_metadata.verify`
passes before it expects the intended fault. Its mutants are labelled `semantic` (a
consistent-looking record whose meaning is false, 26 cases) or `integrity` (a retained
worker, launcher, version identity or intent changed, 5 cases). Pre-native refusals and
Calc consumer refusals are shown by an owned count of the processes the runner starts
and by the absence of any submission record, not only by the absence of a workbook.

The qualifier also drives the schedule through the supported local agent protocol only
(`schemaxis agent`): it authors a baseline draft, plans, executes and verifies it, edits
the draft (an atomic inheritance patch, a source change that alters one stored length,
and a different document with area and volume quantities), and inspects the published
CSV and JSON through `inspect_resource` with bounded, revision-bound paging. Every
GUID, value, origin, unit and absence is compared with a literal. This is not the native
`schemaxis inspect --node` view, which this adaptor does not provide. The Calc
workflow is authored, run and verified the same way and its workbook is read back with
the independent oracle.

Live cancel and timeout runs record the process group of the real native interpreter
before it is held with SIGSTOP, then require the runner to end it with signal 15 or 9,
every owned process to have a finite return code, the process group to be gone, the
fault message and location to match exactly, the logs to be retained and no schedule,
receipt, metadata or sidecar to exist. They do not claim to stop the middle of a
library call.

## Recovery

Faults carry a stable code and a location such as `#13.columns[2]` (the entity and
column) or `native-extract.json.rows[0].cells[3].value`. Typical recoveries: pick a
`missing` policy, declare the project unit in the file, remove Unicode escapes, or
remove `IfcWallStandardCase` walls. A different native version is refused as
`UNSUPPORTED_NATIVE_VERSION`.

## Runtime and upstream

Configure an absolute interpreter of a private environment with IfcOpenShell
0.9.0.post1 (`--ifcopenshell` or `SCHEMAXIS_IFCOPENSHELL`); never install it into the
host. The path is used as given (a virtualenv interpreter is not resolved). The wheel
hash comes from the PyPI install report; no publisher attestation is available, and
none is claimed. See the
[IfcOpenShell Python guide](https://docs.ifcopenshell.org/ifcopenshell-python/code_examples.html),
[`util.element`](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/element/index.html) and
[`util.unit`](https://docs.ifcopenshell.org/autoapi/ifcopenshell/util/unit/index.html).

## Fixtures

The IFC files in `examples/schemaxis/fixtures/ifcopenshell` are original synthetic
ASCII IFC4 text written by `tools/author_ifcopenshell_fixtures.py`
(`--check` verifies they are unchanged). They are not real building data.
