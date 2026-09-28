# Run inside Blender: blender -b [file.blend] -P blender_tools.py -- <mode> [args]
import bpy, sys, json
a = sys.argv[sys.argv.index("--")+1:]
if a[0] == "blend2glb":
    bpy.ops.export_scene.gltf(filepath=a[1], export_format='GLB')
elif a[0] == "info":
    print("RESULT:"+json.dumps({"meshes": len([o for o in bpy.data.objects if o.type=='MESH']),
        "materials": len(bpy.data.materials), "textures": len(bpy.data.images)}))
