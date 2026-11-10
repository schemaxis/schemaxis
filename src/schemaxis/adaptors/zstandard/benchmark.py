"""Finite native benchmark reports; timings are explicitly historical observations."""
import math
import re
from schemaxis.errors import fail

FIELDS={
 'firstLevel':{'type':'integer','minimum':1,'maximum':22,'default':1},
 'lastLevel':{'type':'integer','minimum':1,'maximum':22,'default':3},
 'minimumSeconds':{'type':'integer','minimum':1,'maximum':3,'default':1},
 'benchmarkBlockBytes':{'type':'integer','minimum':0,'maximum':64*1024*1024,'default':0},
 'benchmarkMode':{'type':'enum','values':['roundTrip','decode'],'default':'roundTrip'},
}
NUMBER=r'[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
HEADER=re.compile(r'bench 1\.5\.7 : input ([0-9]+) bytes, ([0-9]+) seconds, ([0-9]+) KB blocks')
ROW=re.compile(r'-([0-9]+)\s+([0-9]+)\s+\(('+NUMBER+r')\)\s+('+NUMBER+r') MB/s\s+('+NUMBER+r') MB/s\s+(.+)')


def validate(p,authored):
    if p['lastLevel']<p['firstLevel'] or p['lastLevel']-p['firstLevel']>=4:
        fail('INVALID_ZSTANDARD_OPTION','Benchmark one to four consecutive compression levels')
    if p['benchmarkBlockBytes'] and p['benchmarkBlockBytes']<1024:
        fail('INVALID_ZSTANDARD_OPTION','Benchmark blocks are zero or at least 1024 bytes')
    if p['benchmarkMode']=='decode' and (any(key in authored for key in ('firstLevel','lastLevel'))
            or p['benchmarkBlockBytes'] or p['tuning'] or p['longWindowLog'] or p['threads']!=1):
        fail('INVALID_ZSTANDARD_OPTION','Decode benchmarking has one result and no compression level, block, worker or match-finder overrides')


def arguments(p):
    result=['-q','-i'+str(p['minimumSeconds']),'-T'+str(p['threads'])]
    if p['benchmarkMode']=='decode':result+=['-b','-d']
    else:
        result+=['-b'+str(p['firstLevel']),'-e'+str(p['lastLevel'])]
        if p['lastLevel']>19:result.append('--ultra')
        if p['benchmarkBlockBytes']:result.append('-B'+str(p['benchmarkBlockBytes']))
    return result


def parse(text,p,input_bytes,decoded_bytes,filename):
    lines=[line.strip() for line in text.replace('\r','\n').splitlines() if line.strip()]
    header=HEADER.fullmatch(lines[0]) if lines else None
    if not header or tuple(map(int,header.groups()))!=(input_bytes,p['minimumSeconds'],p['benchmarkBlockBytes']//1024):
        fail('INVALID_ZSTANDARD_BENCHMARK','Native benchmark header differs from the captured input and requested controls')
    rows=[];levels=[0] if p['benchmarkMode']=='decode' else list(range(p['firstLevel'],p['lastLevel']+1))
    if len(lines)!=len(levels)+1:fail('INVALID_ZSTANDARD_BENCHMARK','Native benchmark result membership differs')
    for line,level in zip(lines[1:],levels):
        match=ROW.fullmatch(line)
        if not match:fail('INVALID_ZSTANDARD_BENCHMARK','Unsupported native benchmark result grammar')
        actual,size,ratio,compression,decompression,name=match.groups()
        values=[float(ratio),float(compression),float(decompression)]
        # v1.5.7 BMK_benchMemAdvancedNoAlloc displays the last 17 bytes.
        # Captured native names are adaptor-owned ASCII, never authored paths.
        if (int(actual)!=level or name!=filename[-17:] or int(size)<=0 or any(not math.isfinite(value) for value in values)
                or values[2]<=0 or (values[1]<=0 if level else values[1]!=0)
                or abs(decoded_bytes/int(size)-values[0])>.000500001):
            fail('INVALID_ZSTANDARD_BENCHMARK','Benchmark sizes, ratio, level or measured rates are inconsistent')
        rows.append({'level':level,'compressedBytes':int(size),'ratio':values[0],
                     'compressionMBps':values[1],'decompressionMBps':values[2]})
    return {'mode':p['benchmarkMode'],'inputBytes':input_bytes,'decodedBytes':decoded_bytes,'levels':rows,
            'timingVerified':False,'timingScope':'Native in-memory measurements; historical speeds are not authenticated by later verification'}
