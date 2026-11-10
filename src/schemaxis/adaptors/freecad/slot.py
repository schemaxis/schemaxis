"""Capsule slot intent lowered into named, fully constrained native geometry."""
import math

def geometry(options):
    length,r=options['length'],options['radius'];half=length/2
    return [{'kind':'line','start':[-half,r],'end':[half,r],'construction':False},
        {'kind':'arc','centre':[half,0],'radius':r,'startAngle':-90,'endAngle':90,'construction':False},
        {'kind':'line','start':[half,-r],'end':[-half,-r],'construction':False},
        {'kind':'arc','centre':[-half,0],'radius':r,'startAngle':90,'endAngle':270,'construction':False}]


def constraints(options):
    def c(kind,first,value=0,name='',firstPos=0,second=-2000,secondPos=0):
        return {'name':name,'type':kind,'value':value,'first':first,'firstPos':firstPos,'second':second,'secondPos':secondPos,'third':-2000,'thirdPos':0}
    return [c('Tangent',0,math.pi/2,firstPos=2,second=1,secondPos=2),c('Tangent',1,math.pi/2,firstPos=1,second=2,secondPos=1),
        c('Tangent',2,math.pi/2,firstPos=2,second=3,secondPos=2),c('Tangent',3,math.pi/2,firstPos=1,second=0,secondPos=1),
        c('Horizontal',0),c('Equal',1,second=3),c('Distance',0,options['length'],'span'),c('Radius',1,options['radius'],'radius'),
        c('DistanceX',0,-options['length']/2,'anchorX',firstPos=1),c('DistanceY',1,0,'centreY',firstPos=3)]
