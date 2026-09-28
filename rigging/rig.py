"""Auto-rigging wrapper. RIGGING HAPPENS HERE (runs blender_rig.py inside headless Blender)."""
import json, re, shutil, subprocess
from pathlib import Path
SCRIPT = Path(__file__).with_name("blender_rig.py")

def auto_rig(src: Path, dst: Path) -> dict:
    """src: GLB/GLTF/FBX/OBJ/DAE/STL/PLY. Returns {ok, reason?, bones?}. Never fakes success."""
    if not shutil.which("blender"):
        return {"ok": False, "reason": "Auto-rigging needs Blender, which is not installed on the server."}
    try:
        p = subprocess.run(["blender","-b","-P",str(SCRIPT),"--",str(src),str(dst)], capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Rigging took too long."}
    m = re.search(r"RESULT:(\{.*\})", p.stdout)
    if not m: return {"ok": False, "reason": "Rigging failed unexpectedly."}
    r = json.loads(m.group(1))
    if r.get("ok") and not Path(dst).exists(): return {"ok": False, "reason": "Rigged file was not produced."}
    return r
