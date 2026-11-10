"""Read-only first-open inspection of a completely host-verified assembly."""
import json
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail
from .step_source import checkpoint


def inspect(directory):
    from .assembly_sources_native import runtime,snapshot,matrix,shape_record
    from .body_seed_native import local_shape
    from .gui_native import frame_view
    directory=Path(directory);request=json.loads((directory/'source-gui-request.json').read_text())
    path=directory/'model.FCStd';checkpoint()
    # Only the installed host writes this request, after full source authority,
    # copied graph, SID/map and payload verification. No submitted path is used.
    if file_digest(path)!=request['sha256']:
        fail('INPUT_CHANGED','Verified sourced assembly changed before GUI inspection')
    runtime();Gui.activateWorkbench('AssemblyWorkbench');checkpoint()
    doc=App.openDocument(str(path))
    try:
        prepared,renames=request['prepared'],request['renames'];bodies={}
        observed=snapshot(doc,prepared,renames)
        visible={o.Name:bool(o.ViewObject.Visibility) for o in doc.Objects}
        providers={}
        for obj in doc.Objects:
            proxy=getattr(obj.ViewObject,'Proxy',None)
            if proxy is not None:
                providers[obj.Name]={'class':type(proxy).__name__,'attached':hasattr(proxy,'app_obj')}
        for part in prepared['parts']:
            checkpoint();body=doc.getObject(renames[part['id']][part['source']['body']])
            bodies[part['id']]={'placement':matrix(body.Placement),'shape':shape_record(local_shape(body))}
        frame_view(doc,list(prepared['native']['components'].values()))
        Gui.activeDocument().activeView().saveImage(str(directory/'source-first-open.png'),900,650,'White')
        checkpoint()
        if file_digest(path)!=request['sha256']:
            fail('INPUT_CHANGED','Read-only assembly GUI inspection changed its native publication')
        return {'snapshot':observed,'visibility':visible,'providers':providers,'bodies':bodies,'sha256':request['sha256']}
    finally:App.closeDocument(doc.Name)
