"""Independent retained sheet, geometry, saved links and publication checks."""
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from . import drawing as policy
from .adaptor import close as numeric_close

def close(a,b):
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(close(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):return numeric_close(a,b)
    return type(a) is type(b) and a==b
from .document_xml import Document
from schemaxis.errors import fail


def checked_brep(data):
    """Normalize observed cache/ownership flags and exact decimal-zero signs.

    Independent input/FCStd observations on1.1.4 show isValid() changes face flags
    0101000->0111000. The bit is not authored geometry. All other bytes, including
    every other topology flag, stay bound. A mesh-derived cylindrical boolean
    source on 1.1.4 also reserializes one positive decimal zero as negative zero
    on GUI publication. Normalize only the sign of complete decimal-zero tokens,
    retaining their precision and every nonzero token; this is numeric equality,
    not a geometric tolerance. Assigning a shape
    to a native property clears the Compound/Solid Free ownership bit (1100000 to
    0100000); mask that ownership flag as well, retaining all geometric bytes.
    """
    lines=data.split(b'\n')
    for i,line in enumerate(lines):
        line=b' '.join(token[1:] if re.fullmatch(rb'-0\.0+',token) else token for token in line.split(b' '))
        lines[i]=line
        if i>=3 and lines[i-3]==b'Fa' and re.fullmatch(rb'[01]{7}',line):lines[i]=line[:2]+b'0'+line[3:]
        if i>=2 and lines[i-2] in (b'Co',b'So') and re.fullmatch(rb'[01]{7}',line):lines[i]=b'0'+line[1:]
    return b'\n'.join(lines)


def verify(directory,require_result):
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,str(directory))
    p=json.loads((directory/'plan.json').read_text());authored=json.loads((directory/'authored.json').read_text())
    require(p==policy._native_plan(authored,captured=directory/p['source']['capture']),'Drawing plan differs from authored intent or captured source')
    if require_result:require(json.loads((directory/'result.json').read_text()).get('verified') is True,'Drawing execution is incomplete')
    if p['source']['format']=='FCStd':require(policy.digest((directory/'source.brep').read_bytes())==p['source']['brepSha256'],'Extracted source BREP differs')
    built=json.loads((directory/'built.json').read_text());reopened=json.loads((directory/'reopened.json').read_text());published=json.loads((directory/'verification.json').read_text())
    require(len({r.get('pid') for r in (built,reopened,published)})==3 and all(type(r.get('pid')) is int for r in (built,reopened,published)),'Drawing lifecycle stages must use three independent native processes')
    require(close(reopened.get('edit'),{'before':p['sheet']['scale'],'changed':p['sheet']['scale']*.9,'restored':p['sheet']['scale']}),'Native view scale edit was not observed and restored')
    require(reopened.get('capturedBrepSha256')==reopened.get('source',{}).get('brepSha256'),'Frozen shape BREP differs from an independent read of the captured source')
    expected_objects={'Source':'Part::Feature','Page':'TechDraw::DrawPage','Template':'TechDraw::DrawSVGTemplate','Title':'TechDraw::DrawViewAnnotation'}
    if p['notes']:expected_objects['Notes']='TechDraw::DrawViewAnnotation'
    expected_objects.update({'View_'+v['id']:'TechDraw::DrawViewPart' for v in p['views']})
    expected_objects.update({'Dimension_'+d['id']:'TechDraw::DrawViewDimension' for d in p['dimensions']})
    expected_views=['View_'+v['id'] for v in p['views']]+['Dimension_'+d['id'] for d in p['dimensions']]+['Title']+(['Notes'] if p['notes'] else [])
    dimtypes={'overallWidth':'DistanceX','overallHeight':'DistanceY','diameter':'Diameter','radius':'Radius','edgeLength':'Distance','horizontal':'DistanceX','vertical':'DistanceY','distance':'Distance'}
    for observed,stage in ((built,'build'),(reopened,'reopen'),(published,'publication')):
        require(observed.get('stage')==stage and observed.get('objects')==expected_objects,'Native object type or membership differs')
        require(observed.get('page')=={'type':'TechDraw::DrawPage','views':expected_views,'template':'Template','scale':p['sheet']['scale']},'Native sheet ownership differs')
        source=observed.get('source',{});require(source.get('valid') is True and type(source.get('solids')) is int and source.get('solids')==1 and close(source.get('volume'),p['source']['volume']) and close(source.get('bounds'),p['source']['bounds']) and close(source.get('centreOfMass'),p['source']['centreOfMass']),'Native geometry differs from independent volume/bounds expectations')
        require(len(observed.get('views',[]))==len(p['views']) and len(observed.get('dimensions',[]))==len(p['dimensions']),'Native view/dimension evidence incomplete')
        for view,spec in zip(observed['views'],p['views']):
            for key,expected in {'id':spec['id'],'name':'View_'+spec['id'],'type':'TechDraw::DrawViewPart','source':['Source'],'direction':spec['direction'],'right':spec['right'],'scale':p['sheet']['scale'],'scaleType':'Custom','position':spec['position'],'caption':spec['id'].upper(),'valid':True,'hardHidden':False,'perspective':False,'rotation':0}.items():
                require(close(view.get(key),expected),'Native projection setting differs: '+spec['id']+'.'+key)
            require(type(view.get('edges')) is int and view['edges']>0,'Projection contains no visible geometry')
            bounds=view.get('bounds');require(isinstance(bounds,list) and len(bounds)==4,'Projected geometry bounds are absent')
            if spec['expectedSpan']:
                require(close([bounds[1]-bounds[0],bounds[3]-bounds[2]],[x*p['sheet']['scale'] for x in spec['expectedSpan']]),'Orthographic view does not show the expected source extents')
        for dim,spec in zip(observed['dimensions'],p['dimensions']):
            require(dim.get('id')==spec['id'] and dim.get('name')=='Dimension_'+spec['id'] and dim.get('nativeType')=='TechDraw::DrawViewDimension' and dim.get('type')==dimtypes[spec['type']] and dim.get('measureType')=='Projected' and dim.get('valid') is True,'Native dimension type or validity differs')
            require(dim.get('arbitrary') is False and dim.get('format')==policy.dimension_format(spec['type']) and dim.get('showUnits') is True and close(dim.get('position'),spec['position']),'Dimension precision, units, placement or measured mode differs')
            refs=dim.get('references');require(isinstance(refs,list) and len(refs)==1 and refs[0][0]=='View_'+spec['view'] and isinstance(refs[0][1],list) and all(re.fullmatch(r'(Edge|Vertex)(0|[1-9][0-9]*)',s) for s in refs[0][1]),'Dimension projection references differ')
            if spec['type'] in ('overallWidth','overallHeight','edgeLength','horizontal','vertical','distance'):
                points=dim.get('linear');require(isinstance(points,list) and len(points)==2 and all(isinstance(q,list) and len(q)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in q) for q in points),'Dimension measured endpoints are absent')
                dx=abs(points[1][0]-points[0][0]);dy=abs(points[1][1]-points[0][1])
                measured=dx if spec['type'] in ('overallWidth','horizontal') else dy if spec['type'] in ('overallHeight','vertical') else math.hypot(dx,dy)
                require(close(measured,spec['expected']*p['sheet']['scale']),'Measured projection anchors differ from independent dimension intent')
            raw=dim.get('text');raw=' '.join(raw) if isinstance(raw,list) else raw
            require(isinstance(raw,str),'Native dimension text is absent')
            values=re.findall(r'[-+]?[0-9]+(?:\.[0-9]+)?',raw)
            require(bool(values) and math.isclose(float(values[0]),spec['expected'],abs_tol=.0051,rel_tol=1e-6),'Native measured dimension text differs from independent expected geometry: '+spec['id'])
        annotations=p['annotations']
        require(observed.get('annotations')==annotations,'Native annotations differ')
    # Independently parse persisted typed properties. Refreshed artifact hashes or
    # receipt text cannot conceal changed saved projection/dimension semantics.
    saved=Document(directory/'drawing.FCStd');require(saved.types==expected_objects,'Saved drawing object membership differs')
    require(all(saved.engine(n)==[] for n in saved.types),'Saved drawing contains an undeclared expression')
    from zipfile import ZipFile
    from .document_xml import read_member
    shape=saved.properties['Source']['Shape'];require(shape.get('type')=='Part::PropertyPartShape' and len(shape.findall('Part'))==1,'Saved frozen source shape property differs')
    with ZipFile(directory/'drawing.FCStd') as archive:payload=read_member(archive,shape.find('Part').get('file'),32*1024*1024)
    if p['source']['format']=='FCStd':
        from .assembly_payloads import same_brep
        require(same_brep(checked_brep((directory/'source.brep').read_bytes()),checked_brep(payload)),'Saved frozen geometry differs from captured native shape')
    placement=saved.child('Source','Placement','PropertyPlacement','App::PropertyPlacement')
    require(close([float(placement.get(k)) for k in ('Px','Py','Pz','Q0','Q1','Q2','Q3')],reopened['source']['placement']),'Saved frozen shape placement differs')
    require(saved.links('Page','Views')==expected_views and saved.link('Page','Template')=='Template','Saved sheet links differ')
    require(close(saved.number('Page','Scale','App::PropertyFloatConstraint'),p['sheet']['scale']),'Saved sheet scale differs')
    for identity,spec in annotations.items():
        entries=saved.child(identity,'Text','StringList','App::PropertyStringList')
        require(entries.get('count')==str(len(spec['text'])) and [c.get('value') for c in entries]==spec['text'],'Saved annotation text differs')
        require(close(saved.number(identity,'TextSize'),3) and saved.child(identity,'Font','String','App::PropertyFont').get('value')=='DejaVu Sans','Saved annotation typography differs')
        require(close(saved.number(identity,'MaxWidth','App::PropertyFloat'),p['sheet']['width']/2-20),'Saved annotation column width differs')
        require(close([saved.number(identity,'X','App::PropertyDistance'),saved.number(identity,'Y','App::PropertyDistance')],spec['position']),'Saved annotation layout differs')
    require(close(saved.number('Template','Width'),p['sheet']['width']) and close(saved.number('Template','Height'),p['sheet']['height']),'Saved template paper dimensions differ')
    included=saved.child('Template','PageResult','FileIncluded','App::PropertyFileIncluded').get('file')
    with ZipFile(directory/'drawing.FCStd') as archive:template=read_member(archive,included,1024*1024)
    from .document_xml import parse_xml
    template=parse_xml(template,'sheet template')
    require(template.tag=='{http://www.w3.org/2000/svg}svg' and template.get('width')==str(p['sheet']['width'])+'mm' and template.get('height')==str(p['sheet']['height'])+'mm','Embedded drawing template units differ')
    rect=template.find('.//{http://www.w3.org/2000/svg}rect')
    require(rect is not None and rect.attrib=={'x':'5','y':'5','width':str(p['sheet']['width']-10),'height':str(p['sheet']['height']-10)},'Embedded template border differs')
    for view in p['views']:
        identity='View_'+view['id'];require(saved.links(identity,'Source')==['Source'],'Saved drawing source link differs')
        require(saved.string(identity,'Caption')==view['id'].upper(),'Saved view caption differs')
        require(close(saved.number(identity,'Scale','App::PropertyFloatConstraint'),p['sheet']['scale']),'Saved view scale differs')
        require(close([saved.number(identity,'X','App::PropertyDistance'),saved.number(identity,'Y','App::PropertyDistance')],view['position']),'Saved view layout differs')
        for prop,key in (('Direction','direction'),('XDirection','right')):
            vector=saved.child(identity,prop,'PropertyVector','App::PropertyVector');require(close([float(vector.get(a)) for a in ('valueX','valueY','valueZ')],view[key]),'Saved view frame differs')
        require(saved.boolean(identity,'Perspective') is False and saved.boolean(identity,'HardHidden') is False,'Saved projection mode differs')
    for dim,spec in zip(published['dimensions'],p['dimensions']):
        identity='Dimension_'+spec['id'];require(saved.string(identity,'FormatSpec')==policy.dimension_format(spec['type']) and saved.boolean(identity,'Arbitrary') is False and saved.boolean(identity,'ShowUnits') is True,'Saved dimension display mode differs')
        for prop,index in (('Type',{'Distance':0,'DistanceX':1,'DistanceY':2,'Radius':4,'Diameter':5}[dimtypes[spec['type']]]),('MeasureType',1)):
            require(saved.child(identity,prop,'Integer','App::PropertyEnumeration').get('value')==str(index),'Saved dimension measured type differs')
        refs=saved.child(identity,'References2D','LinkSubList','App::PropertyLinkSubList')
        # FCStd serialises one Link per selected subelement.
        require([c.get('obj') for c in refs]==['View_'+spec['view']]*len(dim['references'][0][1]) and [c.get('sub') for c in refs]==dim['references'][0][1],'Saved dimension references differ')
        require(close([saved.number(identity,'X','App::PropertyDistance'),saved.number(identity,'Y','App::PropertyDistance')],[spec['position'][i]-next(v for v in p['views'] if v['id']==spec['view'])['position'][i] for i in range(2)]),'Saved dimension label position differs')
    svg=(directory/'drawing.svg').read_bytes();require(len(svg)<64*1024*1024,'Drawing SVG exceeds bound')
    from .document_xml import parse_xml
    root=parse_xml(svg,'drawing.svg');require(root.tag=='{http://www.w3.org/2000/svg}svg','Publication is not SVG')
    require(root.get('width')==str(p['sheet']['width'])+'mm' and root.get('height')==str(p['sheet']['height'])+'mm','SVG sheet dimensions differ')
    content=root.find(".//*[@id='DrawingContent']");require(content is not None and len(content)>0,'Native SVG contains no drawing content')
    alltext=' '.join(root.itertext())
    require(all(v['id'].upper() in alltext for v in p['views']),'SVG is missing a requested projection caption')
    for spec in p['dimensions']:
        prefix={'radius':'R','diameter':'\u2300'}.get(spec['type'],'')
        require(prefix+format(spec['expected'],'.3f')+' mm' in alltext,'SVG measured dimension text differs from independent geometry')
    require(all(line in alltext for record in p['annotations'].values() for line in record['text']),'SVG annotations are missing')
    pdf=(directory/'drawing.pdf').read_bytes();require(pdf.startswith(b'%PDF-') and b'%%EOF' in pdf[-1024:] and len(pdf)>1000,'PDF publication is absent or truncated')
    require(len(published.get('artifacts',[]))==3,'Drawing publication membership differs')
    for artifact,(filename,kind) in zip(published['artifacts'],(('drawing.FCStd','cadScene'),('drawing.svg','image'),('drawing.pdf','document'))):
        path=directory/filename;require(not path.is_symlink() and path.is_file() and artifact=={'file':str(path),'kind':kind,'sha256':policy.digest(path.read_bytes()),'units':'mm'},'Drawing artifact metadata or bytes differ')
    return {'verified':True,'artifacts':3,'runtime':published['runtime'],'views':len(p['views']),'dimensions':len(p['dimensions']),'nativeFile':str(directory/'drawing.FCStd'),'sourceHistoryPreserved':False}
