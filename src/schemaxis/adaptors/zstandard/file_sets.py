"""Captured file selections and collision-checked relative publications.

Selection is frozen before native work. Verification admits its retained path
membership without consulting directories that may no longer exist.
"""
import fnmatch
import os
from pathlib import Path
import stat
import tempfile
from schemaxis.errors import fail
from schemaxis.dispatch import remaining_timeout
from schemaxis.artifacts import atomic_json

PATH={'type':'string','minLength':1,'maxLength':4096}
FIELD={'type':'object','properties':{
    'root':PATH,
    'files':{'type':'array','minItems':1,'maxItems':32,'items':{'type':'object','properties':{
        'source':{**PATH,'required':True},'name':{'type':'string','minLength':1,'maxLength':1024,'required':True}}}},
    'recursive':{'type':'boolean','default':True},
    'include':{'type':'array','minItems':1,'maxItems':16,'default':['*'],'items':{'type':'string','minLength':1,'maxLength':256}},
    'exclude':{'type':'array','maxItems':16,'default':[],'items':{'type':'string','minLength':1,'maxLength':256}},
}}
SUFFIX={'zstd':'.zst','gzip':'.gz','xz':'.xz','lzma':'.lzma','lz4':'.lz4'}
METADATA_RESERVE=32  # .metadata.json.staging plus atomic-publication temporary name


def relative(value):
    if (not isinstance(value,str) or not value or len(value)>1024 or '\\' in value
            or any(ord(c)<32 or ord(c)==127 for c in value) or value.startswith('/')
            or any(part in ('','.','..') for part in value.split('/'))
            or len(value.split('/'))>16):
        fail('INVALID_ZSTANDARD_FILE_SET','Use a bounded relative file name without traversal or control characters')
    try:parts=[part.encode('utf-8') for part in value.split('/')]
    except UnicodeError:fail('INVALID_ZSTANDARD_FILE_SET','Relative publication names must be valid UTF-8')
    if sum(map(len,parts))+len(parts)-1>1024 or any(len(part)>255 for part in parts):
        fail('INVALID_ZSTANDARD_FILE_SET','Relative names permit at most 1024 UTF-8 bytes and 255 bytes per component')
    return value


def absolute(value):
    if not isinstance(value,str) or '\x00' in value or not Path(value).is_absolute():
        fail('INVALID_ZSTANDARD_FILE_SET','Use an absolute local file or directory path')


def validate(p,authored):
    selected=p['fileSet'];raw=authored['fileSet']
    if ('root' in selected)==('files' in selected):
        fail('INVALID_ZSTANDARD_FILE_SET','Choose a root directory or an explicit named files list')
    if 'root' in selected:
        absolute(selected['root'])
        for pattern in [*selected['include'],*selected['exclude']]:
            if pattern.startswith('/') or '\\' in pattern or any(part=='..' for part in pattern.split('/')) or any(ord(c)<32 for c in pattern):
                fail('INVALID_ZSTANDARD_FILE_SET','Selection patterns match relative names and cannot traverse directories')
    else:
        if set(raw)&{'recursive','include','exclude'}:
            fail('INVALID_ZSTANDARD_FILE_SET','Directory selection controls require a root directory')
        for item in selected['files']:
            relative(item['name']);absolute(item['source'])
        retained(p,sorted(selected['files'],key=lambda item:item['name']))
    if p['operation']=='compressFiles' and 'pledgedBytes' in p:
        fail('INVALID_ZSTANDARD_OPTION','A single exact stream pledge cannot describe multiple files')


def excluded(name,selected,*,directory=False):
    parts=name.split('/');candidates=[name,*([name+'/'] if directory else [])]
    for count in range(1,len(parts)):
        prefix='/'.join(parts[:count]);candidates.extend((prefix,prefix+'/'))
    return any(fnmatch.fnmatchcase(candidate,pattern) for candidate in candidates for pattern in selected['exclude'])


def matches(name,selected):
    return any(fnmatch.fnmatchcase(name,p) for p in selected['include']) and not excluded(name,selected)


def selection(p):
    selected=p['fileSet']
    if 'files' in selected:
        result=sorted(selected['files'],key=lambda item:item['name'])
    else:
        root=Path(selected['root'])
        if str(root.resolve())!=str(root) or not root.is_dir():
            fail('INVALID_ZSTANDARD_FILE_SET','Choose an existing canonical directory with no symbolic-link components')
        result=[];pending=[root];visited=0
        try:
            while pending:
                remaining_timeout()
                directory=pending.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        visited+=1
                        if visited>4096:fail('ZSTANDARD_BUDGET','File-set selection exceeds 4096 examined directory entries')
                        name=Path(entry.path).relative_to(root).as_posix()
                        info=entry.stat(follow_symlinks=False)
                        if excluded(name,selected,directory=stat.S_ISDIR(info.st_mode)):continue
                        if stat.S_ISDIR(info.st_mode):
                            if selected['recursive']:
                                if len(name.split('/'))>=16:fail('ZSTANDARD_BUDGET','Recursive file-set selection exceeds 16 path components')
                                pending.append(Path(entry.path))
                        elif matches(name,selected):
                            if not stat.S_ISREG(info.st_mode):fail('INVALID_ZSTANDARD_FILE_SET','Selected inputs must be regular files without symbolic links',name)
                            result.append({'name':relative(name),'source':entry.path})
                            if len(result)>32:fail('ZSTANDARD_BUDGET','Select at most 32 files per durable file set')
        except OSError as error:fail('INVALID_ZSTANDARD_FILE_SET','Cannot examine the selected directory',str(root),detail=str(error))
        result.sort(key=lambda item:item['name'])
    return retained(p,result)


def retained(p,result):
    if not isinstance(result,list) or not 1<=len(result)<=32:
        fail('INVALID_ZSTANDARD_FILE_SET','A captured file set must contain one to 32 selected files')
    selected=p['fileSet'];names=[]
    for item in result:
        if not isinstance(item,dict) or item.keys()!=set(('source','name')):fail('INVALID_ZSTANDARD_FILE_SET','Captured selection membership is malformed')
        name=relative(item['name']);absolute(item['source']);names.append(name)
        if 'root' in selected:
            if item['source']!=str(Path(selected['root'])/name) or not matches(name,selected) or not selected['recursive'] and '/' in name:
                fail('INVALID_ZSTANDARD_FILE_SET','Captured selection differs from directory selection intent')
    if names!=sorted(names) or len({name.casefold() for name in names})!=len(names):
        fail('INVALID_ZSTANDARD_FILE_SET','Selected relative names must be sorted and distinct without case collisions')
    if 'files' in selected and result!=sorted(selected['files'],key=lambda item:item['name']):
        fail('INVALID_ZSTANDARD_FILE_SET','Captured selection differs from the explicit named files')
    output_names(p,result)
    return result


def output_names(p,selected):
    names=[]
    for item in selected:
        name=relative(item['name'])
        if p['operation']=='compressFiles':name+=SUFFIX[p['format']]
        else:
            for suffix,replacement in (('.zstd',''),('.zst',''),('.tzst','.tar'),('.gz',''),('.tgz','.tar'),('.xz',''),('.txz','.tar'),('.lzma',''),('.tlz','.tar'),('.lz4','')):
                if name.endswith(suffix):name=name[:-len(suffix)]+replacement;break
            else:name+='.decoded'
        names.append('files/'+relative(name))
        if len(name.rsplit('/',1)[-1].encode('utf-8'))+METADATA_RESERVE>255:
            fail('INVALID_ZSTANDARD_FILE_SET','Output file names must leave 32 bytes for shared metadata and atomic publication suffixes')
    folded=[name.casefold() for name in names]
    if len(set(folded))!=len(folded) or any(a.startswith(b+'/') for a in folded for b in folded if a!=b):
        fail('INVALID_ZSTANDARD_FILE_SET','Output file names collide or require a file to also be a directory')
    if any(name+suffix in folded for name in folded for suffix in ('.metadata.json','.metadata.json.staging')):
        fail('INVALID_ZSTANDARD_FILE_SET','An output collides with another output metadata companion or staging file')
    return [*names,'files.json']


def destination(p,selected,directory):
    """Admit actual filesystem name/path limits before reading captures or starting native work."""
    try:
        component=os.pathconf(directory,'PC_NAME_MAX');path_limit=os.pathconf(directory,'PC_PATH_MAX')
    except OSError as error:fail('INVALID_ZSTANDARD_FILE_SET','Cannot determine publication filesystem limits',str(directory),detail=str(error))
    component=component if component>0 else 255;path_limit=path_limit if path_limit>0 else 4096
    for name in output_names(p,selected):
        parts=name.split('/')
        if (any(len(part.encode('utf-8'))>component for part in parts[:-1])
                or len(parts[-1].encode('utf-8'))+METADATA_RESERVE>component
                or len(os.fsencode(directory/name))+METADATA_RESERVE>=path_limit):
            fail('INVALID_ZSTANDARD_FILE_SET','Output names exceed the publication filesystem name/path limits',name)


def admit_outputs(p,outputs):
    from . import adaptor as a
    limit=a.MAX_COMPRESSED if p['operation']=='compressFiles' else p['maxDecodedBytes']
    total=0
    for path in outputs:
        try:info=path.lstat()
        except OSError as error:fail('VERIFICATION_FAILED','File-set publication is missing',str(path),detail=str(error))
        if not stat.S_ISREG(info.st_mode) or str(path.resolve())!=str(path):
            fail('VERIFICATION_FAILED','File-set publications must be regular files without symbolic links',str(path))
        total+=info.st_size
        if total>limit:fail('ZSTANDARD_BUDGET','File-set publications exceed their aggregate byte limit')


def subplan(p,item,remaining,captured_bytes):
    from . import adaptor as a
    operation='compress' if p['operation']=='compressFiles' else 'restore'
    values={key:p[key] for key in a.OPTIONS[operation] if key in p and key!='source'}
    if not values.get('dictionary'):values.pop('dictionaryMode',None)
    if values.get('fast'):values.pop('level',None)
    if operation=='restore':values['maxDecodedBytes']=remaining
    elif values['streamInput'] and values['contentSize']=='require':values['pledgedBytes']=captured_bytes
    return a.plan({'version':a.VERSION,'operation':operation,'source':item['source'],**values})


def produce(p,directory,executable,paths,selected):
    from . import adaptor as a
    names=output_names(p,selected);outputs=[];remaining=p.get('maxDecodedBytes',a.MAX_BYTES);encoded=0
    for index,(item,name) in enumerate(zip(selected,names)):
        remaining_timeout();child=directory/('batch-produce-'+str(index));child.mkdir()
        inputs={key:path for key,path in paths.items() if key[0]!='files'};inputs[('source',0)]=paths[('files',index)]
        options=subplan(p,item,remaining,inputs[('source',0)].stat().st_size)
        result=a._produce(options,child,executable,inputs)[0]
        size=result.stat().st_size
        if p['operation']=='restoreFiles':remaining-=size
        else:
            encoded+=size
            if encoded>a.MAX_COMPRESSED:fail('ZSTANDARD_BUDGET','Compressed file set exceeds the aggregate 72 MiB output limit')
        target=directory/name;target.parent.mkdir(parents=True,exist_ok=True);result.replace(target);outputs.append(target)
    # This observer uses fresh child processes and exact captured byte intent.
    observed=check(p,directory,executable,paths,outputs,selected,publication=False)
    atomic_json(directory/'files.json',observed);return [*outputs,directory/'files.json']


def check(p,directory,executable,paths,outputs,selected,publication=True):
    from . import adaptor as a
    names=output_names(p,selected);remaining=p.get('maxDecodedBytes',a.MAX_BYTES);records=[]
    admit_outputs(p,outputs[:len(selected)])
    for index,(item,name) in enumerate(zip(selected,names)):
        remaining_timeout();options=subplan(p,item,remaining,paths[('files',index)].stat().st_size)
        with tempfile.TemporaryDirectory(prefix='schemaxis-zstd-files-') as temporary:
            child=Path(temporary);inputs={key:path for key,path in paths.items() if key[0]!='files'}
            inputs[('source',0)]=paths[('files',index)]
            # Child verification has the same trusted native boundary as a
            # standalone task; paths point only at current retained captures.
            observed=a._check(options,child,executable,inputs,[outputs[index]])
        remaining-=observed['decodedBytes']
        records.append({'sourceName':item['name'],'file':name,'observations':observed})
    observed={'files':records,'decodedBytes':a.MAX_BYTES-remaining if p['operation']=='compressFiles' else p['maxDecodedBytes']-remaining,
              'metadataScope':'Relative file names and content bytes; permissions, ownership and timestamps are not archived'}
    if publication and a._json(directory/'files.json')!=observed:fail('VERIFICATION_FAILED','File-set manifest differs from current captured inputs and published bytes')
    return observed
