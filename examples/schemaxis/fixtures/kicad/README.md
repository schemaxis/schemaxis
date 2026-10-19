# KiCad board fixtures

Four original two-layer boards written by hand for the `schemaxis.kicad/1` adaptor and
saved in the KiCad 10.0 board format with `kicad-cli pcb upgrade --force` (KiCad
10.0.7). They contain no third-party library footprints: every footprint is inline.
Each `.kicad_pro` declares a 0.2 mm Default netclass clearance and sets
`lib_footprint_issues`/`lib_footprint_mismatch` to `ignore`, because the inline
footprints are not in any library.

- `tiny-board`: baseline, clean DRC.
- `tiny-variant`: different outline, rotation, nets, vias and holes; clean DRC.
- `tiny-clearance`: baseline plus an AUX net 0.1 mm from GND; two clearance errors.
- `tiny-open`: baseline without one GND track; one unconnected item.

Expected counts and geometry are derived from the declared coordinates in
[`docs/kicad.md`](../../../../docs/kicad.md#fixtures), not from KiCad output. These
are input data. Source-bound qualification includes their bytes, so editing them
invalidates the KiCad receipt; review geometry and expectations together.
