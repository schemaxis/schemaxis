# Artifact viewer

Artifact is a local, read-only viewer for selected files and folders. Its Python
package, `schemaxis_viewer`, imports no Schemaxis modules and has no third-party
runtime dependencies. The browser UI uses local JavaScript and WebGL, with no
CDN, remote assets or upload service.

## Start it

After installing Schemaxis:

```sh
schemaxis-viewer /path/to/results /path/to/domain.stl
```

From a source checkout:

```sh
PYTHONPATH=src python3 -m schemaxis_viewer /path/to/results
```

With no paths, start an empty viewer, then use **Open folder**, **Add folder**,
**Add files** or drag and drop:

- **Open folder** replaces the contents, filter, selection and playback. Opening
  the same folder again rereads its files and metadata.
- **Add folder**, **Add files** and drops append to the existing contents.
- **Include subfolders** appears in the folder chooser and above the gallery.
  When unchecked, the current folder level is shown. The file navigator still
  lets you enter a subfolder; checking it shows descendants of that location.
- Cancelling a chooser leaves the current contents in place.

The local folder chooser lists directory names and passes the chosen paths to
Python. Media travels only from the local filesystem to the browser over
loopback. Browser-selected files stay in the browser. Neither path requires
uploading CFD data to a remote service. Folder actions avoid the browser's
misleading directory-upload confirmation. File bytes are served only from
explicitly opened collections, behind the session URL. Stop the standalone
server with Ctrl+C.

The **sun/moon button** matches Studio: it switches directly between light and
dark. On first use it follows the system theme; an explicit choice is remembered.
When Studio launches the viewer, its current theme is supplied immediately.
Standalone theme/sidebar preferences and recent folder references are saved under
`$XDG_STATE_HOME/schemaxis/viewer-recent.json` (default
`~/.local/state/schemaxis/viewer-recent.json`). History stores paths and publication
references, not copies of media. Browser-picked files can be reopened from the
recent list during the current page session.

## Studio results

Studio's **Results** window embeds the same viewer assets and local media
transport. Case Runner automatically loads the completed run directory into
this viewer below its progress display, with **Open in Results** for more space.
A successful native Workbench run/preview opens its complete results collection;
the existing single-file reference/picking panels remain available in Workbench.
Planning-only checkpoints do not masquerade as native results.

The handoff inventories the run directory, including original publications,
metadata companions, named aliases, receipts, authored input and supporting
files. Publication hashes are checked before the collection is registered;
subsequent reads reject changed files. This viewer inventory is not a new claim
of scientific verification for every supporting file. A registered image still
needs matching, validated companion metadata for spatial placement.

Studio supplies its theme to the embedded viewer; changing the viewer's theme
also updates Studio's setting. Recent collection references are stored in
`viewer-recent.json` within the Studio workspace. The left sidebar switches
between **Collections**, **Files & folders**, **Recent runs** and **Recent
collections**; the menu button collapses it. Recent-run restoration checks the
retained publication digests before opening the collection again.

`--no-browser` prints the session URL without opening it; `--port PORT` chooses a
port. The complete `schemaxis_viewer` source directory can also be copied and run
on its own with `python3 -m schemaxis_viewer` from its parent directory.

## Share the independent viewer

Create a portable ZIP from the source checkout:

```sh
python3 tools/package_viewer.py dist/artifact-viewer.zip --sample examples/viewer-test
```

Send the ZIP and any result files through your usual file-sharing channel.
Recipients extract the ZIP, then run `python3 launch.py` on Linux/macOS or
double-click `start-viewer.cmd` on Windows (Python launcher required). Python
3.10+ and a current browser with WebGL are the only runtime requirements.
There is no Schemaxis installation, pip dependency, native application, account
or external service. The included sample opens when launched without arguments;
`python3 launch.py /path/to/results` opens another folder. Keep the terminal
open during viewing; Ctrl+C stops the server. Windows and macOS launchers are
provided; the isolated Python acceptance check and Chromium checks run on Linux.

Each colleague runs a local viewer. Its loopback session URL belongs to that
computer; the package is not a hosted collaboration service. Without checked
companions, ordinary images, photos, videos, meshes, text and tables still work.
Scientific placement requires the documented companion contract.

## Acceptance folder

`examples/viewer-test` combines a flat root of outputs with actual Schemaxis
key-value filenames and nested folder/legacy-name examples. The root uses the
same serializer as the ParaView adaptor. It contains 36 synthetic registered X/Y/Z slices for U and p with
`model=on/off` variants, named photos without frame/time keys, a time sequence,
an OBJ domain, STL, a WebM
video, a 450-record log and CSV/TSV tables with quoted multiline cells. Its
README contains a hands-on checklist and an example capture expression. No
solver was run. Choose `kind=slice`, then group by `var → axis → model`.
These keys are decoded from filenames; the companions supply spatial placement
without group, property or sequence labels. A browser acceptance test also
removes all companions and checks the same key intersections and hierarchies.
`folders/alpha/icons` and `folders/beta/icons` contain tiny 16×16 icons with
matching `file-AAA-0-name.png` / `file-AAB-1-name.png` patterns. `legacy/numeric`
and `legacy/alphabetic` contain `shot-001/002/010.png` and `phase-A/B/Z/AA.png`.
`legacy/slices` tests capture rules and unmatched `model.png`/`error.log`.
`legacy/tags` contains overlapping dot-separated tag sets. Import
`legacy/filename-rules.examples.json` to try all three example extraction rules,
or use the built-in slice/tag examples in Filename rules.
Regenerate a separate folder from the source checkout with:

```sh
# Optional video generation requires Node 22+ and Chromium:
node tools/generate_viewer_webm.mjs /tmp/viewer-sample.webm
PYTHONPATH=src python3 tools/generate_viewer_acceptance.py /tmp/viewer-acceptance --video /tmp/viewer-sample.webm
# Omit --video and the preceding Node command for a smaller fixture.
PYTHONPATH=src python3 -m schemaxis_viewer examples/viewer-test
```

The generator imports Schemaxis source to exercise its naming code. Recipients
of the packaged viewer do not need Schemaxis to open the generated files.

## Find the right representation

The default layout is **collection → sequence → file**. Four labelled modes stay
visible, with counts or a short explanation when a mode needs additional data. A contents strip links directly to every image
sequence and the remaining files:

- **Gallery** shows image thumbnails and file cards. X, Y, Z, time and numbered
  stacks have separate headings. The size slider adjusts the grid. Large
  sections load additional rows as you scroll; thumbnails load lazily. A Show more
  control is also available. Select a thumbnail to highlight it
  and locate the slice; **Open** opens its
  individual viewer. Checkboxes control individual previews, responsive gallery
  rows, complete sequences and collections. **Select everything** and **Deselect
  everything** affect all files in the session, including filtered files; mixed
  rows and sequences show an indeterminate checkbox. **Restore hidden previews** is also
  available from other views. Names or compact filename ranges remain visible
  when previews are hidden. Returning from an individual file restores the
  gallery position, selection, loaded rows and thumbnail size.
- **Animate** shows one selected stack, with a slider, forward/reverse play,
  single-step controls and a Play/Pause toggle. **Playback options** holds reverse
  playback, speed and Once/Repeat/Oscillate behaviour. The selector
  switches axis, time or series without introducing indentation.
  **Photo series** also plays any two or more checked images in the current
  collection, in natural filename order, including unnumbered photos. It uses
  the same manual steps, slider, speed, direction and end behaviour. It begins
  at the first photo and makes no claim about physical coordinates or timestamps.
- **Compare XYZ** places compatible X, Y and Z stacks side by side. Numeric
  coordinates snap to the nearest available image; the step buttons move to adjacent
  observed coordinates, including irregularly spaced coordinates. Sliders and
  per-axis playback remain available. **Link slice progress** sweeps the stacks
  at the same fractional progress; turn it off for independent coordinate selection.
  Crosshairs use registered corner mappings and the common coordinate frame.
- **3D space** textures the selected slices on their recorded image planes. Drag
  to orbit, Shift/right-drag to pan, wheel to zoom, arrow keys to rotate, and F to
  fit. The X/Y/Z/ISO buttons snap the view. Compact axis controls move the planes
  without repeating the three image windows below the scene. Mesh controls appear when a domain mesh is present;
  the frame selector appears when there are multiple frames. Three-corner affine
  and four-corner projective image mappings are supported.

Image, sequence, XYZ, 3D, video, table and text panes have a vertical **Height**
slider and a draggable bottom edge. The bottom edge also accepts the arrow and
Page Up/Down keys. Heights are remembered during the current page session.
**Expand** fills the browser content area, including when embedded in Studio.
**Restore** or Escape returns the pane to its previous size and scroll position;
playback, coordinates and camera state remain in the same viewer instance.

**Close viewer** asks for confirmation before ending the viewing session and
releasing loaded media. In Studio Results, confirmation closes that tab; closing
Results through its tab button also confirms. The standalone viewer, and an
inline Case Runner viewer, show a closed screen with **Open viewer** to start
again. Cancelling or pressing Escape at the confirmation retains the collection.

The location panel stays visible while the data pane scrolls. At larger widths
it sits above the optional metadata details on the right; narrower layouts pin a
compact version above the data. It shows the selected axis/coordinate, filename
and position on an overview image or a world-coordinate reference sketch.
Hovering another thumbnail does not change the selection. **Details** opens file
information and raw metadata separately.

**All outputs** shows the opened contents in one scrolling gallery. **Show**
filters images, videos, audio, 3D models, tables, text or other files. **Files &
folders** provides a folder tree, clickable breadcrumbs and child-folder buttons;
file cards retain their relative paths.

**Automatic groups** uses explicit metadata groups, descriptive filename properties,
native publication scene identities, then directory and legacy filename prefixes. **By folder** and **All
selected files** provide broader collections without renaming or moving files.
Independent folder/import scopes and declared spatial frames remain separate
in 3D. These grouping choices affect this viewing session only.

**Group hierarchy** adds up to three nested levels in Collections, for example
`var → axis → model`, or `folder → fileType`. Click a branch to view its files;
each branch has a checkbox to select or deselect all its descendants. List-valued
properties may belong to more than one branch; file membership is deduplicated.
Files without a property appear under `(unspecified)`. **All groups** restores
the full hierarchy, and **Flat collections** restores the default sidebar.

Property filters intersect, so `var=U` plus `axis=X` finds all U slices along X.
**Select matching** and **Deselect matching** affect files matching the current
folder, collection, type, properties and name filter. **Select everything** and
**Deselect everything** retain their session-wide scope. Files are never moved
or deleted by these controls.

## Filename capture rules, tags and automatic sequences

Folder grouping, Schemaxis key-value grouping and filename capture rules can be
used together. **Filename rules** lists editable regex patterns, enabled flags,
case options and one output field per capture. Add a custom rule, or start with
**Add slice example** / **Add tags example**. Captures can become Text, Number,
or **Split into tags**, using a literal separator such as `.`. Apply changes to
the loaded collection; the editor closes to show the results. Invalid or timed
out drafts preserve the last successful rules and values. Removing or disabling
a rule takes effect when changes are applied.

For example, `[sS]lices.([XYZ]).([0-9]*)` can map capture 1 to `axis` (Text)
and capture 2 to `number` (Number). `Slices.X.001.png` then exposes `grep.axis=X`
and `grep.number=1`. Unmatched files get no fields; optional empty captures get
no value. Use `[0-9]+` when at least one digit is required, and `[._-]` to limit
the separator rather than accepting any character with `.`. Expressions use
JavaScript regex syntax without surrounding slashes, match the basename only,
and use the first match. Named captures supply convenient initial field names.

The tags example uses `-tags-([^-]+)-enclosedByDashes-`, maps capture 1 to `tags`,
and splits on `.`. A name containing `-tags-red.blue-enclosedByDashes-` exposes
`grep.tags=["red","blue"]`. List-valued properties have searchable **checkbox
lists**. Checking red and blue includes files containing either tag. A different
property, such as `grep.code=AAA`, is combined with that tag filter using AND.
**Any** (no boxes checked) removes that property's filter and includes files
without it again. Select/Deselect matching can apply these filters to preview
selection. Repeated assignments to the same extracted key combine distinct
values. Derived `grep.*` names keep captured labels separate from checked
metadata and encoded filename properties; they never establish spatial placement.

Applied rules are remembered in browser storage for the same origin. They are
independent of media and source paths. **Export filename rules** saves the
applied rule list as JSON; **Import filename rules** loads a draft for review and
application. Example rule files inside a collection are never executed
automatically. Rules run in a worker with a 1.5-second batch timeout; limits are
20 rules, 20 output captures per rule, 2,000 characters per expression and 64 KiB
per imported rule file.

For common legacy names, no rule is needed. The viewer detects changing integer
and short alphabetic token columns within a consistent filename layout, folder
and source. **auto.numericSequence**, **auto.alphabeticSequence** and
**auto.sequence** become grouping/filter options; **auto.number1** and
**auto.letters1** expose values (additional changing columns receive 2, 3, etc.).
For `file-AAA-0-name.png` / `file-AAB-1-name.png`, both code and number are
available. Numeric ordering handles zero padding; alphabetic ordering follows
A…Z, AA…AZ, BA… and supports existing playback controls. Detected families need
at least two images. The heuristics cover integer runs and uppercase codes of
one to four letters or single lowercase letters, with up to four changing
columns per filename. Custom rules handle other
conventions. These orders are labelled inferred, have no physical units, and do
not create 3D placement. Explicit metadata sequences and new-format Schemaxis
ordinals retain their existing interpretation.

Checked companions can include a `properties` object whose values are strings,
finite numbers, booleans, null, or lists of these values. These optional viewer
labels override the same keys in descriptive filenames. `group`, spatial frame
(`frameName`) and publication scene also become filter and hierarchy choices.
For example, plain `slice.png` can carry
`"properties": {"var": "U", "axis": "X", "model": "on"}` in its checked
companion. These labels describe membership; registered placement still uses
the spatial contract. The existing publisher does not yet forward arbitrary
`properties` fields; the independent acceptance generator authors them directly.

In **3D space**, **Show all selected image planes** displays every checked image
plane currently included by selection and filtering within the chosen source,
frame and units. Turning it off returns to the interactive slice controls. The
domain mesh remains visible. This also supports several individually registered
images that do not belong to any ordered sequence.

## Metadata and domain context

New ParaView names expose overlapping **Filename properties** filters, including
variable, axis, position, model visibility and list members. Details shows decoded
properties. See [Descriptive output filenames](output-filenames.md) for the format
and reproducible mixed-media test folder. Checked metadata takes precedence over
filename hints for sequence order and spatial placement.

See [Output metadata](output-metadata.md) for the producer contract. The viewer
recognises `.metadata.json`, `.scxmeta`, `.scxmeta.json` and `.METADATA` companions,
but the suffix alone is insufficient: the version must be
`schemaxis.artifact-metadata/1`, the sibling basename must match `artifact.file`,
and the artifact SHA-256 must match. Conflicting companions disable placement.
Foreign sidecars remain ordinary files. Import warnings explain rejected
metadata in the context panel. A checked sidecar is not a verification of the
whole Schemaxis run or its publication manifest.

Spatial textures require `spatial.state: "known"`,
`mapping: "pixel-edge-rays-to-slice-plane"`, ordered finite, convex, coplanar
corners and a declared coordinate frame. Camera focal planes are identified in
the inspector and do not become physical slice planes. Accepted corner labels
are `top-left`, `top-right`, `bottom-right`, `bottom-left`; a three-corner mapping
uses `top-left`, `top-right`, `bottom-left`. Rows run down from the top-left pixel
edge. Other origin/row conventions are not currently projected.

For a domain surface, include an STL/OBJ artifact in the collection with known
spatial metadata in the same source scope, frame and units. Use the grouping
selector or a shared metadata `group` to bring it into the same collection. The
first matching mesh is used; wireframe keeps slices visible and solid mode
provides mesh depth occlusion. Without a matching mesh, the 3D viewer shows a
reference cage using declared bounds (honouring `boundsOrder`) or the union of
image corners. A cage is not a reconstruction of the CFD domain.

`overview.file` displays a selected overview image in the context panel. When
its checked metadata includes a camera in the same source scope, frame and units,
selected slice outlines and centre labels are projected onto the overview.
Without that camera registration it remains a reference image; interactive
slice locations appear in 3D. Unknown units are displayed without conversion. The
viewer does not assume equal physical scale across differing frames or units.
Entire viewport images are projected, including their backgrounds and legends;
alpha is preserved. No CFD region mask or scientific value is inferred from
pixel colours.

Explicit `sequence` hints take priority. With existing Schemaxis output, native
slice planes supply physical axes/coordinates; publication identities separate
camera/appearance variants and `viewTime` separates spatial stacks by time.
Repeated fixed coordinates across observed times also form temporal stacks.
Numeric filenames supply a fallback order, clearly labelled as inferred. This
fallback never establishes a physical image plane. XYZ requires compatible
series/time/frame/units and all three axes; oblique planes remain available in
3D even when they do not form an XYZ stack.

## Other file types and limits

- Images: browser-supported PNG/JPEG/WebP/GIF/AVIF/BMP/SVG, with pan and zoom in
  the individual viewer. Animated formats follow browser support.
- Geometry: triangulated binary/ASCII STL and polygonal OBJ previews. OBJ faces
  are fan-triangulated; use triangulated inputs for non-convex polygons. MTL
  materials and external textures are not loaded. Other native mesh/data formats
  can be inspected as text where appropriate or downloaded; they need an STL/OBJ
  preview for interactive geometry.
- Audio/video: browser-native playback and seeking; codec support varies.
- CSV/TSV: quoted/multiline fields, searchable paged rows, selectable numeric
  column plots. The first record is shown as headings. The plot uses preview
  records in file order, independently of the table filter.
- Text: read-only numbered lines and two search modes. **Find in text** keeps
  surrounding lines visible and highlights occurrences; **Next match** and
  **Previous match** wrap across pages. Ctrl/Cmd+F focuses search; Enter/F3 and
  Shift+Enter/Shift+F3 move forward and backward. Literal/regex, case-sensitive
  and whole-word options are available. **Grep / capture table** returns one row
  per match, including line and column, with a selectable field for each regex
  capture group. Named groups use their names; ordinary parentheses use Group
  1, Group 2, etc. For example, `Time=(?<time>[\d.]+) U=([\d.]+)` yields `time`
  and `Group 2` columns. **Export matches CSV** downloads the visible capture
  columns for all preview matches. Searches run in a worker with a one-second
  time limit and a 20,000-match result limit. Expressions run per line using
  JavaScript regex syntax; they do not span line breaks.
- Other files, including XLSX/ODS/PDF/GLTF: download the original. Export workbook
  sheets as CSV/TSV for tables. No native workbook calculation is provided.

Limits are 50,000 files per CLI scan or browser selection, 2 MiB per metadata sidecar, 256 MiB per artifact
for browser hash verification, 64 MiB/200,000 triangles per mesh preview, and
4 MiB per table/text preview. Oversized metadata artifacts remain viewable but
are not spatially registered without verification. Preview limits are shown in
the UI. Open collections retain a file snapshot; reopen the folder to rescan changed
files. Recent folder references and preferences persist independently of that
snapshot. The server rejects artifacts modified
after inventory, so old placement metadata is not used with new file contents. The synthetic demo is procedural sample data, not a solver result.

## Verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_artifact_viewer.py -q
node --test tests/viewer/model.test.mjs
node --test tests/viewer/*.test.mjs
node --test src/schemaxis/studio_ui/tests/results.browser.test.mjs
```

Browser checks require Chromium (or `CHROMIUM=/path/to/chromium`) and Node 22+.
`VIEWER_SCREENSHOTS=/output/folder` records gallery, XYZ and spatial screenshots.
