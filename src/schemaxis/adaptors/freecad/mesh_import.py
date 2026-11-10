"""Explicit STL units, winding and frame for a checked faceted Part solid."""
from . import mesh_source,step_source
from .step_import import AXIS,MAX_COORDINATE,orientation,clocking_rotation,multiply


def declaration(declare):
    return declare('Part::Feature',{
        'file':{'type':'string','minLength':1,'maxLength':4096,'required':True},
        'units':{'type':'enum','values':list(step_source.UNITS),'required':True},
        'reverseWinding':{'type':'boolean','default':False},
        'orientation':{'type':'object','default':{'z':'+Z'},'properties':{'z':{**AXIS,'default':'+Z'},'x':AXIS}},
        'placement':{'type':'object','default':{'position':[0,0,0],'clocking':0},'properties':{
            'position':{'type':'array','items':{'type':'number','minimum':-MAX_COORDINATE,'maximum':MAX_COORDINATE},
                        'minItems':3,'maxItems':3,'default':[0,0,0]},
            'clocking':{'type':'number','minimum':-360,'maximum':360,'default':0}}},
        'refine':{'type':'boolean','default':False}})


def geometry(data, options, location):
    return mesh_source.admit(data,location,scale=step_source.MILLIMETRES[options['units']],reverse=options['reverseWinding'])


def prepare(identity, options, provider):
    location=identity+'.options';normalised,part_from_file=orientation(options['orientation'],location+'.orientation')
    options['orientation']=normalised;rotation=clocking_rotation(options['placement']['clocking'])
    frame={'partFromFile':part_from_file,'worldFromPart':rotation,'worldFromFile':multiply(rotation,part_from_file),
           'translation':[float(v) for v in options['placement']['position']]}
    provider=provider or step_source.AuthoredSources()
    if getattr(provider,'reads',True) is False:return {'frame':frame}
    path,data=provider.read(options['file'],identity,location+'.file')
    facts,_,_=geometry(data,options,location+'.file')
    return {'frame':frame,'source':{'path':path,**facts}}
