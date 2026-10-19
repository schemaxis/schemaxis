"""Independent SVG coordinate oracle and standard-library PNG reconstruction."""
import hashlib
import json
from itertools import product
import math
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from schemaxis.errors import fail

RGB={'red':(214,39,40),'blue':(31,119,180),'green':(44,160,44),'purple':(148,103,189)}
SVG='{http://www.w3.org/2000/svg}'
# Qualified Gnuplot6.0.5 marker/filter definition structure; geometry is checked separately.
QUALIFIED_DEFINITIONS_SHA256='4c586e4207fed109793ff80a1168499688db22e92360911e17bb328099c25e2f'


def require(condition,message):
    if not condition: fail('VERIFICATION_FAILED',message)


def pixels(data):
    """Validate bounded truecolour PNG chunks, inflate and reverse all PNG filters."""
    try:
        require(data[:8]==b'\x89PNG\r\n\x1a\n','PNG signature differs')
        pos=8;chunks=[];compressed=bytearray();width=height=channels=0
        while pos<len(data):
            length=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8];body=data[pos+8:pos+8+length]
            require(length<=8*1024*1024 and len(body)==length and len(data[pos+8+length:pos+12+length])==4,'PNG chunk length differs')
            require(struct.unpack('>I',data[pos+8+length:pos+12+length])[0]==zlib.crc32(kind+body),'PNG CRC differs')
            pos+=12+length;chunks.append(kind)
            if kind==b'IHDR':
                width,height,depth,colour,compression,filtering,interlace=struct.unpack('>IIBBBBB',body)
                require(1<=width<=1600 and 1<=height<=1200 and depth==8 and colour in (2,6) and (compression,filtering,interlace)==(0,0,0),'PNG dimensions/format differ')
                channels=3 if colour==2 else 4
            elif kind==b'IDAT': compressed.extend(body)
            else: require(kind in (b'IEND',b'pHYs'),'unexpected PNG ancillary chunk')
        require(chunks[0]==b'IHDR' and chunks[-1]==b'IEND' and chunks.count(b'IHDR')==1 and chunks.count(b'IEND')==1 and b'IDAT' in chunks and not body and pos==len(data),'PNG chunk membership differs')
        count=(width*channels+1)*height;inflater=zlib.decompressobj();raw=inflater.decompress(bytes(compressed),count+1)
        require(len(raw)==count and inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail,'PNG decompression budget/size differs')
        stride=width*channels;out=[];previous=bytearray(stride)
        for y in range(height):
            start=y*(stride+1);mode=raw[start];require(mode<=4,'PNG filter differs');row=bytearray(raw[start+1:start+1+stride])
            for x in range(stride):
                a=row[x-channels] if x>=channels else 0;b=previous[x];c=previous[x-channels] if x>=channels else 0
                if mode==1: predictor=a
                elif mode==2: predictor=b
                elif mode==3: predictor=(a+b)//2
                elif mode==4:
                    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);predictor=a if pa<=pb and pa<=pc else b if pb<=pc else c
                else: predictor=0
                row[x]=(row[x]+predictor)&255
            out.append([tuple(row[x:x+3]) if channels==3 else tuple(round(row[x+k]*row[x+3]/255+255-row[x+3]) for k in range(3)) for x in range(0,stride,channels)])
            previous=row
        return width,height,out
    except (ValueError,IndexError,struct.error,zlib.error) as error: fail('VERIFICATION_FAILED','invalid bounded PNG: '+str(error))


def coord(value,axis,size,horizontal):
    lower,upper=axis['range']
    if axis['scale']=='log10': value,lower,upper=map(math.log10,(value,lower,upper))
    fraction=(value-lower)/(upper-lower)
    return size*(.15+.8*fraction) if horizontal else size*(.8-.7*fraction)


def inspect_plot(svg,png,p,rows):
    require(b'<!DOCTYPE' not in svg and b'<!ENTITY' not in svg,'SVG entity/doctype unsupported')
    try: root=ET.fromstring(svg)
    except ET.ParseError as error: fail('VERIFICATION_FAILED','invalid SVG: '+str(error))
    w,h=p['width'],p['height']
    require(root.tag==SVG+'svg' and root.attrib=={'width':str(w),'height':str(h),'viewBox':f'0 0 {w} {h}'},'SVG dimensions/attributes differ')
    # One closed native SVG structure: exact attributes for each rendering role.
    # This rejects every unauthorised opacity/paint/filter/transform attribute,
    # rather than attempting to enumerate ways checked content could be hidden.
    defs=list(root.iter(SVG+'defs'));require(len(defs)==1,'SVG definitions membership differs')
    def structure(n): return [n.tag,sorted(n.attrib.items()),(n.text or '').strip(),[structure(c) for c in n]]
    definition_hash=hashlib.sha256(json.dumps(structure(defs[0]),sort_keys=True).encode()).hexdigest()
    require(definition_hash==QUALIFIED_DEFINITIONS_SHA256,'SVG marker definitions differ from qualified Gnuplot')
    definition_nodes=set(defs[0].iter());parents={child:parent for parent in root.iter() for child in parent}
    canvases=[n for n in root if n.tag==SVG+'g' and n.attrib=={'id':'gnuplot_canvas'}]
    require(len(canvases)==1 and len(root)==3 and [n.tag for n in root]==[SVG+'title',SVG+'desc',SVG+'g'],'SVG canvas structure differs')
    canvas=canvases[0];paint={'fill','color','stroke','stroke-width','stroke-linecap','stroke-linejoin'}
    textpaint={'transform','stroke','fill','font-family','font-size','text-anchor'}
    known_colours={'rgb('+','.join(map(str,RGB[c]))+')' for c in RGB}
    def normal_colour(v): return re.sub(r'\s','',v)
    def series_owner(node):
        while node in parents:
            node=parents[node]
            if re.fullmatch(r'gnuplot_plot_[0-9]+',node.get('id','')):return node
        return None
    for node in root.iter():
        if node in definition_nodes or node is root:continue
        attrs=node.attrib;parent=parents.get(node)
        if node.tag in (SVG+'title',SVG+'desc'):
            require(not attrs and not len(node) and (parent is root or parent is not None and re.fullmatch(r'gnuplot_plot_[0-9]+',parent.get('id',''))),'SVG metadata attributes/placement differ')
        elif node.tag==SVG+'rect':
            require(parent is canvas and attrs=={'x':'0','y':'0','width':str(w),'height':str(h),'fill':'none'},'SVG extra overlay rectangle differs')
        elif node.tag==SVG+'g':
            if node is canvas:continue
            if re.fullmatch(r'gnuplot_plot_[0-9]+',attrs.get('id','')):
                require(parent is canvas and set(attrs)=={'id','fill'} and attrs['fill']=='none','SVG series group paint/attributes differ')
            elif set(attrs)==textpaint:
                match=re.fullmatch(r'translate\(([-0-9.]+),([-0-9.]+)\)(?: rotate\(270.00\))?',attrs['transform'])
                require(match is not None and attrs['stroke']=='none' and attrs['fill']=='black' and attrs['font-family']=='Arial' and attrs['font-size']=='12.00' and attrs['text-anchor'] in ('start','middle','end') and len(node)==1 and node[0].tag==SVG+'text','SVG text paint/transform differs')
                x,y=map(float,match.groups());require(0<x<w and 0<y<h,'SVG text is outside visible viewport')
            else:
                require(set(attrs)==paint and attrs['fill']=='none' and attrs['color'] in ('black','white') and attrs['stroke'] in ('black','currentColor') and attrs['stroke-width'] in ('1.00','2.00') and attrs['stroke-linecap']=='butt' and attrs['stroke-linejoin']=='miter','SVG group paint/attributes differ')
                require(attrs['color']!='white' or not len(node),'SVG white group could obscure content')
                require(parent is canvas or re.fullmatch(r'gnuplot_plot_[0-9]+',parent.get('id','')),'SVG unexpected group nesting')
        elif node.tag==SVG+'path':
            require(set(attrs)=={'d','stroke'} and (attrs['stroke']=='black' or normal_colour(attrs['stroke']) in known_colours) and set(parent.attrib)==paint,'SVG path paint/attributes differ')
            if attrs['stroke']!='black': require(series_owner(node) is not None and parent.get('stroke-width')=='2.00','SVG unaccounted coloured path')
        elif node.tag==SVG+'use':
            require(set(attrs)=={'{http://www.w3.org/1999/xlink}href','color','transform'} and attrs['{http://www.w3.org/1999/xlink}href']=='#gpPt6' and set(parent.attrib)==paint and series_owner(node) is not None,'SVG marker attributes/placement differ')
            match=re.fullmatch(r'translate\(([-0-9.]+),([-0-9.]+)\) scale\((3.15|4.50)\)',attrs['transform'])
            require(match is not None and (attrs['color']=='white' and match[3]=='4.50' or normal_colour(attrs['color']) in known_colours and match[3]=='3.15'),'SVG marker scale/paint differs')
        elif node.tag==SVG+'text':
            require(not attrs and not len(node) and set(parent.attrib)==textpaint,'SVG text attributes/placement differ')
        else:require(False,'SVG contains unsupported rendering content')
    # Identify visible label roles by their qualified positions, not text
    # uniqueness. A title may legitimately repeat a series/axis label.
    roles={'title':0,'x':0,'y':0};tick_coordinates={'x':[],'y':[]}
    for node in root.iter(SVG+'text'):
        text=''.join(node.itertext());group=parents[node]
        match=re.match(r'translate\(([-0-9.]+),([-0-9.]+)\)',group.get('transform',''));x,y=map(float,match.groups())
        if series_owner(node) is not None:continue
        close=lambda a,b:abs(a-b)<=.06
        if close(x,w*.55-.01) and close(y,h*.1-23.09):
            require(text==p['title'],'SVG visible title differs');roles['title']+=1
        elif close(x,w*.55-.01) and close(y,h*.8+48.90):
            require(text==p['xAxis']['label']+' ('+p['xAxis']['unit']+')','SVG x-axis label differs');roles['x']+=1
        elif 'rotate' in group.get('transform',''):
            require(15<x<w*.15-25 and close(y,h*.45+.01) and text==p['yAxis']['label']+' ('+p['yAxis']['unit']+')','SVG y-axis label position/text differs');roles['y']+=1
        else:
            try:value=float(text)
            except ValueError:require(False,'SVG contains an unaccounted visible label')
            require(math.isfinite(value),'SVG tick value is non-finite')
            if close(y,h*.8+21.90):
                require(p['xAxis']['range'][0]<=value<=p['xAxis']['range'][1] and close(x,coord(value,p['xAxis'],w,True)),'SVG x tick value/position differs')
                tick_coordinates['x'].append(x)
            else:
                require(close(x,w*.15-8.39) and p['yAxis']['range'][0]<=value<=p['yAxis']['range'][1] and close(y-3.90,coord(value,p['yAxis'],h,False)),'SVG y tick value/position differs')
                tick_coordinates['y'].append(y-3.90)
    require(roles=={'title':1,'x':1,'y':1},'SVG visible label membership differs')
    require(all(len(v)>=2 and len(set(v))==len(v) for v in tick_coordinates.values()),'SVG needs distinct visible numeric ticks on both axes')
    # Black geometry may only be the two qualified border rectangles and
    # opposing major/minor tick pairs. Arbitrary interior strokes could conceal
    # or fabricate scientific content even when coloured series remain intact.
    left,right,top,bottom=w*.15,w*.95-.01,h*.1+.01,h*.8
    rectangles=0;ticks=[]
    for node in root.iter(SVG+'path'):
        if node in definition_nodes or node.get('stroke')!='black':continue
        require(parents[node].get('stroke-width')=='1.00' and series_owner(node) is None,'SVG black geometry paint/placement differs')
        path=node.get('d','');tokens=re.findall(r'([ML])\s*([-0-9.]+),([-0-9.]+)',path)
        if 'Z' in path:
            require(re.sub(r'[ML]\s*[-0-9.]+,[-0-9.]+|Z|\s+','',path)=='' and len(tokens)==5 and [v[0] for v in tokens]==['M','L','L','L','L'] and path.rstrip().endswith('Z'),'SVG border command structure differs')
            expected=[(left,top),(left,bottom),(right,bottom),(right,top),(left,top)]
            require(all(max(abs(float(a)-x),abs(float(b)-y))<=.06 for (_,a,b),(x,y) in zip(tokens,expected)),'SVG border rectangle differs')
            rectangles+=1;continue
        require(re.sub(r'[ML]\s*[-0-9.]+,[-0-9.]+|\s+','',path)=='' and len(tokens)%2==0,'SVG tick command structure differs')
        for a,b in zip(tokens[::2],tokens[1::2]):
            require(a[0]=='M' and b[0]=='L','SVG non-tick black segment differs')
            x,y=float(a[1]),float(a[2]);xx,yy=float(b[1]),float(b[2]);length=abs(xx-x)+abs(yy-y)
            require(abs(length-9)<=.06 or abs(length-4.5)<=.06,'SVG tick length differs')
            if abs(y-yy)<=.01 and top-.06<=y<=bottom+.06:
                if abs(x-left)<=.06 and abs(xx-(left+length))<=.06:axis,side,position='y','near',y
                elif abs(x-right)<=.06 and abs(xx-(right-length))<=.06:axis,side,position='y','far',y
                else:require(False,'SVG black horizontal overlay differs')
            elif abs(x-xx)<=.01 and left-.06<=x<=right+.06:
                if abs(y-bottom)<=.06 and abs(yy-(bottom-length))<=.06:axis,side,position='x','near',x
                elif abs(y-top)<=.06 and abs(yy-(top+length))<=.06:axis,side,position='x','far',x
                else:require(False,'SVG black vertical overlay differs')
            else:require(False,'SVG black interior overlay differs')
            major=abs(length-9)<=.06
            require(major or p['xAxis' if axis=='x' else 'yAxis']['scale']=='log10','SVG minor ticks are unsupported on linear axes')
            ticks.append((axis,side,position,major))
    require(rectangles==2,'SVG border rectangle membership differs')
    for axis,coordinates in tick_coordinates.items():
        for position in coordinates:
            for side in ('near','far'):
                match=next((i for i,t in enumerate(ticks) if t[0]==axis and t[1]==side and t[3] and abs(t[2]-position)<=.06),None)
                require(match is not None,'SVG numeric label has no matching major tick pair');ticks.pop(match)
    require(all(not tick[3] for tick in ticks),'SVG unlabelled major tick remains')
    while ticks:
        axis,side,position,major=ticks.pop()
        match=next((i for i,t in enumerate(ticks) if t[0]==axis and t[1]!=side and abs(t[2]-position)<=.06),None)
        require(match is not None,'SVG minor tick has no opposing pair');ticks.pop(match)
    width,height,image=pixels(png);require((width,height)==(w,h),'PNG dimensions differ')
    groups=[g for g in root.iter(SVG+'g') if re.fullmatch(r'gnuplot_plot_[0-9]+',g.get('id',''))]
    require(len(groups)==len(p['series']),'SVG series membership differs')
    summaries=[]
    def coloured(x,y,rgb):
        def matches(pixel):
            # libgd antialiasing blends line colour with the white background.
            coverage=sum((255-pixel[k])/(255-rgb[k]) for k in range(3))/3
            return .35<=coverage<=1.05 and all(abs(pixel[k]-(255-coverage*(255-rgb[k])))<=10 for k in range(3))
        return any(matches(image[yy][xx])
            for yy in range(max(0,round(y)-3),min(h,round(y)+4)) for xx in range(max(0,round(x)-3),min(w,round(x)+4)))
    for i,s in enumerate(p['series']):
        group=groups[i];require(group.get('id')==f'gnuplot_plot_{i+1}','SVG series order differs')
        legend_text=list(group.iter(SVG+'text'))
        require(len(legend_text)==1 and ''.join(legend_text[0].itertext())==s['label'],'SVG series legend label differs')
        match=re.match(r'translate\(([-0-9.]+),([-0-9.]+)\)',parents[legend_text[0]].get('transform',''));lx,ly=map(float,match.groups())
        require(0<lx<w and abs(ly-(h-14.10))<=.06,'SVG legend label position differs')
        rgb=RGB[s['colour']];normal=lambda v:tuple(map(int,re.findall(r'\d+',v))) if v.startswith('rgb(') else None
        points=[]
        for row in rows: points.append((coord(row[s['x']],p['xAxis'],w,True),coord(row[s['y']],p['yAxis'],h,False)))
        marks=[];paths=[];marker_roles=[];legend_marks=[]
        for n in group.iter():
            if n.tag==SVG+'path': require(normal(n.get('stroke',''))==rgb,'SVG series path colour differs')
            if n.tag==SVG+'use':
                require(n.get('color')=='white' or normal(n.get('color',''))==rgb,'SVG series marker colour differs')
                marker_roles.append(n.get('color')=='white')
            if n.tag==SVG+'use' and normal(n.get('color',''))==rgb:
                match=re.fullmatch(r'translate\(([-0-9.]+),([-0-9.]+)\) scale\([0-9.]+\)',n.get('transform',''));require(match is not None,'SVG marker transform differs')
                x,y=map(float,match.groups())
                if y<=h*.8+.1: marks.append((x,y))
                else:legend_marks.append((x,y))
            if n.tag==SVG+'path' and normal(n.get('stroke',''))==rgb: paths.append(n.get('d',''))
        all_markers=list(group.iter(SVG+'use'))
        if 'error' in s:
            for white,coloured_marker in zip(all_markers[::2],all_markers[1::2]):
                require(white.get('transform').split(' scale')[0]==coloured_marker.get('transform').split(' scale')[0],'SVG uncertainty marker backing position differs')
        expected_roles=([True,False] if 'error' in s else [False])*(len(points)+1)
        require(marker_roles==expected_roles,'SVG marker order/membership differs')
        require(len(legend_marks)==1 and 0<legend_marks[0][0]<w and h*.9<legend_marks[0][1]<h,'SVG legend marker membership differs')
        require(len(marks)==len(points),'SVG sample marker count differs')
        for actual,expected in zip(marks,points): require(max(abs(a-b) for a,b in zip(actual,expected))<=.06,'SVG sample coordinates differ')
        # Reject replaced paths, including plausible markers above incorrect line
        # geometry. Native paths contain M/L segments, including errorbar caps.
        segments=[]
        for path in paths:
            tokens=re.findall(r'([ML])\s*([-0-9.]+),([-0-9.]+)',path)
            require(re.sub(r'[ML]\s*[-0-9.]+,[-0-9.]+|\s+','',path)=='','SVG series path contains unsupported geometry')
            previous=None
            for op,x,y in tokens:
                current=(float(x),float(y))
                if op=='L' and previous is not None: segments.append((previous,current))
                previous=current
        expected_segments=list(zip(points,points[1:]))
        for row,(x,y) in zip(rows,points):
            if 'error' in s:
                dy=row[s['error']];low=coord(row[s['y']]-dy,p['yAxis'],h,False);high=coord(row[s['y']]+dy,p['yAxis'],h,False)
                left,right=max(w*.15,x-4.5),min(w*.95,x+4.5)
                if dy>0: expected_segments.append(((x,low),(x,high)))
                expected_segments.extend([((left,low),(right,low)),((left,high),(right,high))])
        # Every coloured segment in the data rectangle must have a declared
        # semantic role. Remove exact matches, preserving duplicate membership.
        data_segments=[];legend=[]
        for segment in segments:
            if all(w*.15-.06<=x<=w*.95+.06 and h*.1-.06<=y<=h*.8+.06 for x,y in segment):data_segments.append(segment)
            else:legend.append(segment)
        # Quantised indexing keeps acceptance bounded for dense 2048-row plots;
        # exact tolerance comparisons still decide every match and duplicate.
        buckets={}
        for segment in data_segments:
            flat=tuple(v for point in segment for v in point)
            key=tuple(round(v*10) for v in flat);buckets.setdefault(key,[]).append(flat)
        offsets=[(0,0,0,0),*[v for v in product((-1,0,1),repeat=4) if any(v)]]
        for expected in expected_segments:
            flat=tuple(v for point in expected for v in point);key=tuple(round(v*10) for v in flat);found=False
            for offset in offsets:
                candidates=buckets.get(tuple(a+b for a,b in zip(key,offset)),[])
                index=next((i for i,actual in enumerate(candidates) if max(abs(x-y) for x,y in zip(actual,flat))<=.06),None)
                if index is not None:candidates.pop(index);found=True;break
            require(found,'SVG declared line/error segment differs')
        require(not any(buckets.values()),'SVG contains undeclared scientific series segments')
        require(len(legend)==(3 if 'error' in s else 1) and all(0<x<w and h*.9<y<h for pair in legend for x,y in pair),'SVG legend segment membership differs')
        def has_segment(a,b):
            return any(max(abs(x-y) for observed,wanted in zip(pair,(a,b)) for x,y in zip(observed,wanted))<=.06 for pair in segments)
        checks=[]
        for row,(x,y) in zip(rows,points):
            require(coloured(x,y,rgb),'PNG series sample colour/position differs')
            if 'error' in s:
                dy=row[s['error']];low=coord(row[s['y']]-dy,p['yAxis'],h,False);high=coord(row[s['y']]+dy,p['yAxis'],h,False)
                if dy>0:
                    require(has_segment((x,low),(x,high)),'SVG uncertainty endpoints differ')
                    require(coloured(x,low,rgb) and coloured(x,high,rgb),'PNG uncertainty endpoint pixels differ')
                checks.append([round(low,3),round(high,3)])
        # Probe each connected segment at its midpoint, away from marker centres.
        for a,b in zip(points,points[1:]): require(coloured((a[0]+b[0])/2,(a[1]+b[1])/2,rgb),'PNG connected line pixel differs')
        summaries.append({'label':s['label'],'x':s['x'],'y':s['y'],'error':s.get('error'),'colour':s['colour'],
            'points':[[round(a,3),round(b,3)] for a,b in points],'errorPixels':checks})
    return {'rows':len(rows),'series':len(p['series']),'width':w,'height':h,'geometry':summaries,
        'scales':[p['xAxis']['scale'],p['yAxis']['scale']],'units':[p['xAxis']['unit'],p['yAxis']['unit']]}
