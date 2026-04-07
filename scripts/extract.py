"""
Blender-скрипт для извлечения данных из .blend файла.
Запускается через: blender --background file.blend --python extract.py -- [args]
Выводит JSON в stdout с маркером для парсинга.
"""

import bpy
import json
import sys
import math
from collections import Counter


def get_args():
    """Получить аргументы после '--' в командной строке Blender."""
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def extract_object_transform(obj):
    loc = obj.location
    rot = obj.rotation_euler
    scale = obj.scale
    return {
        "position": [round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)],
        "rotation_deg": [
            round(math.degrees(rot.x), 2),
            round(math.degrees(rot.y), 2),
            round(math.degrees(rot.z), 2),
        ],
        "scale": [round(scale.x, 4), round(scale.y, 4), round(scale.z, 4)],
    }


def extract_mesh_data(obj):
    """Извлечь данные меша."""
    mesh = obj.data
    mesh.calc_loop_triangles()

    verts = len(mesh.vertices)
    edges = len(mesh.edges)
    faces = len(mesh.polygons)

    # Подсчёт типов полигонов
    poly_sizes = Counter()
    for poly in mesh.polygons:
        n = len(poly.vertices)
        if n == 3:
            poly_sizes["tris"] += 1
        elif n == 4:
            poly_sizes["quads"] += 1
        else:
            poly_sizes["ngons"] += 1

    # Bounding box и dimensions
    bbox = [list(corner) for corner in obj.bound_box]
    dims = obj.dimensions

    # Vertex groups
    vgroups = [vg.name for vg in obj.vertex_groups]

    # UV maps
    uv_layers = [uv.name for uv in mesh.uv_layers]

    # Loose geometry
    verts_in_faces = set()
    for poly in mesh.polygons:
        verts_in_faces.update(poly.vertices)

    edges_in_faces = set()
    for poly in mesh.polygons:
        for i in range(len(poly.vertices)):
            v1 = poly.vertices[i]
            v2 = poly.vertices[(i + 1) % len(poly.vertices)]
            edges_in_faces.add(tuple(sorted((v1, v2))))

    loose_verts = verts - len(verts_in_faces)
    loose_edges = 0
    for edge in mesh.edges:
        key = tuple(sorted((edge.vertices[0], edge.vertices[1])))
        if key not in edges_in_faces:
            loose_edges += 1

    # Non-manifold edges (рёбра, принадлежащие != 2 полигонам)
    edge_face_count = Counter()
    for poly in mesh.polygons:
        for i in range(len(poly.vertices)):
            v1 = poly.vertices[i]
            v2 = poly.vertices[(i + 1) % len(poly.vertices)]
            edge_face_count[tuple(sorted((v1, v2)))] += 1

    non_manifold = sum(1 for count in edge_face_count.values() if count != 2)

    # Topology density — разделим bounding box на зоны по высоте (Z)
    density_zones = {}
    if verts > 0 and dims.z > 0:
        z_coords = [v.co.z for v in mesh.vertices]
        z_min, z_max = min(z_coords), max(z_coords)
        z_range = z_max - z_min
        if z_range > 0:
            zone_count = min(5, max(1, verts // 100))
            zone_size = z_range / zone_count
            zone_labels = ["bottom", "lower", "middle", "upper", "top"]
            for i in range(zone_count):
                z_low = z_min + i * zone_size
                z_high = z_low + zone_size
                count = sum(1 for z in z_coords if z_low <= z < z_high or (i == zone_count - 1 and z == z_high))
                label = zone_labels[i] if i < len(zone_labels) else f"zone_{i}"
                density_zones[label] = count

    # Экспорт геометрии для 3D-превью (с применёнными модификаторами)
    world_matrix = obj.matrix_world
    normal_matrix = world_matrix.to_3x3().normalized()

    # Получаем меш с применёнными модификаторами
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    # Вершины в world-space
    world_verts = []
    for v in eval_mesh.vertices:
        co = world_matrix @ v.co
        world_verts.append([round(co.x, 4), round(co.y, 4), round(co.z, 4)])

    # Рёбра (с децимацией)
    preview_edges = []
    max_edges_for_preview = 5000
    edge_step = max(1, len(eval_mesh.edges) // max_edges_for_preview)
    for i, edge in enumerate(eval_mesh.edges):
        if i % edge_step != 0:
            continue
        preview_edges.append([edge.vertices[0], edge.vertices[1]])

    # Полигоны для solid-режима (без триангуляции): [verts_list, nx, ny, nz, mat_idx]
    preview_faces = []
    max_faces_for_preview = 8000
    face_step = max(1, len(eval_mesh.polygons) // max_faces_for_preview)
    for i, poly in enumerate(eval_mesh.polygons):
        if i % face_step != 0:
            continue
        n = normal_matrix @ poly.normal
        preview_faces.append([
            list(poly.vertices),
            round(n.x, 3), round(n.y, 3), round(n.z, 3),
            poly.material_index,
        ])

    # Цвета материалов (Base Color)
    mat_colors = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat and mat.use_nodes and mat.node_tree:
            found = False
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    bc = node.inputs.get("Base Color")
                    if bc and not bc.is_linked:
                        val = bc.default_value
                        mat_colors.append([round(val[0], 3), round(val[1], 3), round(val[2], 3)])
                    else:
                        mat_colors.append([0.5, 0.5, 0.5])
                    found = True
                    break
            if not found:
                mat_colors.append([0.5, 0.5, 0.5])
        else:
            mat_colors.append([0.5, 0.5, 0.5])

    eval_obj.to_mesh_clear()

    return {
        "vertices": verts,
        "edges": edges,
        "faces": faces,
        "tris": poly_sizes.get("tris", 0),
        "quads": poly_sizes.get("quads", 0),
        "ngons": poly_sizes.get("ngons", 0),
        "dimensions": [round(dims.x, 4), round(dims.y, 4), round(dims.z, 4)],
        "bounding_box_min": [round(min(c[i] for c in bbox), 4) for i in range(3)],
        "bounding_box_max": [round(max(c[i] for c in bbox), 4) for i in range(3)],
        "vertex_groups": vgroups,
        "uv_layers": uv_layers,
        "loose_vertices": loose_verts,
        "loose_edges": loose_edges,
        "non_manifold_edges": non_manifold,
        "density_zones": density_zones,
        "preview_verts": world_verts,
        "preview_edges": preview_edges,
        "preview_faces": preview_faces,
        "mat_colors": mat_colors,
    }


def extract_materials(obj):
    """Извлечь материалы объекта."""
    materials = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            materials.append({"name": "(empty slot)", "type": None})
            continue

        mat_info = {
            "name": mat.name,
            "use_nodes": mat.use_nodes,
        }

        if mat.use_nodes and mat.node_tree:
            # Найти основной шейдер
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    inputs = {}
                    for inp in node.inputs:
                        if inp.is_linked:
                            # Найти подключённую текстуру
                            for link in mat.node_tree.links:
                                if link.to_socket == inp and link.from_node.type == 'TEX_IMAGE':
                                    img = link.from_node.image
                                    inputs[inp.name] = f"[Texture: {img.name if img else 'None'}]"
                                    break
                            else:
                                inputs[inp.name] = "[linked node]"
                        elif hasattr(inp, 'default_value'):
                            val = inp.default_value
                            if hasattr(val, '__len__'):
                                inputs[inp.name] = [round(v, 3) for v in val]
                            else:
                                inputs[inp.name] = round(val, 3) if isinstance(val, float) else val
                    mat_info["shader"] = "Principled BSDF"
                    mat_info["params"] = inputs
                    break

        materials.append(mat_info)
    return materials


def extract_modifiers(obj):
    """Извлечь модификаторы объекта."""
    mods = []
    for mod in obj.modifiers:
        mod_info = {"name": mod.name, "type": mod.type}

        # Основные параметры для частых модификаторов
        if mod.type == 'SUBSURF':
            mod_info["levels_viewport"] = mod.levels
            mod_info["levels_render"] = mod.render_levels
        elif mod.type == 'MIRROR':
            mod_info["axis"] = [mod.use_axis[0], mod.use_axis[1], mod.use_axis[2]]
            mod_info["merge_threshold"] = round(mod.merge_threshold, 5)
        elif mod.type == 'ARRAY':
            mod_info["count"] = mod.count
            mod_info["use_relative_offset"] = mod.use_relative_offset
        elif mod.type == 'SOLIDIFY':
            mod_info["thickness"] = round(mod.thickness, 4)
        elif mod.type == 'BEVEL':
            mod_info["width"] = round(mod.width, 4)
            mod_info["segments"] = mod.segments
        elif mod.type == 'ARMATURE':
            mod_info["armature"] = mod.object.name if mod.object else None
        elif mod.type == 'BOOLEAN':
            mod_info["operation"] = mod.operation
            mod_info["object"] = mod.object.name if mod.object else None
        elif mod.type == 'SHRINKWRAP':
            mod_info["target"] = mod.target.name if mod.target else None
            mod_info["wrap_method"] = mod.wrap_method

        mods.append(mod_info)
    return mods


def extract_armature_data(obj):
    """Извлечь данные арматуры."""
    armature = obj.data
    bones = []
    for bone in armature.bones:
        bone_info = {
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": [round(v, 4) for v in bone.head_local],
            "tail": [round(v, 4) for v in bone.tail_local],
            "length": round(bone.length, 4),
            "connected": bone.use_connect,
            "children": [child.name for child in bone.children],
        }
        bones.append(bone_info)

    # Действия (анимации)
    actions = []
    if bpy.data.actions:
        for action in bpy.data.actions:
            actions.append({
                "name": action.name,
                "frame_range": [int(action.frame_range[0]), int(action.frame_range[1])],
                "channels": len(action.fcurves),
            })

    return {
        "bone_count": len(bones),
        "bones": bones,
        "actions": actions,
    }


def extract_collections():
    """Извлечь структуру коллекций."""
    def collect(col, depth=0):
        result = {
            "name": col.name,
            "objects": [obj.name for obj in col.objects],
            "children": [collect(child, depth + 1) for child in col.children],
        }
        return result

    scene_col = bpy.context.scene.collection
    return collect(scene_col)


def extract_all(filter_object=None, meshes_only=False):
    """Извлечь все данные."""
    data = {
        "file": bpy.data.filepath,
        "blender_version": ".".join(str(v) for v in bpy.app.version),
        "scene": bpy.context.scene.name,
        "objects": [],
        "collections": extract_collections(),
    }

    for obj in bpy.context.scene.objects:
        if filter_object and obj.name != filter_object:
            continue

        # Пропускаем скрытые объекты
        # hide_viewport = глазик в Outliner, hide_get() = скрыт через H
        # Также проверяем скрытые коллекции
        if obj.hide_viewport or obj.hide_get():
            continue
        obj_hidden_by_collection = False
        for col in obj.users_collection:
            if col.hide_viewport:
                obj_hidden_by_collection = True
                break
        if obj_hidden_by_collection:
            continue

        obj_data = {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "transform": extract_object_transform(obj),
        }

        if obj.type == 'MESH':
            obj_data["mesh"] = extract_mesh_data(obj)
            obj_data["materials"] = extract_materials(obj)
            obj_data["modifiers"] = extract_modifiers(obj)
        elif obj.type == 'ARMATURE':
            if meshes_only:
                continue
            obj_data["armature"] = extract_armature_data(obj)
        elif meshes_only:
            continue

        if not meshes_only or obj.type == 'MESH':
            data["objects"].append(obj_data)

    # Проблемы
    issues = detect_issues(data["objects"])
    data["issues"] = issues

    return data


def detect_issues(objects):
    """Обнаружить типичные проблемы."""
    issues = []

    for obj in objects:
        name = obj["name"]

        if obj["type"] == 'MESH':
            mesh = obj["mesh"]
            transform = obj["transform"]

            if mesh["ngons"] > 0:
                issues.append({
                    "object": name,
                    "severity": "info",
                    "message": f"{mesh['ngons']} n-gon(s) detected",
                })

            if mesh["loose_vertices"] > 0:
                issues.append({
                    "object": name,
                    "severity": "warning",
                    "message": f"{mesh['loose_vertices']} loose vertex(es)",
                })

            if mesh["loose_edges"] > 0:
                issues.append({
                    "object": name,
                    "severity": "warning",
                    "message": f"{mesh['loose_edges']} loose edge(s)",
                })

            if mesh["non_manifold_edges"] > 0:
                issues.append({
                    "object": name,
                    "severity": "error",
                    "message": f"{mesh['non_manifold_edges']} non-manifold edge(s)",
                })

            scale = transform["scale"]
            if any(abs(s - 1.0) > 0.001 for s in scale):
                issues.append({
                    "object": name,
                    "severity": "warning",
                    "message": f"Scale not applied: {scale}",
                })

            rot = transform["rotation_deg"]
            if any(abs(r) > 0.01 for r in rot):
                issues.append({
                    "object": name,
                    "severity": "info",
                    "message": f"Rotation not applied: {rot}",
                })

            if not mesh["uv_layers"]:
                issues.append({
                    "object": name,
                    "severity": "warning",
                    "message": "No UV map",
                })

            if not obj["materials"]:
                issues.append({
                    "object": name,
                    "severity": "info",
                    "message": "No materials assigned",
                })

            if mesh["vertex_groups"] == [] and any(
                o["type"] == "ARMATURE" for o in objects
            ):
                issues.append({
                    "object": name,
                    "severity": "warning",
                    "message": "No vertex groups (needs weight painting for rigging)",
                })

    return issues


def main():
    args = get_args()

    filter_object = None
    meshes_only = False

    i = 0
    while i < len(args):
        if args[i] == "--object" and i + 1 < len(args):
            filter_object = args[i + 1]
            i += 2
        elif args[i] == "--meshes":
            meshes_only = True
            i += 1
        else:
            i += 1

    data = extract_all(filter_object=filter_object, meshes_only=meshes_only)

    # Маркер для парсинга — CLI-обёртка ищет этот маркер
    output = json.dumps(data, ensure_ascii=False, indent=2)
    print("===BLEND_ANALYZER_JSON_START===")
    print(output)
    print("===BLEND_ANALYZER_JSON_END===")


if __name__ == "__main__":
    main()
