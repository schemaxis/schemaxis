"""Analytic drilling fixtures, independent of native feature implementation."""
import copy
import math


def part(kind='boltGrid',layout=None,hole=None):
    return {'version':'schemaxis.freecad/1','units':'mm','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'rectangle','options':{'width':30,'height':30},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':10},'inputs':{'body':'body','profile':'outline'}},
        {'id':'locations','filter':kind,'options':{'onFace':{'face':'top'},**(layout or {})},'inputs':{'body':'body','support':'stock'}},
        {'id':'holes','filter':'hole','options':{'diameter':3,**(hole or {})},'inputs':{'body':'body','base':'stock','profile':'locations'}}], 'output':'holes'}


def expected_volume(count,diameter,depth=10,*,tip=0,tip_included=False,recess_diameter=0,recess_depth=0,recess_angle=None):
    r=diameter/2;removed=math.pi*r*r*(depth-tip if tip_included else depth)+math.pi*r*r*tip/3
    if recess_diameter:
        radius=recess_diameter/2
        removed+=math.pi*(radius*radius-r*r)*recess_depth
        if recess_angle is not None:removed+=math.pi*(radius-r)**2*(radius+2*r)/(3*math.tan(math.radians(recess_angle/2)))
    return 9000-count*removed


def cases():
    grid={'columns':2,'rows':2,'xPitch':16,'yPitch':14};centres=[[-8,-7],[8,-7],[-8,7],[8,7]]
    def item(identity,document,volume,positions=centres,axis='Z',sample=5):return identity,document,{'volume':volume,'positions':positions,'axis':axis,'voidSample':sample,'diameter':document['nodes'][-1]['options']['diameter'],'holeOptions':copy.deepcopy(document['nodes'][-1]['options'])}
    yield item('plain-grid',part(layout=grid),expected_volume(4,3))
    positions=[[0,0],[6,5],[-7,-4]]
    yield item('explicit-centres',part('holeLocations',{'centres':positions}, {'diameter':2.4}),expected_volume(3,2.4),positions)
    positions=[[1,-8],[1,-1],[1,6]]
    yield item('single-offset-column',part(layout={'columns':1,'rows':3,'xPitch':12,'yPitch':7,'centre':[1,-1]},hole={'diameter':2}),expected_volume(3,2),positions)
    positions=[[1+8*math.cos(math.radians(-20+72*n)),-2+8*math.sin(math.radians(-20+72*n))] for n in range(5)]
    yield item('offset-odd-bolt-circle',part('boltCircle',{'count':5,'phase':-20,'radius':8,'centre':[1,-2]},{'diameter':2}),expected_volume(5,2),positions)
    positions=[[-5,-4],[6,5]]
    d=part('sketch',{'geometry':[{'id':'a','kind':'circle','centre':positions[0],'radius':2},{'id':'b','kind':'circle','centre':positions[1],'radius':3},{'id':'construction','kind':'line','start':[0,0],'end':[4,0],'construction':True}]},{'diameter':2})
    yield item('general-circular-sketch',d,expected_volume(2,2),positions)
    for count,phase,radius in [(4,0,10),(6,30,9)]:
        positions=[[radius*math.cos(math.radians(phase+360*n/count)),radius*math.sin(math.radians(phase+360*n/count))] for n in range(count)]
        yield item('bolt-circle-'+str(count),part('boltCircle',{'count':count,'phase':phase,'radius':radius},{'diameter':2.4}),expected_volume(count,2.4),positions)
    yield item('blind-flat',part(layout=grid,hole={'extent':'length','depth':5}),expected_volume(4,3,5),sample=7.5)
    tip=1.5/math.tan(math.radians(59))
    for convention in ['cylindrical','tip']:
        yield item('blind-conical-'+convention,part(layout=grid,hole={'extent':'length','depth':5,'tip':'conical','tipAngle':118,'depthMeasure':convention}),expected_volume(4,3,5,tip=tip,tip_included=convention=='tip'),sample=8)
    yield item('blind-custom-tip-angle',part(layout=grid,hole={'extent':'length','depth':4,'tip':'conical','tipAngle':90}),expected_volume(4,3,4,tip=1.5),sample=8)
    yield item('counterbore',part(layout=grid,hole={'recess':'counterbore','recessDiameter':6,'recessDepth':2}),expected_volume(4,3,recess_diameter=6,recess_depth=2))
    yield item('countersink',part(layout=grid,hole={'recess':'countersink','recessDiameter':6,'recessAngle':90}),expected_volume(4,3,recess_diameter=6,recess_angle=90))
    yield item('counterdrill',part(layout=grid,hole={'recess':'counterdrill','recessDiameter':6,'recessDepth':2,'recessAngle':90}),expected_volume(4,3,recess_diameter=6,recess_depth=2,recess_angle=90))
    d=part('holeLocations',{'centres':[[0,5],[8,5]]},{'diameter':2});d['nodes'][-2]['options']['onFace']={'face':'right'}
    yield item('side-face-drilling',d,expected_volume(2,2,30),[[0,5],[8,5]],axis='X',sample=0)
    d=part(layout=grid,hole={'direction':'forward'});d['nodes'][-2]['options'].pop('onFace');d['nodes'][-2]['options']['frame']={'origin':[0,0,0],'xAxis':[1,0,0],'normal':[0,0,1]};d['nodes'][-2]['inputs'].pop('support')
    yield item('forward-from-bottom',d,expected_volume(4,3))
    d=part('circle',{'radius':7},{'diameter':2});yield item('circle-radius-is-not-hole-diameter',d,expected_volume(1,2),[[0,0]])
    d=part(layout=grid);d['nodes'].extend([{'id':'lid','filter':'body'},{'id':'lidProfile','filter':'rectangle','options':{'width':12,'height':12,'frame':{'origin':[50,0,0],'xAxis':[1,0,0],'normal':[0,0,1]}},'inputs':{'body':'lid'}},{'id':'lidSolid','filter':'pad','options':{'length':2},'inputs':{'body':'lid','profile':'lidProfile'}},{'id':'bossProfile','filter':'circle','options':{'radius':3,'onFace':{'face':'top'}},'inputs':{'body':'body','support':'holes'}},{'id':'boss','filter':'pad','options':{'length':2},'inputs':{'body':'body','base':'holes','profile':'bossProfile'}}]);d['output']='boss'
    yield 'multiple-bodies-and-followup-pad',d,{'volume':expected_volume(4,3)+18*math.pi,'positions':centres,'axis':'Z','voidSample':5,'diameter':3}
    positions=[[-8,-5],[-8,5]];d=part('holeLocations',{'centres':positions},{'diameter':2});d['nodes'].append({'id':'repeated','filter':'linearPattern','options':{'direction':'X','length':16,'count':3},'inputs':{'base':'holes','feature':'holes'}});d['output']='repeated'
    yield 'pattern-native-hole',d,{'volume':expected_volume(6,2),'positions':[[x,y] for x in [-8,0,8] for y in [-5,5]],'axis':'Z','voidSample':5,'diameter':2}

    d=part('holeLocations',{'centres':[[0,0]]},{'diameter':2});o=d['nodes'][-2]['options'];o.pop('onFace');o['frame']={'origin':[15,0,25],'xAxis':[0,1,0],'normal':[math.sqrt(.5),0,math.sqrt(.5)]};d['nodes'][-2]['inputs'].pop('support')
    yield 'oblique-explicit-frame',d,{'volume':9000-10*math.pi/math.sqrt(.5),'diameter':2,'axis':'oblique','lineOrigin':[0,0,10],'direction':[math.sqrt(.5),0,math.sqrt(.5)],'voidPoints':[[-5,0,5]]}


def driven_grid():
    d=part(layout={'columns':2,'rows':2,'yPitch':14},hole={'recess':'counterbore','recessDiameter':6})
    d['parameters']={k:{'kind':'length','value':v,'minimum':a,'maximum':b} for k,v,a,b in [('pitch',16,12,20),('drill',3,2,4),('headDepth',2,1,3.5)]}
    d['nodes'][-2]['drive']={'xPitch':{'terms':{'pitch':1}}};d['nodes'][-1]['options'].pop('diameter');d['nodes'][-1]['drive']={'diameter':{'terms':{'drill':1}},'recessDepth':{'terms':{'headDepth':1}}}
    return d
