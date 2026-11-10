"""Strict encoding comparison for freshly regenerated design-history maps.

The local postfix dictionary and document string IDs are storage encodings, not
stable identities. Resolve their referenced encodings before comparing two
executions of the SAME regeneration. This is deliberately not a semantic
source-to-copy name-equivalence decoder. Public format basis: FreeCAD 1.1.4 App/ElementMap.cpp and
App/StringHasher.cpp. This reader is independent of native geometry execution.
"""
import hashlib
import json
import re

TAG=re.compile(r';:H(-?)([0-9a-f]+)')
HASH=re.compile(r'#([0-9a-f]+)')
TOKENS=re.compile(r';:H(?P<sign>-?)(?P<owner>[0-9a-f]+)(?::(?P<length>[0-9a-f]+))?,(?P<kind>[FEV])|#(?P<sid>[0-9a-f]+)')


def postfix_inventory(members,root,tags=None):
    """Bind all local dictionary entries, including those no map row uses."""
    from schemaxis.dispatch import remaining_timeout
    from .assembly_payloads import file_map,object_ids
    from .source_envelope import element_map
    identities=object_ids(root)
    records=strings(members[root.find('StringHasher2').get('file')])
    names=Names(records,tags if tags is not None else {v:v for v in identities.values()})
    result={}
    for key,member in file_map(root).items():
        if key[2]!='ElementMap2':continue
        parsed=element_map(members[member],member,'VERIFICATION_FAILED',member);values=[]
        for value in parsed['postfixes']:
            remaining_timeout()
            values.append(json.dumps(names.text(value),sort_keys=True,separators=(',',':')))
        # Allocation order may differ; multiplicity and every value may not.
        result[key]=sorted(values)
    return result


def strings(data):
    """Return sparse-ID records, retaining encoded values and related-ID order."""
    from .source_envelope import string_ids
    string_ids(data,'elementMap','VERIFICATION_FAILED','StringHasher')
    records={};previous=[];last=0
    for line in data.decode('ascii').splitlines()[1:]:
        head,_,payload=line.partition(' ');fields=head.split('.');relative=fields[0].startswith('-')
        identity=last+int(fields[0][1:],16) if relative else int(fields[0],16)
        refs=[]
        for index,field in enumerate(fields[2:]):
            value=int(field,16)
            refs.append((previous[index]+value if index<len(previous) else identity-value) if relative else value)
        records[identity]=(int(fields[1],16),payload,refs)
        last=identity;previous=refs
    return records


def string_inventory(members, root, tags=None):
    """Bind every persistent string, including records no map or shadow uses.

    Only allocation IDs may change under the complete named-object bijection.
    Retention bits keep their existing non-semantic treatment in Names; unknown
    flags, dangling references, cycles and duplicate semantic records fail closed.
    """
    from .source_envelope import document_ids
    from schemaxis.dispatch import remaining_timeout
    identities = document_ids(root)
    records = strings(members[root.find('StringHasher2').get('file')])
    names = Names(records, tags if tags is not None else {v: v for v in identities.values()})
    inventory = []
    for identity in records:
        remaining_timeout()
        inventory.append(names.sid(identity))
    if len(set(inventory)) != len(inventory):
        raise ValueError('complete string inventory is not bijective')
    return sorted(inventory)


class Names:
    def __init__(self,records,tags):
        self.records=records;self.tags=tags;self.cache={};self.active=set()

    def text(self,value,*,literal_hashes=False):
        # A tag's optional hexadecimal length describes the preceding operation
        # substring (MappedName.cpp public format), not an invariant integer.
        # Renaming a nested owner from a three- to four-digit ID changes this
        # length. Bind its exact substring boundary in the token sequence;
        # never discard it or compare the unadjusted byte offset after rename.
        result=[];ranges=[];position=0
        for match in TOKENS.finditer(value):
            if literal_hashes and match['sid'] is not None:continue
            result.append(value[position:match.start()]);ranges.append((position,match.start(),len(result)-1,True))
            if match['sid'] is not None:
                token={'string':self.sid(int(match['sid'],16))}
            else:
                identity=int(match['owner'],16)
                if identity not in self.tags:raise ValueError('topological name refers outside its owned source')
                length=int(match['length'],16) if match['length'] is not None else 0
                start=match.start()-length;anchor=None
                if length:
                    for lo,hi,index,literal in ranges:
                        if literal and lo<=start<=hi:
                            anchor=[index,start-lo];break
                        if not literal and start==lo:
                            anchor=[index,0];break
                    if anchor is None:raise ValueError('topological operation length splits an encoded token or escapes its name')
                token={'owner':self.tags[identity],'negative':match['sign']=='-',
                       'kind':match['kind'],'operationStart':anchor}
            result.append(token);ranges.append((match.start(),match.end(),len(result)-1,False));position=match.end()
        result.append(value[position:])
        if TAG.search(''.join(item for item in result if isinstance(item,str))):
            raise ValueError('topological owner marker has unsupported syntax')
        return result

    def sid(self,identity):
        if identity in self.cache:return self.cache[identity]
        if identity not in self.records or identity in self.active or len(self.active)>256:
            raise ValueError('missing, recursive or excessively deep topological string dependency')
        self.active.add(identity)
        flags,payload,refs=self.records[identity]
        # Persistent/marked bits describe retention, not name interpretation.
        if flags & ~511 or flags & 3:
            raise ValueError('unknown, binary or cryptographically hashed topological string flags')
        if flags & (4|16|32|64) and not flags & 8:
            raise ValueError('topological string encoding flags require a postfix')
        if flags & 64 and flags & 32:
            raise ValueError('topological prefix cannot use both indexed and unindexed reference encodings')
        semantic=[flags&127,self.text(payload),[self.sid(ref) for ref in refs]]
        digest=hashlib.sha256(json.dumps(semantic,separators=(',',':')).encode()).hexdigest()
        self.cache[identity]=digest;self.active.remove(identity)
        return digest


def canonical(parsed,records,tags):
    names=Names(records,tags);dictionary=parsed['postfixes'];result=[];digests=[]
    def postfix(index):
        if index==0:return []
        if not 1<=index<=len(dictionary):raise ValueError('element-map local postfix index is absent')
        return names.text(dictionary[index-1])
    for map_index,(_,sections) in enumerate(parsed['maps'],1):
        converted=[]
        kinds=set()
        for kind,_,_,children,rows in sections:
            if kind not in {'Edge','Face','Vertex'} or kind in kinds:
                raise ValueError('unknown or duplicate element-map section')
            kinds.add(kind)
            child_records=[]
            starts=set()
            for child in children:
                fields=child.split()
                if len(fields)!=7:raise ValueError('element-map child record has unsupported syntax')
                start,offset,count,tag,child_map=map(int,fields[:5])
                if min(start,offset,count)<0 or not 0<=child_map<map_index:
                    raise ValueError('element-map child range or local map reference is invalid')
                if start in starts or not count:
                    raise ValueError('duplicate child start or empty child range')
                starts.add(start)
                if tag and abs(tag) not in tags:raise ValueError('element-map child tag escapes its source')
                tag=(1 if tag>=0 else -1)*tags[abs(tag)] if tag else 0
                ids=fields[6].split('.')
                if ids[0]!='0':raise ValueError('element-map child string list is malformed')
                # FreeCAD 1.1.4 ElementMap::save writes zero when the child has
                # no elementMap; restore makes that pointer nullptr. It is not
                # an alias of the last preceding map (Python index -1).
                child_records.append([start,offset,count,tag,digests[child_map-1] if child_map else None,names.text(fields[5]),
                                      [names.sid(int(value)) for value in ids[1:]]])
            encoded=[]
            for row in rows:
                tokens=row.split()
                if not tokens or tokens[-1]!='0':raise ValueError('element-map name row lacks its terminator')
                entries=[]
                for token in tokens[:-1]:
                    fields=token.split('.');prefix=fields[0];at=1
                    if prefix.startswith(':'):
                        if len(fields)<3:raise ValueError('indexed element-map name is truncated')
                        prefix_index=int(prefix[1:],16)
                        if not prefix_index:raise ValueError('indexed element-map prefix dictionary index must be positive')
                        base=['indexed',postfix(prefix_index),int(fields[1],16)];at=2
                    elif prefix.startswith('$#'):
                        match=re.fullmatch(r'\$#([0-9a-f]+)(?::([0-9a-f]+))?',prefix)
                        if not match:raise ValueError('element-map string prefix is malformed')
                        base=['hashed',names.sid(int(match[1],16)),int(match[2],16) if match[2] else 0]
                    elif prefix.startswith(';'):
                        # The ';' marker is literal text, even when it looks
                        # like '#25'. Only '$#25' declares a StringID reference.
                        base=['literal',names.text(prefix[1:],literal_hashes=True)]
                    else:raise ValueError('element-map name marker is unsupported')
                    if len(fields)<=at:raise ValueError('element-map name lacks a postfix index')
                    entries.append([base,postfix(int(fields[at],16)),[names.sid(int(value,16)) for value in fields[at+1:]]])
                encoded.append(entries)
            converted.append([kind,child_records,encoded])
        result.append(converted)
        digests.append(hashlib.sha256(json.dumps(converted,separators=(',',':')).encode()).hexdigest())
    if not result:raise ValueError('element-map has no local maps')
    if parsed['postfixId']!=parsed['maps'][-1][0]:
        raise ValueError('element-map file root does not name its final local map')
    return result


def archive_maps(members,root,*,tags=None):
    """Validate all document-wide aliases and return each map's full encoding.

    An alias may be repeated only with identical contents. Native restoration
    can reuse an earlier alias instead of reading a later definition, so this
    check spans every property payload rather than each file separately.
    """
    from .source_envelope import element_map
    from .assembly_payloads import file_map,object_ids
    identities=object_ids(root)
    tags=tags if tags is not None else {v:v for v in identities.values()}
    records=strings(members[root.find('StringHasher2').get('file')])
    names=Names(records,tags)
    encodings=[names.sid(identity) for identity in records]
    if len(set(encodings))!=len(encodings):
        raise ValueError('string table contains duplicate encoded identities instead of a bijective allocation')
    aliases={};out={}
    for key,member in file_map(root).items():
        if key[2]!='ElementMap2':continue
        parsed=element_map(members[member],member,'VERIFICATION_FAILED',member)
        converted=canonical(parsed,records,tags)
        for (alias,_),content in zip(parsed['maps'],converted):
            if alias<=0 or alias in aliases and aliases[alias]!=content:
                raise ValueError('conflicting document-wide element-map alias: '+member)
            aliases[alias]=content
        # Bind even inert local definitions. Root reachability alone would not
        # establish the stated all-encoded-map persistence contract.
        out[key]=converted
    # XML shadow names have the same indirect StringID and owner dependencies.
    shadows={}
    for obj in root.findall('./ObjectData/Object'):
        for prop in obj.findall('./Properties/Property'):
            for index,element in enumerate(prop.iter()):
                if element.get('shadow'):
                    shadows[(obj.get('name'),prop.get('name'),index)]=names.text(element.get('shadow'))
    return out,shadows
