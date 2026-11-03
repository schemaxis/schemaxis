# Copyright (C) 2026 David L F Gaden
"""Bracketed search for one CAD length controlling one named scalar quantity."""
import copy
import json
import math
from pathlib import Path
from schemaxis import feedback
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from .measurements import QUANTITIES

LENGTH_CONTROLS = {'box':('length','width','height'), 'cylinder':('radius','height'),
    'sphere':('radius',), 'cone':('radius1','radius2','height'), 'torus':('majorRadius','minorRadius'),
    'rectangle':('width','height'), 'circle':('radius',), 'extrude':('length',),
    'fillet':('radius',), 'chamfer':('distance',)}
SCALARS = ('volume','surfaceArea','extentX','extentY','extentZ','totalEdgeLength')
ARGUMENTS = {
    'parameter':{'type':'object','required':True,'properties':{
        'node':{'type':'string','required':True},'option':{'type':'string','required':True},
        'minimum':{'type':'number','required':True},'maximum':{'type':'number','required':True}}},
    'target':{'type':'object','required':True,'properties':{
        'measurement':{'type':'string','required':True},'value':{'type':'number','required':True},
        'tolerance':{'type':'number','minimum':0,'exclusiveMinimum':True,'required':True},
        'units':{'type':'enum','values':['mm','mm^2','mm^3'],'required':True}}},
    'response':{'type':'enum','values':['increasing','decreasing'],'required':True},
    'maxIterations':{'type':'integer','minimum':2,'maximum':20,'default':12},
    'minimumStep':{'type':'number','minimum':1e-9,'maximum':1000,'default':1e-6}}


def prepare(raw, document, prepared):
    keys(raw,tuple(ARGUMENTS),'$.designStudy')
    settings=validate_arguments(ARGUMENTS,raw,location='$.designStudy')
    parameter=settings['parameter'];nodes={n['id']:n for n in prepared['nodes']}
    node=nodes.get(parameter['node'])
    if node is None or parameter['option'] not in LENGTH_CONTROLS.get(node['filter'],()):
        fail('INVALID_STUDY','control one supported scalar CAD length option','$.designStudy.parameter')
    if parameter['minimum']>=parameter['maximum']:
        fail('INVALID_STUDY','parameter bounds must be strictly increasing','$.designStudy.parameter')
    measurements={m['id']:m for m in prepared.get('measurements',[])}
    selected=measurements.get(settings['target']['measurement'])
    if selected is None or selected['quantity'] not in SCALARS:
        fail('INVALID_STUDY','target a declared scalar geometric measurement','$.designStudy.target')
    if settings['target']['units']!=QUANTITIES[selected['quantity']]:
        fail('UNIT_MISMATCH','target units must equal the named measurement units','$.designStudy.target.units')
    from .adaptor import _native_plan
    base=copy.deepcopy(document);base.pop('designStudy')
    for bound in ('minimum','maximum'):
        for candidate in base['nodes']:
            if candidate['id']==parameter['node']:
                candidate.setdefault('options',{})[parameter['option']]=parameter[bound]
        _native_plan(base)
    return settings


class Policy:
    def __init__(self,document):
        from .adaptor import _native_plan
        self.settings=_native_plan(document)['designStudy'];self.limit=self.settings['maxIterations']
        self.base=copy.deepcopy(document);self.base.pop('designStudy')
        self.direction=1 if self.settings['response']=='increasing' else -1

    def describe(self):
        return {'name':'freecad.bracketed-dimension/1',**self.settings,'parameterUnits':'mm',
            'limitations':['one resolved scalar option changes; other resolved inputs stay fixed',
                'declared response direction is checked only at sampled candidates, not proven globally',
                'native invalidity is an execution fault, not an acceptable search sample',
                'first tested candidate inside the target band; no global optimum claim']}

    def coordinate(self,candidate):
        control=self.settings['parameter']
        return next(n for n in candidate['nodes'] if n['id']==control['node'])['options'][control['option']]

    def samples(self,history):
        return sorted((self.coordinate(h['document']),h['observation']['value']) for h in history)

    def bracket(self,history):
        target=self.settings['target']['value'];samples=self.samples(history)
        below=[x for x,y in samples if self.direction*(y-target)<0]
        above=[x for x,y in samples if self.direction*(y-target)>0]
        return (max(below),min(above)) if below and above else None

    def propose(self,history):
        control=self.settings['parameter']
        if len(history)<2:coordinate=control['minimum' if not history else 'maximum']
        else:
            bounds=self.bracket(history)
            if bounds is None or bounds[1]-bounds[0]<=self.settings['minimumStep']:return None
            coordinate=bounds[0]/2+bounds[1]/2
            if coordinate in bounds:return None
        candidate=copy.deepcopy(self.base)
        for node in candidate['nodes']:
            if node['id']==control['node']:node.setdefault('options',{})[control['option']]=coordinate
        return candidate

    def judge(self,candidate,observation,history):
        target=self.settings['target'];value=observation['value'];tolerance=target['tolerance']
        if type(value) not in (int,float) or not math.isfinite(value) or observation['units']!=target['units']:
            fail('INVALID_MEASUREMENT','design target observation has wrong type or units')
        if history and observation['sources']!=history[0]['observation']['sources']:
            fail('INPUT_CHANGED','CAD sources changed between design candidates')
        samples=self.samples(history)+[(self.coordinate(candidate),value)];samples.sort()
        minimum_delta=min((self.direction*(b[1]-a[1]) for a,b in zip(samples,samples[1:])),default=0)
        checks=[{'requirement':target['measurement']+' lower bound','observed':value,'relation':'>=',
                 'requested':target['value']-tolerance,'units':target['units'],'passed':value>=target['value']-tolerance},
                {'requirement':target['measurement']+' upper bound','observed':value,'relation':'<=',
                 'requested':target['value']+tolerance,'units':target['units'],'passed':value<=target['value']+tolerance},
                {'requirement':'sampled response direction','observed':minimum_delta,'relation':'>=',
                 'requested':-tolerance,'units':target['units'],'passed':minimum_delta>=-tolerance}]
        accepted=all(c['passed'] for c in checks);stop=None
        if not checks[-1]['passed']:stop='response_assumption_violated'
        elif not accepted and history:
            errors=[self.direction*(y-target['value']) for _,y in samples]
            if not min(errors)<0<max(errors):stop='target_not_bracketed'
        return {'accepted':accepted,'checks':checks,'stop':stop}


def observe(directory):
    authored=json.loads((directory.parent/'authored.json').read_text())
    target=authored['designStudy']['target']['measurement']
    payload=json.loads((directory/'measurements.json').read_text())
    quantity=payload['measurements'][target]
    sources=json.loads((directory/'sources.json').read_text())
    return {**quantity,'sources':{key:{'file':v['file'],'sha256':v['sha256']} for key,v in sources.items()}}


def require_accepted(result,directory):
    if not result['accepted']:
        fail('STUDY_REQUIREMENTS_NOT_MET','no CAD candidate met the declared target; inspect study-summary.json',str(directory),
             reason=result['reason'],attempts=result['attempts'])
    return result


def run(document,directory,*,executable,timeout):
    from .adaptor import _native_run,_native_verify
    result=feedback.run(document,directory,Policy(document),
        lambda d,p,**options:_native_run(d,p,executable=executable,**options),_native_verify,observe,timeout=timeout)
    return {**require_accepted(result,directory),'status':'succeeded'}


def verify(directory,*,require_acceptance=True):
    from .adaptor import _native_verify
    directory=Path(directory).absolute();document=json.loads((directory/'authored.json').read_text())
    result=feedback.verify(directory,document,Policy(document),_native_verify,observe)
    return require_accepted(result,directory) if require_acceptance else result
