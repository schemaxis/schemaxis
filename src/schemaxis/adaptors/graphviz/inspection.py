"""Literal topology oracle and closed SVG/plain geometry consistency checks.

Plain is independent of our DOT generator but shares Graphviz's layout engine
with SVG. Neither is evidence of an optimal layout or measured font rendering.
"""
import math
import re
import shlex
import xml.etree.ElementTree as ET
from schemaxis.errors import fail

SVG='{http://www.w3.org/2000/svg}'
NUMBER=r'-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
DOCTYPE=b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'


def require(condition,message):
    if not condition:fail('VERIFICATION_FAILED',message)
def number(value):
    require(re.fullmatch(NUMBER,value) is not None,'invalid numeric layout token')
    v=float(value);require(math.isfinite(v) and abs(v)<=100000,'nonfinite/oversized layout coordinate');return v
def near(a,b):
    # Graphviz plain emits five significant figures; SVG emits two decimals.
    # 0.011pt covers SVG rounding; 5e-5 relative + 0.008pt covers plain rounding.
    return abs(a-b)<=.02+max(abs(a),abs(b))*5e-5

def points(text):
    values=text.split();out=[]
    for item in values:
        xy=item.split(',');require(len(xy)==2,'invalid SVG coordinate pair');out.append([number(x) for x in xy])
    return out

def element(node,tag,attrs,children=None):
    require(node.tag==SVG+tag and node.attrib==attrs,'unexpected SVG '+tag+' attributes/identity')
    require(not (node.text or '').strip() or tag in ('title','text'),'unexpected SVG text overlay')
    require(not (node.tail or '').strip(),'unexpected SVG tail text')
    if children is not None:require([x.tag for x in node]==[SVG+x for x in children],'unexpected SVG '+tag+' child membership')



def curve_points(control):
    """Evaluate cubic extrema rather than mistaking off-curve controls for bounds."""
    result=[]
    for start in range(0,len(control)-1,3):
        c=control[start:start+4];parameters={0.0,1.0}
        for axis in (0,1):
            p0,p1,p2,p3=[v[axis] for v in c]
            a=-p0+3*p1-3*p2+p3;b=2*(p0-2*p1+p2);d=p1-p0
            if abs(a)<1e-12:
                if abs(b)>1e-12:parameters.add(-d/b)
            else:
                discriminant=b*b-4*a*d
                if discriminant>=0:
                    parameters.update(((-b+math.sqrt(discriminant))/(2*a),(-b-math.sqrt(discriminant))/(2*a)))
        for t in parameters:
            if 0<=t<=1:result.append([sum(v[axis]*weight for v,weight in zip(c,((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3))) for axis in (0,1)])
    return result


def plain(data,p):
    require(len(data.splitlines())<=702,'native plain record budget exceeded')
    lines=[shlex.split(s) for s in data.decode('ascii').splitlines()]
    require(len(lines)>=4 and lines[0][0]=='graph' and len(lines[0])==4 and lines[-1]==['stop'],'plain graph/stop records differ')
    scale,width,height=map(number,lines[0][1:]);require(scale==1 and 0<width<=1000 and 0<height<=1000,'plain positive finite graph bounds differ')
    labels={n['id']:n['label'] for n in p['nodes']};wanted={(e['source'],e['target']) for e in p['edges']};nodes={};edges={};edge_started=False
    for fields in lines[1:-1]:
        require(bool(fields),'empty plain record')
        if fields[0]=='node':
            require(not edge_started and len(fields)==11,'plain node fields/order differ')
            _,name,x,y,w,h,label,style,shape,colour,fill=fields
            require(name in labels and name not in nodes and label==labels[name],'plain node multiplicity/label differs from literal declaration')
            require((style,shape,colour,fill)==('solid','box','black','lightgrey'),'plain fixed node appearance differs')
            x,y,w,h=map(number,(x,y,w,h));require(w==2.5 and h==.5 and x>=w/2-.001 and y>=h/2-.001 and x+w/2<=width+.02 and y+h/2<=height+.02,'plain fixed boxes/bounds differ')
            nodes[name]={'centre':[x,y],'size':[w,h]}
        elif fields[0]=='edge':
            edge_started=True;require(len(fields)>=14,'plain edge fields differ')
            pair=tuple(fields[1:3]);require(pair in wanted and pair not in edges,'plain edge multiplicity differs from literal declaration')
            require(re.fullmatch('[0-9]+',fields[3]) is not None,'plain spline count differs');n=int(fields[3])
            require(4<=n<=800 and (n-1)%3==0 and len(fields)==6+2*n and fields[-2:]==['solid','black'],'plain cubic spline shape/style differs')
            values=[number(x) for x in fields[4:-2]];pts=[values[i:i+2] for i in range(0,len(values),2)]
            require(all(-.02<=x<=width+.02 and -.02<=y<=height+.02 for x,y in curve_points(pts)),'plain spline exceeds graph bounds')
            edges[pair]=pts
        else:require(False,'unexpected plain record')
    require(set(nodes)==set(labels) and set(edges)==wanted,'plain exact declared topology membership differs')
    # Every fixed box has a distinct nonoverlapping interior, independently of
    # any claim supplied in a native summary or our layout.json.
    ordered=list(nodes)
    for i,name in enumerate(ordered):
        x,y=nodes[name]['centre']
        for other in ordered[i+1:]:
            a,b=nodes[other]['centre'];require(abs(x-a)>=2.5-.002 or abs(y-b)>=.5-.002,'native node box interiors overlap')
    def distance_to_box(pt,node):
        x,y=pt;cx,cy=node['centre'];dx=abs(x-cx)-1.25;dy=abs(y-cy)-.25
        return max(dx,dy) if dx>0 or dy>0 else min(-dx,-dy)
    for (source,target),pts in edges.items():
        require(distance_to_box(pts[0],nodes[source])<=.04,'spline tail detached from declared source box')
        # Graphviz plain omits the arrowhead: its tip lies between final control
        # point and the target box. The qualified normal arrow is <=0.2 inches.
        require(distance_to_box(pts[-1],nodes[target])<=.2,'spline head detached from declared target box')
        if p['graphPolicy']=='dag':
            a,b=nodes[source]['centre'],nodes[target]['centre']
            require(a[1]>b[1]+.5 if p['rankDirection']=='TB' else b[0]>a[0]+2.5,'DAG edge violates declared rank direction')
    return width,height,nodes,edges


def svg(data,p,width,height,nodes,edges):
    require(data.count(DOCTYPE)==1,'qualified SVG doctype differs');data=data.replace(DOCTYPE,b'')
    require(b'<!DOCTYPE' not in data and b'<!ENTITY' not in data,'SVG entity declarations unsupported')
    # Comments and XML declaration are metadata; processing instructions inside
    # the document are rejected instead of silently discarded by ElementTree.
    cleaned=re.sub(br'<!--.*?-->',b'',data,flags=re.S)
    cleaned=re.sub(br'^<\?xml version="1.0" encoding="UTF-8" standalone="no"\?>',b'',cleaned)
    require(b'<?' not in cleaned,'SVG processing instructions unsupported')
    try:root=ET.fromstring(cleaned)
    except ET.ParseError as e:fail('VERIFICATION_FAILED','invalid SVG: '+str(e))
    require(set(root.attrib)=={'width','height','viewBox'} and root.tag==SVG+'svg','SVG root attributes differ')
    require(root.get('width','').endswith('pt') and root.get('height','').endswith('pt'),'SVG physical units must be points')
    sw,sh=number(root.get('width')[:-2]),number(root.get('height')[:-2]);view=[number(v) for v in root.get('viewBox').split()]
    require(len(view)==4 and view[:2]==[0,0] and abs(view[2]-width*72)<=.51+width*72*5e-5 and abs(view[3]-height*72)<=.51+height*72*5e-5,'SVG/plain view bounds differ')
    require(abs(sw-view[2])<=.51 and abs(sh-view[3])<=.51,'SVG viewport size differs')
    require(len(root)==1 and not (root.text or '').strip() and not (root.tail or '').strip(),'SVG canvas membership differs');canvas=root[0]
    require(set(canvas.attrib)=={'id','class','transform'} and canvas.get('id')=='graph0' and canvas.get('class')=='graph','SVG graph identity differs')
    transform=re.fullmatch(r'scale\(1 1\) rotate\(0\) translate\(0 ('+NUMBER+r')\)',canvas.get('transform',''))
    require(transform is not None and near(number(transform.group(1)),height*72),'SVG translation differs')
    require(not (canvas.text or '').strip() and not (canvas.tail or '').strip(),'SVG graph text differs')
    children=list(canvas);require(len(children)==2+len(nodes)+len(edges),'SVG node/edge group multiplicity differs')
    element(children[0],'title',{},[]);require(children[0].text=='G','SVG graph title differs')
    background=children[1];element(background,'polygon',{'fill':'white','stroke':'none','points':background.get('points')},[])
    bg=points(background.get('points',''));require(len(bg)==5,'SVG background shape differs')
    # Graphviz adds four-point stroke padding to the white background even with
    # pad=0; its polygon is a rectangle exactly surrounding the graph bounds.
    expected=[[0,0],[0,-height*72],[width*72,-height*72],[width*72,0],[0,0]]
    require(all(near(a,b) for aa,bb in zip(bg,expected) for a,b in zip(aa,bb)),'SVG background rectangle differs')
    seen_nodes=set();seen_edges=set();ids=set()
    for group in children[2:]:
        require(set(group.attrib)=={'id','class'} and group.get('id') not in ids,'SVG group attributes/identity differ');ids.add(group.get('id'))
        role=group.get('class');require(role in ('node','edge'),'SVG unexpected group class')
        element(group,'g',dict(group.attrib),['title','polygon','text'] if role=='node' else ['title','path','polygon'])
        title=group[0];element(title,'title',{},[])
        if role=='node':
            name=title.text;require(name in nodes and name not in seen_nodes and re.fullmatch('node[0-9]+',group.get('id')),'SVG literal node identity/multiplicity differs');seen_nodes.add(name)
            polygon,text=group[1:];element(polygon,'polygon',{'fill':'none','stroke':'black','points':polygon.get('points')},[])
            pts=points(polygon.get('points',''));require(len(pts)==5,'SVG fixed node polygon differs')
            x,y=nodes[name]['centre'];x*=72;y*=-72
            expected=[[x+90,y-18],[x-90,y-18],[x-90,y+18],[x+90,y+18],[x+90,y-18]]
            require(all(near(a,b) for aa,bb in zip(pts,expected) for a,b in zip(aa,bb)),'SVG/plain fixed box coordinates differ')
            attrs={'{http://www.w3.org/XML/1998/namespace}space':'preserve','text-anchor':'middle','x':text.get('x'),'y':text.get('y'),'font-family':'Courier,monospace','font-size':'10.00'}
            element(text,'text',attrs,[]);label=next(n['label'] for n in p['nodes'] if n['id']==name)
            require(text.text==label and near(number(text.get('x')),x) and abs(number(text.get('y'))-y)<=10,'SVG literal node label or label position differs')
        else:
            pair=tuple((title.text or '').split('->'));require(pair in edges and pair not in seen_edges and re.fullmatch('edge[0-9]+',group.get('id')),'SVG literal edge identity/multiplicity differs');seen_edges.add(pair)
            path,arrow=group[1:];element(path,'path',{'fill':'none','stroke':'black','d':path.get('d')},[])
            d=path.get('d','');tokens=re.findall(NUMBER+'|[MC]',d)
            require(''.join(tokens)==re.sub(r'[ ,]','',d) and tokens[0]=='M' and tokens[3]=='C' and tokens.count('M')==1 and tokens.count('C')==1,'SVG cubic path grammar differs')
            xy=[number(t) for t in tokens if t not in ('M','C')];expected=[v for pt in edges[pair] for v in (pt[0]*72,-pt[1]*72)]
            require(len(xy)==len(expected) and all(near(a,b) for a,b in zip(xy,expected)),'SVG/plain cubic control points differ')
            element(arrow,'polygon',{'fill':'black','stroke':'black','points':arrow.get('points')},[])
            pts=points(arrow.get('points',''));require(len(pts)==4 and pts[0]==pts[-1],'SVG normal arrow polygon differs')
            # Arrow shape uses already-checked SVG path coordinates to avoid
            # amplifying plain five-digit rounding on very large diagrams.
            end=xy[-2:];cx,cy=nodes[pair[1]]['centre'];cx*=72;cy*=-72
            base=[(pts[0][i]+pts[2][i])/2 for i in (0,1)];tangent=[end[i]-xy[-4+i] for i in (0,1)];length=math.hypot(*tangent)
            require(length>0 and math.dist(base,end)<.5 and abs(math.dist(pts[0],pts[2])-7)<.1 and abs(math.dist(pts[1],base)-10)<.25,'SVG normal arrow dimensions differ')
            require(sum((pts[1][i]-base[i])*tangent[i] for i in (0,1))/(10*length)>.98,'SVG normal arrow orientation differs')
            require(all(math.dist(v,end)<=17 for v in pts),'SVG arrow detached from spline')
            require(abs((pts[1][0]-pts[0][0])*(pts[2][1]-pts[0][1])-(pts[2][0]-pts[0][0])*(pts[1][1]-pts[0][1]))>1,'SVG arrow degenerate')
            require(any(abs(abs(x-cx)-90)<2 and abs(y-cy)<=19 or abs(abs(y-cy)-18)<2 and abs(x-cx)<=91 for x,y in pts),'SVG arrow tip detached from target box')
    require(seen_nodes==set(nodes) and seen_edges==set(edges),'SVG exact declared topology membership differs')


def inspect(directory,p,bounded,topology):
    try:
        w,h,nodes,edges=plain(bounded(directory/'graph.plain'),p)
        svg(bounded(directory/'graph.svg'),p,w,h,nodes,edges)
        return {'units':'inch','origin':'lower-left','width':w,'height':h,'rankDirection':p['rankDirection'],'graphPolicy':p['graphPolicy'],
            **topology(p),'labels':{n['id']:n['label'] for n in p['nodes']},'nodes':nodes,
            'edges':[{'source':e['source'],'target':e['target'],'controlPoints':edges[(e['source'],e['target'])]} for e in p['edges']]}
    except (ValueError,IndexError,KeyError,TypeError,UnicodeError) as e:fail('VERIFICATION_FAILED','invalid native graph geometry: '+str(e))
