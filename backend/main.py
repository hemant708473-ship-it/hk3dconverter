"""HK 3D Converter API. FILE UPLOAD, JOBS and DOWNLOAD endpoints live here."""
import json, os, re, shutil, sys, threading, time, uuid, zipfile
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from converter import engine
from rigging import rig as rigger

UP, OUT = ROOT/"uploads", ROOT/"outputs"
UP.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "200")); TTL = 2*3600
app = FastAPI(title="HK 3D Converter")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
JOBS = {}

def sweep():  # remove stale temp files
    while True:
        for base in (UP, OUT):
            for d in base.iterdir():
                if d.is_dir() and time.time()-d.stat().st_mtime > TTL: shutil.rmtree(d, True)
        time.sleep(600)
threading.Thread(target=sweep, daemon=True).start()

def folder(fid):
    if not re.fullmatch(r"[0-9a-f]{12}", fid) or not (UP/fid).is_dir(): raise HTTPException(404, "File not found. Please upload again.")
    return UP/fid
def main_file(d): return d/json.loads((d/"meta.json").read_text())["main"]

def start(fn, *a):
    jid = uuid.uuid4().hex[:12]
    job = JOBS[jid] = {"id": jid, "stage": "Processing", "progress": 0, "error": None, "done": False, "files": {}, "paths": {}, "warnings": [], "rig": None}
    def run():
        try: fn(job, *a); job["done"] = True
        except engine.ConvertError as e: job["error"] = str(e)
        except OSError: job["error"] = "Not enough storage space on the server."
        except Exception as e: job["error"] = "Unexpected error: "+str(e)[:150]
    threading.Thread(target=run, daemon=True).start(); return jid

@app.get("/api/capabilities")
def caps(): return {**engine.capabilities(), "max_mb": MAX_MB}

@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    fid = uuid.uuid4().hex[:12]; d = UP/fid; d.mkdir(parents=True); total = 0; main = None; msize = 0
    try:
        for f in files:
            name = re.sub(r"[^\w.\- ]", "_", Path(f.filename or "file").name); n = 0
            if shutil.disk_usage(UP).free < 300*2**20: raise HTTPException(507, "Server storage is almost full.")
            with open(d/name, "wb") as o:
                while chunk := await f.read(1 << 20):
                    n += len(chunk); total += len(chunk)
                    if total > MAX_MB*2**20: raise HTTPException(413, f"File too large (limit {MAX_MB} MB).")
                    o.write(chunk)
            if main is None and Path(name).suffix.lower() in engine.INPUTS: main, msize = name, n
        if not main: raise HTTPException(400, engine.UNSUPPORTED)
        info = await run_in_threadpool(engine.inspect, d/main)
    except HTTPException: shutil.rmtree(d, True); raise
    except engine.ConvertError as e: shutil.rmtree(d, True); raise HTTPException(422, str(e))
    except OSError: shutil.rmtree(d, True); raise HTTPException(507, "Not enough storage space on the server.")
    (d/"meta.json").write_text(json.dumps({"main": main}))  # original file is never modified
    return {**info, "id": fid, "name": main, "size": msize}

@app.get("/api/preview/{fid}")
def preview(fid: str):
    d = folder(fid); m = main_file(d)
    if m.suffix.lower() == ".glb": return FileResponse(m, media_type="model/gltf-binary")
    p = d/"preview.glb"
    if not p.exists():
        try:
            r = engine.convert_file(m, "glb", d/"_pv"); shutil.move(str(r), p); shutil.rmtree(d/"_pv", True)
        except engine.ConvertError as e: raise HTTPException(422, str(e))
    return FileResponse(p, media_type="model/gltf-binary")

class RigReq(BaseModel): file_id: str
@app.post("/api/rig")
def rig_start(r: RigReq):
    d = folder(r.file_id)
    def do(job, fid):
        job["stage"] = "Processing"; src = main_file(d)
        if src.suffix.lower() not in (".glb",".gltf",".fbx",".obj",".dae",".stl",".ply"):
            src = engine.convert_file(src, "glb", d/"_rigsrc")
        job["stage"] = "Rigging"; job["progress"] = 30
        job["rig"] = rigger.auto_rig(src, d/"rigged.glb"); job["progress"] = 100
        shutil.rmtree(d/"_rigsrc", True)
    return {"job": start(do, r.file_id)}
@app.get("/api/rigged/{fid}")
def rigged(fid: str):
    p = folder(fid)/"rigged.glb"
    if not p.exists(): raise HTTPException(404, "No rigged model.")
    return FileResponse(p, media_type="model/gltf-binary")
@app.post("/api/rig/cancel/{fid}")
def rig_cancel(fid: str): (folder(fid)/"rigged.glb").unlink(missing_ok=True); return {"ok": True}

class ConvReq(BaseModel): file_id: str; formats: list[str]; optimize: bool = False; use_rig: bool = False
@app.post("/api/convert")
def convert(r: ConvReq):
    d = folder(r.file_id)
    if not r.formats: raise HTTPException(400, "Choose at least one output format.")
    if [f for f in r.formats if f not in engine.capabilities()["outputs"]]: raise HTTPException(400, engine.UNSUPPORTED)
    def do(job, r):
        job["stage"] = "Processing"; job["progress"] = 5
        src = d/"rigged.glb" if r.use_rig and (d/"rigged.glb").exists() else main_file(d)
        n = len(r.formats)
        for i, f in enumerate(r.formats):
            job["stage"] = "Converting + optimizing" if r.optimize else "Converting"
            job["progress"] = 10 + int(80*i/n)
            if r.use_rig and f in engine.NO_RIG: job["warnings"].append(f"{f.upper()} cannot store a skeleton; rig not included.")
            job["paths"][f] = engine.convert_file(src, f, OUT/job["id"]/f, r.optimize)  # <- CONVERSION CALL
        job["stage"] = "Preparing Download"; job["progress"] = 95
        job["files"] = {f: {"name": p.name, "size": p.stat().st_size} for f, p in job["paths"].items()}
        job["progress"] = 100
    return {"job": start(do, r)}

@app.get("/api/job/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j: raise HTTPException(404, "Job not found.")
    return {k: v for k, v in j.items() if k != "paths"}

@app.get("/api/download/{jid}/{fmt}")  # DOWNLOAD (single format)
def download(jid: str, fmt: str):
    p = JOBS.get(jid, {}).get("paths", {}).get(fmt)
    if not p or not p.exists(): raise HTTPException(404, "Converted file no longer available. Convert again.")
    return FileResponse(p, filename=p.name)

@app.get("/api/zip/{jid}")  # DOWNLOAD ALL
def zip_all(jid: str):
    j = JOBS.get(jid)
    if not j or not j["paths"]: raise HTTPException(404, "Nothing to download.")
    z = OUT/jid/"HK3D_converted.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f, p in j["paths"].items(): zf.write(p, f"{f}_{p.name}")
    return FileResponse(z, filename=z.name)

@app.post("/api/cleanup/{jid}")
def cleanup(jid: str): shutil.rmtree(OUT/re.sub(r"\W", "", jid), True); JOBS.pop(jid, None); return {"ok": True}

app.mount("/", StaticFiles(directory=ROOT/"frontend", html=True), name="web")
