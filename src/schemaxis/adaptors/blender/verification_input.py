"""The authored program owns lowering; submitted replay files are evidence."""
import copy
import json
from pathlib import Path
from schemaxis.errors import fail
from .asset_fidelity import matching


def lowered(master):
    result=copy.deepcopy(master.document)
    result['version']='schemaxis.blender/1'
    return result


def verify_lowered(directory,expected):
    submitted=json.loads((Path(directory)/'input.json').read_text())
    if not matching(submitted,expected,exact=True):
        fail('VERIFICATION_FAILED','lowered replay input differs from trusted authored intent','input.json',
             recovery='Preserve the packet. Rerun its trusted authored intent and original inputs into a NEW output; do not replace authored intent or resnapshot the submitted consumer to authorise a different replay.')
