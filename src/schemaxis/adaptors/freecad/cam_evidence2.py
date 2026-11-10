"""Bounded typed JSON receipts for CAM2; observation records are not authority."""
import json
import math
from pathlib import Path


def same(actual,expected):
    if type(actual) is not type(expected):return False
    if isinstance(expected,dict):return actual.keys()==expected.keys() and all(same(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):return len(actual)==len(expected) and all(same(a,b) for a,b in zip(actual,expected))
    return actual==expected


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate CAM2 receipt key')
        result[key]=value
    return result


def _constant(value):raise ValueError('non-finite CAM2 receipt value')


def _float(raw):
    value=float(raw)
    if not math.isfinite(value):raise ValueError('overflowed CAM2 receipt number')
    return value


def binary(path,limit):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        raise ValueError('CAM2 receipt must be one bounded regular file: '+path.name)
    with path.open('rb') as stream:data=stream.read(limit+1)
    if len(data)>limit:raise ValueError('CAM2 receipt grew beyond its bounded read')
    return data


def text(path):return binary(path,4*1024*1024).decode('ascii')


def read(path,limit=8*1024*1024):
    return json.loads(binary(path,limit),object_pairs_hook=_pairs,parse_constant=_constant,parse_float=_float)
