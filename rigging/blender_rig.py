# Headless Blender: detect humanoid (heuristic), build skeleton, auto-weight, export GLB.
import bpy, sys, json
from mathutils import Vector
src, dst = sys.argv[sys.argv.index("--")+1:][:2]
def out(d): print("RESULT:"+json.dumps(d)); sys.stdout.flush(); sys.exit(0)
bpy.ops.wm.read_factory_settings(use_empty=True)
ext = src.lower().rsplit(".",1)[-1]
try:
    {"glb":lambda:bpy.ops.import_scene.gltf(filepath=src),"gltf":lambda:bpy.ops.import_scene.gltf(filepath=src),
     "fbx":lambda:bpy.ops.import_scene.fbx(filepath=src),"obj":lambda:bpy.ops.wm.obj_import(filepath=src),
     "dae":lambda:bpy.ops.wm.collada_import(filepath=src),"stl":lambda:bpy.ops.wm.stl_import(filepath=src),
     "ply":lambda:bpy.ops.wm.ply_import(filepath=src)}[ext]()
except Exception as e:
    out({"ok":False,"reason":"Could not import the model for rigging: "+str(e)[:120]})
objs = list(bpy.context.scene.objects)
if any(o.type=='ARMATURE' for o in objs): out({"ok":False,"reason":"This model already has a skeleton."})
meshes = [o for o in objs if o.type=='MESH']
if not meshes: out({"ok":False,"reason":"No mesh found to rig."})
pts = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
mn = Vector((min(p.x for p in pts),min(p.y for p in pts),min(p.z for p in pts)))
mx = Vector((max(p.x for p in pts),max(p.y for p in pts),max(p.z for p in pts)))
h = mx.z-mn.z; wx = mx.x-mn.x; wy = mx.y-mn.y
if h <= 0: out({"ok":False,"reason":"Model has no height."})
span, depth = max(wx,wy), min(wx,wy)
ax = Vector((1,0,0)) if wx >= wy else Vector((0,1,0))
# Heuristic: upright, arms-out or A-pose proportions, thin front-to-back. Not a guarantee.
if not (0.4 <= span/h <= 1.3 and depth/h <= 0.45):
    out({"ok":False,"reason":"This model does not look like an upright humanoid (standing person in T-pose or A-pose). Automatic rigging only supports humanoids."})
tpose = span/h >= 0.85; s = span/h/2; drop = 0 if tpose else 0.25
arm = bpy.data.armatures.new("Rig"); rig = bpy.data.objects.new("Rig", arm)
bpy.context.collection.objects.link(rig); bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
c = Vector(((mn.x+mx.x)/2,(mn.y+mx.y)/2,mn.z))
def P(a,z): return c + ax*(a*h) + Vector((0,0,z*h))
def bone(n,h0,t0,par=None):
    b = arm.edit_bones.new(n); b.head = P(*h0); b.tail = P(*t0)
    if par: b.parent = arm.edit_bones[par]
bone("hips",(0,.50),(0,.56)); bone("spine",(0,.56),(0,.68),"hips"); bone("chest",(0,.68),(0,.80),"spine")
bone("neck",(0,.80),(0,.86),"chest"); bone("head",(0,.86),(0,.98),"neck")
for sd,k in (("L",1),("R",-1)):
    bone("upperarm."+sd,(k*.06,.78),(k*s*.55,.78-drop*.5),"chest"); bone("forearm."+sd,(k*s*.55,.78-drop*.5),(k*s*.95,.78-drop),"upperarm."+sd)
    bone("thigh."+sd,(k*.07,.50),(k*.07,.27),"hips"); bone("shin."+sd,(k*.07,.27),(k*.07,.05),"thigh."+sd); bone("foot."+sd,(k*.07,.05),(k*.07,.01),"shin."+sd)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.select_all(action='DESELECT')
for m in meshes: m.select_set(True)
rig.select_set(True); bpy.context.view_layer.objects.active = rig
try: bpy.ops.object.parent_set(type='ARMATURE_AUTO')
except RuntimeError: out({"ok":False,"reason":"Automatic weight painting failed (mesh may be non-manifold or too complex)."})
if not any(len(m.vertex_groups) for m in meshes): out({"ok":False,"reason":"Weight painting produced no bone weights."})
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_skins=True)
out({"ok":True,"humanoid":True,"bones":len(arm.bones),"pose":"T-pose" if tpose else "A-pose"})
