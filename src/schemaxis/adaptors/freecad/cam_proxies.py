"""Closed saved-state contract for the qualified native CAM proxy classes.

This decodes bounded JSON primitives only; it never imports or restores a proxy.
The installed 1.1.4 toolbit serialises its quantities in millimetres to two places.
Exact saved native quantities are checked independently by cam_checks.
"""
import base64
import json

TOOL_ID='bffbfb6d-8a40-46dd-9147-73c44f21775b'


def tool_state(tool):
    params={prop:format(tool[key],'.2f')+' mm' for prop,key in (('CuttingEdgeHeight','cuttingLength'),('Diameter','diameter'),('Length','length'),('ShankDiameter','shankDiameter'))}
    params.update(Flutes=int(tool['flutes']),Material='HSS',SpindleDirection='Forward')
    return {'id':TOOL_ID,'_in_update':False,'_obj_data':{'version':2,'id':TOOL_ID,'name':'Endmill','shape':'endmill.fcstd','shape-type':'Endmill','parameter':dict(params,Chipload='0.00 mm'),'attribute':{}},'_shape_data':{'id':'endmill','name':'Endmill','parameters':params}}


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate proxy state key')
        result[key]=value
    return result


def _constant(value):raise ValueError('non-finite proxy state')


def _same(actual,expected):
    if type(actual) is not type(expected):return False
    if isinstance(expected,dict):return actual.keys()==expected.keys() and all(_same(actual[k],v) for k,v in expected.items())
    return actual==expected


def check(node,module,cls,expected):
    if set(node.attrib)!={'module','class','encoded','value'} or node.get('module')!=module or node.get('class')!=cls or node.get('encoded')!='yes' or len(node) or (node.text or '').strip():raise ValueError('Saved native proxy attributes differ')
    encoded=node.get('value')
    if len(encoded)>8192:raise ValueError('Saved native proxy state exceeds the bounded contract')
    raw=base64.b64decode(encoded,validate=True)
    if len(raw)>4096 or base64.b64encode(raw).decode()!=encoded:raise ValueError('Saved native proxy encoding differs')
    state=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
    if not _same(state,expected):raise ValueError('Saved native proxy state differs from the reviewed tool and class contract')
