# Copyright (C) 2026 David L F Gaden
"""Persistent Blender worker with bounded authored input and native geometry.

LiveSession(executable, fresh_directory) supports request('apply', document=...),
request('geometry'), request('status'), image(absolute_png_path),
save(absolute_blend_path) / request('save', path=...), and close().
Use one scene and one geometry state; batch iteration is explicitly unsupported.
Face IDs identify evaluated mesh polygons within a revision, not CAD topology.
Coordinates and units are native. Compatible edits retain native object handles.
Native scenes are process-local, with no reverse synchronisation of GUI edits.
Images are fixed-camera 640x480 CPU previews, not authored batch publications.
Only bounded geometry is transferred (100000 faces, 500000 face vertices,
32 MiB JSON); limits do not bound the native application's transient memory.
Timeout/exit closes the session. Native apply failures rebuild and compare the
previous observations and tessellation, or report UNCERTAIN_STATE. Close the
session explicitly (or use a with block). Idle workers exit when the host dies.
Save produces a .blend and .blend.receipt.json, embeds authored metadata, and
checks the saved library's native object/material membership. The receipt states
that geometry replay is not independently verified by save itself. Native tests
add a fresh-process geometry-reopen check. Saved files never replace live handles.
Cancellation through dispatch.allocation closes the session with RUNNER_CANCELLED.
"""
from schemaxis.live_transport import ProcessSession


class LiveSession(ProcessSession):
    provider = 'blender'
