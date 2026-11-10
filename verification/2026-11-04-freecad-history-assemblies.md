# Typed history assembly bridge

The assembly route now admits the qualified mechanical-history publications,
including multiple Bodies, attached sketches, datum axes, dress-ups, patterns,
lofts and common native Hole features. This completes a source-history bridge;
whole FreeCAD completion remains open.

Each part definition retains the complete source document. Its producer-selected
final feature identifies the Body instantiated by component links. Mounts are
appended only to that Body. Repeated components share one copied source, while
distinct part definitions keep separate histories even when they name the same
producer document. Parameters, expressions, ordered groups and native feature
properties remain checked under one complete object-name bijection.

## Persistence contract and independent controls

Native copy/recompute genuinely regenerates some persistent topology names.
Source/copy equality of those names would be an incorrect acceptance rule. The
bridge instead qualifies this explicit regeneration:

- A fresh trusted FreeCAD process opens only byte-identical, bounded, admitted
  retained sources. It captures every indexed face/edge/vertex in every history
  shape and every actual downstream subelement consumer, recomputes sources,
  copies whole histories and constructs the declared native assembly.
- Source/copy indexed geometry and consumer target/index/geometry must agree
  under the existing 64-ULP history round-trip rule. Native copy can select the
  built-in plane/line attachment engine for sketches/datum axes; the exact
  reviewed conversion and complete enumeration list are checked.
- Current saved maps and XML shadows must match this fresh regeneration in
  full, including nested StringID dependencies, ordered alternatives, local map
  children, indices, signed owners and operation-span boundaries. Document-wide
  aliases are checked across all payloads, including repeated definitions.
- Native operation-span lengths count characters and therefore change when a
  nested allocated owner ID changes width. Comparison retains the precise
  substring boundary in a structured token sequence. It does not drop these
  lengths. The literal `;#25` map prefix remains literal text; `$#25` declares an
  actual StringID dependency and must resolve.
- Current saved BREP payloads must equal fresh regeneration, apart from the
  earlier same-token negative-zero spelling allowance. The provisional global
  1e-17 numeric allowance was removed. Geometry alone cannot accept a changed
  map or shadow, even when artifact hashes are refreshed.

Format interpretation used public
[MappedName operation spans](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/App/MappedName.cpp),
[element-map persistence](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/App/ElementMap.cpp)
and [StringHasher persistence](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/App/StringHasher.cpp).
The host encoding comparator is independently written and deliberately does not
claim to decode source-to-copy semantic name equivalence. No upstream
implementation is copied.

## Executed acceptance

Actual FreeCAD1.1.4 acceptance includes:

| Case | Result |
| --- | --- |
| Enclosure housing and lid from two complete two-Body producers; three instances, including a shared second housing | Pass: four Bodies retained and only selected Bodies instantiated |
| Height-driven lid mount; native housing-height edits20→22→24mm | Pass: both housing instances update; lid placement follows the connector; each edit saves and reopens in a separate process |
| Independent analytic housing/lid volumes | Pass: housing baseline10128+60πmm³; edited volumes10896+60π and11664+60πmm³; lid3(1176−π)mm³ |
| Standalone assembly opened with producer and retained source files unavailable | Pass: native editing/solving needs no source files; Schemaxis provenance verification still requires its pinned producers |
| Existing-wrong StringID, nested string content, wrong map root, existing-wrong/absent shadow IDs and altered shape payload, with refreshed artifact SHA | All refused, including a full caller-facing registry verification |
| Workflow resume | Pass: all three operations reused |
| AdditiveLoft+linearPattern; SubtractiveLoft+polarPattern; datum-axis revolution+Body fillet; mirror+constrained sketch | Four native assemblies pass full build, reopen and fresh current-code regeneration verification |
| Same enclosure using one native fastening-grid/Hole feature instead of four separate Pockets | Pass: the complete workflow, two edits, fresh reopening, standalone opening, seven hostile checks and reuse |

The enclosure qualifier is `tools/qualify_freecad_history_assembly.py`; add
`--drilled` for the native Hole variant. Source-bound reports retain exact source
identities separately: enclosure final-r3 at a0b0b60, family assemblies-r4 at
d52b20c and drilled enclosure-r1 at771c314. The preceding183-test FreeCAD host
suite passed; later integrated delivery checks must include the Hole changes.
Earlier failed rounds exposed real assumptions about map allocation, datum
engines and regenerated shadows; their failures are not counted as qualification.

A separate read-only review identified two additional guards. Comparison now
retains every local map definition, including those unreachable from the payload
root. Object IDs must be canonical positive bounded unique integers before any
owner-tag normalisation, both on admitted sources and saved assemblies. Mutated
source fixtures with duplicate, zero, negative, noncanonical or oversized IDs
are rejected before a native launcher is called. The reviewed six native
assemblies passed fresh verification with the complete local-map comparison;
the subsequent195-test integrated FreeCAD host suite passed after the ID guard.

## Delivery and limits

The existing typed source-file contract and route version remain compatible.
Guidance, readiness context and the assembly guide describe multi-Body selection,
the required configured runtime, source provenance and explicit regeneration.
The closed vocabulary admits only reviewed native classes/properties/extensions;
unknown objects, Python state, external dependencies, malformed archives and
unqualified payloads fail before source opening. Discovery and planning remain
host-only. Host tests cover sparse IDs, indirect dependencies, alias conflicts,
operation-span renaming/corruption, literal/hash distinctions and tiny payload
changes. Shared generated Help/schema/assessment assets and canonical receipt
freshness are checked at the consolidated integration epoch.

Fixed joint trees remain the assembly scope. Moving joints, mechanism simulation,
subassemblies, mixed constructor/source forms, interference/contact and general
third-party FCStd editing remain important open families. The earlier phase-one
source path retains its explicitly documented weaker name-map limit; this stronger
regeneration contract applies to typed mechanical histories. No exhaustive API,
universal topology-repair or unchanged internal-name guarantee is claimed.

The integrated uniform-wall enclosure also passes the complete history-assembly
qualifier with `--shelled`: four retained Bodies, repeated shared housing source,
height edits 20→22→24 mm, separate fresh reopenings, standalone source removal,
seven refreshed-digest map/shadow/payload attacks and verified workflow reuse.
The source admission vocabulary now includes only the measured native Thickness
property/type identities; semantic values still pass the original history checks.

A subsequent actual GUI reopen exposed a missing final Camera record in the
minimal visibility XML. New publications write the native empty Camera record;
legacy visibility-only records remain verifiable. The reader refuses nonempty,
malformed or duplicate camera records. An isolated FreeCAD1.1.4 GUI process
restored the intended first-open visibility and installed joint view providers,
solved successfully, and produced a visually reviewed assembly view without the
previous embedded-GUI restore failure. The relevant public persistence format is
[FreeCAD GUI Document](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Gui/Document.cpp).
