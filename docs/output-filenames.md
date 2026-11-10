# Descriptive output filenames

New ParaView publications use `schemaxis.artifact-name/1`:

```text
000000__kind_slice__scene_sliceX00__axis_X__pos_-0.0483__var_U__time_0__model_off__view_0.png
000001__kind_slice__scene_sliceX00__axis_X__pos_-0.0483__var_p__time_0__model_off__view_0.png
```

Double underscores separate properties; one underscore separates a key from its
value. Keys start with an ASCII letter and contain ASCII letters and digits.
Keys cannot repeat. Property order does not affect meaning. The file extension
remains at the end. A companion appends `.metadata.json` to the entire filename.

## Run numbering

The six-digit ordinal starts at `000000` for a fresh run. ParaView operations,
analytic visits, workflow children and local parallel workers share the outer
run's allocator. Native subprocesses receive that root explicitly, without
changing the host process environment. Other adaptors retain their existing
publication conventions; the shared allocator is available for their adoption.

Reserve before writing. Geometry, measurements, explicit exports, images, scenes
and state bundles each receive a reservation. Companions consume none. Failed
writes leave gaps. Resumes retain reservations in `.output-index/`; legacy runs
without a ledger advance beyond retained numeric prefixes. Preserve this directory
with resumable runs. The viewer excludes it from inventories.

Exclusive creation of zero-byte reservation files arbitrates processes and threads,
without stale locks after a process crash. Reservations are synced on POSIX. The
filesystem must honour exclusive creation. Allocation beyond `999999` fails
explicitly. Parallel completion order can differ from reservation order.

The optional worker suffix is an identifier, not a fraction. `000003.2` and
`000003.20` differ and imply no relationship. The viewer retains it as text.
ParaView currently uses the shared integer allocator and needs no worker suffix.

For native multi-file formats, the reservation identifies the publication as a
whole. Internal pieces, relative references and fixed state-bundle members such
as `state.pvsm` retain their native layout. Their directory carries the publication
identity. Explicit writer exports use a short ordinal directory and descriptive
payload basename to avoid repeating long names at two directory levels.

## Values and portability

Numbers retain ordinary minus signs, decimal points and scientific notation:

```text
pos_-4.83e-2
pos_4.83e2
pos_0.0483
pos_-483.2
normal_list_-2.1_1.0_3
related_list_A_B_C_11
related_list_A
related_list
```

`list` introduces a flat list, including one-item and empty lists. Nested data
belongs in metadata. Nonfinite numbers are refused. Booleans are `true`/`false`;
null is `null`.

Text preserves ASCII letters, digits and hyphens. Other UTF-8 bytes become `.xHH.`
with uppercase hexadecimal digits: `wall_shear` becomes `wall.x5F.shear`.
Literal dots are escaped too, so escape-looking source text round-trips. Empty
text is `.empty.`. Text resembling a number, boolean, null or the list marker
has its first byte escaped: the string `"11"` becomes `.x31.1`. The viewer decodes
these forms for display and filtering.

Generated stems are limited to 180 ASCII characters, leaving room for extensions,
companions and staging suffixes within ordinary component limits. Longer
descriptions fail explicitly. Ordinals ensure uniqueness even on case-insensitive
filesystems. Full Windows path limits still depend on the output directory and
application settings; use a reasonably short output path.

## ParaView descriptions

Properties include scene, an observed slice axis/position where available,
resolved colour field names, time and camera index. Multiple colour fields use
a list. Nondefault component indices and opacities are included. Oblique slices
use `origin_list_...` and `normal_list_...`.

`var` comes from each geometry representation's resolved `field` setting in
the scene appearance, for example `["POINTS", "U"]` or `["CELLS", "p"]`.
The renderer checks that the requested array exists on that pipeline output,
applies `ColorBy`, and reads back the native colour-array selection before
the naming helper uses that appearance. A calculated array is named by its
selected output-array name. Node IDs, legend titles and image pixels do not
choose `var`. Solid-colour styles contribute no variable name; several selected
arrays produce a list such as `__var_list_U_p`.

This is automatic naming from the current pipeline/presentation contract.
User-defined filename decorators on nodes, filters, scenes or writers are not
implemented. Labels that cannot be inferred from observed output would need an
explicit authored contract; no such input key is claimed here.

The curated single-plane `slice` explicitly sets zero offsets, so its first
instance and later instances have the same native plane contract. General
`pvSlice` offsets retain their existing behaviour and conservative metadata checks.

For exactly one visible native planar Slice, `model_on` means additional non-text
geometry is visible; `model_off` means it is absent. Zero-opacity objects do not
count. This description does not establish image-plane registration for mixed
scenes: existing conservative spatial metadata rules still apply.

An appearance index remains when declared appearances share the same field
selection, since their colours/ranges can still differ. Multiple image writers
also carry writer identity. Complete settings remain in the receipt and companion.

## Viewer behaviour

**Filename properties** provides overlapping filters combined with AND. Each
list member is selectable. Counts describe files before property filtering.
**Clear properties** removes the filters. Opening a replacement collection clears
them; adding files preserves them. Details shows the output number and properties.

Slice groups span numbered scene names. Variable, time, appearance, model and view
variants retain distinct sequences. Legacy filenames keep the existing inference
path; malformed dictionaries do not fall back to numbered animations.

Only explicit `pos`, `time` or `frame` properties supply new-format sequence order.
The output ordinal never creates an animation. Filename coordinates are inferred
and cannot establish spatial registration. Checked metadata governs placement and
order; contradictions appear as warnings in Details.

## Mixed-media sample folder

`examples/viewer-test` is the compact collection shipped in the portable
viewer ZIP. Its root media payloads have ordinals and encoded key-value pairs;
slice names use ParaView's actual `image_properties` helper and the shared
`OutputSequence` serializer. It exercises `var → axis → model` hierarchies and
intersecting `kind`, `var`, `axis`, `pos` and `model` filters in a single folder.
Its companions provide spatial evidence without supplying grouping labels.
Nested `folders/` and `legacy/` examples additionally exercise folder groups,
automatic numeric/alphabetic orders and filename capture rules with tag lists.
See [Artifact viewer](artifact-viewer.md#acceptance-folder) for regeneration.

## Adoption beyond ParaView

The shared serializer and run allocator are available to all adaptors, but
ParaView is currently the only adaptor using them for publication paths.
For example, Blender still writes numeric render basenames and NumPy uses
semantic fixed basenames such as `spectrum.csv` and `scores.csv`.
The key-value pattern is therefore not yet a uniform cross-adaptor contract.

Adoption belongs at each producer before writing, with its publication planning
and independent receipt verification updated together. Renaming final files
after verification can invalidate hashes, receipts and native bundle references.
Native internal member names must retain any layout required by their format.

## Larger mixed-media fixture

The bounded native acceptance input is
[`paraview-output-names.json`](../examples/schemaxis/paraview-output-names.json):
two X slices, U/p appearances, four images, two datasets and two measurements.

From a source checkout, with Pillow, FFmpeg containing libx264, Node 22+ and Chromium:

```sh
PYTHONPATH=src python3 tools/generate_viewer_fixture.py /path/to/viewer-test --ffmpeg /path/to/ffmpeg
PYTHONPATH=src python3 -m schemaxis_viewer /path/to/viewer-test
```

The destination must be new. `--no-video` omits MP4/WebM and the FFmpeg/Chromium
requirements. These tools are generator dependencies; the viewer and host runtime
remain dependency-free.

The synthetic sample contains X/Y/Z slices of U and p, appearance variants,
negative/irregular coordinates, checked companions, a time sequence, animated GIF,
H.264 MP4, VP8 WebM, WAV audio, multiline CSV/TSV, searchable text, STL/OBJ geometry,
lists, escaped values, worker suffixes, legacy and malformed names, unregistered
images and conflicting filename hints. No solver is run. Check actual video decoding:

```sh
VIEWER_FIXTURE=/path/to/viewer-test node --test tests/viewer/filename.browser.test.mjs
```

Set `PARAVIEW_FILENAME_FIXTURE` to a completed output directory from the native
acceptance example to also check the actual U/p images, planes and grouping.
