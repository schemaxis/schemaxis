"""Independent rectangular-partition oracles for editable Draft profiles."""
import math


def outline(kind='L',edited=False):
    if kind=='L':
        w=12 if edited else 10
        return [[0,0],[w,0],[w,2],[4,2],[4,6],[0,6]]
    floor=2 if edited else 3
    return [[0,0],[12,0],[12,8],[9,8],[9,floor],[3,floor],[3,8],[0,8]]


def document(kind='L',*,clockwise=False):
    points=outline(kind)
    if clockwise:points=list(reversed(points))
    options={'points':points}
    if kind=='U':options.update(plane='YZ',origin=[20,-10,5],angle=17)
    nodes=[{'id':'outline','filter':'draftProfile','options':options},
           {'id':'stock','filter':'extrude','inputs':{'profile':'outline'},'options':{'length':10 if kind=='L' else 7,'direction':[0,0,1] if kind=='L' else [1,0,0]}}]
    if kind=='L':nodes.extend([
        {'id':'drill','filter':'cylinder','options':{'radius':.5,'height':20,'origin':[7,1,-5]}},
        {'id':'bracket','filter':'cut','inputs':{'base':'stock','tool':'drill'}}])
    return {'version':'schemaxis.freecad/1','nodes':nodes,'output':'bracket' if kind=='L' else 'stock'}


def oracle(kind='L',*,edited=False,moved=False):
    if kind=='L':
        w=12 if edited else 10;shift=2 if moved else 0;h=10
        # Disjoint lower rectangle and upper-left rectangle, then through bore.
        v1=w*2*h;v2=4*4*h;removed=math.pi*.5**2*h;volume=v1+v2-removed
        centre=[(v1*(shift+w/2)+v2*(shift+2)-removed*7)/volume,
                (v1*1+v2*4-removed*1)/volume,5]
        return {'volume':volume,'centreOfMass':centre,'bounds':[shift,shift+w,0,6,0,10],
                'area':2*(2*w+16)+2*(w+6)*h-2*math.pi*.5**2+2*math.pi*.5*h,
                'inside':[[shift+1,4,5],[shift+w-1,1,5]],'outside':[[shift+8,4,5],[7,1,5]],
                'sections':[{'normal':[0,0,1],'offset':5,'areas':[2*w+16,math.pi*.5**2]}]}
    floor=2 if edited else 3;origin=[23,-12,7] if moved else [20,-10,5]
    # Outer12x8 rectangle minus the6-wide slot open through the far side.
    area=12*8-6*(8-floor);perimeter=2*(12+8)+2*(8-floor)
    cy=(96*4-6*(8-floor)*(floor+8)/2)/area
    c,s=math.cos(math.radians(17)),math.sin(math.radians(17))
    def world(p):x,y,z=p;return [origin[0]+z,origin[1]+c*x-s*y,origin[2]+s*x+c*y]
    points=outline('U',edited);ys=[origin[1]+c*x-s*y for x,y in points];zs=[origin[2]+s*x+c*y for x,y in points]
    return {'volume':area*7,'centreOfMass':world([6,cy,3.5]),
            'bounds':[origin[0],origin[0]+7,min(ys),max(ys),min(zs),max(zs)],
            'area':2*area+perimeter*7,'inside':[world([1,6,3.5]),world([6,1,3.5])],
            'outside':[world([6,6,3.5]),world([13,1,3.5])],
            'sections':[{'normal':[1,0,0],'offset':origin[0]+3.5,'areas':[area]}]}


def xz_case():
    doc=document('U');doc['nodes'][0]['options'].update(plane='XZ',origin=[-12,8,2],angle=-23)
    doc['nodes'][1]['options']['direction']=[0,-1,0]
    c,s=math.cos(math.radians(-23)),math.sin(math.radians(-23))
    def world(x,y,z):return [-12+c*x-s*y,8-z,2+s*x+c*y]
    boundary=[world(x,y,0) for x,y in outline('U')]
    # Independent disjoint bottom/side rectangles:36+15+15, centroid(6,73/22).
    cy=(36*1.5+30*5.5)/66
    expected={'volume':462,'area':482,'centreOfMass':world(6,cy,3.5),
        'bounds':[min(p[0] for p in boundary),max(p[0] for p in boundary),1,8,min(p[2] for p in boundary),max(p[2] for p in boundary)],
        'inside':[world(1,6,3.5),world(6,1,3.5)],'outside':[world(6,6,3.5),world(13,1,3.5)],
        'sections':[{'normal':[0,1,0],'offset':4.5,'areas':[66]}]}
    return doc,expected


def maximum_case():
    n=256;r=10;points=[[r*math.cos(2*math.pi*i/n),r*math.sin(2*math.pi*i/n)] for i in range(n)]
    area=n*r*r*math.sin(2*math.pi/n)/2;perimeter=2*n*r*math.sin(math.pi/n)
    doc={'version':'schemaxis.freecad/1','nodes':[{'id':'outline','filter':'draftProfile','options':{'points':points}},
        {'id':'stock','filter':'extrude','inputs':{'profile':'outline'},'options':{'length':2}}],'output':'stock'}
    expected={'volume':2*area,'area':2*area+2*perimeter,'centreOfMass':[0,0,1],
        'bounds':[-10,10,-10,10,0,2],'inside':[[0,0,1]],'outside':[[11,0,1]],
        'sections':[{'normal':[0,0,1],'offset':1,'areas':[area]}]}
    return doc,expected


def loft_case():
    doc={'version':'schemaxis.freecad/1','nodes':[
        {'id':'bottom','filter':'draftProfile','options':{'points':[[0,0],[6,0],[0,4]]}},
        {'id':'top','filter':'draftProfile','options':{'points':[[0,0],[3,0],[0,2]],'origin':[0,0,8]}},
        {'id':'stock','filter':'loft','inputs':{'sections':['bottom','top']},'options':{'ruled':True}}],'output':'stock'}
    # Similar triangular frustum, section scale 1-z/16. Integrate its first
    # moments analytically; lateral areas are three literal trapezoids.
    expected={'volume':56,'area':75+3*math.sqrt(217),'centreOfMass':[45/28,15/14,22/7],
        'bounds':[0,6,0,4,0,8],'inside':[[.5,.5,4]],'outside':[[5,3,4]],
        'sections':[{'normal':[0,0,1],'offset':4,'areas':[6.75]}]}
    return doc,expected
