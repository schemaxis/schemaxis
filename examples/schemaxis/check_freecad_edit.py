# Copyright (C) 2026 David L F Gaden
"""Run inside FreeCADCmd to prove the saved bracket remains parametrically editable.

SCHEMAXIS_CAD_GALLERY=/absolute/gallery /path/freecadcmd /absolute/check_freecad_edit.py
Changes remain in memory; the original FCStd file is not overwritten.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import FreeCAD as App

gallery=os.environ.get('SCHEMAXIS_CAD_GALLERY')
if not gallery:
    raise RuntimeError('Set SCHEMAXIS_CAD_GALLERY to the saved gallery directory')
root=Path(gallery).resolve()
jobs=json.loads((root/'result.json').read_text())['jobs']
target=Path(next(j['directory'] for j in jobs if j['operation']=='bracket'))/'model.FCStd'
before=hashlib.sha256(target.read_bytes()).hexdigest()
doc=App.openDocument(str(target))
objects={o.Label:o for o in doc.Objects}
original=objects['cut3'].Shape.Volume
objects['upright'].Height=80
doc.recompute()
shape=objects['cut3'].Shape
expected=original+100*8*20
if not shape.isValid() or len(shape.Solids)!=1 or not math.isclose(shape.Volume,expected,rel_tol=1e-9):
    raise RuntimeError('Native feature-tree edit did not propagate through boolean dependencies')
report={'verified':True,'source':str(target),'originalHeightMM':60,'editedHeightMM':80,
        'originalVolumeMM3':original,'editedVolumeMM3':shape.Volume,'expectedVolumeMM3':expected}
App.closeDocument(doc.Name)
if hashlib.sha256(target.read_bytes()).hexdigest()!=before:
    raise RuntimeError('Read-only edit qualification changed the source file')
report['sourceUnchanged']=True
(root/'cad-edit-check.json').write_text(json.dumps(report,indent=2)+'\n')
print('CAD_EDIT_VERIFIED',json.dumps(report))
