"""Typed semantic node socket/declaration helpers shared by reviewed catalogues."""

def number(default=0, **bounds): return {'type':'number','default':default,**bounds}
def integer(default=1, **bounds): return {'type':'integer','default':default,**bounds}
def vector(default=(0,0,0)): return {'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3,'default':list(default)}
def colour(default=(.8,.8,.8,1)): return {'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':4,'maxItems':4,'default':list(default)}
def choice(default, values): return {'type':'enum','values':values,'default':default}
def boolean(default=False): return {'type':'boolean','default':default}
def text(default=''): return {'type':'string','default':default,'maxLength':4096}
def socket(native, kind, spec=None): return {'native':native,'kind':kind,**({'value':spec} if spec else {})}
def node(native, inputs=None, outputs=None, properties=None):
    return {'native':native,'inputs':inputs or {},'outputs':outputs or {},'properties':properties or {}}
S=lambda name,default=0:socket(name,'number',number(default))
V=lambda name,default=(0,0,0):socket(name,'vector',vector(default))
C=lambda name,default=(.8,.8,.8,1):socket(name,'colour',colour(default))
G=lambda name:socket(name,'geometry')
H=lambda name:socket(name,'shader')
I=lambda name:socket(name,'image')
