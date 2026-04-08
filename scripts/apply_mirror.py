"""
Blender-скрипт: применить все Mirror-модификаторы.
Запускается: blender --background file.blend --python apply_mirror.py -- output_path [--ignore name1,name2]
"""

import bpy
import sys


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def main():
    args = get_args()
    if not args:
        print("Usage: ... -- output_path [--ignore name1,name2]")
        return

    output_path = args[0]

    ignore_names = set()
    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))

    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    applied = 0
    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type != 'MESH':
            continue

        bpy.context.view_layer.objects.active = obj
        for mod in list(obj.modifiers):
            if mod.type == 'MIRROR':
                bpy.ops.object.modifier_apply(modifier=mod.name)
                applied += 1

    bpy.ops.wm.save_as_mainfile(filepath=output_path)
    print(f"===MIRROR_DONE=== {applied} mirror modifiers applied, saved to {output_path}")


if __name__ == "__main__":
    main()
