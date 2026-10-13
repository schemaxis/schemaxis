"""Generate exhaustive host-only ParaView documentation appendices.

Run from the repository root with PYTHONPATH=src. Native qualification is separate.
"""
import argparse, json, re
from pathlib import Path
from collections import Counter
from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.adaptors.paraview.capabilities import catalogue as capabilities
from schemaxis.adaptors.paraview.publication import STYLE
from schemaxis.camera import CAMERA
from schemaxis.functions import FUNCTIONS
from schemaxis.studio_guidance import load
from schemaxis.adaptors.paraview.schema import document_schema
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='Fail on generated documentation drift without rewriting')
check = parser.parse_args().check
def write(path, text):
 if check:
  if not path.is_file() or path.read_text() != text:
   raise SystemExit('Stale generated ParaView reference: ' + str(path))
 else:
  path.write_text(text)
C=catalogue(); caps=capabilities()['operations']; out=Path('docs')
# Conceptual guidance is the same text Studio shows beside each operation and field.
G=load('paraview'); F=G['routes']['schemaxis/1']['fields']; S=document_schema()
def unwrap(node, path):
 for key in ('anyOf','oneOf'):
  b=node.get(key) if isinstance(node,dict) else None
  if isinstance(b,list) and len(b)==2 and sum(isinstance(x,dict) and set(x)=={'$ref'} for x in b)==1:
   i=0 if not (isinstance(b[0],dict) and set(b[0])=={'$ref'}) else 1
   return unwrap(b[i], f'{path}/{key}/{i}')
 return node, path
def esc_key(k): return str(k).replace('~','~0').replace('/','~1')
def field_help(node, path, keys):
 """Follow option keys and proxy-choice labels to the guidance record address."""
 node, path = unwrap(node, path)
 if not keys: return F.get(path, {})
 head, rest = keys[0], keys[1:]
 own = unwrap(node.get('properties',{}).get('type',{}), '')[0].get('enum') if isinstance(node,dict) else None
 if own == [head] and 'options' in node.get('properties', {}):
  return field_help(node['properties']['options'], path+'/properties/options', rest)
 if head in node.get('properties', {}):
  return field_help(node['properties'][head], path+'/properties/'+esc_key(head), rest)
 for key in ('anyOf','oneOf'):
  for i,choice in enumerate(node.get(key, [])):
   inner, ipath = unwrap(choice, f'{path}/{key}/{i}')
   label = unwrap(inner.get('properties',{}).get('type',{}), '')[0].get('enum') if isinstance(inner,dict) else None
   if label == [head]:
    return field_help(inner['properties']['options'], ipath+'/properties/options', rest)
 return {}
def meaning(op, keys):
 record = field_help(S['$defs'].get('options-'+op, {}), '/$defs/options-'+op, keys)
 return record.get('explanation') if record.get('status') != 'pending' else None
VARIANT={v['properties']['filter'].get('const'):i for i,v in enumerate(S['properties']['nodes']['items']['oneOf'])}
def port_help(op, port):
 r=F.get(f'/properties/nodes/items/oneOf/{VARIANT.get(op)}/properties/inputs/properties/{esc_key(port)}',{})
 return r.get('explanation') if r.get('status')!='pending' else None
def summary(op):
 r=G['operations'].get(op,{})
 return r['explanation'] if r.get('explanation') and r.get('status')!='pending' else caps[op]['purpose']
def j(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def clean(text): return '\n'.join(line.rstrip() for line in text.splitlines()).rstrip()+'\n'
def esc(v): return str(v).replace('|','\\|').replace('\n',' ')
def example(s):
 if 'default' in s:return s['default']
 t=s.get('type')
 if t=='enum':return s['values'][0]
 if t=='union':return example(s['options'][0])
 if t=='object':return {k:example(v) for k,v in s.get('properties',{}).items() if v.get('required')}
 if t=='array':return [example(s['items']) for _ in range(s.get('minItems',1))]
 if t=='string':return 'REPLACE_WITH_VALUE'
 if t=='boolean':return False
 if t in ('integer','number'):
  x=s.get('minimum',1)
  return x+1 if s.get('exclusiveMinimum') else x
 return None
def table(specs):
 lines=['| Key | Syntax / constraints | Default / requirement |','| --- | --- | --- |']
 for k,s in specs.items():lines.append(f'| `{k}` | `{esc(j({a:b for a,b in s.items() if a not in ("default","required")}))}` | '+ ('required' if s.get('required') else '`'+esc(j(s['default']))+'`' if 'default'in s else 'omitted')+' |')
 return '\n'.join(lines)
p=['# ParaView adaptor: complete operation reference\n','Generated from the current installed declarations and conceptual guidance on 2026-10-10. Regenerate with `PYTHONPATH=src python3 tools/generate_paraview_guide.py` from the repository root.\n',f'{len(C)} operation identifiers. This lists every registered input, option (including nested proxy choices), declared command, output kind and coverage gap. Native selection descriptions retain their provenance in [native-context.json](../src/schemaxis/adaptors/paraview/native-context.json); the [ParaView copyright notice](../src/schemaxis/adaptors/paraview/ParaView-Copyright.txt) applies.\n','[Guide](paraview-guide.md) · [Shared dollar syntax](dollar-reference.md)\n','Examples are **syntax templates**, not native acceptance fixtures. Replace placeholder strings, upstream node IDs and data-dependent settings with appropriate real values. The small values illustrate types only; array domains, scientific intent and native compatibility require planning/inspection/execution. Options without defaults deliberately preserve native initialisation. Each option row supplies an example, including optional keys. Nested proxy examples show selection syntax; their own option tables follow.\n','## Index\n']
p += [f'- [{n}](#{n.lower()}) — {esc(re.split(r"(?<=[.])\\s", summary(n))[0])}' for n in sorted(C)]
def options(bindings,prefix='',op=None,keys=()):
 lines=[]
 if not bindings:return ['No authored options.\n']
 lines+=['| Key | Meaning / native assignment | Type and constraints | Default / required | Example value |','| --- | --- | --- | --- | --- |']
 for k,b in bindings.items():
  s=b['value']; path='.'.join(map(str,b.get('path',[k])))
  desc=meaning(op,[*keys,k]) or s.get('summary',s.get('title',f'Assigns native `{path}`.'))
  if b.get('constructor'):desc+=' Fixed at construction; cannot vary per visit.'
  if b.get('tupleSize'):desc+=f' Complete tuples of {b["tupleSize"]} values.'
  constraint={a:v for a,v in s.items() if a not in ('default','required')}
  if b.get('proxyChoices'):constraint={'type':'typed proxy','choices':list(b['proxyChoices'])}
  default='required' if s.get('required') else j(s['default']) if 'default'in s else 'native initialisation / omitted'
  lines.append(f'| `{prefix+k}` | {esc(desc)} | `{esc(j(constraint))}` | `{esc(default)}` | `{esc(j(example(s)))}` |')
 for k,b in bindings.items():
  for typ,ch in b.get('proxyChoices',{}).items():
   lines+=['',f'### Nested `{prefix+k}` → `{typ}`\n',f'Syntax: `{{"type":{j(typ)},"options":{{...}}}}`. Native identity: `{ch.get("identity")}`. Omitted nested options retain native values on subsequent visits.\n']
   lines+=options(ch['options'],prefix+k+'.options.',op,(*keys,k,typ))
   if ch.get('gaps'):lines+=['Unbound nested properties: `'+j(ch['gaps'])+'`.\n']
 return lines
for n,d in sorted(C.items()):
 p+=['',f'## {n}\n',summary(n)+'\n']
 record=G['operations'].get(n,{})
 if record.get('status')!='pending' and record.get('pitfalls'):
  p+=['Common mistakes and assumptions:\n',*[f'- {" ".join(x.split())}' for x in record['pitfalls']],'']
 elif record.get('status')=='pending':
  for semantic in caps[n].get('semantics',[]):p.append(semantic+'\n')
 p += [f'Native constructor: `{d["native"]}`. Identity: `{d.get("nativeIdentity","curated binding")}`. Role: `{d.get("role","pipeline")}`. Output kinds: `{j(d.get("kinds",["data"]))}`.\n','### Inputs\n']
 if d['inputs']:
  p+=['| Port | Meaning / native port | Required | Multiplicity | Kind | Contract |','| --- | --- | --- | --- | --- | --- |']
  for k,s in d['inputs'].items():p.append(f'| `{k}` | {esc(port_help(n,k) or "Connect upstream object to `"+s.get("native",k)+"`")} | {s.get("required",False)} | '+('nonempty list' if s.get('multiple') else 'one object')+f' | `{s.get("kind","data")}` | `{esc(j(s.get("contract",{})))}` |')
 else:p+=['No connected inputs (source/resource).\n']
 p+=['\n### Options\n',*options(d['options'],'',n)]
 for k,label in [('checks','Cross-option checks'),('requires','Conditional requirements'),('commands','onVisit commands'),('publication','Output publication contract'),('execution','Execution contract'),('coverage','Coverage and unbound native properties')]:
  if d.get(k):p += ['\n'+label+':\n','```json',json.dumps(d[k],indent=2),'```']
 opts={k:example(b['value']) for k,b in d['options'].items() if b['value'].get('required')}
 if d.get('role')=='writer':
  ex={'id':'exportResult','node':'DATA_NODE','writer':n}
  if d.get('publication',{}).get('losses'):ex['acceptLosses']=d['publication']['losses']
  placement='Place in `scenes[].exports`; writers cannot be graph nodes. The main data input is `node`; non-data ports go in `resources`.'
  resources={k:'RESOURCE_NODE' for k,s in d['inputs'].items() if s.get('kind','data')!='data' and s.get('required')}
  if resources:ex['resources']=resources
 else:
  ex={'id':'result','filter':n}
  ins={k:([f'UPSTREAM_{k}'] if s.get('multiple') else f'UPSTREAM_{k}') for k,s in d['inputs'].items() if s.get('required')}
  if ins:ex['inputs']=ins
  placement='Place in `nodes`. Data outputs may be selected by a scene; resource outputs must be connected to a compatible consumer.'
 if opts:ex['options']=opts
 p+=['\n### Syntax example\n',placement+'\n','```json',json.dumps(ex,indent=2),'```']
 if d.get('commands'):p+=['Example command request (pipeline node only): `"onVisit":'+j(list(d['commands']))+'`. Commands run in this authored order before the update.\n']
write(out/'paraview-operation-reference.md', clean('\n'.join(p)))
# Settings appendix keeps full typed direction grammar and function signatures.
s=['# Shared function and ParaView settings signatures\n','[Guide](paraview-guide.md) · [Dollar syntax](dollar-reference.md)\n','All type constraints below are taken directly from declarations. `required`, defaults, enum values and array lengths are authoritative; cross-field rules still require the planner. Examples are type templates, requiring semantically suitable values.\n','## Appearance\n',table(STYLE),'\n## Camera\n',table(CAMERA),'\n## Registered value functions\n']
meanings={'boundsCentre':'Centre of six-component VTK bounds.','boundsCentre3D':'Centre of min/max bounds.','boundsExtend':'Extend min/max bounds by before/after vectors.','boundsFrame':'Frame bounds with margins, a floor and an aspect ratio.','boundsSize':'Axis extents of min/max bounds.','boundsUnion':'Union of a nonempty list of min/max bounds.','directionVector':'Resolve a direction declaration to an XYZ vector.','fitCamera':'Fit a camera to bounds.','foamRegions':'Convert tyres/body //patch selectors to internalMesh and patch/name reader regions.','orbitCameras':'Produce camera declarations around bounds.','rangeCentre':'Midpoint of a two-number range.','sinDegrees':'Sine of an angle in degrees.','slicePositions':'Produce scalar slice positions along one bounds axis.','vectorLength':'Euclidean length of an XYZ vector.'}
for n,d in FUNCTIONS.describe().items():
 s += [f'## {n}\n',meanings.get(n,'Registered pure typed function.')+'\n',table(d['arguments']),'\nResult contract: `'+j(d['result'])+'`.\n','```json',json.dumps({'$value':n,'args':{k:example(v) for k,v in d['arguments'].items() if v.get('required')}},indent=2),'```','Use `$call` instead of `$value` when arguments contain graph runtime expressions.\n']
write(out/'paraview-settings-reference.md', clean('\n'.join(s)))
print(f'Generated {len(C)} entries; roles {dict(Counter(d.get("role","pipeline") for d in C.values()))}')
