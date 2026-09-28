"""Conversion engine. FORMAT CONVERSION HAPPENS HERE (Assimp CLI, Blender for .blend input)."""
import json, re, shutil, subprocess, zipfile
from pathlib import Path

class ConvertError(Exception): pass

INPUTS = {".glb",".gltf",".fbx",".obj",".dae",".stl",".ply",".3ds",".blend"}
ASSIMP_OUT = {"glb":"glb2","gltf":"gltf2","fbx":"fbx","obj":"obj","dae":"collada","stl":"stl"}
EXT = {"glb":"glb","gltf":"gltf","fbx":"fbx","obj":"obj","dae":"dae","stl":"stl"}
NO_RIG = {"obj","stl"}  # formats that cannot store skeletons/animation
BLENDER_TOOLS = Path(__file__).with_name("blender_tools.py")
UNSUPPORTED = "Format not supported for this conversion."

def run(cmd, timeout=900):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ConvertError("The model took too long to process. Try a smaller file.")
    except FileNotFoundError:
        raise ConvertError(f"Server tool '{cmd[0]}' is not installed.")
    if p.returncode != 0:
        raise ConvertError((p.stderr or p.stdout).strip()[-300:] or "Processing tool failed.")
    return p.stdout

def capabilities():
    outs = []
    if shutil.which("assimp"):
        try: lst = run(["assimp","listexport"], 30)
        except ConvertError: lst = ""
        outs = [f for f, a in ASSIMP_OUT.items() if re.search(r"(^|\s)"+a+r"(\s|-|$)", lst)]
    blender = bool(shutil.which("blender"))
    ins = sorted(e[1:] for e in INPUTS if shutil.which("assimp") and (e != ".blend" or blender))
    return {"outputs": outs, "inputs": ins, "can_rig": blender and bool(shutil.which("assimp"))}

def _magic_ok(p: Path, ext):
    h = p.read_bytes()[:32] if p.stat().st_size else b""
    if not h: return False
    if ext == ".glb": return h[:4] == b"glTF"
    if ext == ".gltf": return h.lstrip()[:1] == b"{"
    if ext == ".fbx": return h.startswith(b"Kaydara FBX Binary") or h.startswith(b";")
    if ext == ".blend": return h.startswith(b"BLENDER") or h[:2] == b"\x1f\x8b"
    if ext == ".ply": return h.startswith(b"ply")
    if ext == ".3ds": return h[:2] == b"\x4d\x4d"
    if ext == ".dae": return b"<" in h[:8]
    return True  # obj/stl: text or binary, Assimp is the real validator

def _texture_report(p: Path):
    """Best-effort texture list + missing files for glTF/OBJ."""
    refs = []
    try:
        if p.suffix.lower() == ".gltf":
            j = json.loads(p.read_text())
            refs = [i["uri"] for k in ("images","buffers") for i in j.get(k, []) if "uri" in i and not i["uri"].startswith("data:")]
        elif p.suffix.lower() == ".obj":
            for m in re.findall(r"(?m)^mtllib\s+(.+)$", p.read_text(errors="ignore")):
                mt = p.parent/m.strip()
                refs.append(m.strip())
                if mt.exists():
                    refs += re.findall(r"(?mi)^\s*map_\w+\s+(?:-\S+\s+)*(.+)$", mt.read_text(errors="ignore"))
    except Exception: pass
    refs = [r.strip() for r in refs]
    return refs, [r for r in refs if not (p.parent/r).exists()]

def inspect(p: Path):
    """Validates the file for real (magic bytes + parse by Assimp/Blender) and reports stats."""
    ext = p.suffix.lower()
    if ext not in INPUTS: raise ConvertError(UNSUPPORTED)
    if not _magic_ok(p, ext): raise ConvertError("This file looks corrupted or is not really a "+ext[1:].upper()+" model.")
    info = {"format": ext[1:].upper(), "meshes": None, "materials": None, "textures": None, "warnings": []}
    if ext == ".blend":
        if not shutil.which("blender"): raise ConvertError(UNSUPPORTED)
        out = run(["blender","-b",str(p),"-P",str(BLENDER_TOOLS),"--","info"], 120)
        m = re.search(r"RESULT:(\{.*\})", out)
        if not m: raise ConvertError("Blender could not read this file.")
        info.update(json.loads(m.group(1)))
    else:
        if not shutil.which("assimp"): raise ConvertError("Conversion engine (Assimp) is not installed on the server.")
        try: out = run(["assimp","info",str(p)], 120)
        except ConvertError: raise ConvertError("The model could not be read. It may be corrupted.")
        g = lambda k: (lambda m: int(m.group(1)) if m else None)(re.search(k+r"\D{0,20}(\d+)", out, re.I))
        info["meshes"], info["materials"] = g(r"meshes"), g(r"materials")
        info["textures"] = g(r"embedded textures|textures")
        if info["meshes"] == 0: raise ConvertError("No 3D mesh found in this file.")
    refs, missing = _texture_report(p)
    if refs and info["textures"] is None: info["textures"] = len(refs)
    if missing: info["warnings"].append("Missing textures/files: "+", ".join(missing[:5]))
    return info

def convert_file(src, fmt, outdir: Path, optimize=False) -> Path:
    """Convert src -> fmt. Returns the deliverable (single file, or a ZIP when the format writes several files)."""
    if fmt not in ASSIMP_OUT: raise ConvertError(UNSUPPORTED)
    if not shutil.which("assimp"): raise ConvertError("Conversion engine (Assimp) is not installed on the server.")
    src = Path(src); outdir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+","_", src.stem) or "model"
    tmp = None
    if src.suffix.lower() == ".blend":  # .blend is read by Blender and handed to Assimp as GLB
        if not shutil.which("blender"): raise ConvertError(UNSUPPORTED)
        tmp = outdir.parent/("_blend_"+outdir.name+".glb")
        run(["blender","-b",str(src),"-P",str(BLENDER_TOOLS),"--","blend2glb",str(tmp)])
        src = tmp
    dst = outdir/f"{stem}.{EXT[fmt]}"
    cmd = ["assimp","export",str(src),str(dst),"-f"+ASSIMP_OUT[fmt]]
    if optimize: cmd += ["-jiv","-icl","-rrm"]  # join vertices, cache locality, drop duplicate materials
    try: run(cmd)
    finally:
        if tmp: tmp.unlink(missing_ok=True)
    if not dst.exists() or dst.stat().st_size == 0:
        raise ConvertError("The converter produced no output. This model may not be convertible to "+fmt.upper()+".")
    files = [f for f in outdir.rglob("*") if f.is_file()]
    if len(files) == 1: return dst
    z = outdir/f"{stem}_{fmt}.zip"
    with zipfile.ZipFile(z,"w",zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f != z: zf.write(f, f.relative_to(outdir))
    return z
