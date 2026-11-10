"""Exact six-decimal native Path serialization/readback binding for CAM2."""
import math
import re
from zipfile import ZipFile
from schemaxis.errors import fail
from .cam_code import WORD
from .cam_code2 import GROUPS
from .document_xml import read_member


def commands(directory,saved,identity):
    member=saved.child(identity,'Path','Path','Path::PropertyPath').get('file')
    with ZipFile(directory/'machining.FCStd') as archive:data=read_member(archive,member,4*1024*1024).decode('ascii')
    if not data.startswith('('+identity+')\n'):fail('VERIFICATION_FAILED','Saved CAM2 path identity differs',identity)
    result=[]
    for line in data.splitlines():
        line=line.strip()
        if not line:continue
        if line.startswith('(') and line.endswith(')'):
            if '(' in line[1:] or ')' in line[:-1]:raise ValueError('nested native path comment')
            result.append({'name':line,'parameters':{}});continue
        words=WORD.findall(line)
        if not words or WORD.sub('',line).strip():raise ValueError('invalid saved native path syntax')
        letter,raw=words[0];value=float(raw)
        if letter!='G' or value not in GROUPS:raise ValueError('unsupported saved native operation command')
        name='G'+(str(int(value)) if value.is_integer() else str(value));parameters={}
        for key,raw in words[1:]:
            value=float(raw)
            if key not in 'XYZIJKFRPQ' or key in parameters or not math.isfinite(value):raise ValueError('unsupported or duplicate saved path parameter')
            if key=='K' and value!=0:raise ValueError('nonzero saved native XY arc K')
            parameters[key]=value
        result.append({'name':name,'parameters':parameters})
    if not 1<len(result)<=10000:raise ValueError('saved CAM2 path is empty or exceeds its bounded command count')
    return result


def readback(record,expected):
    """Native Path::Save writes each parameter with exactly six decimal places.

An in-memory construction may retain unrounded doubles; an unchanged reopen may
hold precisely the saved decimal values. Bind BOTH via that exact serialization
function, without introducing a geometric/metric comparison tolerance.
"""
    if not isinstance(record,list) or len(record)!=len(expected):return False
    for actual,reference in zip(record,expected):
        if (not isinstance(actual,dict) or set(actual)!={'name','parameters'} or actual['name']!=reference['name']
                or not isinstance(actual['parameters'],dict) or actual['parameters'].keys()!=reference['parameters'].keys()):return False
        for key,value in actual['parameters'].items():
            if (type(value) not in (int,float) or not math.isfinite(value)
                    or format(value,'.6f')!=format(reference['parameters'][key],'.6f')):return False
    return True
