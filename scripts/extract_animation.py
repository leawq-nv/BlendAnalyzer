"""
Blender-скрипт: экспорт анимации — вершины на каждом кадре.
Для каждого action экспортирует evaluated mesh vertices на каждом кадре.

Запускается: blender --background file.blend --python extract_animation.py -- [--ignore name1,name2]
"""

import bpy
import sys
import json


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def main():
    args = get_args()

    ignore_names = set()
    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))

    scene = bpy.context.scene

    # Собираем видимые меши
    mesh_objects = []
    for obj in scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type == 'MESH':
            mesh_objects.append(obj)

    if not mesh_objects:
        print("===ANIM_JSON_START===")
        print(json.dumps({"actions": [], "objects": []}))
        print("===ANIM_JSON_END===")
        return

    # Собираем actions
    all_actions = list(bpy.data.actions) if bpy.data.actions else []

    if not all_actions:
        # Проверяем есть ли keyframes
        has_kf = False
        for obj in mesh_objects:
            if obj.animation_data and obj.animation_data.action:
                has_kf = True
                break
        if not has_kf:
            print("===ANIM_JSON_START===")
            print(json.dumps({"actions": [], "objects": [obj.name for obj in mesh_objects]}))
            print("===ANIM_JSON_END===")
            return
        all_actions_info = [{"name": "Scene", "fs": scene.frame_start, "fe": scene.frame_end}]
    else:
        all_actions_info = []
        for action in all_actions:
            all_actions_info.append({
                "name": action.name,
                "fs": int(action.frame_range[0]),
                "fe": int(action.frame_range[1]),
            })

    # Макс рёбер на объект для превью
    max_edges = 3000

    result_actions = []

    for ainfo in all_actions_info:
        action_name = ainfo["name"]
        fs = ainfo["fs"]
        fe = ainfo["fe"]

        # Назначаем action
        if action_name != "Scene" and action_name in bpy.data.actions:
            action = bpy.data.actions[action_name]
            for obj in scene.objects:
                if obj.animation_data is None:
                    obj.animation_data_create()
                if obj.animation_data:
                    obj.animation_data.action = action

        # Экспортируем каждый кадр
        frames_data = {}

        for frame in range(fs, fe + 1):
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()

            frame_verts = {}  # obj_name → [[x,y,z], ...]

            for obj in mesh_objects:
                eval_obj = obj.evaluated_get(depsgraph)
                eval_mesh = eval_obj.to_mesh()

                world = obj.matrix_world

                verts = []
                for v in eval_mesh.vertices:
                    co = world @ v.co
                    verts.append([round(co.x, 3), round(co.y, 3), round(co.z, 3)])

                frame_verts[obj.name] = verts
                eval_obj.to_mesh_clear()

            frames_data[str(frame)] = frame_verts

        # Рёбра — берём с первого кадра (топология не меняется)
        scene.frame_set(fs)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        obj_edges = {}
        for obj in mesh_objects:
            eval_obj = obj.evaluated_get(depsgraph)
            eval_mesh = eval_obj.to_mesh()

            edges = []
            edge_step = max(1, len(eval_mesh.edges) // max_edges)
            for i, e in enumerate(eval_mesh.edges):
                if i % edge_step == 0:
                    edges.append([e.vertices[0], e.vertices[1]])

            obj_edges[obj.name] = edges
            eval_obj.to_mesh_clear()

        result_actions.append({
            "name": action_name,
            "frame_start": fs,
            "frame_end": fe,
            "frames": frames_data,
            "edges": obj_edges,
        })

    # Сброс
    scene.frame_set(scene.frame_start)

    result = {
        "actions": result_actions,
        "objects": [obj.name for obj in mesh_objects],
        "fps": scene.render.fps,
    }

    print("===ANIM_JSON_START===")
    print(json.dumps(result, ensure_ascii=False))
    print("===ANIM_JSON_END===")


if __name__ == "__main__":
    main()
