"""Remove package installation tools from the final runtime filesystem."""

from pathlib import Path
import shutil

for directory in (Path("/usr/bin"), Path("/usr/local/bin"), Path("/usr/sbin")):
    for pattern in ("apt*", "dpkg*", "pip*", "easy_install*", "ensurepip*"):
        for path in directory.glob(pattern):
            if path.is_file() or path.is_symlink():
                path.unlink()
for root in (Path("/usr/local/lib/python3.14"),):
    for directory in (root, root / "site-packages"):
        for pattern in ("pip", "pip-*.dist-info", "ensurepip"):
            for path in directory.glob(pattern):
                if path.is_dir():
                    shutil.rmtree(path)
for path in (Path("/var/lib/apt/lists"), Path("/var/cache/apt")):
    if path.exists():
        shutil.rmtree(path)
