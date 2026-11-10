"""Portable native CAM document plus its finite regeneration preference profile."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.errors import fail

PROFILE=b'''<?xml version="1.0" encoding="UTF-8"?>
<FCParameters><FCParamGroup Name="Root"><FCParamGroup Name="BaseApp"><FCParamGroup Name="Preferences"><FCParamGroup Name="Mod"><FCParamGroup Name="CAM"><FCFloat Name="LibAreaCurveAccuracy" Value="0.00001"/><FCParamGroup Name="Tools"><FCText Name="ToolPath">cam-assets</FCText></FCParamGroup><FCParamGroup Name="Migration"><FCText Name="OfferedToMigrateCAMAssets">v1-1</FCText></FCParamGroup></FCParamGroup></FCParamGroup></FCParamGroup></FCParamGroup></FCParamGroup></FCParameters>
'''
README=b'''Editable FreeCAD CAM project (FreeCAD 1.1.4)

Extract all files into one directory. Run from that directory and launch
FreeCAD with this separate profile:

  FreeCAD --user-cfg preferences.cfg machining.FCStd

Activate the CAM workbench before editing or regenerating operations. Its curve
accuracy must be 0.00001 mm. The Job also retains GeometryTolerance=0.00001 mm.
The carried profile keeps the local tool assets in this extracted directory;
FreeCAD 1.1's optional asset-migration offer is already handled for this profile.
This isolated profile does not change your usual FreeCAD preferences. A plain
FCStd opened in an arbitrary session does not preserve this global CAM setting.

Recompute and repost after an edit; independently verify the changed program
against the desired CAD solid before manufacture. The supplied program belongs
to the original verified design. It is not updated automatically by a CAD edit.
This bundle does not certify your machine, tool, fixture or controller setup.
'''
MEMBERS=('machining.FCStd','preferences.cfg','README.txt','cam-assets/')
REDUCED_README=README.replace(
    b'FreeCAD --user-cfg preferences.cfg machining.FCStd',
    b'FreeCAD --user-cfg preferences.cfg open-cam.FCMacro')+b'''
This project uses the supplied, finite SCXReducedDrill Python tool extension.
The launcher registers that extension before opening the native document.
Keep its Python file and launcher beside machining.FCStd. Opening the FCStd
alone in a session without the extension does not support tool regeneration.
Automatic Schemaxis use checks both files against its installed extension
before importing code or opening this document. Replaced bundle code is refused.
'''


def contents(prepared=None):
    from .cam_reduced import needed,module_bytes,FILENAME,LAUNCHER_NAME,LAUNCHER
    reduced=prepared is not None and needed(prepared)
    records={'preferences.cfg':PROFILE,'README.txt':REDUCED_README if reduced else README,'cam-assets/':b''}
    if reduced:records.update({FILENAME:module_bytes(),LAUNCHER_NAME:LAUNCHER})
    return records


def publish(directory,runtime,prepared=None):
    directory=Path(directory);(directory/'preferences.cfg').write_bytes(PROFILE)
    with ZipFile(directory/'cam-project.zip','w',ZIP_DEFLATED) as archive:
        archive.write(directory/'machining.FCStd','machining.FCStd')
        for name,data in contents(prepared).items():archive.writestr(name,data)
    record={'runtime':runtime,'artifacts':artifacts(directory)};atomic_json(directory/'verification.json',record)
    return record


def artifacts(directory):
    directory=Path(directory)
    return [{'file':str(directory/filename),'kind':kind,'sha256':file_digest(directory/filename),**({'units':'mm'} if kind!='archive' else {})} for filename,kind in [('machining.FCStd','cadScene'),('program.ngc','machineCode'),('remaining.brep','cad'),('cam-project.zip','archive')]]


def verify(directory,prepared=None):
    directory=Path(directory)
    if (directory/'preferences.cfg').read_bytes()!=PROFILE:fail('VERIFICATION_FAILED','Native regeneration preference profile differs')
    path=directory/'cam-project.zip'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64*1024*1024:fail('VERIFICATION_FAILED','Missing, linked or oversized editable CAM bundle')
    expected=contents(prepared)
    with ZipFile(path) as archive:
        if tuple(archive.namelist())!=('machining.FCStd',*expected) or any(i.file_size>32*1024*1024 for i in archive.infolist()):fail('VERIFICATION_FAILED','Editable CAM bundle membership differs')
        # Installed bytes are authority, including the launcher and complete
        # self-contained native extension. No submitted Python is imported here.
        if (any(archive.read(name)!=data for name,data in expected.items()) or
                archive.read('machining.FCStd')!=(directory/'machining.FCStd').read_bytes()):fail('VERIFICATION_FAILED','Editable CAM bundle differs from its verified native document, installed tool extension or finite profile')
    return artifacts(directory)
