# Copyright (C) 2026 David L F Gaden
"""Bounded independent classic GeoTIFF reader and nearest-window oracle (stdlib)."""
from fractions import Fraction
import math
import struct
import xml.etree.ElementTree as ET

MAX_PIXELS = 262144
TYPES = {'UInt16': (16, 1, 'H'), 'Int16': (16, 2, 'h'), 'Float32': (32, 3, 'f')}
SNAPSHOT_KEYS = {'width','height','dtype','epsg','geotransform','pixelInterpretation','band','units','nodata','pixels'}


def real_finite(value):
    if type(value) not in (int,float): return False
    try: return math.isfinite(value)
    except OverflowError: return False


def conditioned(geotransform, width, height):
    """Require pixel spacing well above double-coordinate roundoff."""
    if not isinstance(geotransform,(list,tuple)) or len(geotransform)!=6 or any(not real_finite(v) for v in geotransform):
        raise ValueError('finite numeric six-value geotransform required')
    x,dx,rx,y,ry,dy=geotransform
    if rx!=0 or ry!=0 or dx<=0 or dy>=0: raise ValueError('north-up affine required')
    for origin,step,count in ((x,dx,width),(y,dy,height)):
        edge=origin+step*count
        if not math.isfinite(edge) or abs(step)<1024*max(math.ulp(origin),math.ulp(edge)):
            raise ValueError('unresolvable affine: pixel spacing must exceed 1024 coordinate ULPs')


def extent_violation(raster):
    """Return observed details when the raster extent contradicts its declared CRS, else None.

    This is a plausibility gate for new runs, not part of parse(): receipts verified
    under the earlier contract keep their original verification meaning.
    """
    validate_snapshot(raster)
    if raster['epsg']==4326:
        _,_,_,y,_,dy=raster['geotransform']
        minimum,maximum=y+raster['height']*dy,y
        if minimum < -90-1e-6 or maximum > 90+1e-6:
            return {'epsg':4326,'axis':'latitude','minimum':minimum,'maximum':maximum,'limits':[-90,90]}
    return None


def validate_snapshot(raster):
    if not isinstance(raster,dict) or set(raster)!=SNAPSHOT_KEYS: raise ValueError('raster snapshot closed shape differs')
    for k in ('width','height','epsg','band'):
        if type(raster[k]) is not int: raise ValueError(k+' must be an integer, not a boolean')
    w,h=raster['width'],raster['height']
    if not 1<=w<=4096 or not 1<=h<=4096 or w*h>MAX_PIXELS or raster['band']!=1 or raster['epsg'] not in (4326,3857): raise ValueError('raster dimensions/band/CRS differ')
    if type(raster['dtype']) is not str or raster['dtype'] not in TYPES or type(raster['units']) is not str or raster['units'] not in ('m','K','1') or raster['pixelInterpretation']!='area': raise ValueError('raster type/units/interpretation differ')
    dtype=raster['dtype'];nodata=raster['nodata'];pixels=raster['pixels']
    if not isinstance(pixels,list) or len(pixels)!=w*h: raise ValueError('raster pixel cardinality differs')
    if not real_finite(nodata): raise ValueError('finite numeric nodata required')
    values=[nodata,*pixels]
    if any(not real_finite(v) for v in values): raise ValueError('pixels require finite numbers, not booleans')
    if dtype=='Float32':
        try:
            if any(struct.unpack('<f',struct.pack('<f',v))[0]!=v for v in values): raise ValueError('pixels/nodata must be exactly Float32-representable')
        except (OverflowError,struct.error) as error: raise ValueError('Float32 pixel range') from error
        if any(type(v) is not float for v in pixels): raise ValueError('Float32 snapshot pixels must be floating point')
    else:
        lo,hi=(0,65535) if dtype=='UInt16' else (-32768,32767)
        if any(type(v) is not int or not lo<=v<=hi for v in pixels) or not lo<=nodata<=hi or int(nodata)!=nodata: raise ValueError('integer pixel/nodata range or type')
    conditioned(raster['geotransform'],w,h)


def _parse(data):
    if len(data) > 8*1024**2 or len(data) < 8: raise ValueError('TIFF byte limit/header')
    endian = {'II': '<', 'MM': '>'}.get(data[:2].decode('ascii'))
    if not endian: raise ValueError('TIFF byte order')
    def unpack(fmt, offset):
        size=struct.calcsize(endian+fmt)
        if offset < 0 or offset+size > len(data): raise ValueError('TIFF offset outside file')
        return struct.unpack_from(endian+fmt, data, offset)
    magic, offset=unpack('HI',2)
    if magic != 42: raise ValueError('classic TIFF required; no BigTIFF')
    count=unpack('H',offset)[0]
    if not 1 <= count <= 32: raise ValueError('TIFF tag limit')
    tags={}; metadata_spans=[(0,8),(offset,offset+2+12*count+4)]
    if offset<8: raise ValueError('IFD overlaps TIFF header')
    for i in range(count):
        address=offset+2+12*i
        tag, kind, n=unpack('HHI',address)
        if tag in tags or kind not in (2,3,4,12) or n > MAX_PIXELS: raise ValueError('duplicate/unsupported TIFF field')
        single_short={258,259,262,274,277,284,339}
        single_integer={256,257,278}
        if n<1 or (tag in single_short and (kind!=3 or n!=1)) or (tag in single_integer and (kind not in (3,4) or n!=1)):
            raise ValueError('TIFF scalar tag kind/count mismatch')
        if (tag in (273,279) and kind not in (3,4)) or (tag==33550 and (kind!=12 or n!=3)) or (tag==33922 and (kind!=12 or n!=6)) or (tag==34735 and kind!=3) or (tag==34736 and (kind!=12 or n>2)) or (tag in (34737,42112,42113) and kind!=2):
            raise ValueError('TIFF array/metadata tag kind/count mismatch')
        fmt={2:'B',3:'H',4:'I',12:'d'}[kind]; size=struct.calcsize(fmt)*n
        position=address+8 if size<=4 else unpack('I',address+8)[0]
        if size>4:
            if any(position<b and position+size>a for a,b in metadata_spans): raise ValueError('overlapping TIFF metadata')
            metadata_spans.append((position,position+size))
        value=unpack(str(n)+fmt,position)
        if kind==2:
            raw=bytes(value)
            if not raw.endswith(b'\0'): raise ValueError('unterminated TIFF ASCII')
            value=raw[:-1].decode('ascii')
        tags[tag]=value
    if unpack('I',offset+2+12*count)[0] != 0: raise ValueError('multiple TIFF images/overviews refused')
    allowed={256,257,258,259,262,273,274,277,278,279,284,339,33550,33922,34735,34736,34737,42112,42113}
    if set(tags)-allowed: raise ValueError('unsupported TIFF metadata/tile/mask tags: '+str(sorted(set(tags)-allowed)))
    def scalar(tag, default=None):
        value=tags.get(tag,(default,))
        if not isinstance(value,tuple) or len(value)!=1: raise ValueError('scalar TIFF tag expected')
        return value[0]
    w,h=scalar(256),scalar(257)
    if not isinstance(w,int) or not isinstance(h,int) or not 1<=w<=4096 or not 1<=h<=4096 or w*h>MAX_PIXELS: raise ValueError('pixel budget')
    if (scalar(259),scalar(262),scalar(277),scalar(274,1),scalar(284,1))!=(1,1,1,1,1): raise ValueError('require uncompressed north-up grayscale single-band strips')
    key=scalar(258),scalar(339,1)
    dtype=next((name for name,v in TYPES.items() if v[:2]==key),None)
    if not dtype: raise ValueError('supported dtype UInt16/Int16/Float32 required')
    rows=scalar(278)
    if not isinstance(rows,int) or rows<1: raise ValueError('invalid rows per strip')
    offsets,counts=tags.get(273,()),tags.get(279,())
    if len(offsets)!=(h+rows-1)//rows or len(counts)!=len(offsets): raise ValueError('strip cardinality')
    values=[]; spans=[]
    for i,(start,size) in enumerate(zip(offsets,counts)):
        n=w*min(rows,h-i*rows)
        if size!=n*key[0]//8 or start<8 or start+size>len(data): raise ValueError('strip size/range')
        if any(start<b and start+size>a for a,b in spans+metadata_spans): raise ValueError('overlapping strips')
        spans.append((start,start+size));values.extend(unpack(str(n)+TYPES[dtype][2],start))
    if any(not math.isfinite(v) for v in values): raise ValueError('nonfinite pixels')
    scale,tie=tags.get(33550),tags.get(33922)
    if not scale or not tie or len(scale)!=3 or len(tie)!=6 or tie[:3]!=(0,0,0) or scale[2]!=0 or tie[5]!=0:
        raise ValueError('require one north-up zero-raster-origin tiepoint and scale')
    if not all(math.isfinite(v) for v in (*scale,*tie)) or scale[0]<=0 or scale[1]<=0: raise ValueError('invalid geotransform')
    raw=tags.get(34735,())
    if len(raw)<4 or raw[:3]!=(1,1,0) or len(raw)!=4+4*raw[3]: raise ValueError('GeoKey directory')
    geo={}; used_doubles=set()
    for i in range(raw[3]):
        k,loc,n,v=raw[4+4*i:8+4*i]
        if k in geo: raise ValueError('duplicate GeoKey')
        if k in (1026,2049,3073):
            if loc!=34737 or not isinstance(tags.get(34737),str) or v+n>len(tags[34737])+1: raise ValueError('citation GeoKey')
        elif k in (2057,2059):
            doubles=tags.get(34736,())
            if loc!=34736 or n!=1 or v>=len(doubles) or doubles[v]!={2057:6378137.,2059:298.257223563}[k]: raise ValueError('WGS84 ellipsoid differs')
            used_doubles.add(v)
        elif loc!=0 or n!=1: raise ValueError('unsupported indirect GeoKey')
        geo[k]=v
    if used_doubles!=set(range(len(tags.get(34736,())))): raise ValueError('unreferenced GeoDouble metadata')
    epsg=geo.get(2048) if geo.get(1024)==2 else geo.get(3072)
    permitted={1024,1025,1026,2048,2049,2054,2057,2059} if epsg==4326 else {1024,1025,1026,2049,2054,3072,3073,3076}
    if epsg not in (4326,3857) or set(geo)-permitted or geo.get(1025)!=1 or geo.get(1024)!=(2 if epsg==4326 else 1): raise ValueError('only EPSG4326/3857 PixelIsArea')
    if (epsg==4326 and geo.get(2054,9102)!=9102) or (epsg==3857 and geo.get(3076,9001)!=9001): raise ValueError('CRS units differ')
    nodata_text=tags.get(42113)
    if not isinstance(nodata_text,str): raise ValueError('explicit nodata required')
    nodata=float(nodata_text)
    if not math.isfinite(nodata): raise ValueError('finite nodata required')
    if dtype!='Float32' and (not nodata.is_integer() or not (0<=nodata<=65535 if dtype=='UInt16' else -32768<=nodata<=32767)): raise ValueError('nodata outside dtype')
    if dtype=='Float32' and struct.unpack('<f',struct.pack('<f',nodata))[0]!=nodata: raise ValueError('nodata must be exactly Float32-representable')
    metadata=tags.get(42112)
    unit=''
    if metadata is not None:
        if '<!' in metadata: raise ValueError('XML declarations refused')
        root=ET.fromstring(metadata)
        if root.tag!='GDALMetadata' or root.attrib or len(root)!=1: raise ValueError('unsupported GDAL metadata')
        item=root[0]
        if item.tag!='Item' or item.attrib!={'name':'UNITTYPE','sample':'0','role':'unittype'} or len(item): raise ValueError('only band units metadata supported')
        if (root.text or '').strip() or (item.tail or '').strip(): raise ValueError('unexpected metadata text')
        unit=item.text or ''
    if unit not in ('m','K','1'): raise ValueError('explicit m/K/1 band unit required')
    return {'width':w,'height':h,'dtype':dtype,'epsg':epsg,'geotransform':[tie[3],scale[0],0,tie[4],0,-scale[1]],'pixelInterpretation':'area','band':1,'units':unit,'nodata':nodata,'pixels':values}


def parse(data):
    try:
        raster=_parse(data);validate_snapshot(raster);return raster
    except (struct.error, OverflowError, ET.ParseError) as error:
        raise ValueError('malformed TIFF/metadata: '+str(error)) from error


def expected(source, plan):
    validate_snapshot(source)
    x,y,w,h=(plan[k] for k in ('x','y','width','height'))
    ow,oh=plan['outputWidth'],plan['outputHeight']
    if x+w>source['width'] or y+h>source['height']: raise ValueError('window outside source pixels')
    if source['epsg']!=plan['epsg'] or source['units']!=plan['units'] or source['nodata']!=plan['nodata']: raise ValueError('declared CRS/units/nodata do not match source')
    gt=source['geotransform']
    pixels=[source['pixels'][(y+min(h-1,((2*j+1)*h)//(2*oh)))*source['width']+x+min(w-1,((2*i+1)*w)//(2*ow))] for j in range(oh) for i in range(ow)]
    result={**source,'width':ow,'height':oh,'geotransform':[gt[0]+x*gt[1],gt[1]*w/ow,0,gt[3]+y*gt[5],0,gt[5]*h/oh],'pixels':pixels}
    validate_snapshot(result);return result


def compare(expected, actual):
    validate_snapshot(expected);validate_snapshot(actual)
    for k,v in expected.items():
        if k=='geotransform':
            # Four representable-double steps, never a tolerance proportional
            # to the large coordinate origin. Conditioning bounds this below
            # 1/256 of a pixel, including the far edge.
            if any(abs(a-b)>4*max(math.ulp(a),math.ulp(b)) for a,b in zip(v,actual[k])):
                raise ValueError('geotransform differs beyond four ULPs')
        elif actual[k]!=v: raise ValueError(k+' differs')


def summary(raster):
    valid=[v for v in raster['pixels'] if v!=raster['nodata']];gt=raster['geotransform']
    return {k:v for k,v in raster.items() if k!='pixels'} | {'validCount':len(valid),'nodataCount':len(raster['pixels'])-len(valid),'minimum':min(valid) if valid else None,'maximum':max(valid) if valid else None,'mean':math.fsum(valid)/len(valid) if valid else None,'corners':[[gt[0],gt[3]],[gt[0]+raster['width']*gt[1],gt[3]+raster['height']*gt[5]]]}


# ------------------------------------------------------------------ zonal summaries
MAX_ZONES = 16
MAX_ZONE_VISITS = 2*1024**2
# Resolution ceiling of the native comparison: a zone is refused (ZONE_SUM_UNRESOLVABLE) unless the allowance derived below is at most
# 2**-26 (about 1.5e-8) of the exact magnitude it must resolve. This is a consistency threshold for comparing native output with the
# host oracle, chosen well above the roundoff of ordinary data and well below any decisive forgery; it is not a scientific accuracy claim.
RESOLUTION = Fraction(1, 2**26)
# Every Float32/UInt16/Int16 value is a whole multiple of 2**-149, so scaled integers sum exactly (and fast) before one Fraction division.
SCALE = 2**149
ZONE_ID_CHARS = frozenset(chr(c) for c in range(0x20, 0x7f))
NULL_TOKEN = '\\N'
CSV_COLUMNS = (('zone', 'text', False), ('valid', 'number', False), ('missing', 'number', False), ('coverage', 'number', False),
               ('minimum', 'number', True), ('maximum', 'number', True), ('sum', 'number', True), ('mean', 'number', True))
GEOJSON_CRS = {4326: 'urn:ogc:def:crs:OGC:1.3:CRS84', 3857: 'EPSG:3857'}


class ZoneError(ValueError):
    """A zone contradicts the authored policy or the source grid; carries a stable fault code and zone index."""
    def __init__(self, code, message, index=None):
        super().__init__(message); self.code = code; self.index = index


def valid_zone_id(value):
    return type(value) is str and 1 <= len(value) <= 32 and set(value) <= ZONE_ID_CHARS and value == value.strip() and value != NULL_TOKEN


def zone_corners(source, zone):
    """World corners of a pixel-aligned rectangle: upper-left then lower-right."""
    gt = source['geotransform']
    return [[gt[0]+zone['x']*gt[1], gt[3]+zone['y']*gt[5]], [gt[0]+(zone['x']+zone['width'])*gt[1], gt[3]+(zone['y']+zone['height'])*gt[5]]]


def zones_geojson(source, zones):
    """Trusted closed GeoJSON rectangles built from authored pixel indices and the source affine."""
    features = []
    for zone in zones:
        (x0, y0), (x1, y1) = zone_corners(source, zone)
        features.append({'type': 'Feature', 'properties': {'zone': zone['id']}, 'geometry': {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    return {'type': 'FeatureCollection', 'name': 'zones', 'crs': {'type': 'name', 'properties': {'name': GEOJSON_CRS[source['epsg']]}}, 'features': features}


def validate_zones(zones, width, height):
    if not isinstance(zones, list) or not 1 <= len(zones) <= MAX_ZONES: raise ZoneError('INVALID_ZONE', 'between 1 and 16 zones are required')
    seen = set(); visits = 0
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict) or set(zone) != {'id', 'x', 'y', 'width', 'height'}: raise ZoneError('INVALID_ZONE', 'zone closed shape differs', index)
        if not valid_zone_id(zone['id']) or zone['id'] in seen: raise ZoneError('INVALID_ZONE', 'zone ids must be unique printable ASCII text of 1 to 32 characters, without edge spaces or the null token', index)
        seen.add(zone['id'])
        if any(type(zone[k]) is not int for k in ('x', 'y', 'width', 'height')): raise ZoneError('INVALID_ZONE', 'zone indices must be integers, not booleans', index)
        if zone['x'] < 0 or zone['y'] < 0 or zone['width'] < 1 or zone['height'] < 1 or (width is not None and (zone['x']+zone['width'] > width or zone['y']+zone['height'] > height)):
            raise ZoneError('INVALID_ZONE', 'zone '+zone['id']+' is outside the source pixel grid', index)
        visits += zone['width']*zone['height']
    if visits > MAX_ZONE_VISITS: raise ZoneError('INVALID_ZONE', 'aggregate zone pixel visits exceed 2097152')


def summation_allowance(count, absolute_sum):
    """Exact rational bound on |recursive double sum - exact sum| of `count` values whose absolute values sum exactly to `absolute_sum`.

    (n-1)u/(1-(n-1)u) times the sum of absolute values holds for any summation order, so it covers whatever order the native code uses.
    """
    n = Fraction(max(count-1, 0))*Fraction(1, 2**53)
    return n/(1-n)*absolute_sum


def zone_targets(valid):
    """Exact (rational) targets and native comparison allowances for the valid values of one zone.

    The target is the real-number sum S of the stored values, never the host's rounded `fsum`, so host rounding is accounted exactly.
    Sum allowance: gamma*A with A = sum|x|. Mean allowance: native mean = fl(native sum / n), so |m - S/n| <= (gamma*A*(1+u) + u*|S|)/n.
    """
    count = len(valid)
    exact = Fraction(sum(int(v*SCALE) for v in valid), SCALE)
    absolute = Fraction(sum(abs(int(v*SCALE)) for v in valid), SCALE)
    total = summation_allowance(count, absolute)
    unit = Fraction(1, 2**53)
    return exact, absolute, total, (total*(1+unit)+unit*abs(exact))/count


def resolvable(exact, sum_allowance, mean_allowance, count):
    """True when both derived allowances are within RESOLUTION of the magnitude they must resolve (zero needs zero allowance)."""
    return sum_allowance <= RESOLUTION*abs(exact) and mean_allowance <= RESOLUTION*abs(exact)/count


def canonical_zero(value):
    """Published zonal numbers never carry a signed zero: -0.0 becomes 0.0 (window outputs are unaffected)."""
    return None if value is None else value+0.0


def zonal_expected(source, plan):
    """Independent stdlib oracle: visit every pixel of every authored zone, no native output used."""
    validate_snapshot(source)
    if source['epsg'] != plan['epsg'] or source['units'] != plan['units'] or source['nodata'] != plan['nodata']: raise ValueError('declared CRS/units/nodata do not match source')
    validate_zones(plan['zones'], source['width'], source['height'])
    rows = []
    for index, zone in enumerate(plan['zones']):
        values = [source['pixels'][r*source['width']+c] for r in range(zone['y'], zone['y']+zone['height']) for c in range(zone['x'], zone['x']+zone['width'])]
        valid = [float(v) for v in values if v != source['nodata']]
        total = zone['width']*zone['height']
        if plan['missing'] == 'refuse' and len(valid) != total: raise ZoneError('ZONE_MISSING_VALUES', 'zone '+zone['id']+' contains '+str(total-len(valid))+' nodata pixels and the missing policy is refuse', index)
        exact = sum_allowance = mean_allowance = None
        if valid:
            target, _, sum_allowance, mean_allowance = zone_targets(valid)
            if not resolvable(target, sum_allowance, mean_allowance, len(valid)):
                raise ZoneError('ZONE_SUM_UNRESOLVABLE', 'zone '+zone['id']+' sum is not resolvable: the derived roundoff allowance of its absolute values exceeds 2**-26 of the exact sum (cancellation)', index)
            exact = math.fsum(valid)
        rows.append({'zone': zone['id'], 'x': zone['x'], 'y': zone['y'], 'width': zone['width'], 'height': zone['height'], 'pixels': total, 'valid': len(valid), 'missing': total-len(valid),
                     'coverage': len(valid)/total, 'minimum': canonical_zero(min(valid)) if valid else None, 'maximum': canonical_zero(max(valid)) if valid else None,
                     'sum': canonical_zero(exact), 'mean': canonical_zero(exact/len(valid)) if valid else None,
                     'exactSum': target if valid else None, 'sumAllowance': sum_allowance, 'meanAllowance': mean_allowance,
                     'corners': zone_corners(source, zone)})
    return rows


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalise_native_zones(features, expected_ids):
    """Closed shape of native zonal-stats features; absent keys are accepted only for an all-missing zone."""
    if not isinstance(features, list) or len(features) != len(expected_ids): raise ValueError('native zone feature count differs')
    result = []
    for feature, zone_id in zip(features, expected_ids):
        if not isinstance(feature, dict) or set(feature) != {'type', 'properties', 'geometry'} or feature['type'] != 'Feature' or feature['geometry'] is not None: raise ValueError('native zone feature shape differs')
        p = feature['properties']
        if not isinstance(p, dict) or p.get('zone') != zone_id or type(p.get('zone')) is not str: raise ValueError('native zone identity/order differs')
        count = p.get('count')
        if type(count) not in (int, float) or not _number(count) or count != int(count) or count < 0: raise ValueError('native count must be an exact nonnegative integer')
        if count == 0:
            if set(p) != {'zone', 'count', 'sum'} or type(p['sum']) not in (int, float) or p['sum'] != 0: raise ValueError('native all-missing zone shape differs')
            result.append({'zone': zone_id, 'count': 0, 'minimum': None, 'maximum': None, 'sum': None, 'mean': None})
            continue
        if set(p) != {'zone', 'count', 'min', 'max', 'sum', 'mean'} or any(not _number(p[k]) for k in ('min', 'max', 'sum', 'mean')): raise ValueError('native zone statistics shape differs')
        result.append({'zone': zone_id, 'count': int(count), 'minimum': float(p['min']), 'maximum': float(p['max']), 'sum': float(p['sum']), 'mean': float(p['mean'])})
    return result


def compare_zonal(expected, native):
    """Counts and extrema are exact; sum/mean must lie within the derived allowance of the exact rational target (exact comparison)."""
    if len(expected) != len(native): raise ValueError('zone count differs')
    for e, n in zip(expected, native):
        if e['zone'] != n['zone'] or e['valid'] != n['count']: raise ValueError('zone '+e['zone']+' identity/valid count differs')
        for k in ('minimum', 'maximum'):
            if e[k] != n[k]: raise ValueError('zone '+e['zone']+' '+k+' differs')
        if e['valid']:
            if abs(Fraction(n['sum'])-e['exactSum']) > e['sumAllowance']: raise ValueError('zone '+e['zone']+' sum differs beyond the roundoff bound')
            if abs(Fraction(n['mean'])-e['exactSum']/e['valid']) > e['meanAllowance']: raise ValueError('zone '+e['zone']+' mean differs beyond the roundoff bound')
        elif n['sum'] is not None or n['mean'] is not None: raise ValueError('zone '+e['zone']+' invents statistics for no valid pixel')


def decimal(value):
    if type(value) is int: return str(value)
    text = repr(float(value)+0.0)
    if text.endswith('.0'): text = text[:-2]
    return text.replace('e-0', 'e-').replace('e+0', 'e').replace('e+', 'e')


def csv_text(rows):
    """Fixed typed CSV: header and text always quoted, shortest round-trip numbers, bare null token."""
    lines = [','.join('"'+name+'"' for name, _, _ in CSV_COLUMNS)]
    for row in rows:
        cells = []
        for name, kind, nullable in CSV_COLUMNS:
            value = row[name]
            if value is None: cells.append(NULL_TOKEN)
            elif kind == 'text': cells.append('"'+value.replace('"', '""')+'"')
            else: cells.append(decimal(value))
        lines.append(','.join(cells))
    return '\n'.join(lines)+'\n'


def zonal_report(source, plan, rows):
    published = [{k: v for k, v in row.items() if k not in ('exactSum', 'sumAllowance', 'meanAllowance', 'corners')} for row in rows]
    return {'epsg': source['epsg'], 'units': source['units'], 'nodata': source['nodata'], 'dtype': source['dtype'], 'width': source['width'], 'height': source['height'],
            'geotransform': source['geotransform'], 'missingPolicy': plan['missing'], 'nullToken': NULL_TOKEN, 'zones': [{**p, 'corners': r['corners']} for p, r in zip(published, rows)],
            'columns': [{'name': n, 'kind': k, 'nullable': nl} for n, k, nl in CSV_COLUMNS],
            'zoneCount': len(rows), 'pixelVisits': sum(r['pixels'] for r in rows)}


def zone_extent_violation(rows, epsg):
    """Latitude plausibility of the selected zones only (EPSG:4326), as for windows; None otherwise."""
    if epsg != 4326: return None
    low = min(c[1] for r in rows for c in r['corners']); high = max(c[1] for r in rows for c in r['corners'])
    if low < -90-1e-6 or high > 90+1e-6: return {'epsg': 4326, 'axis': 'latitude', 'minimum': low, 'maximum': high, 'limits': [-90, 90]}
    return None
