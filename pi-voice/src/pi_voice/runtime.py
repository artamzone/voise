"""Load project-local NVIDIA DLLs without changing the system PATH."""
import os
from pathlib import Path
import sys

_DLL_HANDLES = []


def configure_cuda():
    roots = [Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"]
    directories = sorted({p.parent for root in roots if root.exists()
                          for p in root.rglob("*.dll")})
    if os.name == "nt":
        for directory in directories:
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        # CTranslate2 also loads DLLs dynamically; PATH is process-local only.
        if directories:
            os.environ["PATH"] = os.pathsep.join(map(str, directories)) + os.pathsep + os.environ.get("PATH", "")
    return directories
