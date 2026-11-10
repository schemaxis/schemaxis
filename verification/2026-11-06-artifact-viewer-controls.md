# Viewer controls aligned with Studio — 2026-11-06

The viewer uses Studio's sun/moon icon geometry and direct light/dark toggle.
System appearance supplies the first-use default; a saved explicit choice takes
precedence. Studio passes its theme on launch and synchronises later changes in
both directions.

Sequence/XYZ, spatial and individual-file panes share vertical height sliders,
pointer/keyboard resize handles, and Expand/Restore controls. Expansion uses the
existing pane DOM and fills the browser area, including through Studio's iframe
bridge. Placeholders and scroll snapshots preserve browsing position. Escape
restores the pane; resize observers update canvas sizes and slice crosshairs.

Close viewer confirms before releasing the collection and stopping playback.
Studio Results tab closure also confirms; a child-confirmed close does not ask a
second time. Standalone and inline viewers show a closed state with a reopen
action. No run files are removed.

Verification:

- All 20 viewer/model/Studio browser checks pass. New acceptance covers initial
  system appearance, explicit theme precedence, actual pointer resizing, pane
  dimensions, slice continuity, retained height and scroll position, Escape,
  expansion across Studio chrome, cancel/confirm closure and reopening.
- Existing gallery, metadata, HTTP import/CSP, sequence, textured-3D, mesh, table,
  text and Studio theme checks remain passing.
- Desktop resized XYZ and expanded 3D screenshots were inspected. Narrow and
  dark appearances were checked separately.
- This revision changes browser controls only. Native scientific applications
  and the complete Python host suite were not rerun.
