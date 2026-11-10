"""Independent sweep control solids and an attached, editable flanged elbow."""
import math

BEND_FRAME={'origin':[0,0,0],'xAxis':[-1,0,0],'normal':[0,1,0]}


def elbow(options=None,*,hollow=True,angle=90,radius=10,section=3):
    nodes=[{'id':'body','filter':'body'},
        {'id':'outer','filter':'circle','options':{'radius':section},'inputs':{'body':'body'}},
        {'id':'bend','filter':'arcPath','options':{'frame':BEND_FRAME,'bendRadius':radius,'sweepAngle':angle},'inputs':{'body':'body'}},
        {'id':'stock','filter':'additivePipe','options':options or {},'inputs':{'body':'body','profile':'outer','spine':'bend'}}]
    if hollow:nodes.extend([{'id':'inner','filter':'circle','options':{'radius':2},'inputs':{'body':'body'}},
        {'id':'tube','filter':'subtractivePipe','options':options or {},'inputs':{'body':'body','base':'stock','profile':'inner','spine':'bend'}}])
    return {'version':'schemaxis.freecad/1','units':'mm','nodes':nodes,'output':'tube' if hollow else 'stock'}


def elbow_integrals(bend=10,outer=3,inner=2,angle=90,flange=0,length=0):
    theta=math.radians(angle);volume=math.pi*(outer*outer-inner*inner)*bend*theta
    mean_radius=bend+(outer*outer+inner*inner)/(4*bend)
    centre=[bend-mean_radius*math.sin(theta)/theta,0,mean_radius*(1-math.cos(theta))/theta]
    if length:
        assert angle==90
        each=math.pi*(flange*flange-inner*inner)*length
        centre=[(volume*centre[0]+each*(bend+length/2))/(volume+2*each),0,
            (volume*centre[2]+each*(bend-length/2))/(volume+2*each)]
        volume+=2*each
    return {'volume':volume,'centre':centre,'bend':bend,'outer':outer,'inner':inner,'angle':angle,'flange':flange,'length':length,'shape':'elbow'}


def flanged():
    document=elbow();document['parameters']={key:{'kind':'length','value':value,'minimum':lo,'maximum':hi} for key,value,lo,hi in [('bendRadius',10,8,15),('outerRadius',3,2.5,3.5),('wall',1,.5,1.5),('flangeRadius',5,4.5,6),('flangeLength',5,3,7)]}
    for identity,field,terms in [('bend','bendRadius',{'bendRadius':1}),('outer','radius',{'outerRadius':1}),('inner','radius',{'outerRadius':1,'wall':-1})]:
        node=next(n for n in document['nodes'] if n['id']==identity);node.get('options',{}).pop(field,None);node['drive']={field:{'terms':terms}}
    base='tube'
    for prefix,face in [('outlet','right'),('inlet','bottom')]:
        p=prefix+'Profile';pad=prefix+'Stock';bore=prefix+'Bore';done=prefix+'Finished'
        document['nodes'].extend([
            {'id':p,'filter':'circle','options':{'onFace':{'face':face,'anchor':'centroid'}},'inputs':{'body':'body','support':base},'drive':{'radius':{'terms':{'flangeRadius':1}}}},
            {'id':pad,'filter':'pad','inputs':{'body':'body','base':base,'profile':p},'drive':{'length':{'terms':{'flangeLength':1}}}},
            {'id':bore,'filter':'holeLocations','options':{'centres':[[0,0]],'onFace':{'face':face,'anchor':'centroid'}},'inputs':{'body':'body','support':pad}},
            {'id':done,'filter':'hole','options':{'extent':'length'},'inputs':{'body':'body','base':pad,'profile':bore},'drive':{'depth':{'terms':{'flangeLength':1}},'diameter':{'terms':{'outerRadius':2,'wall':-2}}}}])
        base=done
    document['output']=base;return document


def straight(options=None,*,oblique=False,multisection=False,subtractive=False):
    nodes=[{'id':'body','filter':'body'},{'id':'profile','filter':'circle','options':{'radius':2},'inputs':{'body':'body'}},
        {'id':'spine','filter':'sketch','options':{'plane':'XZ','geometry':[{'id':'path','kind':'line','start':[0,0],'end':[10 if oblique else 0,20]}]},'inputs':{'body':'body'}}]
    inputs={'body':'body','profile':'profile','spine':'spine'}
    if subtractive:
        nodes[1:1]=[{'id':'blankProfile','filter':'circle','options':{'radius':5},'inputs':{'body':'body'}},
            {'id':'blank','filter':'pad','options':{'length':20},'inputs':{'body':'body','profile':'blankProfile'}}];inputs['base']='blank'
    if multisection:
        nodes.append({'id':'end','filter':'circle','options':{'radius':3,'origin':[0,0,20]},'inputs':{'body':'body'}});inputs['sections']=['end']
    nodes.append({'id':'finished','filter':'subtractivePipe' if subtractive else 'additivePipe','options':options or {},'inputs':inputs})
    return {'version':'schemaxis.freecad/1','units':'mm','nodes':nodes,'output':'finished'}


def cases():
    for mode in ['normal','frenet','binormal']:
        options={'orientation':mode,**({'binormal':[0,1,0]} if mode=='binormal' else {})}
        yield 'hollow-'+mode,elbow(options),elbow_integrals()
    for angle in [60,210,359]:yield 'bend-'+str(angle),elbow(angle=angle),elbow_integrals(angle=angle)
    for equivalence in [True,False]:
        d=elbow({'orientation':'auxiliary','auxiliaryEquivalence':equivalence})
        d['nodes'].insert(3,{'id':'guide','filter':'arcPath','options':{'frame':{**BEND_FRAME,'origin':[0,5,0]}},'inputs':{'body':'body'}})
        for n in d['nodes']:
            if n['filter'].endswith('Pipe'):n['inputs']['auxiliary']='guide'
        yield 'auxiliary-'+str(equivalence).lower(),d,elbow_integrals()
    d=elbow({'orientation':'binormal','binormal':[0,1,0]},hollow=False)
    d['nodes'][1]['options']={'width':4,'height':2};d['nodes'][1]['filter']='rectangle'
    yield 'rectangular-binormal',d,{'volume':40*math.pi,'centre':[10-(10+4/30)*2/math.pi,0,(10+4/30)*2/math.pi],'shape':'rectangular-elbow'}
    yield 'fixed-oblique',straight({'orientation':'fixed'},oblique=True),{'volume':80*math.pi,'centre':[5,0,10],'shape':'oblique','radius':2}
    yield 'multisection',straight(multisection=True),{'volume':380*math.pi/3,'centre':[0,0,20*43/76],'shape':'cone','outer':False}
    yield 'subtractive-multisection',straight(multisection=True,subtractive=True),{'volume':(500-380/3)*math.pi,'centre':[0,0,(500*10-380/3*20*43/76)/(500-380/3)],'shape':'cone','outer':True}
    d=elbow(hollow=False);d['nodes'][2]={'id':'bend','filter':'sketch','options':{'frame':BEND_FRAME,'geometry':[{'id':'loop','kind':'circle','centre':[-10,0],'radius':10}]},'inputs':{'body':'body'}}
    yield 'closed-ring',d,{'volume':180*math.pi**2,'centre':[10,0,0],'shape':'ring','bend':10,'outer':3}
    yield 'flanged-elbow',flanged(),elbow_integrals(flange=5,length=5)
    for transition in ['miter','rounded']:yield 'smooth-'+transition,elbow({'transition':transition}),elbow_integrals()
    d=straight({'transition':'miter'});d['nodes'][2]['options']['geometry'].append({'id':'second','kind':'line','start':[0,20],'end':[20,20]})
    # Split at x+z=L. Each leg has V=A*L and disc second moment I=A*r²/4;
    # combined moments are Mx=A*L²/2-3I/2, Mz=3A*L²/2+3I/2.
    yield 'mitered-corner',d,{'volume':160*math.pi,'centre':[5-3*4/320,0,15+3*4/320],'shape':'miter'}
    d=elbow(hollow=False);d['nodes'][1]['filter']='sketch';d['nodes'][1]['options']={'geometry':[{'id':'outside','kind':'circle','centre':[0,0],'radius':3},{'id':'inside','kind':'circle','centre':[0,0],'radius':2}]}
    yield 'annular-section',d,elbow_integrals()
    d=elbow({'orientation':'binormal','binormal':[0,0,1]})
    for n in d['nodes']:
        if n['filter']=='circle':n['options']['frame']={'origin':[20,30,40],'xAxis':[0,1,0],'normal':[1,0,0]}
        elif n['filter']=='arcPath':n['options']['frame']={'origin':[20,30,40],'xAxis':[0,-1,0],'normal':[0,0,1]}
    expected=elbow_integrals();x,y,z=expected['centre'];expected['centre']=[20+z,30+x,40+y];expected['pose']='cycled'
    yield 'rotated-binormal',d,expected
    for equivalence in [True,False]:
        coarse=guide_integrals(equivalence,256);fine=guide_integrals(equivalence,512)
        assert abs(coarse['volume']-fine['volume'])<1e-8
        assert all(abs(a-b)<1e-8 for a,b in zip(coarse['centre'],fine['centre']))
        yield 'curved-guide-'+str(equivalence).lower(),guided(equivalence),fine


def guided(equivalence):
    d=straight({'orientation':'auxiliary','auxiliaryEquivalence':equivalence});d['linearDeflection']=.01
    d['nodes'][1].update(filter='rectangle',options={'width':4,'height':1});r=40/math.sqrt(3);u=1/math.sqrt(2)
    d['nodes'].insert(3,{'id':'guide','filter':'sketch','options':{'frame':{'origin':[5,0,0],'xAxis':[-u,u,0],'normal':[u,u,0]},'geometry':[{'id':'curvedGuide','kind':'arc','centre':[-r,0],'radius':r,'startAngle':0,'endAngle':60}]},'inputs':{'body':'body'}})
    d['nodes'][-1]['inputs']['auxiliary']='guide';return d


def guide_frame(t,equivalence):
    # Independent straight-spine/curved-guide geometry. Arc-length matching
    # generally inclines the transported section: N is not perpendicular to Z.
    theta=math.pi/3;r=40/math.sqrt(3)
    phi=t*theta if equivalence else math.asin(t*math.sin(theta))
    rate=theta if equivalence else math.sin(theta)/math.sqrt(1-(t*math.sin(theta))**2)
    q=r*(1-math.cos(phi))/math.sqrt(2);dq=r*math.sin(phi)*rate/math.sqrt(2)
    n=[5+q,-q,r*math.sin(phi)-20*t];dn=[dq,-dq,r*math.cos(phi)*rate-20]
    h=math.hypot(*n[:2]);dh=sum(a*b for a,b in zip(n[:2],dn[:2]))/h
    length=math.hypot(*n);dl=sum(a*b for a,b in zip(n,dn))/length
    x=[a/length for a in n];dx=[a/length-b*dl/length**2 for a,b in zip(dn,n)]
    y=[-n[1]/h,n[0]/h,0];dy=[-dn[1]/h+n[1]*dh/h**2,dn[0]/h-n[0]*dh/h**2,0]
    z=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    return x,y,z,dx,dy


def guide_integrals(equivalence,intervals=512):
    # r(t,u,v)=P(t)+uX(t)+vY(t), |u|<=2, |v|<=.5.
    # J=Zsection dot (P'+uX'+vY'). Odd section moments vanish;
    # Iu=A*4²/12=16/3, Iv=A*1²/12=1/3. No Pipe output is used.
    def values(t):
        x,y,z,dx,dy=guide_frame(t,equivalence);j0=20*z[2];ju=sum(a*b for a,b in zip(z,dx));jv=sum(a*b for a,b in zip(z,dy))
        return [4*j0]+[4*(20*t if k==2 else 0)*j0+16/3*x[k]*ju+1/3*y[k]*jv for k in range(3)]
    rows=[values(i/intervals) for i in range(intervals+1)];totals=[sum((1 if i in (0,intervals) else 4 if i%2 else 2)*row[k] for i,row in enumerate(rows))/(3*intervals) for k in range(4)]
    return {'volume':totals[0],'centre':[v/totals[0] for v in totals[1:]],'shape':'guided','equivalence':equivalence}
