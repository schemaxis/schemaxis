# YAML input and source authoring

Install optional host YAML support with `pip install 'schemaxis[yaml]'`. JSON-only
installations remain dependency-free. YAML is parsed on the host and normalised
into ordinary JSON-compatible values before existing schema validation, planning
and native execution. Adaptors and native runtime packages need no YAML parser.

Files ending in `.yaml` or `.yml` select YAML; other names select strict JSON.
An explicit CLI input format overrides the extension, including for stdin.
Malformed JSON is never retried as YAML. Workflow template manifests, referenced
workflow files and case parameter files can use either syntax.

The supported profile is one YAML 1.2 document with string mapping keys and
finite JSON-compatible values. Comments, block/flow collections, quoted scalars
and multiline strings are supported. Duplicate keys, custom/explicit tags,
anchors, aliases, merge keys, non-string keys, infinities, NaN and YAML 1.1
version directives are rejected. Plain `yes` and `no` are strings; `true` and
`false` are booleans. Dates and timestamps remain strings. Quoting a value makes
its type unambiguous. Schemaxis references and expressions retain their existing
meaning and RFC 6901 pointer addresses in either syntax.

Studio's input and designer source tabs offer a JSON/YAML selector. Both formats
share schemas, validation, property completion, hover information, guided filling
and structured property/snippet edits. Source drafts preserve invalid input for
repair; invalid drafts cannot execute. Saved revisions and undo/redo retain the
source format. Source diagnostics and pointer location queries address the
original YAML source.

YAML source comments and quotes are retained during structured edits. Objects
with `id` fields retain their associated comments when reordered. Formatting may
be normalised by an edit, and comments attached to deleted fields disappear with
those fields. Format conversion is explicit: JSON-to-YAML preserves supported
values; YAML-to-JSON preserves values but discards YAML comments and presentation.
Keep one authoritative source file, rather than independently editing equivalent
JSON and YAML documents.

The packaged browser parser is the ISC-licensed `yaml` 2.8.2 distribution, bundled
as an ES module for offline Studio operation. Its licence accompanies the module.
Host parsing uses the optional `ruamel.yaml` 0.18 family. Profile/parity tests
cover scalar typing, rejected constructs, source locations, schema assistance,
comment retention, invalid-draft recovery and grouped structured edits.
