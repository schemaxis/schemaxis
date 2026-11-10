"""Finite first-open inspection of a host-verified typed Part publication."""
import json
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail
from .native import check_definition,output_object,export_snapshot
from .step_source import checkpoint


def inspect(directory):
    directory=Path(directory);request=json.loads((directory/'part-gui-request.json').read_text())
    path=Path(request['file']);checkpoint()
    # The host verifies this owned packet before launch. The digest closes the
    # transport race; this finite GUI worker is not a foreign-document importer.
    if file_digest(path)!=request['sha256']:fail('INPUT_CHANGED','Verified Part publication changed before GUI inspection')
    doc=App.openDocument(str(path))
    try:
        prepared=request['prepared']
        sources={n['id']:{'sha256':n['source']['sha256']} for n in prepared['nodes']
                 if n['filter'] in ('importSTEP','importMesh')}
        check_definition(doc,prepared,sources)
        output=output_object(doc,prepared)
        visible={obj.Name:bool(obj.ViewObject.Visibility) for obj in doc.Objects}
        if 'partDesign' in prepared:
            # A Body and its final tip are both visible in the existing native
            # history policy. Bind actual GUI values to that same full map.
            from .part_design_native import observe
            from .part_design import verify_observation
            observed=observe(doc,prepared,visibility=False);observed['visibility']=visible
            verify_observation(prepared,observed)
        elif visible!={obj.Name:obj==output for obj in doc.Objects}:
            fail('VERIFICATION_FAILED','First-open Part visibility differs from selected output')
        Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll()
        Gui.activeDocument().activeView().saveImage(str(directory/'part-first-open.png'),900,650,'White')
        checkpoint()
        return {'visible':visible,'output':output.Name,'geometry':export_snapshot(output.Shape)}
    finally:App.closeDocument(doc.Name)
