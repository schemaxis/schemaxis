# Copyright (C) 2026 David L F Gaden
"""Persistent serial builtin ParaView worker; no GUI or remote server required.

The API matches blender.live.LiveSession. executable accepts pvpython, pvbatch,
or an installation root. One scene/state is supported using existing declared
operations. Geometry uses native coordinates and surface-cell face IDs scoped
to the revision and composite leaf; these are not stable CAD topology names.
Lifecycle, rollback, transfer limits and context management match blender.live.
image(path) writes a fixed-camera 640x480 neutral-surface PNG; authored batch
publications are not executed. Tables and non-dataset geometry are rejected.
save(path) / request('save', path=...) creates .pvsm plus .pvsm.receipt.json.
Verification checks XML and live proxy membership, not an independent data reload.
State files reference external datasets; no dataset is copied. The receipt lists
declared file/files references but does not exhaustively enumerate case directories
or transitive sidecars. Native state is not advertised as a portable data bundle.
"""
from schemaxis.live_transport import ProcessSession


class LiveSession(ProcessSession):
    provider = 'paraview'
