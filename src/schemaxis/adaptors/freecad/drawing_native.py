"""Native TechDraw execution. Loaded only in isolated FreeCAD processes."""
import hashlib
import json
import math
import os
from pathlib import Path
from xml.sax.saxutils import escape

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .adaptor import close


def _load(directory):
    directory=Path(directory);return directory,json.loads((directory/'plan.json').read_text())


def _bounds(shape):
    b=shape.BoundBox;return [b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax]


def _check(shape,p):
    if not shape.isValid() or len(shape.Solids)!=1 or not close(shape.Volume,p['source']['volume']) or not close(_bounds(shape),p['source']['bounds']) or not close(_v(shape.Solids[0].CenterOfMass),p['source']['centreOfMass']):
        fail('EXPECTATION_FAILED','Source solid differs from declared validity, volume or bounds')


def _template(p):
    s=p['sheet'];w,h=s['width'],s['height']
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:freecad="http://www.freecadweb.org/wiki/index.php?title=Svg_Namespace" width="'+str(w)+'mm" height="'+str(h)+'mm" viewBox="0 0 '+str(w)+' '+str(h)+'">'
      '<g fill="none" stroke="black" stroke-width="0.3"><rect x="5" y="5" width="'+str(w-10)+'" height="'+str(h-10)+'"/><path d="M5 '+str(h-30)+' H'+str(w-5)+'"/></g></svg>')


def build(directory):
    import FreeCAD as App,Part
    directory,p=_load(directory);doc=App.newDocument('SchemaxisDrawing')
    source=doc.addObject('Part::Feature','Source')
    shape=Part.Shape()
    shape.read(str(directory/('source.brep' if p['source']['format']=='FCStd' else 'source.step')))
    _check(shape,p);source.Shape=shape
    page=doc.addObject('TechDraw::DrawPage','Page');template=doc.addObject('TechDraw::DrawSVGTemplate','Template')
    (directory/'sheet.svg').write_text(_template(p));template.Template=str(directory/'sheet.svg');page.Template=template
    page.Scale=p['sheet']['scale']
    for spec in p['views']:
        v=doc.addObject('TechDraw::DrawViewPart','View_'+spec['id']);v.Label=spec['id'];v.Source=[source]
        page.addView(v)
        v.Direction=App.Vector(*spec['direction']);v.XDirection=App.Vector(*spec['right']);v.ScaleType='Custom';v.Scale=p['sheet']['scale']
        v.X,v.Y=spec['position'];v.Caption=spec['id'].upper()
    doc.recompute()
    for spec in p['dimensions']:
        view=doc.getObject('View_'+spec['view']);d=doc.addObject('TechDraw::DrawViewDimension','Dimension_'+spec['id']);d.Label=spec['id']
        typ=spec['type'];edges=[];vertices=[]
        for i in range(10000):
            try:vertices.append(view.getVertexByIndex(i).Point)
            except (ValueError,IndexError,RuntimeError):break
        for i in range(10000):
            try:edges.append(view.getEdgeByIndex(i))
            except (ValueError,IndexError,RuntimeError):break
        if typ in ('horizontal','vertical','distance'):
            refs=[]
            for end in ('from','to'):
                target=spec[end];matches=[]
                if target['on']=='vertex':
                    matches=['Vertex'+str(i) for i,q in enumerate(vertices) if close([q.x,q.y],target['projected'])]
                    # Coincident projected vertices are equivalent for this
                    # dimension; select afresh and retain actual native anchors.
                    if matches:matches=matches[:1]
                else:
                    circles=[i for i,e in enumerate(edges) if isinstance(e.Curve,Part.Circle) and close(e.Curve.Radius,target['radius']) and close([e.Curve.Center.x,e.Curve.Center.y],target['projected'])]
                    matches=['Vertex'+str(i) for i,q in enumerate(vertices) if close([q.x,q.y],target['projected'])][:1] if circles else []
                if len(matches)!=1:fail('AMBIGUOUS_SELECTION' if matches else 'EMPTY_SELECTION','Dimension endpoint does not select exactly one projected geometric anchor',spec['id']+'.'+end,matches=len(matches))
                refs.extend(matches)
            d.Type={'horizontal':'DistanceX','vertical':'DistanceY','distance':'Distance'}[typ]
        elif typ in ('overallWidth','overallHeight'):
            axis=0 if typ=='overallWidth' else 1
            if not vertices:fail('EMPTY_SELECTION','Projected view contains no vertices for an overall dimension',spec['id'])
            # Equal extrema are equivalent for an axis-distance dimension. The
            # orthogonal coordinate tie-breaker is geometric, never a cached index.
            ordered=sorted(range(len(vertices)),key=lambda i:(vertices[i][axis],vertices[i][1-axis]))
            indices=[ordered[0],ordered[-1]];refs=['Vertex'+str(i) for i in indices]
            d.Type='DistanceX' if axis==0 else 'DistanceY'
        else:
            matches=[]
            for i,e in enumerate(edges):
                curve=e.Curve
                if typ in ('diameter','radius') and isinstance(curve,Part.Circle) and close(curve.Radius,spec['radius']):matches.append(i)
                if typ=='edgeLength' and isinstance(curve,Part.Line) and close(e.Length,spec['expected']):matches.append(i)
            if len(matches)!=1:fail('AMBIGUOUS_SELECTION' if matches else 'EMPTY_SELECTION','Dimension needs exactly one matching projected edge',spec['id'],matches=len(matches))
            refs=['Edge'+str(matches[0])];d.Type={'diameter':'Diameter','radius':'Radius','edgeLength':'Distance'}[typ]
        from .drawing import dimension_format
        d.References2D=[(view,tuple(refs))];d.MeasureType='Projected';d.FormatSpec=dimension_format(typ);d.ShowUnits=True;d.X,d.Y=[spec['position'][i]-next(v for v in p['views'] if v['id']==spec['view'])['position'][i] for i in range(2)];page.addView(d)
    for identity,spec in p['annotations'].items():
        note=doc.addObject('TechDraw::DrawViewAnnotation',identity);page.addView(note);note.Text=spec['text'];note.Font='DejaVu Sans';note.TextSize=3;note.MaxWidth=p['sheet']['width']/2-20;note.TextColor=(0.,0.,0.);note.X,note.Y=spec['position']
    doc.recompute();doc.saveAs(str(directory/'drawing.FCStd'))
    atomic_json(directory/'built.json',observe(doc,p,'build'));App.closeDocument(doc.Name)


def _fingerprint(shape):
    from .drawing_checks import checked_brep
    return hashlib.sha256(checked_brep(shape.exportBrepToString().encode())).hexdigest()


def _v(vector):return [vector.x,vector.y,vector.z]


def observe(doc,p,stage):
    import FreeCAD as App
    _check(doc.getObject('Source').Shape,p)
    page=doc.getObject('Page');source=doc.getObject('Source');views=[];dimensions=[]
    for spec in p['views']:
        view=doc.getObject('View_'+spec['id']);edges=view.getVisibleEdges();vertices=view.getVisibleVertexes();points=[v for e in edges for v in (e.BoundBox.XMin,e.BoundBox.XMax)]
        bounds=[min(e.BoundBox.XMin for e in edges),max(e.BoundBox.XMax for e in edges),min(e.BoundBox.YMin for e in edges),max(e.BoundBox.YMax for e in edges)] if edges else []
        views.append({'id':spec['id'],'name':view.Name,'type':view.TypeId,'source':[x.Name for x in view.Source],
          'direction':_v(view.Direction),'right':_v(view.XDirection),'scale':view.Scale,'scaleType':view.ScaleType,
          'position':[view.X.Value,view.Y.Value],'caption':view.Caption,'bounds':bounds,'edges':len(edges),'vertices':len(vertices),
          'valid':view.isValid(),'hardHidden':view.HardHidden,'perspective':view.Perspective,'rotation':view.Rotation.Value})
    for spec in p['dimensions']:
        dim=doc.getObject('Dimension_'+spec['id'])
        linear=[_v(v) for v in dim.getLinearPoints()] if spec['type'] in ('overallWidth','overallHeight','edgeLength','horizontal','vertical','distance') else []
        arc=dim.getArcPoints() if spec['type'] in ('diameter','radius') else None
        dimensions.append({'id':spec['id'],'name':dim.Name,'nativeType':dim.TypeId,'type':dim.Type,'measureType':dim.MeasureType,
            'references':[[v.Name,list(sub)] for v,sub in dim.References2D],'position':[dim.X.Value+next(v for v in p['views'] if v['id']==spec['view'])['position'][0],dim.Y.Value+next(v for v in p['views'] if v['id']==spec['view'])['position'][1]],
            'format':dim.FormatSpec,'showUnits':dim.ShowUnits,'arbitrary':dim.Arbitrary,'text':dim.getText(),
            'linear':linear,'arc':str(arc) if arc else None,'valid':dim.isValid()})
    return {'stage':stage,'pid':os.getpid(),'runtime':'.'.join(App.Version()[:3]),'objects':{o.Name:o.TypeId for o in doc.Objects},
      'page':{'type':page.TypeId,'views':[v.Name for v in page.Views],'template':page.Template.Name,'scale':page.Scale},
      'source':{'placement':[*_v(source.Placement.Base),*source.Placement.Rotation.Q],'brepSha256':_fingerprint(source.Shape),'volume':source.Shape.Volume,'bounds':_bounds(source.Shape),'centreOfMass':_v(source.Shape.Solids[0].CenterOfMass),'valid':source.Shape.isValid(),'solids':len(source.Shape.Solids)},
      'views':views,'dimensions':dimensions,'annotations':{o.Name:{'text':list(o.Text),'position':[o.X.Value,o.Y.Value]} for o in doc.Objects if o.TypeId=='TechDraw::DrawViewAnnotation'}}


def reopen(directory):
    import FreeCAD as App
    directory,p=_load(directory);doc=App.openDocument(str(directory/'drawing.FCStd'));doc.recompute()
    result=observe(doc,p,'reopen')
    import Part
    original=Part.Shape();original.read(str(directory/('source.brep' if p['source']['format']=='FCStd' else 'source.step')))
    _check(original,p)
    # Native property ownership stores even an identity TopLoc_Location.
    # Reassigning the exact same placement materialises that metadata without
    # moving geometry, making the independent import comparable to persistence.
    original.Placement=original.Placement
    result['capturedBrepSha256']=_fingerprint(original)
    # Edit one native view scale, recompute, and restore it. The saved drawing
    # keeps native editable TechDraw objects; edit is not reverse synchronisation.
    first=doc.getObject('View_'+p['views'][0]['id']);before=first.Scale;first.Scale=before*.9;doc.recompute()
    result['edit']={'before':before,'changed':first.Scale};first.Scale=before;doc.recompute();result['edit']['restored']=first.Scale
    atomic_json(directory/'reopened.json',result);App.closeDocument(doc.Name)


def publish(directory):
    import FreeCAD as App,FreeCADGui as Gui,TechDrawGui
    directory,p=_load(directory);doc=App.openDocument(str(directory/'drawing.FCStd'));doc.recompute();page=doc.getObject('Page')
    Gui.activeDocument().getObject('Page').show();Gui.updateGui()
    for spec in p['views']:
        obj=doc.getObject('View_'+spec['id']);obj.ViewObject.LineWidth=.35;obj.ViewObject.FaceColor=(1.,1.,1.)
    for spec in p['dimensions']:
        dim=doc.getObject('Dimension_'+spec['id']);dim.ViewObject.Fontsize=3;dim.ViewObject.Font='DejaVu Sans';dim.ViewObject.Arrowsize=2.5;dim.ViewObject.Color=(0.,0.,0.);dim.touch()
    doc.recompute();Gui.updateGui();doc.save()
    # Creating the view providers and showing the page must precede publication;
    # the same API otherwise succeeds with an empty DrawingContent group.
    TechDrawGui.exportPageAsSvg(page,str(directory/'drawing.svg'));TechDrawGui.exportPageAsPdf(page,str(directory/'drawing.pdf'))
    result=observe(doc,p,'publication');result['artifacts']=[]
    for filename,kind in (('drawing.FCStd','cadScene'),('drawing.svg','image'),('drawing.pdf','document')):
        path=directory/filename;result['artifacts'].append({'file':str(path),'kind':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'units':'mm'})
    atomic_json(directory/'verification.json',result);atomic_json(directory/'publication.json',result)
