"""Build exact NumPy/OpenBLAS inside the separately capped Debian builder.

Fixed /build and /opt/runtime are disposable build-container paths. The caller
owns the memory/no-swap/CPU/PID/deadline envelope and captures its kernel proof.
"""
from pathlib import Path,PurePosixPath
import hashlib,json,os,shutil,subprocess,tarfile,time
root=Path('/build');root.mkdir(exist_ok=True)
apps=root/'apps';apps.mkdir()
(root/'tmp').mkdir()
(root/'home').mkdir(exist_ok=True)
logs=root/'logs';logs.mkdir()
records=[]
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def unpack(path,expected,name):
 if sha(path)!=expected:raise RuntimeError('Build source SHA differs')
 with tarfile.open(path) as archive:
  members=archive.getmembers();size=0
  if len(members)>100000:raise RuntimeError('Too many source members')
  for member in members:
   p=PurePosixPath(member.name)
   if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!=name or member.isdev() or member.isfifo():raise RuntimeError('Unsafe source member')
   if member.isfile():size+=member.size
   if size>512*1024**2:raise RuntimeError('Source expansion exceeds bound')
  archive.extractall(apps,filter='data')
 return apps/name
def run(name,command,cwd,extra=None):
 start=time.monotonic()
 env={**os.environ,'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/build/home','LC_ALL':'C','TMPDIR':'/build/tmp',
  'CFLAGS':'-O2 -ffile-prefix-map=/build=/build','CXXFLAGS':'-O2 -ffile-prefix-map=/build=/build',
  'FFLAGS':'-O2 -ffile-prefix-map=/build=/build',**(extra or {})}
 with (logs/(name+'.log')).open('wb') as log:
  p=subprocess.Popen([str(x) for x in command],cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  tee=subprocess.Popen(['tee','-a','/transcript.log'],stdin=p.stdout,stdout=log);p.stdout.close()
  rc=p.wait(timeout=1200);trc=tee.wait(timeout=10)
 records.append({'name':name,'exitCode':rc,'teeExitCode':trc,'wallSeconds':time.monotonic()-start,'command':[str(x) for x in command]})
 (root/'stages.json').write_text(json.dumps(records,indent=2)+'\n')
 if rc or trc:raise RuntimeError('Native build failed '+name)
blas=unpack(Path('/inputs/openblas.tar.gz'),'cd7e129868320cc2d033afa920e31202dfe0b8066a5b66661900ccc0f197dfed','OpenBLAS-0.3.34')
np=unpack(Path('/inputs/numpy.tar.gz'),'9a94cf751c9ad8ebaa835bcd3d40dacf8534ad086b88c38029b65123c7999d2a','numpy-2.5.4')
flags=['TARGET=HASWELL','DYNAMIC_ARCH=0','USE_THREAD=0','NUM_THREADS=1','NO_AFFINITY=1','NO_LAPACKE=1','FC=gfortran-14']
run('openblas-build',['make','-j2',*flags],blas)
run('openblas-install',['make',*flags,'PREFIX=/opt/runtime','install'],blas)
wheels=root/'wheels';wheels.mkdir()
run('numpy-wheel',['/usr/local/bin/python3','-m','pip','wheel','--no-index','--no-build-isolation','--no-deps','--wheel-dir',wheels,
 '-Csetup-args=-Dblas=openblas','-Csetup-args=-Dlapack=openblas','-Ccompile-args=-j2',np],root,
 {'PKG_CONFIG_PATH':'/opt/runtime/lib/pkgconfig','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
wheel,=wheels.glob('numpy-2.5.4-*.whl')
# GCC runtime closure is copied from this pinned Debian build image, never host.
libs=[]
for name in ('libgfortran.so.5','libquadmath.so.0','libstdc++.so.6','libgcc_s.so.1'):
 source=Path('/usr/lib/x86_64-linux-gnu')/name
 target=Path('/opt/runtime/lib')/name
 shutil.copyfile(source.resolve(),target);libs.append({'file':name,'sha256':sha(target)})
licences=Path('/opt/runtime/LICENCES');licences.mkdir(exist_ok=True)
for package in ('libgfortran5','libquadmath0','libstdc++6','libgcc-s1'):
 source=Path('/usr/share/doc')/package/'copyright'
 shutil.copyfile(source.resolve(),licences/(package+'-copyright'))
for name in ('GPL-3','GPL-2','LGPL-2.1'):
 shutil.copyfile(Path('/usr/share/common-licenses')/name,licences/name)
shutil.copyfile(blas/'LICENSE',licences/'OpenBLAS-LICENSE')
provenance={'numpy':'2.5.4','numpySourceSha256':'9a94cf751c9ad8ebaa835bcd3d40dacf8534ad086b88c38029b65123c7999d2a',
 'openblas':'0.3.34','openblasSourceSha256':'cd7e129868320cc2d033afa920e31202dfe0b8066a5b66661900ccc0f197dfed',
 'openblasFlags':flags,'prefix':'/opt/runtime','wheel':{'file':wheel.name,'sha256':sha(wheel)},'libraries':libs,
 'recipeSha256':sha(__file__),'scope':'native build only; image compatibility and fixture qualification pending'}
(root/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print(json.dumps({'built':True,'wheelSha256':sha(wheel)}))
