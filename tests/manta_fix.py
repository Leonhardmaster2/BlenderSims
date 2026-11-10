"""Make Mantaflow usable inside the pip ``bpy`` module (test environments only).

In the module build Blender initialises Mantaflow's Python module while
``import bpy`` runs, before Mantaflow has linked its class hierarchy, so
simulation scripts fail with errors such as "'LevelsetGrid' object has no
attribute 'setConst'". Re-running the registration and rebuilding the module
in the right order fixes it. A regular Blender does not need any of this.
"""

import ctypes
import subprocess
import sys


def apply():
    import bpy

    if not getattr(bpy.app, "module", False):   # a real Blender executable: nothing to do
        return False
    import glob
    import os
    so, folder = None, os.path.dirname(os.path.abspath(bpy.__file__))
    for _ in range(6):                # the binary sits a few folders above the scripts
        found = glob.glob(os.path.join(folder, "__init__*.so"))
        if found:
            so = found[0]
            break
        folder = os.path.dirname(folder)
    if so is None:
        return False
    want = {
        "PyInit_manta_main": None,
        "Pb::WrapperRegistry::instance()": None,
        "Pb::WrapperRegistry::registerBaseclasses()": None,
        "Pb::WrapperRegistry::registerMeta()": None,
        "Pb::WrapperRegistry::registerDummyTypes()": None,
    }
    out = subprocess.run(["nm", "-C", so], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[2] in want:
            want[parts[2]] = int(parts[0], 16)
    if any(v is None for v in want.values()):
        return False

    lib = ctypes.PyDLL(so)
    init = lib.PyInit_manta_main
    init.restype = ctypes.py_object
    base = ctypes.cast(init, ctypes.c_void_p).value - want["PyInit_manta_main"]

    def call(name, restype, *args):
        proto = ctypes.PYFUNCTYPE(restype, *([ctypes.c_void_p] * len(args)))
        return proto(base + want[name])(*args)

    registry = call("Pb::WrapperRegistry::instance()", ctypes.c_void_p)
    for step in ("registerBaseclasses()", "registerMeta()", "registerDummyTypes()"):
        call("Pb::WrapperRegistry::" + step, None, registry)
    sys.modules["manta"] = init()
    return True
