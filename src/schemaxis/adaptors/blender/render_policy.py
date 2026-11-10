"""Typed rendering engines, technical shading and display transforms.

Legacy Cycles controls retain their addresses. Other engines expose their own
controls and reject nondefault legacy settings that would have no effect.
"""
import math
import struct
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from .node_catalogue import number,integer,choice,boolean


def rgb(default):return {'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':3,'maxItems':3,'default':list(default)}
def record(fields):return {'type':'object','properties':fields}
def options(fields):return {**record(fields),'default':validate_arguments(fields,{})}
def variant(kind,fields):return record({'kind':{'type':'enum','values':[kind],'required':True},**fields})
def union(variants,default):
    spec={'type':'union','options':variants}
    return {**spec,'default':validate_arguments({'value':spec},{'value':default})['value']}

DENOISE=union([variant('none',{}),variant('filtered',{'spatial':boolean(True),'temporal':boolean(True),'bilateral':boolean(True)})],{'kind':'filtered'})
TRACE_COMMON={'resolution':choice('2',['1','2','4','8','16']),'denoise':DENOISE}
BACKFACE=union([variant('singleSided',{}),variant('bothSides',{'radianceReuse':number(.25,minimum=0,maximum=1)})],{'kind':'bothSides'})
RAY_TRACING=union([variant('off',{}),variant('screen',{**TRACE_COMMON,'quality':number(.25,minimum=0,maximum=1),'thickness':number(.1,minimum=.000001,maximum=100000),'backfaces':BACKFACE})],{'kind':'off'})
GI_OPTIONS={'resolution':choice('2',['1','2','4','8','16']),'quality':number(.25,minimum=0,maximum=1),'rays':integer(2,minimum=1,maximum=16),'steps':integer(8,minimum=1,maximum=64),
 'roughnessThreshold':number(.5,minimum=0,maximum=1,exclusiveMaximum=True),'distance':number(0,minimum=0,maximum=100000),'thickness':number(.1,minimum=0,maximum=100000),'bias':number(.05,minimum=0,maximum=1)}
FAST_GI=union([variant('off',{}),variant('ambient',GI_OPTIONS),variant('global',GI_OPTIONS)],{'kind':'off'})
STUDIO_PRESETS=['basic.sl','outdoor.sl','paint.sl','rim.sl','studio.sl']
MATCAP_PRESETS=['basic_bright.exr','basic_dark.exr','basic_grey.exr','basic_side.exr','ceramic_dark.exr','ceramic_lightbulb.exr','check_gradient.exr','check_normal+y.exr','check_reflection_horizontal.exr','check_reflection_vertical.exr','check_rim_dark.exr','check_rim_light.exr','clay_brown.exr','clay_green.exr','clay_studio.exr','clay_warm.exr','fullmetal.exr','hard_surface_grey.exr','hard_surface_red.exr','metal_bronze.exr','metal_carpaint.exr','pearl.exr','red_wax.exr','resin.exr','toon_dark.exr','toon_light.exr']
LIGHTING=union([variant('flat',{}),variant('studio',{'preset':choice('basic.sl',STUDIO_PRESETS),'worldSpace':boolean(),'rotation':number(0,minimum=-math.pi,maximum=math.pi),'specular':boolean(True)}),variant('matcap',{'preset':choice('basic_grey.exr',MATCAP_PRESETS)})],{'kind':'studio'})
COLOUR_SOURCE=union([variant('material',{}),variant('object',{}),variant('random',{}),variant('attribute',{}),variant('single',{'colour':rgb((.8,.8,.8))}),variant('texture',{})],{'kind':'material'})
CAVITY=union([variant('off',{}),variant('world',{'ridge':number(1,minimum=0,maximum=250),'valley':number(1,minimum=0,maximum=250)}),variant('screen',{'ridge':number(1,minimum=0,maximum=2),'valley':number(1,minimum=0,maximum=2)}),variant('both',{'worldRidge':number(1,minimum=0,maximum=250),'worldValley':number(1,minimum=0,maximum=250),'screenRidge':number(1,minimum=0,maximum=2),'screenValley':number(1,minimum=0,maximum=2)})],{'kind':'off'})
SHADOW=union([variant('off',{}),variant('on',{'direction':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3,'default':[1,1,1]},'darkness':number(.5,minimum=0,maximum=1),'shift':number(.1,minimum=0,maximum=1),'focus':number(0,minimum=0,maximum=1)})],{'kind':'off'})
SHADING_SYSTEM={'type':'enum','values':['svm','osl']}
RENDERER=union([variant('cycles',{'shadingSystem':SHADING_SYSTEM}),variant('eevee',{'samples':integer(8,minimum=1,maximum=4096),'rayTracing':RAY_TRACING,'fastGI':FAST_GI,'shadowRays':integer(1,minimum=1,maximum=4),'shadowSteps':integer(6,minimum=1,maximum=16)}),variant('workbench',{'lighting':LIGHTING,'colourSource':COLOUR_SOURCE,'background':rgb((.05,.05,.05)),'antiAliasing':choice('8',['OFF','FXAA','5','8','11','16','32']),'shadows':SHADOW,'cavity':CAVITY,'outline':union([variant('off',{}),variant('on',{'colour':rgb((0,0,0))})],{'kind':'off'}),'xray':union([variant('off',{}),variant('on',{'alpha':number(.5,minimum=0,maximum=1)})],{'kind':'off'}),'backfaceCulling':boolean()})],{'kind':'cycles'})

AGX_LOOKS={'base':'None','punchy':'AgX - Punchy','veryHigh':'AgX - Very High Contrast','high':'AgX - High Contrast','mediumHigh':'AgX - Medium High Contrast','mediumLow':'AgX - Medium Low Contrast','low':'AgX - Low Contrast','veryLow':'AgX - Very Low Contrast'}
VIEWS={'agx':'AgX','standard':'Standard','neutral':'Khronos PBR Neutral','aces13':'ACES 1.3','aces20':'ACES 2.0','raw':'Raw'}
VIEW=union([variant('agx',{'contrast':choice('base',list(AGX_LOOKS))}),*[variant(k,{}) for k in VIEWS if k!='agx']],{'kind':'agx'})
WHITE_BALANCE=union([variant('off',{}),variant('on',{'temperature':number(6500,minimum=1800,maximum=100000),'tint':number(10,minimum=-500,maximum=500)})],{'kind':'off'})
COLOUR_MANAGEMENT=options({'view':VIEW,'exposure':number(0,minimum=-32,maximum=32),'gamma':number(1,minimum=0,exclusiveMinimum=True,maximum=5),'whiteBalance':WHITE_BALANCE})


def validate(settings):
    from .settings import RENDER_OPTIONS
    if struct.unpack('f',struct.pack('f',settings['colourManagement']['gamma']))[0]<=0:
        fail('INVALID_RENDERER','gamma must remain positive in native float storage','render.colourManagement.gamma')
    engine=settings['renderer'];kind=engine['kind']
    if kind=='cycles':
        # Preserve historical normalized defaults. Explicit SVM is identical
        # to omission; native readback includes the field only for OSL.
        if engine.get('shadingSystem')=='svm':engine.pop('shadingSystem')
        if engine.get('shadingSystem')=='osl' and settings['device'] not in ('CPU','OPTIX'):
            fail('UNSUPPORTED_SHADER_BACKEND','OSL requires the CPU or OptiX Cycles device','render.renderer.shadingSystem')
    inactive=[]
    if kind!='cycles':inactive+=['device','samples','denoise','seed']
    if kind=='workbench':inactive+=['worldColour','worldStrength','lightEnergy','lightPosition','lightSize']
    for key in inactive:
        if settings[key]!=RENDER_OPTIONS[key]['default']:fail('INEFFECTIVE_RENDER_SETTING','this legacy setting does not control the selected renderer; use its typed options','render.'+key,renderer=kind)
    if kind=='eevee':
        ray=engine['rayTracing'];denoise=ray.get('denoise',{})
        if ray['kind']=='off' and engine['fastGI']['kind']!='off':fail('INEFFECTIVE_RENDER_SETTING','fast GI approximation requires ray tracing','render.renderer.fastGI')
        if denoise.get('kind')=='filtered' and not any(denoise[k] for k in ('spatial','temporal','bilateral')):fail('INVALID_RENDERER','filtered ray tracing needs at least one filter; choose none to disable it','render.renderer.rayTracing.denoise')
    if kind=='workbench' and engine['shadows']['kind']=='on':
        direction=engine['shadows']['direction']
        scale=max(map(abs,direction))
        if not scale:fail('INVALID_RENDERER','shadow direction must be nonzero','render.renderer.shadows.direction')
        normalized=[v/scale for v in direction];length=math.hypot(*normalized)
        if not math.isclose(math.hypot(*direction),1,rel_tol=4e-16,abs_tol=0):
            engine['shadows']['direction']=[v/length for v in normalized]
    if kind=='workbench' and engine['lighting']['kind']=='studio' and not engine['lighting']['worldSpace'] and engine['lighting']['rotation']!=0:
        fail('INEFFECTIVE_RENDER_SETTING','studio rotation requires world-space lighting','render.renderer.lighting.rotation')
    return settings
