"""Finite production bridge for independently constructed simulation caches.

Only installed fresh-scene construction may create FeatureCaches. Saved receipts
are observations, never constructor capabilities. The caller must bind the whole
master DAG/source intent and admit source bytes before fresh construction, compare
files before submitted native open, then check submitted physics/geometry.
"""
import copy
import hashlib
from pathlib import Path
import stat
import bpy
from schemaxis.errors import fail
from . import cache_policy as policy
from . import cache_native as native
from . import cache_fidelity_native as fidelity


def _dependencies(sources):
    result=[];total=0
    for identity,source in sorted(sources.items()):
        path=Path(source['retained'])
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            fail('INVALID_CACHE','captured cache dependency must be a plain admitted file',identity)
        size=path.stat().st_size;total+=size
        if total>policy.MAX_BYTES:fail('RESOURCE_BUDGET_EXCEEDED','cache dependencies exceed64 MiB')
        digest=hashlib.sha256();read=0
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1<<20),b''):
                read+=len(block)
                if read>size:fail('INPUT_CHANGED','cache dependency grew during read',identity)
                digest.update(block)
        if read!=size or digest.hexdigest()!=source['sha256']:
            fail('INPUT_CHANGED','cache dependency differs from admitted source',identity)
        result.append({'id':identity,'sha256':digest.hexdigest(),'bytes':size})
    return result


def _inventory(folder, *, publication_directory=None):
    if folder.is_symlink():fail('INVALID_CACHE','managed cache directory cannot be a symlink',str(folder))
    return policy.inventory(folder,publication_directory=publication_directory) if folder.exists() else {}


class FeatureCaches:
    def __init__(self,spec,objects,sources,project_path,*,event=None):
        self.project_path=Path(project_path).absolute();self.scene=bpy.context.scene
        self.folder=self.project_path.parent/('blendcache_'+self.project_path.stem)
        self.records=[];self.tokens=[];self._files_admitted_project=None
        requests=spec.get('simulationCaches',[])
        if not requests:return
        constructor={'version':'schemaxis.blender.cache-constructor/1',
                     'intent':copy.deepcopy(spec),'dependencies':_dependencies(sources),
                     'runtime':{'version':[5,2,3],'build':'e13b728c6880'}}
        compiled=[]
        for request in requests:
            logical=request['object'];name=''
            if request['kind']=='cloth':
                obj=objects.get(logical)
                if obj is None or self.scene.objects.get(obj.name)!=obj:
                    fail('INVALID_CACHE','cloth must nominate an actual fresh owning-scene handle',logical)
                name=obj.name
            compiled.append(policy.plan({**request,'object':name,'scene':self.scene.name},constructor))
        if _inventory(self.folder):fail('INVALID_CACHE','fresh cache construction cannot inherit existing managed payloads')
        previous=self.scene.frame_current
        try:
            self.tokens=native.prepare_consumers(compiled,self.scene,self.project_path)
            self.records=[native.bake(token,event=event) for token in self.tokens]
        finally:
            self.scene.frame_set(spec['currentFrame'] if 'currentFrame' in spec else previous)
        expected={name:info for record in self.records for name,info in record['files'].items()}
        if _inventory(self.folder)!=expected:fail('VERIFICATION_FAILED','fresh managed cache directory has unowned payloads')
        # Persist the declared current frame after all observations, without backups.
        native._save(self.project_path)

    def observation(self):
        return copy.deepcopy(self.records)

    def publication_records(self):
        result=[]
        for record in self.records:
            for name,info in sorted(record['files'].items()):
                path=self.folder/name
                result.append({'kind':'simulationCache','cacheId':record['plan']['id'],
                               'relativePath':str(path.relative_to(self.project_path.parent)),
                               'file':str(path),'sha256':info['sha256'],'bytes':info['bytes']})
        return result

    def nominated_cache_handles(self,scene=None):
        """Nominate fresh handles, or candidate handles AFTER successful checks."""
        if scene is None:return [(token.cache,token.input_fingerprint) for token in self.tokens]
        if getattr(self,'_verified_scene',None)!=scene:
            fail('VERIFICATION_CONTEXT_REQUIRED','submitted cache nominations require whole fresh-reference checks')
        return list(self._submitted_nominations)

    def verify_fresh_files(self,submitted_project_path):
        """Call on the FRESH reference before opening any submitted native file."""
        self._files_admitted_project=None;self._verified_scene=None
        submitted=Path(submitted_project_path).absolute()
        if submitted.name!=self.project_path.name:
            fail('VERIFICATION_FAILED','cache reference and submitted visit basenames differ')
        folder=submitted.parent/('blendcache_'+submitted.stem)
        actual,expected=_inventory(folder,publication_directory=submitted.parent),_inventory(self.folder)
        self._files_admitted_project=None
        if actual!=expected:fail('VERIFICATION_FAILED','whole managed cache payload differs from fresh construction')
        self._files_admitted_project=submitted
        return actual

    def verify_submitted(self,scene,*,project_path=None):
        """After whole-source/file admission, compare to this fresh trusted reference."""
        self._verified_scene=None;self._submitted_nominations=[]
        submitted=Path(project_path or bpy.data.filepath).absolute()
        if submitted!=self._files_admitted_project:
            fail('VERIFICATION_CONTEXT_REQUIRED','submitted cache geometry requires prior whole fresh-file admission')
        for token,record in zip(self.tokens,self.records):
            native.verify_inputs(scene,token.plan,token.input_fingerprint,
                                 project_path=submitted)
            frames=list(range(token.plan['frameStart'],token.plan['frameEnd']+1))
            actual=fidelity.observe(scene,native.consumer_names(scene,token.plan),frames)
            fidelity.compare(actual,record['geometry'])
            self._submitted_nominations.append((native.resolve(scene,token.plan),token.input_fingerprint))
        self._verified_scene=scene
        return True
