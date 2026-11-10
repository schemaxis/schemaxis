"""Independent analytic feature-family cases for FreeCAD history qualification."""
import math

def body(i='body'):return {'id':i,'filter':'body'}
def rect(i='stock',b='body',**o):return {'id':i,'filter':'rectangle','options':{'width':40,'height':30,**o},'inputs':{'body':b}}
def circle(i,b='body',**o):return {'id':i,'filter':'circle','options':{'radius':3,**o},'inputs':{'body':b}}
def pad(p='stock',i='plate',b='body',base=None,**o):return {'id':i,'filter':'pad','options':{'length':10,**o},'inputs':{'body':b,'profile':p,**({'base':base} if base else {})}}
def doc(nodes):return {'version':'schemaxis.freecad/1','nodes':nodes,'output':nodes[-1]['id']}
CASES={}
CASES['multiBody']=doc([body('first'),rect('s1','first'),pad('s1','f1','first'),body('second'),circle('s2','second',origin=[50,0,0]),pad('s2','f2','second')])
CASES['polygon']=doc([body(),{'id':'p','filter':'polygon','options':{'points':[[0,0],[10,0],[10,4],[4,4],[4,10],[0,10]],'origin':[0,0,2]},'inputs':{'body':'body'}},pad('p')])
CASES['obliqueFrame']=doc([body(),rect(frame={'origin':[3,4,5],'xAxis':[0,1,0],'normal':[1,0,0]}),pad(direction='symmetric')])
CASES['fixedSketch']=doc([body(),{'id':'s','filter':'sketch','options':{'geometry':[{'id':'outer','kind':'circle','centre':[0,0],'radius':8},{'id':'inner','kind':'circle','centre':[0,0],'radius':3}]},'inputs':{'body':'body'}},pad('s')])
CASES['solveSketch']=doc([body(),{'id':'s','filter':'sketch','options':{'geometry':[{'id':'outer','kind':'circle','centre':[2,3],'radius':8}], 'constraintMode':'solve','constraints':[
 {'id':'x','kind':'distanceX','first':{'geometry':'outer','point':'centre'},'value':2},
 {'id':'y','kind':'distanceY','first':{'geometry':'outer','point':'centre'},'value':3},
 {'id':'r','kind':'radius','first':{'geometry':'outer'},'value':8}]},'inputs':{'body':'body'}},pad('s')])
for k in ['bodyFillet','bodyChamfer']:
 CASES[k]=doc([body(),rect(),pad(),{'id':'finish','filter':k,'options':{'edges':{'where':{'parallelTo':[0,0,1]},'expect':4}},'inputs':{'base':'plate'}}])
for k in ['linearPattern','polarPattern','mirror']:
 nodes=[body(),rect(),pad(),circle('hole',centre=[8,0],origin=[0,0,10]),{'id':'cut','filter':'pocket','options':{'direction':'backward'},'inputs':{'base':'plate','profile':'hole'}}]
 options={'linearPattern':{'length':8,'count':2,'direction':'Y'},'polarPattern':{'angle':360,'count':4,'axis':'Z'},'mirror':{'plane':'YZ'}}[k]
 CASES[k]=doc(nodes+[{'id':'pattern','filter':k,'options':options,'inputs':{'base':'cut','feature':'cut'}}])
CASES['bodyRevolve']=doc([body(),{'id':'p','filter':'polygon','options':{'points':[[2,0],[6,0],[6,10],[2,10]],'plane':'XZ'},'inputs':{'body':'body'}},{'id':'revolved','filter':'bodyRevolve','inputs':{'body':'body','profile':'p'}}])
CASES['additiveLoft']=doc([body(),circle('bottom',radius=5),circle('top',radius=8,origin=[0,0,10]),{'id':'loft','filter':'additiveLoft','options':{'ruled':True},'inputs':{'body':'body','sections':['bottom','top']}}])
CASES['groove']=doc([body(),circle('bottom',radius=8),pad('bottom'),{'id':'grooveProfile','filter':'polygon','options':{'points':[[6,4],[9,4],[9,6],[6,6]],'plane':'XZ'},'inputs':{'body':'body'}},{'id':'grooved','filter':'groove','inputs':{'body':'body','base':'plate','profile':'grooveProfile'}}])
CASES['subtractiveLoft']=doc([body(),rect(),pad(),circle('bottom',radius=3),circle('top',radius=5,origin=[0,0,10]),{'id':'loft','filter':'subtractiveLoft','options':{'ruled':True},'inputs':{'body':'body','base':'plate','sections':['bottom','top']}}])
expected={'multiBody':90*math.pi,'polygon':640,'obliqueFrame':12000,'fixedSketch':550*math.pi,'solveSketch':640*math.pi,'bodyFillet':11960+10*math.pi,'bodyChamfer':11980,'linearPattern':12000-180*math.pi,'polarPattern':12000-360*math.pi,'mirror':12000-180*math.pi,'bodyRevolve':320*math.pi,'additiveLoft':430*math.pi,'groove':584*math.pi,'subtractiveLoft':12000-490*math.pi/3}
CASES['slot']=doc([body(),{'id':'slotProfile','filter':'slot','options':{'length':10,'radius':2},'inputs':{'body':'body'}},pad('slotProfile')]);expected['slot']=400+40*math.pi
CASES['datumRevolve']=doc([body(),{'id':'axis','filter':'datumAxis','options':{'origin':[10,0,0],'direction':[0,0,1]},'inputs':{'body':'body'}},{'id':'p','filter':'polygon','options':{'points':[[12,0],[16,0],[16,10],[12,10]],'plane':'XZ'},'inputs':{'body':'body'}},{'id':'turned','filter':'bodyRevolve','inputs':{'body':'body','profile':'p','axis':'axis'}}]);expected['datumRevolve']=320*math.pi
CASES['standaloneSketch']=doc([{'id':'sketch','filter':'sketch','options':{'geometry':[{'id':'c','kind':'circle','centre':[1,2],'radius':3}]}},{'id':'solid','filter':'extrude','inputs':{'profile':'sketch'}}]);expected['standaloneSketch']=90*math.pi


def cases():
    return [(identity,document,expected[identity]) for identity,document in CASES.items()]
