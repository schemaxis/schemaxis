SYNTHETIC ACCEPTANCE FOLDER - no solver was run.
Root media use the actual Schemaxis filename serializer; folders/ and legacy/ exercise other naming conventions.
Choose kind=slice, then group by var > axis > model; these properties come from filenames.
Slice names use the same image_properties helper as the ParaView adaptor.
Companions supply checked spatial placement only; no group/properties/sequence labels.
Try var=U, axis=X, model=on. Select matching / Deselect matching.
Choose series=photos for manually named photo playback; series=pulse for time frames.
3D space: Show all selected image planes with the domain mesh.
Open name=solver: Find, Enter/Shift+Enter, F3, whole words; Grep + Regex:
Time=(?<time>[\d.]+) U=(?<velocity>[\d.]+) residual=([\d.]+)
Toggle individual capture columns; export matches CSV.
CSV/TSV: quoted fields, paging, search, selectable numeric graph axes.
STL/OBJ: orbit, pan, zoom, fit. kind=animation selects the optional WebM.

FOLDER AND LEGACY RULE CHECKS (16x16 synthetic icons)
folders/alpha/icons and folders/beta/icons: group by folder, then auto.number1 or auto.letters1.
legacy/numeric: shot-001/002/010; legacy/alphabetic: phase-A/B/Z/AA.
Filename rules: Add slice example and Add tags example, then Apply filename rules.
Or Import filename rules from legacy/filename-rules.examples.json (includes file code/index).
legacy/slices: grep.axis and grep.number. model.png and error.log get no capture values.
legacy/tags: grep.tags checklist. red OR blue matches three files; combine grep.code with tags.
Any tag means no tag filter. Selected values within a key use OR; different keys use AND.
Auto sequence groups are inferred filename order, never physical image placement.
