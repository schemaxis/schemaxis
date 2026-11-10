"""Assemble reviewed, digest-locked build inputs; never fetch or execute an app."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile


def checked(path, variable):
    expected = os.environ[variable]
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SystemExit(f"{variable} must be a pinned SHA-256")
    with Path(path).open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected:
        raise SystemExit(f"{variable} does not match the supplied artifact")


checked("/inputs/runtime.tar", "RUNTIME_SHA256")
checked("/inputs/schemaxis.whl", "WHEEL_SHA256")
family = os.environ["RUNTIME_FAMILY"]
version = os.environ["RUNTIME_VERSION"]
stage = Path("/assembled")
stage.mkdir()
with tarfile.open("/inputs/runtime.tar") as archive:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SystemExit("Unsafe runtime archive path")
        if path.parts[0] not in {"runtime", "site-packages"}:
            raise SystemExit("Runtime archive must contain runtime/ or site-packages/")
        if member.isdev() or member.isfifo():
            raise SystemExit("Runtime archive contains a special file")
    archive.extractall(stage, filter="data")
runtime = stage / "runtime"
provenance = json.loads((runtime / "provenance.json").read_text())
if provenance.get("family") != family or provenance.get("version") != version:
    raise SystemExit("Runtime provenance does not match the image family/version")
if not provenance.get("sources") or not provenance.get("build"):
    raise SystemExit("Runtime source and build provenance are required")
if not (runtime / "LICENCES").is_dir() or not any((runtime / "LICENCES").iterdir()):
    raise SystemExit("Runtime licence texts and dependency notices are required")

site = stage / "site-packages"
site.mkdir(exist_ok=True)
with zipfile.ZipFile("/inputs/schemaxis.whl") as wheel:
    names = wheel.namelist()
    metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
    wheel_metadata = [name for name in names if name.endswith(".dist-info/WHEEL")]
    if len(metadata) != 1 or "\nName: schemaxis\n" not in wheel.read(metadata[0]).decode():
        raise SystemExit("Expected a Schemaxis wheel")
    if len(wheel_metadata) != 1 or "Root-Is-Purelib: true" not in wheel.read(wheel_metadata[0]).decode():
        raise SystemExit("Expected a pure-Python Schemaxis wheel")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SystemExit("Unsafe wheel path")
        if path.parts[0].endswith(".data"):
            raise SystemExit("Wheel data relocation is not supported")
        target = site.joinpath(*path.parts)
        if target.exists():
            raise SystemExit("Wheel conflicts with bundled packages")
    wheel.extractall(site)

locations = {
    "blender": {"blender": "/opt/runtime/bin/blender"},
    "freecad": {"freecad": "/opt/runtime/bin/freecadcmd"},
    "exiftool": {"exiftool": "/opt/runtime/bin/exiftool"},
    "sympy": {"sympy": "/usr/local/bin/python3"},
    "numpy": {"numpy": "/usr/local/bin/python3"},
    "ffmpeg": {"ffmpeg": "/opt/runtime/bin/ffmpeg"},
    "paraview": {"roots": ["/opt/runtime"]},
}
config = stage / "config"
config.mkdir()
(config / "runtime.json").write_text(json.dumps({"version": 1, "locations": locations[family]}) + "\n")
(config / "inputs.json").write_text(json.dumps({
    "family": family, "version": version,
    "runtimeSha256": os.environ["RUNTIME_SHA256"],
    "wheelSha256": os.environ["WHEEL_SHA256"],
    "qualification": "pending", "measurements": None,
}) + "\n")
