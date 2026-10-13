# Inkscape technical-diagram qualification — 2026-10-10

The new `schemaxis.inkscape/1` route was tested on native
`Inkscape 1.4.4 (1:1.4.4+202605061436+dcaf3e7d9e)` from the official stable
Inkscape PPA. Runtime and required dependencies were privately extracted into
ignored evidence; no system installation or user PATH changes were made.
The [official 2026-05-06 announcement](https://lists.inkscape.org/hyperkitty/list/inkscape-docs@lists.inkscape.org/thread/OCEYDBJCKK2ZF65O3FNKZOSTL7JBTZND/)
confirms this release despite stale draft wording in its wiki notes.

Two independently specified cases exercise an editable 120 x 60 mm diagram:
454 x 227 native RGBA8 PNG at 96 dpi, two labelled boxes, one directed connector,
and 34.6 mm minimum stroked clearance. The variant moves the second box down
15 mm, changes its label and colour and measures a native orthogonal dogleg.
Host verification reconstructs the intended SVG, checks native stroked box,
connector and arrow bounds within 0.015 mm, measures label fit inside 2 mm
padding and decodes page dimensions and known background/interior colour probes.
This is bounded geometric/layout acceptance and sparse raster evidence, not a
whole-image visual or typography certificate.

Native kit conformance checks independent literals, altered/missing publications,
authored and plan integrity, timeout and pre-launch cancellation. An additional
native check uses an 80-character label: geometry planning succeeds, actual
font-dependent measurement rejects `LABEL_OVERFLOW` with observed bounds and
recovery; shortening the label then succeeds. Mutating SVG width and refreshing
its declared hash still fails semantic verification, followed by restored success.

The fresh reproducible recipe is `tools/qualify_inkscape.py`. Its successful native
kit receipt is registered in the adaptor's `qualification.json`; additional recovery
and semantic-tamper results remain in ignored `evidence/2026-10-10-inkscape-native-4`.
Nine focused host tests, host kit conformance and readiness structural admission
pass. Conceptual guidance has 25 reference-backed records, zero pending and zero
stale addresses; those are authored explanations, not a human-reviewed claim.

Two earlier failed attempts are retained: a private runtime with an incorrect data
prefix could not load `units.xml`, corrupting mm interpretation. Repairing the
private wrapper restored correct CSS-pixel query bounds and page dimensions;
verification was not loosened to accept those bad results. A temporary scale
interpretation was reverted after the actual runtime resource issue was diagnosed.

Publications remain ordered editable SVG text, PNG image (index 1), and geometry
JSON text in mm. Scheduled reuse has a self-contained input fingerprint; the main
integration qualification separately exercises handoff and reuse. No arbitrary
SVG imports/scripts, native live editor, MPI, PDF conversion, general automatic
routing or exact installed-font equivalence is claimed.
