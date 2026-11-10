"""Retain exact loaded qualifier recipes alongside source-bound native proofs."""
import hashlib,subprocess,sys
from pathlib import Path
import schemaxis
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(output,executable):
    folder=Path(__file__).resolve().parent;recipes=Path(output)/'recipes';recipes.mkdir()
    files={Path(module.__file__).resolve() for module in list(sys.modules.values())
           if getattr(module,'__file__',None) and Path(module.__file__).resolve().parent==folder
           and Path(module.__file__).suffix=='.py'}
    hashes={}
    for path in sorted(files):
        content=path.read_bytes();(recipes/path.name).write_bytes(content)
        hashes[path.name]=hashlib.sha256(content).hexdigest()
    commit=subprocess.check_output(['git','-C',str(folder.parent),'rev-parse','HEAD'],text=True).strip()
    from_checkout=Path(schemaxis.__file__).resolve().is_relative_to(folder.parent/'src')
    return {'providerCommit':commit if from_checkout else None,'toolRepositoryCommit':commit,
            'sourceFingerprint':source_fingerprint('blender'),
            'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),
            'runtimeBinarySha256':digest(executable),'loadedToolRecipeSha256':hashes}


def verify_identity(report,executable):
    folder=Path(__file__).resolve().parent
    assert source_fingerprint('blender')==report['sourceFingerprint']
    assert hashlib.sha256(runtime_archive()).hexdigest()==report['runtimeArchiveSha256']
    assert digest(executable)==report['runtimeBinarySha256']
    assert all(digest(folder/name)==value for name,value in report['loadedToolRecipeSha256'].items())
