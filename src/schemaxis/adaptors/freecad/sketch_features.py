"""Native dimensional constraints for centred rectangle and circle profiles.

Constraint indexing follows FreeCAD's public Sketcher scripting API:
https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_scripting.md
"""
import FreeCAD as App
import Part
import Sketcher
from schemaxis.errors import fail


def configure(obj, kind, options):
    if kind == 'circle':
        centre=options.get('centre',[0,0])
        obj.addGeometry(Part.Circle(App.Vector(*centre,0),App.Vector(0,0,1),options['radius']),False)
        if 'centre' in options:
            for name,kind,value in [('centreX','DistanceX',centre[0]),('centreY','DistanceY',centre[1])]:
                obj.renameConstraint(obj.addConstraint(Sketcher.Constraint(kind,0,3,value)),name)
        else:
            obj.addConstraint(Sketcher.Constraint('Coincident',0,3,-1,1))
        index = obj.addConstraint(Sketcher.Constraint('Radius',0,options['radius']))
        obj.renameConstraint(index,'radius')
    else:
        w, h = options['width'], options['height']
        points = [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]
        for a,b in zip(points,points[1:]+points[:1]):
            obj.addGeometry(Part.LineSegment(App.Vector(*a,0),App.Vector(*b,0)),False)
        for i in range(4):
            obj.addConstraint(Sketcher.Constraint('Coincident',i,2,(i+1)%4,1))
        for i in range(4):
            obj.addConstraint(Sketcher.Constraint('Horizontal' if i%2==0 else 'Vertical',i))
        for name, constraint in (
            ('width',Sketcher.Constraint('Distance',0,w)),
            ('height',Sketcher.Constraint('Distance',1,h)),
            ('anchorX',Sketcher.Constraint('DistanceX',0,1,-w/2)),
            ('anchorY',Sketcher.Constraint('DistanceY',0,1,-h/2))):
            obj.renameConstraint(obj.addConstraint(constraint),name)
        obj.setExpression('Constraints.anchorX','-Constraints.width / 2')
        obj.setExpression('Constraints.anchorY','-Constraints.height / 2')
    obj.Document.recompute()
    if obj.solve() != 0 or obj.FullyConstrained is not True:
        fail('CONSTRAINT_FAILED','native sketch did not become fully constrained',obj.Label)


def check(obj, kind, options, close, require):
    require(bool(obj.FullyConstrained) and obj.solve()==0,'fullyConstrained')
    constraints={c.Name:c for c in obj.Constraints if c.Name}
    if kind=='circle':
        require(obj.GeometryCount==1 and obj.ConstraintCount==(3 if 'centre' in options else 2),'sketchMembership')
        require('radius' in constraints and close(constraints['radius'].Value,options['radius']),'radiusConstraint')
        require(close(obj.Geometry[0].Radius,options['radius']) and close(list(obj.Geometry[0].Center),[*options.get('centre',[0,0]),0]),'circle')
        if 'centre' in options:
            for name,value in zip(('centreX','centreY'),options['centre']):
                require(name in constraints and close(constraints[name].Value,value),name)
    else:
        require(obj.GeometryCount==4 and obj.ConstraintCount==12,'sketchMembership')
        for name in ('width','height'):
            require(name in constraints and close(constraints[name].Value,options[name]),name+'Constraint')
        w,h=options['width'],options['height']
        points=[[-w/2,-h/2,0],[w/2,-h/2,0],[w/2,h/2,0],[-w/2,h/2,0]]
        for index,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
            require(close(list(obj.Geometry[index].StartPoint),a) and close(list(obj.Geometry[index].EndPoint),b),'rectangle')
