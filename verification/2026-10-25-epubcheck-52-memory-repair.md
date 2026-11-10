# EPUBCheck allocation 52: bounded host memory for the container and package index (care 52 review, low finding L-new3)

Scope: the host role index in `src/schemaxis/adaptors/epubcheck/adaptor.py` (`xml_member_names`). Nothing else in the adaptor's behaviour changed.

## Finding and change
`xml_member_names` built a whole ElementTree of the container and of every package (each up to the 32 MiB member limit). A document of
repeated irrelevant elements therefore cost memory proportional to the element count, many times the input size, before any native process started.
It now feeds the already strict-scanned text to the standard `ElementTree.XMLParser` with a target that receives start tags and builds no tree, in 64 Ki
character chunks, and reads to the end of the document. Names, media-type matching, reference resolution and every refusal are unchanged:

* The strict `scan_xml` profile, the encoding/DTD backstop, the 32 MiB limits and the unique-package parsed-once property are unchanged.
* A malformed document is refused only after it was read to the end, so XML errors after useful tags are still found. A malformed tail still wins over an ambiguous
  reference seen earlier in the same document, as with the whole-document parse. The first ambiguous reference is remembered (60 characters) and refused afterwards.
* Rootfile spellings are resolved as they stream past; a memo of at most 4096 distinct spellings skips repeats, beyond which a repeat is simply resolved again.
* The standard parser raises the same `ParseError` as before (for example undefined entities), which is why raw expat was not used.

## Measured, small inputs only (never the 32 MiB ceiling)
* tracemalloc peak for a container with 262144 sibling `<a/>` elements (1,048,798 bytes): **1,331,966 bytes** now, **24,160,927 bytes** with the previous whole-tree parse.
* Capped process (RLIMIT_AS 12 MiB above the import-time VmSize, 1 MiB documents): the new source completes and returns the exact index; the previous source raises MemoryError.
* Prototype (1 MiB, tracemalloc, above the input): repeated `<a/>`: whole tree 23.1 MB, incremental target 0.27 MB. 115,970 distinct tag names: whole tree 39.9 MB, target 28.6 MB.

## Limits (honest)
* Only the per-element tree cost is removed. Parser state still grows with **open-element nesting depth and distinct element and attribute names**, in addition to
  the document bytes, decoded text, current chunk and retained role references. The 32 MiB limit was not narrowed; this is input-bounded, not constant-memory.
* The distinct-tag-name prototype measured about 28 bytes of parser allocation per input byte on its 1 MiB fixture. Deep nesting was not measured: the independent
  reviewer's rough, runtime-dependent estimate was 120–150 bytes per open element, potentially around 1.3 GB for 32 MiB of unclosed nesting. That estimate is not a
  measured maximum or a heap guarantee; no large nesting stress was run.
* This is not an operating-system memory boundary, and the Java heap remains the launcher's own option.

## Tests
Four host tests were added to `tests/unit/test_epubcheck.py` (Preflight): the same exact role index, refusals and ambiguity detection with 160000 irrelevant elements around the
real items (including unlisted package and media-type names); late malformed forms (unclosed, junk, undefined entity, second root) and malformed-over-ambiguous precedence with and without
padding; 4300 distinct rootfile spellings with a second package; and the memory test above (tracemalloc ratio and ceiling, and nothing retained after a fault). On the previous source the
memory test fails (peak 24,156,959 bytes against the 5,243,990 limit); the equivalence tests pass on both, which shows the semantics are preserved.

Doc correction: `upstream.json` now attributes the direct media-type, `file:` and `jar:http` loopback controls to `tests/unit/test_epubcheck_native_boundary.py`. The qualifier only has
host refusals of those forms with zero native starts and a recorded, not asserted, `file:` DTD observation.
