"""Bounded semantic graph construction for artist surface expressions."""
import json,math
from collections import namedtuple

Port=namedtuple('Port','node socket')


class Graph:
    def __init__(self,surface,images):
        self.surface=surface;self.nodes=[];self.links=[]
        self.samplers={s['id']:s for s in surface['samplers']}
        self.images={image['id']:image for image in images}
        self.cache={};self.outputs={}

    def node(self,kind,values=None,properties=None):
        identifier='n'+str(len(self.nodes))
        node={'id':identifier,'kind':kind,'values':values or {},'properties':properties or {}}
        self.nodes.append(node);return node

    def bind(self,node,key,value):
        if isinstance(value,Port):
            self.links.append({'from':value._asdict(),'to':{'node':node['id'],'socket':key}})
        else:node['values'][key]=value

    def output(self,node,socket):return Port(node['id'],socket)

    def scale(self,value,factor):
        if not isinstance(value,Port):return value*factor
        if factor==1:return value
        node=self.node('math',{'b':factor},{'operation':'MULTIPLY'})
        self.bind(node,'a',value);return self.output(node,'value')

    def coordinates(self,sampler):
        intent=sampler['coordinates'];key=('coordinates',json.dumps(intent,sort_keys=True))
        if key in self.cache:return self.cache[key]
        if intent['kind']=='uv':
            uv=intent['set'];node=self.node('uvMap',properties={'name':uv.get('name','')});port=self.output(node,'uv')
            transform=intent['transform'];translation=[*transform['offset'],0]
            rotation=[0,0,math.radians(transform['rotationDegrees'])];scale=[*transform['tile'],1]
        else:
            node=self.node('coordinates');port=self.output(node,intent['kind'])
            transform=intent['transform'];translation=transform['translation']
            rotation=[math.radians(v) for v in transform['rotationDegrees']];scale=transform['scale']
        if any(translation) or any(rotation) or scale!=[1,1,1]:
            node=self.node('mapping',{'translation':translation,'rotation':rotation,'scale':scale})
            self.bind(node,'vector',port);port=self.output(node,'vector')
        self.cache[key]=port;return port

    def image(self,identifier):
        if identifier in self.outputs:return self.outputs[identifier]
        sampler=self.samplers[identifier];projection=sampler['projection']
        properties={'image':sampler['image'],
                    'interpolation':{'linear':'Linear','nearest':'Closest','cubic':'Cubic','smart':'Smart'}[sampler['filter']],
                    'extension':{'repeat':'REPEAT','extend':'EXTEND','clip':'CLIP','mirror':'MIRROR'}[sampler['wrap']],
                    'projection':{'flat':'FLAT','box':'BOX','sphere':'SPHERE','tube':'TUBE'}[projection['kind']]}
        if projection['kind']=='box':properties['projectionBlend']=projection['blend']
        node=self.node('image',properties=properties);self.bind(node,'vector',self.coordinates(sampler))
        result={'colour':self.output(node,'colour'),'alpha':self.output(node,'alpha')}
        self.outputs[identifier]=result;return result

    def colour_sample(self,identifier):
        """Canonical straight colour independent of other alpha consumers.

        Fixed Cycles changes colour association when Alpha becomes connected.
        An actual positive-alpha colour mask makes that connection semantic,
        including the defined black result for associated zero-alpha texels.
        Data, channel-packed and ignored-alpha images keep raw RGB semantics.
        """
        raw=self.image(identifier);sampler=self.samplers[identifier];image=self.images[sampler['image']]
        if image['colourSpace']=='Non-Color' or image['alphaMode'] in ('channelPacked','ignore'):return raw['colour']
        key=('associated-colour',identifier)
        if key not in self.cache:
            positive=self.node('math',{'b':0},{'operation':'GREATER_THAN'})
            self.bind(positive,'a',raw['alpha'])
            node=self.node('mixColour',{'a':[0,0,0,1]},{'clamp':False})
            self.bind(node,'factor',self.output(positive,'value'));self.bind(node,'b',raw['colour'])
            self.cache[key]=self.output(node,'colour')
        return self.cache[key]

    def channel(self,sampler,channel):
        image=self.image(sampler)
        if channel=='alpha':return image['alpha']
        colour=self.colour_sample(sampler)
        key=('channels',sampler)
        if channel=='luminance':
            if key+('luminance',) not in self.cache:
                node=self.node('vectorMath',{'b':[.2126,.7152,.0722]},{'operation':'DOT_PRODUCT'})
                self.bind(node,'a',colour);self.cache[key+('luminance',)]=self.output(node,'value')
            return self.cache[key+('luminance',)]
        if key not in self.cache:
            node=self.node('separateColour');self.bind(node,'colour',colour)
            self.cache[key]={c:self.output(node,c) for c in ('red','green','blue')}
        return self.cache[key][channel]

    def scalar(self,source):
        if source['kind']=='constant':return source['value']
        low,high=source['range']
        if low==high:return low
        key=('scalar',json.dumps(source,sort_keys=True))
        if key not in self.cache:
            node=self.node('mapRange',{'fromMin':0,'fromMax':1,'toMin':low,'toMax':high},{'clamp':True})
            self.bind(node,'value',self.channel(source['sampler'],source['channel']))
            self.cache[key]=self.output(node,'value')
        return self.cache[key]

    def colour(self,source,clamp=True):
        if source['kind']=='constant':return [*source['value'],1]
        key=('colour',json.dumps(source,sort_keys=True),clamp)
        if key not in self.cache:
            node=self.node('mixColour',{'factor':1,'b':[*source['tint'],1]},
                           {'blend':'MULTIPLY','clamp':clamp})
            self.bind(node,'a',self.colour_sample(source['sampler']));self.cache[key]=self.output(node,'colour')
        return self.cache[key]

    def normal_map(self,intent):
        space=intent['space'];properties={'space':space['kind'].upper(),
            'convention':{'openGL':'OPENGL','directX':'DIRECTX'}[intent['convention']],
            'base':intent['base'].upper()}
        if space['kind']=='tangent':
            uv=space['uv']
            if uv['kind']=='sampler':uv=self.samplers[intent['sampler']]['coordinates']['set']
            properties['uvMap']=uv.get('name','')
        node=self.node('normalMap',properties=properties)
        self.bind(node,'colour',self.image(intent['sampler'])['colour'])
        self.bind(node,'strength',self.scalar(intent['strength']));return self.output(node,'normal')

    def normal(self,intent):
        kind=intent['kind']
        if kind=='geometric':return None
        previous=self.normal_map(intent['map']) if kind in ('normalMap','normalAndBump') else None
        if kind in ('heightBump','normalAndBump'):
            bump=intent['bump'];node=self.node('bump',{'distance':bump['distance'],'filterWidth':bump['filterWidth']},
                                              {'invert':bump['invert']})
            self.bind(node,'height',self.scalar(bump['height']));self.bind(node,'strength',self.scalar(bump['strength']))
            if previous is not None:self.bind(node,'normal',previous)
            previous=self.output(node,'normal')
        return previous
