# Copyright (C) 2026 David L F Gaden
"""Read the persisted Body history independently of native object readback."""
from . import part_design as policy
from .document_xml import Document, ARCHIVE_ERRORS
from schemaxis.errors import fail


def observation(prepared,xml):
    mapped=policy.names(prepared);record=prepared['partDesign'];body=mapped[record['body']]
    origin=xml.link(body,'Origin')
    aux={'container':{'name':origin,'type':xml.types[origin]}}
    for name in xml.links(origin,'OriginFeatures'):
        role=xml.string(name,'Role')
        if role in aux:raise ValueError('duplicate origin role')
        aux[role]={'name':name,'type':xml.types[name]}
    extra=policy.verify_auxiliaries(prepared,aux)
    from .adaptor import DECLARATIONS
    expected={mapped[n['id']]:DECLARATIONS[n['filter']]['native'] for n in prepared['nodes']}
    expected.update(extra)
    if 'parameters' in prepared:expected['SchemaxisParameters']='App::VarSet'
    if xml.types!=expected:raise ValueError('saved Body object membership/type differs')
    result={'body':{'name':body,'type':xml.types[body],'label':xml.string(body,'Label'),
                   'group':xml.links(body,'Group'),'tip':xml.link(body,'Tip'),
                   'baseFeature':xml.link(body,'BaseFeature'),'origin':origin},
            'auxiliaries':aux,'profiles':{},'features':{},'expressions':{name:xml.engine(name) for name in expected},
            'visibility':{name:xml.boolean(name,'Visibility') for name in expected}}
    def enum(name,prop,index,label):
        item=xml.child(name,prop,'Integer','App::PropertyEnumeration')
        if item.attrib['value']!=str(index):raise ValueError('saved enum differs: '+name+'.'+prop)
        return label
    def identity(name,prop):
        item=xml.child(name,prop,'PropertyPlacement','App::PropertyPlacement')
        if any(float(item.attrib[k])!=v for k,v in {'Px':0,'Py':0,'Pz':0,'Q0':0,'Q1':0,'Q2':0,'Q3':1}.items()):
            raise ValueError('saved Body sketch placement differs')
        return policy.IDENTITY
    result['body']['placement']=identity(body,'Placement')
    for node in prepared['nodes']:
        if node['id'] not in record['members']:continue
        name=mapped[node['id']]
        if name not in result['body']['group']:raise ValueError('saved feature is outside Body group')
        if node['filter'] in ('rectangle','circle'):
            support=xml.child(name,'AttachmentSupport','LinkSubList','App::PropertyLinkSubList')
            if len(support)!=1 or support[0].tag!='Link' or support.get('count')!='1':raise ValueError('saved sketch support differs')
            result['profiles'][node['id']]={'owner':body,'mapMode':enum(name,'MapMode',5,'FlatFace'),
                'support':[[support[0].attrib['obj'],[support[0].attrib['sub']]]],
                'offset':identity(name,'AttachmentOffset'),'placement':identity(name,'Placement'),
                'fullyConstrained':xml.boolean(name,'FullyConstrained'),'constraints':xml.constraints(name)}
        else:
            profile=xml.child(name,'Profile','LinkSub','App::PropertyLinkSub')
            if len(profile) or profile.get('count')!='0':raise ValueError('saved profile subelement differs')
            pad=node['filter']=='pad'
            result['features'][node['id']]={'owner':body,'profile':[profile.attrib['value'],[]],
                'baseFeature':xml.link(name,'BaseFeature'),'type':enum(name,'Type',0 if pad else 1,'Length' if pad else 'ThroughAll'),
                'sideType':enum(name,'SideType',0,'One side'),'reversed':xml.boolean(name,'Reversed'),
                'alongSketchNormal':xml.boolean(name,'AlongSketchNormal'),'customVector':xml.boolean(name,'UseCustomVector'),
                'refine':xml.boolean(name,'Refine')}
            if pad:result['features'][node['id']]['length']=xml.number(name,'Length')
    policy.verify_observation(prepared,result,saved=True)
    return result


def verify(prepared,path):
    try:
        result=observation(prepared,Document(path))
        from .gui_state import verify as verify_gui
        verify_gui(path,result['visibility'])
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError,*ARCHIVE_ERRORS) as error:
        fail('VERIFICATION_FAILED','Saved PartDesign history is malformed',str(path),detail=str(error))
