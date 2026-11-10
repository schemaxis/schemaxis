"""Independent uniform-wall control geometries and cross-family enclosure."""
import math


def part(options=None,circle=False):
    return {'version':'schemaxis.freecad/1','units':'mm','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'circle' if circle else 'rectangle','options':{'radius':10} if circle else {'width':40,'height':30},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':20},'inputs':{'body':'body','profile':'outline'}},
        {'id':'housing','filter':'shell','options':{'thickness':3,'openings':[{'face':'top'}],**(options or {})},'inputs':{'base':'stock'}}], 'output':'housing'}


def cases():
    for side,corners,expected,moment in [('inward','sharp',10128,80472),('inward','rounded',10128,80472),
        ('outward','sharp',14088,83748),('outward','rounded',12000+513*math.pi,77340+1779.75*math.pi)]:
        # Rounded outward offset: vertical rounded rectangle plus five-side
        # bottom offset. Sphere/cylinder contributions integrate exactly.
        yield side+'-'+corners,part({'side':side,'corners':corners}),{'volume':expected,'centre':[0,0,moment/expected],'side':side,'corners':corners,'axis':'Z','openings':1,'thickness':3}
    yield 'intersection-handling',part({'intersectionHandling':True}),{'volume':10128,'centre':[0,0,80472/10128],'side':'inward','corners':'sharp','axis':'Z','openings':1,'thickness':3}
    yield 'through-tube',part({'openings':[{'face':'top'},{'face':'bottom'}]}),{'volume':7680,'centre':[0,0,10],'side':'inward','corners':'sharp','axis':'Z','openings':2,'thickness':3}
    yield 'side-opening',part({'openings':[{'face':'right'}]}),{'volume':24000-37*24*14,'centre':[-18648/11568,0,10],'side':'inward','corners':'sharp','axis':'X','openings':1,'thickness':3}
    yield 'cylindrical-cup',part(circle=True),{'volume':(2000-49*17)*math.pi,'centre':[0,0,10420.5/1167],'side':'inward','corners':'sharp','axis':'Z','openings':1,'thickness':3,'cylindrical':True}
