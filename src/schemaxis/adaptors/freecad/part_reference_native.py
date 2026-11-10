"""Finite save lifecycle of a freshly constructed trusted Part reference.

Only the host-created reconstruction directory reaches this worker. It never
receives a submitted FCStd or a path selected by a saved receipt.
"""
import json
from pathlib import Path
import FreeCAD as App
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .native import check_definition,output_object,export_snapshot
from .step_source import checkpoint


def resave(directory, *, body_local=False):
    if type(body_local) is not bool:
        raise ValueError('body_local must be an exact boolean')
    directory=Path(directory);checkpoint()
    prepared=json.loads((directory/'plan.json').read_text())
    sources=json.loads((directory/'sources.json').read_text())
    from .helix import active as helical
    if body_local:
        # The host opts in only for an explicitly selected portable Body.
        # This worker receives its freshly compiled reference, never the
        # submitted source or receipt-selected object names.
        from .source_bridge import selected_body
        selected_body(prepared)
    elif (not any(n['filter']=='draftProfile' for n in prepared['nodes'])
            and not prepared.get('partDesign',{}).get('seeds') and not helical(prepared)):
        fail('VERIFICATION_FAILED','A pure Body reference lifecycle requires explicit local admission; nonlocal saves require Draft, a seed or Helix')
    doc=App.openDocument(str(directory/'model.FCStd'))
    try:
        check_definition(doc,prepared,sources)
        before=export_snapshot(output_object(doc,prepared).Shape)
        if body_local:
            from .assembly_sources_native import ordered_history
            objects=sorted(obj.Name for obj in doc.Objects)
            mapping={name:name for name in objects}
            history_before=ordered_history(doc,mapping)
        for obj in doc.Objects:checkpoint();obj.touch()
        doc.recompute();checkpoint();check_definition(doc,prepared,sources)
        after=export_snapshot(output_object(doc,prepared).Shape)
        if body_local:
            history_after=ordered_history(doc,mapping)
        target=directory/'resaved';target.mkdir()
        doc.saveAs(str(target/'model.FCStd'));checkpoint()
        from .gui_state import persist
        persist(target/'model.FCStd',{obj.Name:bool(obj.Visibility) for obj in doc.Objects})
        evidence=({'version':'schemaxis.freecad.body-reference-lifecycle/1',
                   'objects':objects,'before':history_before,'after':history_after}
                  if body_local else {'before':before,'after':after})
        atomic_json(target/'reference-lifecycle.json',evidence)
    finally:App.closeDocument(doc.Name)
