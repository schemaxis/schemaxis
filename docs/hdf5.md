# HDF5 scientific data files

`schemaxis.hdf5/1` creates, inspects, extracts, edits, compares and exchanges HDF5 files through
**h5py 3.16.0** (with its bundled **HDF5 2.0.0** library) running in an isolated Python process.
The host never imports h5py or NumPy. Every publication is accepted only when the host's own
expected state, computed from your declarations and captured bytes, agrees with two independent
readings of the saved file: a fresh h5py process and the **HDF Group `h5dump` 2.2.0** XML output,
which the host parses with the standard library. `schemaxis verify` recomputes the expectations and
reruns both readers on the current bytes of every publication and captured source (a fresh h5py
process and h5dump), never trusting retained manifests, so a file edited after publication fails
even when its recorded digests were refreshed.

Sources and dependent files are always captured into the run directory. Originals are never
modified: edits apply to a copy that is published under a new name.

## Contents

- [Configure the runtime](#configure-the-runtime)
- [Operations](#operations)
- [Paths, types and values](#paths-types-and-values)
- [Storage: chunks, filters, fill and layouts](#storage-chunks-filters-fill-and-layouts)
- [Attributes, units and dimension scales](#attributes-units-and-dimension-scales)
- [Links, references and committed types](#links-references-and-committed-types)
- [Virtual datasets, external storage and dependent files](#virtual-datasets-external-storage-and-dependent-files)
- [Selections and extraction](#selections-and-extraction)
- [Access tuning and memory-bounded reads](#access-tuning-and-memory-bounded-reads)
- [Editing an existing file](#editing-an-existing-file)
- [Mesh and field time series (XDMF)](#mesh-and-field-time-series-xdmf)
- [SWMR live series](#swmr-live-series)
- [Parallel MPI-IO writes](#parallel-mpi-io-writes)
- [Inspection and comparison](#inspection-and-comparison)
- [Verification and its limits](#verification-and-its-limits)
- [Faults and recovery](#faults-and-recovery)
- [Scope and exclusions](#scope-and-exclusions)

## Configure the runtime

```sh
python3 -m venv /opt/hdf5-runtime
/opt/hdf5-runtime/bin/pip install --only-binary=:all: h5py==3.16.0 numpy==2.5.4
schemaxis configure hdf5 /opt/hdf5-runtime/bin/python
schemaxis configure hdf5H5dump /path/to/HDF5-2.2.0/bin/h5dump
```

Explicit `--hdf5` and `--hdf5-h5dump` arguments override configuration; the environment variables
`SCHEMAXIS_HDF5` and `SCHEMAXIS_HDF5_H5DUMP` are the last fallback. Other h5py, HDF5 or NumPy
builds are refused with `HDF5_UNSUPPORTED_RUNTIME`, and an h5dump other than 2.2.0 is refused,
rather than assumed compatible. The official HDF Group binary archives include `h5dump`.

## Operations

| Operation | Use it to | Publishes |
| --- | --- | --- |
| `createFile` | Build a new file from groups, datasets, attributes, links and storage choices. | the file (and family/split members, new raw files, dependent files), extracts, report |
| `editFile` | Apply ordered edits to a captured copy; optionally repack. | the edited file, extracts, report |
| `inspectFile` | Inventory a received file and decide typed expectations. | `inventory.json`, `expectations.json`, report |
| `extractData` | Read selections into CSV, NPY or JSON for other tools. | one file per extract, report |
| `writeMeshFields` | Write mesh points, cells and per-step fields with an XDMF 3 description. | `.h5`, `.xdmf`, report |
| `appendSeries` | Append sample batches in SWMR mode with concurrent readers. | the series file, report |
| `parallelWrite` | Write datasets from several MPI ranks with parallel HDF5. | the file, report |
| `compareFiles` | Regression-compare two files with tolerances (h5diff semantics). | `comparison.json`, report |

Starting documents for every operation are in `examples/schemaxis/hdf5-*.json`; Studio offers
the same starters with placeholders for every file you must choose.

## Paths, types and values

Every object is named by its **absolute path** (`/run/raw/counts`). A path segment is any
UTF-8 link name an HDF5 file can hold - spaces, units, Greek letters, punctuation and leading dots
and brackets are ordinary (`/Experiment 1/Temperature (°C)`, `/μm`, `/.calibration`,
`/channel[2]`) - except that it may not contain `/` (the separator), NUL or other control
characters, be `.` or `..`, or exceed 255 UTF-8 bytes. (h5dump reads such datasets with
`--no-compact-subset`, so a `[` in a name is never taken as selection syntax.) Paths nest at most 16 levels and are compared code point for code point (no Unicode
normalisation). These rules apply to names inside the file; file names on disk (outputs, external
links, dependencies) keep the stricter portable rule described below. Parent groups are created
implicitly; declare a group explicitly only to give it attributes or link creation order.
`examples/schemaxis/hdf5-human-names.json` creates, links, references and extracts such names.

A dataset is normally an array with a `shape` (`[]` is a scalar of one element, `[0]` an empty
extent that can grow). `empty: true` instead declares a **null-dataspace** dataset (h5py's
`h5py.Empty`): it has an element type and attributes but no shape, no extent and no elements -
common in vendor files as a typed placeholder (for example a calibration value that is not yet
known). It takes `type`, `attributes`, `units` and `trackOrder` only. Null datasets are inventoried,
inspected, copied, moved, deleted, repacked and compared like any other object; the h5py readback
reports `shape: null` with `null: true` together with the stored element type (including bitfields,
enums, compounds, opaque, references, arrays, strings and committed types) and the stored layout
(contiguous or compact), exactly as for datasets with elements; because h5dump's XML output prints
no dataspace for them, each one is confirmed independently from h5dump's DDL header
(`DATASPACE NULL`). Selecting,
extracting, writing, resizing, appending to, using in `where`, scaling or chunk-copying a null
dataset is refused at the located path, because there are no elements to address.

`type.class` chooses the element type:

| Class | Fields | Notes |
| --- | --- | --- |
| `int`, `uint` | `bits` 8/16/32/64, `order` little/big | out-of-range values are refused, never wrapped |
| `float` | `bits` 16/32/64, `order` | values are rounded once (IEEE round-to-nearest-even); `"nan"`, `"inf"`, `"-inf"` are allowed |
| `complex` | `bits` 64/128 | values are `[real, imaginary]`; stored as h5py's `r`/`i` compound |
| `bool` | | stored as the HDF5 enum FALSE/TRUE |
| `string` | `encoding` utf-8/ascii, optional `length` (bytes) | without `length` the string is variable-length |
| `enum` | `members` [{name, value}], `bits`, `signed` | values may be member names or codes |
| `compound` | `fields` [{name, type, units}] | records are arrays in field order; a field may have `dims` (e.g. a 3-vector) |
| `vlen` | `base` | ragged numeric sequences |
| `reference` | `reference` object/region | filled with `data.source` `references` |
| `opaque` | `size` bytes | values are lower-case hex |
| `named` | `path` of a committed `datatype` object | the dataset shares that committed type |

`shape` is required (`[]` is a scalar). `data.source` says where values come from: `values`
(row-major literals), `fill` (the fill value), `range` (`start + i*step`), `linspace` (`start + i*(stop-start)/(n-1)`,
last element exactly `stop`), `input` (a captured CSV column/columns, NPY array or raw binary
input), `references` or `copy` (another dataset of the same shape). These formulas, not library
calls, define generated values; the host computes the same values independently.

## Storage: chunks, filters, fill and layouts

`storage.layout` is `contiguous`, `chunked`, `compact` (raw data in the object header, at most about
64 KiB), `external` or `virtual`; it is inferred when omitted. Filters require chunking:
`compression` gzip (`level` 0-9), lzf or szip (`szipMethod` nn/ec, even `szipPixels`), plus
`shuffle`, `fletcher32`, `nbit` (lossless bit packing) and `scaleOffset` (integer minimum bits, 0 = automatic; for floats the
number of decimal digits kept, which is lossy). `maxshape` entries larger than `shape` or
`"unlimited"` make a dataset resizable. `fillValue`, `fillTime` (ifSet/alloc/never) and
`allocTime` (early/incremental/late) control unwritten elements.

LZF is h5py's own filter: other HDF5 software needs the LZF plugin to read it, although the
HDF Group 2.2.0 tools used here decode it. Prefer gzip for files you will hand to others.

## Attributes, units and dimension scales

Attributes take a `value` (scalar, text or list) with an optional explicit `type` and `shape`;
`empty: true` writes a null-dataspace attribute. `units` on a dataset is shorthand for a text
`units` attribute; Schemaxis does not interpret unit strings beyond keeping them exact, and
extracts carry them into CSV headers (`pressure [kPa]`). Numeric attributes can instead take
`data` with the `range` or `linspace` generator over their declared `type` and `shape`, which keeps
large lookup tables or calibration maps out of the document. Attributes hold at most 65,536
elements; bulk arrays belong in datasets.

**Large attributes and creation order.** HDF5 stores attributes compactly in the object header,
where one attribute message is limited to 64 KiB. Larger attributes need dense attribute storage,
which HDF5 uses for objects that track attribute creation order and for files written with
`libver` v108 or later. Set `trackOrder: true` on the group or dataset (or on `file` for root
attributes), as the h5py documentation recommends for large attributes, or raise the file's
`libver`; a fixed-size attribute larger than 63 KiB without either is refused at planning at
`$.objects[i].attributes[j]`, and a large `setAttribute` on an adopted object that stores
attributes compactly is refused at the edit (`HDF5_ATTRIBUTE_TOO_LARGE`). On an object with
`trackOrder`, attributes keep their creation order: it is part of the expected state, checked
against the h5py readback and against h5dump listing attributes `--sort_by=creation_order`, and
edits follow HDF5's behaviour - rewriting or renaming an attribute moves it to the end, deleting
removes it, copies and repacks keep the order. The compact-to-dense switching thresholds
themselves (`H5Pset_attr_phase_change`) are not offered: they only tune when HDF5 changes storage
form internally, while the outcomes users need - large attributes and stable attribute order -
are covered by `trackOrder` and `libver`. `examples/schemaxis/hdf5-large-attributes.json` stores
80 KiB and 72 KiB tables on the root, a group and a dataset.

Set `scale` (the scale name, may be empty) on a one-dimensional dataset to make it a dimension
scale, then attach it with `dimensions: [{axis, label, scales}]`. Each attached scale must have
exactly the length of its axis. The reserved bookkeeping attributes (`CLASS`, `NAME`,
`DIMENSION_LIST`, `REFERENCE_LIST`, `DIMENSION_LABELS`) cannot be authored directly.

### NetCDF-4 and xarray readability

NetCDF-4 is HDF5 with conventions: its dimensions are dimension scales. A dataset is presented
with named dimensions by netCDF-C, h5netcdf and xarray only when **every** axis has a scale (or
none has); a label alone is not enough. Keep NetCDF-facing data to numeric and string types and
avoid external links that readers cannot resolve. `createFile` reports `netcdf4.namedDimensions`
with reasons. `examples/schemaxis/hdf5-numpy-workflow.json` writes a `(time, channel)` array that
xarray opens with units and label selection.

## Links, references and committed types

`links` adds `soft` (stored text path, may dangle), `hard` (another name for an existing object)
and `external` links (`file` is a relative file name or an `externalLink` dependency). Object
references point at whole objects; region references at a selection of a dataset. A
`kind: "datatype"` object commits a type that datasets reuse with `class: "named"`.

## Virtual datasets, external storage and dependent files

`dependencies` declares other files the result needs: `virtualSource`, `externalLink`,
`rawStorage`, `copySource` or `reference`. They are captured under their file names and
published beside the result so the bundle is self-contained. A virtual dataset maps source
selections (`select`) to target selections (`at`) from this file (`.`) or a `virtualSource`
dependency; unmapped elements read as `virtual.fill`. External storage maps a dataset onto raw
byte segments (`file`, `offset`, `size`) of a `rawStorage` dependency (existing instrument
bytes) or of a new raw file that the run writes.

When you inspect, extract, edit or compare a file that contains virtual datasets or external raw
storage, declare every file they read as a dependency with the same file name. Otherwise the run
is refused with `HDF5_MISSING_DEPENDENCY`: HDF5 itself would silently return fill values.
Before any process reads a value, a metadata-only preflight lists every external raw file and
virtual source a file names (recursively through captured dependencies) without following soft or
external links. Only bare file names that equal a captured dependency of the right role are
admitted; absolute or traversing paths are refused with `HDF5_UNSAFE_DEPENDENCY_PATH`, so a
received file can never make Schemaxis read other local files. External links follow the same
rule: their file names must be bare names; a name present in the bundle must be a captured HDF5
dependency (declare `externalLink`) and is admitted recursively, and an absolute or traversing
link name refuses the file, because h5dump would otherwise resolve it (also through soft-link
aliases). Links to absent bare names stay unresolved and are reported.
`examples/schemaxis/hdf5-chain-workflow.json` binds producer artifacts as dependencies.

`examples/schemaxis/hdf5-campaign.json` stitches two run files into one ten-element signal:
`[0.5, 1.5, 2.5, 3.5, -999, 5.5, 6.5, 7.5, -999, -999]`.

## Selections and extraction

A selection is `all`, `slices` (per-axis `start`/`stop`/`step`, negative indices allowed when the
shape is known), `hyperslab` (`start`, `count`, `stride`, `block`) or `points`. Extracts write
`csv` (rows follow axis 0, remaining axes flattened in C order, axis-0 scale as the first column
when `coordinates` is true; `header: "names"` drops the `[units]` suffixes for consumers such as the
NumPy adaptor), `npy` or `json` (natural numbers, non-finite as text). `fields`
selects compound members, written in the order you list them. Enum values are written as their
integer codes.

### Filtering rows with `where`

`where` keeps the axis-0 rows of an existing file's dataset for which every listed condition holds
(the conditions are combined with AND; there is no expression language). Each condition reads a
one-dimensional dataset with one value per row - the extracted dataset itself when `dataset` is
omitted, or a companion such as a state flag or a time axis - optionally one compound `field`, and
compares it with `op`:

| `op` | Operands | Element classes |
| --- | --- | --- |
| `eq`, `ne` | `value` | integer, float, bool, enum (member name), string |
| `lt`, `le`, `gt`, `ge` | `value` | integer, float |
| `between` | `value` <= x <= `upper` | integer, float |
| `in` | `values` (1-256) | integer, float, bool, enum, string |
| `finite`, `nan` | none | float |

Comparisons use the exact stored values: a float32 101.31 is stored as 101.30999755859375, so it is
greater than 101.305 but not equal to 101.31. NaN satisfies only `ne` and `nan`. Integer datasets
compare with integers that fit their type; anything else is refused at the operand. The rows are
chosen twice - by h5py/NumPy in the native process and by the host from the independent h5dump
reading - and must agree before any value is accepted; verification re-chooses them from a fresh
h5dump reading of the captured source. `where` combines with `fields`, `columns`, `coordinates`
and `access.memoryBytes` (the chosen rows are streamed in blocks), but not with `selection` or
`parallel`, and is offered for extractData and editFile extracts of existing files.
`examples/schemaxis/hdf5-filter-rows.json` keeps the counts recorded while acquiring with a valid
pressure, the pressures above a threshold, and the overload events of a compound log. The report
records the number of rows kept of the total.

Files larger than the full independent reading budget (1,048,576 elements) can still be
inspected and extracted: h5dump then reads only the selected hyperslab (or up to 256 points) of
integer and float datasets, and the dimension-scale coordinates, as the independent check.
Appending to such a large integer or float dataset is supported: the preserved rows are checked
by digest against the captured source in a fresh process, and the appended block by an independent
h5dump read. Writing into the interior of a large dataset is not offered.

### Chunk indexes

`format: "chunks"` writes `<id>.chunks.json` instead of values: the dataset's shape, chunk shape,
element type and filter pipeline, and for every allocated chunk its logical `offset`, its
`byteOffset` and `size` in the file, its `filterMask` and the SHA-256 of its stored bytes, read
with HDF5's direct chunk interface. Tools that reference compressed chunks in place - kerchunk or
VirtualiZarr manifests, GPU or cloud decoders, fast chunk-level transfers - can use it without
re-reading or recompressing the data; the byte offsets refer to the captured file, whose SHA-256 is
in `capture.json` (for extractData and editFile) or to the published file (createFile).

The index is not trusted: the host reads every listed chunk from the file itself, checks its
digest, checks Fletcher-32, inflates gzip and undoes the shuffle in pure Python, and compares every
element inside the dataset bounds with the independent h5dump values. Elements outside every
allocated chunk must read back as the fill value, and the listed sizes must add up to the
allocated bytes HDF Group h5ls reports. Because two chunks can hold identical bytes, decoded values
cannot tie a listed file position to its logical chunk, so a fresh h5py process also lists the
current file's chunks from HDF5's own chunk records and the published index must equal that listing
exactly (positions, offsets, sizes, masks and digests; masks and offsets must be plain integers). Chunk indexes are therefore offered for chunked integer and
float datasets whose filters are gzip, shuffle and Fletcher-32 (the pipelines the host decodes
itself) in single-file outputs (not the family or split drivers); other filters, layouts or types
are refused at `$.extracts.<id>.format`. `examples/schemaxis/hdf5-chunk-index.json` indexes the
shuffled, compressed, checksummed big-endian counts of the sensor fixture.

## Access tuning and memory-bounded reads

Every operation accepts an `access` record that is applied to each HDF5 open of the run and read
back from the open file's access properties; a mismatch fails the run. `chunkCache` (`bytes`,
`slots`, `preemption`) sizes the raw-data chunk cache, which matters when a selection revisits
compressed chunks (for example reading columns of row-chunked data). For newly written files,
`alignment` (`threshold`, `interval`) aligns large objects to file-system or object-store blocks
(checked through every dataset's file offset), `metaBlockBytes` aggregates metadata, and
`pageBufferBytes` buffers files written with paged file-space management. `sieveBufferBytes`
(512 B to 256 MiB; HDF5's default is 64 KiB) sizes the raw-data sieve buffer that combines the
many small reads and writes of a partial selection of a contiguous dataset - strided columns,
bands or hyperslabs of an uncompressed array - into larger block I/O. It is set on the same file
access property list h5py builds for every open, including SWMR readers and MPI ranks, read back
from the open file in every native stage, and counted in the memory bound of streamed extraction.
`examples/schemaxis/hdf5-sieve-columns.json` reads a strided column and a band of a contiguous grid
with a 1 MiB sieve buffer.

`memoryBytes` turns extraction into a streamed, memory-bounded job: each extract is read and
written in axis-0 blocks of at most that many raw bytes, so a selection larger than available
memory can still be exported to CSV, NPY or JSON. The run records the number of blocks, the
largest block and the measured peak memory growth, which must stay within 16 MiB plus four times
the budget plus the chunk cache. `examples/schemaxis/hdf5-streamed-grid.json` exports a
600,000-element array in 75 blocks of 64 KiB.

Blocks are sized from what is actually held in memory. Selected compound `fields` are read
directly (HDF5 converts only those members, so one narrow field of a wide record costs only its own
bytes), and whole records are read packed, without the padding an adopted file may store between
members. Variable-length strings, ragged sequences and references keep their payload outside the
element, so their size is not known before reading: `memoryBytes` refuses them at
`$.extracts.<id>` (`INVALID_HDF5_ACCESS`) instead of claiming a bound it cannot keep; select the
fixed-size fields or omit `memoryBytes`. Each block is also checked natively against the budget
before its values are read, so an adopted record whose nested members carry padding larger than
their declared sizes is refused at `$.extracts.<id>` (`HDF5_RESOURCE_LIMIT`).

With `parallel` (`ranks`, `io`), extractData reads each selection with MPI ranks through parallel
HDF5 (each rank its block of axis-0 rows, gathered in order by rank 0); this uses the same
separately built parallel runtime as parallelWrite and is checked like a serial extraction plus
rank receipts. `examples/schemaxis/hdf5-parallel-extract.json` reads the vendor frames on two ranks.

## Editing an existing file

`editFile` captures `source`, reads it with both consumers, and simulates each edit in order on
that observed state before any native work. Actions: `create`, `delete`, `move`, `copy` (also
from a `copySource` dependency; `shallow`, `withoutAttributes`, `expandSoft`), `link`,
`setAttribute`, `deleteAttribute`, `renameAttribute` (keeps the stored type and value), `write` (a selection, optionally of
compound `fields` only), `resize`, `append` (along an axis),
`makeScale`, `attachScale`, `detachScale`, `relayout` (new chunking/filters/layout) and
`copyChunks` (stored chunks copied unchanged, below).
`repack: true` rewrites everything into a fresh file, reclaiming space freed by deletions and
allowing other format bounds or drivers. Object and region references in an adopted file are part
of the expected state: they must keep designating the same object (and the same selected
elements) after moves and repacks. Deleting an object that a remaining reference still designates
is refused at that edit, because HDF5 frees the object and the reference would become undefined;
delete or rewrite the referencing dataset first. Deleting a dataset detaches its dimension scales.
Copies and repacks rebuild dimension-scale
attachments, references and hard-link aliasing explicitly, because HDF5's own object copy does
not keep scale attachments valid in a new file. The report warns when an axis has outgrown its
scale (for example after `append`); extracts then need `coordinates: false` or a longer scale.

`write` with `fields` changes only the named members of the selected records of a compound
dataset: values are given per selected element as the field value (one field) or a list in the
order of `fields`, using the same `selection` forms as elsewhere (`all`, `slices`, `hyperslab`,
`points`) on datasets of any rank. HDF5 converts and writes only those members, so every other
member - including 64-bit identifiers, flags and members separated by padding in vendor layouts -
keeps its stored value exactly; the simulation, the h5py readback and h5dump all check the complete
records. Field values are typed by their member (a uint64 `id` refuses 2**64, for example).
`examples/schemaxis/hdf5-edit-fields.json` corrects one level, replaces two codes and sample numbers,
sets one position vector and adds a null placeholder dataset.

`copyChunks` (`path` -> `to`) writes every stored chunk of a dataset into another dataset with the
same shape, chunk shape, element type and filter pipeline through HDF5's direct chunk interface,
without decompressing or recompressing anything - the fast way to archive, mirror or merge
compressed data. The source must be a dataset of the captured file that earlier edits have not
created, moved or changed, with every chunk allocated; mismatched layouts are refused at the edit
(`INVALID_HDF5_EDIT` from the simulation, `HDF5_CHUNK_LAYOUT_MISMATCH` when only the native
pipeline parameters differ, such as the gzip level). The target's values must equal the source's
(read independently by h5dump, or by digest beyond the full-reading budget), and fresh HDF5 chunk
listings of the captured source and the published file must show the same chunk positions, sizes,
masks and stored-byte digests, so re-encoded chunks with equal values are refused.
`examples/schemaxis/hdf5-copy-chunks.json` mirrors the sensor counts into a new archive dataset.

## Mesh and field time series (XDMF)

`writeMeshFields` stores `/mesh/points`, `/mesh/<block>/connectivity` (zero-based), `/time` and
`/fields/<name>/step_<k>` and writes `<name>.xdmf`, an XDMF 3 temporal collection that tools such
as ParaView open. Connectivity outside the point range or degenerate cells are refused; the
report gives an independent signed-volume (tetrahedra) or area (triangles) total per block.
Cell-associated fields need exactly one cell block.

## SWMR live series

`appendSeries` writes one chunked unlimited dataset with `libver` latest, enters SWMR mode and
appends each batch with a flush. `readers` concurrent reader processes open the file with
`swmr=True` and record what they observe; every observation must equal the independently
computed flushed prefix. Readers need HDF5 1.10 or later.

## Parallel MPI-IO writes

`parallelWrite` needs a second runtime: h5py 3.16.0 built from source against a parallel HDF5
2.0.0 (`HDF5_MPI=ON`) with mpi4py, plus the matching Open MPI 4.1 `mpiexec`. Configure them as
`hdf5Mpi` and `hdf5Mpiexec` (or `--hdf5-mpi`, `--hdf5-mpiexec`); authored documents never choose
executables. `ranks` processes open the file with the `mpio` driver; groups, attributes and
datasets are created collectively and rank `r` writes rows `[r*n/R, (r+1)*n/R)` of axis 0 with
`collective` or `independent` I/O (filters such as gzip require collective I/O). The run
reserves one CPU per rank. Every rank writes a receipt (rank, size, process, rows, driver); the
host requires the planned communicator, distinct processes and complete row coverage, then the
serial wheel runtime and h5dump check the closed file like any other publication. With `reduce`
the ranks read their blocks back in parallel and combine count, minimum, maximum and sum, which
must equal the host's statistics. Only integer and float datasets are written in parallel; build
the rest of a file with `createFile` or `editFile`.

## Inspection and comparison

`inspectFile` lists every object with types, shapes, layouts, filters, scales, attributes,
links and hard-link groups, with bounded previews (`preview`). Expectations (`present`, `kind`,
`class`, `bits`, `shape`, `units`, `attribute`/`value`, `minimum`/`maximum`, `finite`,
`compression`, `minCompressionRatio`, `maxAllocatedBytes`) are decided by the host as met, unmet or
indeterminate with reasons. The inventory reports each dataset's logical and allocated bytes and,
for chunked data, the chunk count, smallest and largest stored chunk and chunks whose optional
filters were skipped; logical and allocated bytes must agree with an independent `h5ls -v` reading
(the HDF Group h5ls 2.2.0 beside the configured h5dump). Ranges and
finiteness are computed by the host from the independent h5dump values (reading the whole dataset
through h5dump when the file exceeds the full-reading budget); datasets above 4,194,304 elements
are reported indeterminate rather than decided from a single reader. `compareFiles` reports
presence, kind, type/shape, attribute, optional storage and value differences; a value differs
when `|a-b| > absolute + relative*|reference|`, and NaN equals NaN.

## Verification and its limits

Checked independently: every declared object, kind, type, shape, maximum shape, layout, chunk
shape, filter set, fill value, scale status, attached scales (by object identity), labels,
attributes, links, hard-link sharing, reference targets, region points, external segments,
superblock version and every element value (by SHA-256 of a canonical form, and literally
against h5dump for up to 1,048,576 elements in total; larger files are checked by digest and by
independent h5dump reads of every extracted selection). Recorded h5dump XML limits: some UTF-8
strings are printed with an unknown character set, LZF and scale-offset filters are omitted from
its filter list, region-reference data is not printed and fill values of non-native byte order
are mis-rendered; those facts are checked by the fresh h5py readback only.

## Faults and recovery

| Code | Meaning and recovery |
| --- | --- |
| `INVALID_HDF5_PATH` | Malformed or conflicting path: not absolute, a `.`/`..` segment, control characters, a segment over 255 UTF-8 bytes or deeper than 16 levels. |
| `INVALID_HDF5_TYPE` / `INVALID_HDF5_VALUE` | Type fields that do not apply, or values that do not fit (range, length, encoding, members). |
| `INVALID_HDF5_DATA` | Wrong value count, generator or input mapping; the message names the expected count. |
| `INVALID_HDF5_STORAGE` | Filters without chunking, chunk larger than the axis, unsupported filter for the type. |
| `INVALID_HDF5_DIMENSION` | Scale missing, not a scale or of the wrong length. |
| `INVALID_HDF5_VIRTUAL` / `INVALID_HDF5_LINK` / `INVALID_HDF5_REFERENCE` | Mapping counts, dependency roles or targets do not match. |
| `INVALID_HDF5_EDIT` | An edit refers to a missing path or would break an invariant, located at that edit. |
| `INVALID_HDF5_EXTRACT` / `INVALID_HDF5_SELECTION` | Selection out of range, unsupported format for the type, scale too short for coordinates. |
| `HDF5_MISSING_DEPENDENCY` | A virtual source or external raw file of the source was not supplied; declare it in `dependencies`. |
| `HDF5_UNSAFE_DEPENDENCY_PATH` | A file names an absolute or traversing raw/virtual path; such files cannot be adopted. |
| `HDF5_UNSUPPORTED_FILTER` | A dataset uses a filter outside gzip, shuffle, fletcher32, szip, nbit, scale-offset and LZF; dynamic filter plugins are never loaded. |
| `HDF5_INPUT_CHANGED` | A captured file differs from its declared `sha256`. |
| `HDF5_RESOURCE_LIMIT` | Beyond the verified value budget; reduce the selection or dataset. |
| `HDF5_UNSUPPORTED_RUNTIME`, `INTERPRETER_NOT_FOUND` | Configure the exact runtime and h5dump. |
| `VERIFICATION_FAILED` | A consumer disagreed with the expected state; the location names the object. Retain the run for diagnosis. |

## Scope and exclusions

The PyPI wheel is serial; MPI-IO is available through `parallelWrite` and parallel extraction with
a separately built parallel runtime. Version 1 deliberately supports **local MPI only**: ranks run on
one machine (Open MPI 4.1.7, 2-3 ranks qualified) and are launched on localhost, so an inherited
scheduler allocation cannot place them elsewhere. Multi-node correctness, parallelisability and
parallel performance/scaling are not claimed; they are recorded as future work with acceptance
criteria in `docs/design/hdf5-multinode-mpi-backlog.md`. Chunks are written directly only by `copyChunks`, from another dataset of the
captured file with the same pipeline; arbitrary pre-compressed bytes from outside a file are not
accepted.
Remote S3/HDFS drivers, third-party filter plugins (Blosc, Zstd via plugins; every native process
runs with `HDF5_PLUGIN_PRELOAD=::` and an empty plugin path) and Python file-object drivers are
not available. These limits are recorded as open or excluded families
in the programme inventory and are not hidden by the operations above.
