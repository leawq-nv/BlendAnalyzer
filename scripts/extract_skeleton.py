"""
Blender-скрипт: геометрическое извлечение скелета.

Алгоритм:
1. Применяет модификаторы и трансформации
2. Нарезает вертикально (Z) для спины/ног
3. Нарезает горизонтально (X) на уровне плеч для рук
4. Строит ветки скелета
5. Создаёт арматуру

Запускается: blender --background file.blend --python extract_skeleton.py -- output_path [--ignore ...]
"""

import bpy
import sys
import os
from mathutils import Vector
from collections import defaultdict


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def apply_all_modifiers_and_transforms(ignore_names):
    """Применить все модификаторы и трансформации."""
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Скрыть ignored
    for obj in bpy.context.scene.objects:
        if obj.name in ignore_names:
            obj.hide_viewport = True
            obj.hide_render = True

    bpy.ops.object.select_all(action='DESELECT')

    count = 0
    for obj in list(bpy.context.scene.objects):
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type != 'MESH':
            continue

        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        for mod in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
                print(f"  Applied {mod.name} on {obj.name}")
            except Exception as e:
                print(f"  Failed {mod.name} on {obj.name}: {e}")

        try:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        except Exception:
            pass

        obj.select_set(False)
        count += 1

    print(f"Processed {count} objects")
    # Обновить depsgraph после изменений
    bpy.context.view_layer.update()


def get_all_vertices(ignore_names):
    """Получить все вершины видимых мешей в world space."""
    all_verts = []

    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type != 'MESH':
            continue

        world = obj.matrix_world
        for v in obj.data.vertices:
            co = world @ v.co
            all_verts.append(Vector((co.x, co.y, co.z)))

    return all_verts


def find_clusters(points_2d, merge_dist):
    """Кластеризация 2D-точек через grid flood-fill."""
    if not points_2d:
        return []

    grid = defaultdict(list)
    cell = merge_dist

    for i, (x, y) in enumerate(points_2d):
        grid[(int(x / cell), int(y / cell))].append(i)

    visited = set()
    clusters = []

    for ck in grid:
        if ck in visited:
            continue
        indices = []
        queue = [ck]
        while queue:
            k = queue.pop()
            if k in visited:
                continue
            visited.add(k)
            if k in grid:
                indices.extend(grid[k])
                gx, gy = k
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nk = (gx + dx, gy + dy)
                        if nk not in visited and nk in grid:
                            queue.append(nk)

        if indices:
            cx = sum(points_2d[i][0] for i in indices) / len(indices)
            cy = sum(points_2d[i][1] for i in indices) / len(indices)
            clusters.append({"center": (cx, cy), "count": len(indices)})

    return clusters


def extract_vertical_branches(all_verts, num_slices=50):
    """Вертикальные ветки (спина, ноги) через Z-срезы."""
    z_min = min(v.z for v in all_verts)
    z_max = max(v.z for v in all_verts)
    z_range = z_max - z_min
    if z_range < 0.001:
        return []

    x_range = max(v.x for v in all_verts) - min(v.x for v in all_verts)
    y_range = max(v.y for v in all_verts) - min(v.y for v in all_verts)
    # Маленький merge_dist чтобы ноги не сливались
    merge_dist = min(x_range, y_range) * 0.08

    slice_h = z_range / num_slices
    thickness = slice_h * 1.2

    slices = []
    for i in range(num_slices):
        zc = z_min + (i + 0.5) * slice_h
        pts = [(v.x, v.y) for v in all_verts if abs(v.z - zc) < thickness / 2]
        if pts:
            slices.append((zc, find_clusters(pts, merge_dist)))

    return _track_branches(slices, merge_dist, z_range)


def extract_horizontal_branches(all_verts, z_shoulder_min, z_shoulder_max, num_slices=30):
    """Горизонтальные ветки (руки) через X-срезы на уровне плеч."""
    # Фильтруем вершины на уровне плеч
    shoulder_verts = [v for v in all_verts if z_shoulder_min <= v.z <= z_shoulder_max]
    if len(shoulder_verts) < 10:
        return []

    x_min = min(v.x for v in shoulder_verts)
    x_max = max(v.x for v in shoulder_verts)
    x_range = x_max - x_min
    if x_range < 0.01:
        return []

    y_range = max(v.y for v in shoulder_verts) - min(v.y for v in shoulder_verts)
    z_range = z_shoulder_max - z_shoulder_min
    merge_dist = max(y_range, z_range) * 0.2

    slice_w = x_range / num_slices
    thickness = slice_w * 1.5

    slices = []
    for i in range(num_slices):
        xc = x_min + (i + 0.5) * slice_w
        pts = [(v.y, v.z) for v in shoulder_verts if abs(v.x - xc) < thickness / 2]
        if pts:
            clusters = find_clusters(pts, merge_dist)
            # Конвертируем обратно в (x, _, z) для совместимости
            for cl in clusters:
                cy, cz = cl["center"]
                cl["center_3d"] = (xc, cy, cz)
            slices.append((xc, clusters))

    # Строим ветки по X
    branches = []
    if not slices:
        return []

    # Левая сторона (x < center)
    x_center = (x_min + x_max) / 2
    left_pts = []
    right_pts = []

    for xc, clusters in slices:
        for cl in clusters:
            pt = cl.get("center_3d", (xc, cl["center"][0], cl["center"][1]))
            if xc < x_center - x_range * 0.1:
                left_pts.append(pt)
            elif xc > x_center + x_range * 0.1:
                right_pts.append(pt)

    if len(left_pts) >= 3:
        left_pts.sort(key=lambda p: p[0])
        branches.append(left_pts)
    if len(right_pts) >= 3:
        right_pts.sort(key=lambda p: p[0], reverse=True)
        branches.append(right_pts)

    return branches


def _track_branches(slices, merge_dist, total_range):
    """Отслеживать ветки по срезам."""
    branches = []
    active = []  # (cx, cy, branch_idx)

    for val, clusters in slices:
        if not clusters:
            continue

        if not active:
            for cl in clusters:
                idx = len(branches)
                branches.append([(cl["center"][0], cl["center"][1], val)])
                active.append((cl["center"][0], cl["center"][1], idx))
            continue

        pairs = []
        for ci, cl in enumerate(clusters):
            cx, cy = cl["center"]
            for bi, (bx, by, bidx) in enumerate(active):
                d = ((cx - bx)**2 + (cy - by)**2)**0.5
                pairs.append((d, ci, bi))
        pairs.sort()

        used_c = set()
        used_b = set()
        new_active = []

        for d, ci, bi in pairs:
            if ci in used_c or bi in used_b:
                continue
            if d > merge_dist * 4:
                continue
            cl = clusters[ci]
            _, _, bidx = active[bi]
            branches[bidx].append((cl["center"][0], cl["center"][1], val))
            new_active.append((cl["center"][0], cl["center"][1], bidx))
            used_c.add(ci)
            used_b.add(bi)

        for ci, cl in enumerate(clusters):
            if ci not in used_c:
                idx = len(branches)
                branches.append([(cl["center"][0], cl["center"][1], val)])
                new_active.append((cl["center"][0], cl["center"][1], idx))

        active = new_active

    # Фильтр коротких
    min_len = total_range * 0.06
    return [b for b in branches if len(b) >= 2 and
            max(p[2] for p in b) - min(p[2] for p in b) >= min_len]


def simplify_branch(branch, max_bones=5):
    if len(branch) <= max_bones:
        return branch
    step = max(1, (len(branch) - 1) // (max_bones - 1))
    result = [branch[i] for i in range(0, len(branch), step)]
    if result[-1] != branch[-1]:
        result.append(branch[-1])
    return result


def create_armature(vert_branches, arm_branches, all_verts):
    """Создать арматуру из вертикальных и горизонтальных веток."""
    z_min = min(v.z for v in all_verts)
    z_max = max(v.z for v in all_verts)
    z_center = (z_min + z_max) / 2
    x_center = sum(v.x for v in all_verts) / len(all_verts)

    arm_data = bpy.data.armatures.new("Skeleton")
    arm_obj = bpy.data.objects.new("Skeleton", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    all_edit_bones = {}
    spine_bones = []

    # Вертикальные ветки
    vert_sorted = sorted(vert_branches, key=lambda b: max(p[2] for p in b) - min(p[2] for p in b), reverse=True)

    for bi, branch in enumerate(vert_sorted):
        simplified = simplify_branch(branch)
        if len(simplified) < 2:
            continue

        bx_avg = sum(p[0] for p in simplified) / len(simplified)
        bz_min = min(p[2] for p in simplified)

        if bi == 0:
            name = "Spine"
        elif bz_min < z_center:
            name = "Leg.L" if bx_avg < x_center else "Leg.R"
        else:
            name = f"Branch.{bi}"

        prev = None
        for si in range(len(simplified) - 1):
            p1, p2 = simplified[si], simplified[si + 1]
            bname = f"{name}.{si:02d}"
            bone = arm_data.edit_bones.new(bname)
            bone.head = Vector(p1)
            bone.tail = Vector(p2)
            if (bone.tail - bone.head).length < 0.005:
                bone.tail = bone.head + Vector((0, 0, 0.03))
            if prev:
                bone.parent = prev
                bone.use_connect = True
            prev = bone
            all_edit_bones[bname] = bone
            if name == "Spine":
                spine_bones.append(bone)

    # Горизонтальные ветки (руки)
    for ai, arm_pts in enumerate(arm_branches):
        if len(arm_pts) < 2:
            continue

        ax_avg = sum(p[0] for p in arm_pts) / len(arm_pts)
        name = "Arm.L" if ax_avg < x_center else "Arm.R"

        simplified = simplify_branch(arm_pts, max_bones=4)
        prev = None

        for si in range(len(simplified) - 1):
            p1, p2 = simplified[si], simplified[si + 1]
            bname = f"{name}.{si:02d}"
            bone = arm_data.edit_bones.new(bname)
            bone.head = Vector(p1)
            bone.tail = Vector(p2)
            if (bone.tail - bone.head).length < 0.005:
                bone.tail = bone.head + Vector((0.03, 0, 0))
            if prev:
                bone.parent = prev
                bone.use_connect = True
            prev = bone
            all_edit_bones[bname] = bone

        # Привязать руку к ближайшей кости спины
        first_arm_bone = all_edit_bones.get(f"{name}.00")
        if first_arm_bone and spine_bones:
            closest = min(spine_bones, key=lambda b: (b.head - first_arm_bone.head).length)
            first_arm_bone.parent = closest

    # Привязать ноги к спине
    for bn, bone in all_edit_bones.items():
        if bn.startswith("Leg.") and bn.endswith(".00") and bone.parent is None and spine_bones:
            closest = min(spine_bones, key=lambda b: (b.head - bone.head).length)
            bone.parent = closest

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


def main():
    args = get_args()
    if not args:
        return

    output_path = args[0]
    ignore_names = set()
    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))

    print(f"Ignore: {ignore_names}")

    # 1. Применить модификаторы
    apply_all_modifiers_and_transforms(ignore_names)

    # 2. Получить вершины (уже с applied модификаторами)
    all_verts = get_all_vertices(ignore_names)
    if not all_verts:
        print("===SKELETON_ERROR=== No vertices")
        return

    print(f"Vertices: {len(all_verts)}")

    z_min = min(v.z for v in all_verts)
    z_max = max(v.z for v in all_verts)
    z_range = z_max - z_min

    # 3. Вертикальные ветки (спина, ноги)
    vert_branches = extract_vertical_branches(all_verts)
    print(f"Vertical branches: {len(vert_branches)}")

    # 4. Горизонтальные ветки (руки) — на уровне верхних 30-60% высоты
    z_shoulder_min = z_min + z_range * 0.55
    z_shoulder_max = z_min + z_range * 0.85
    arm_branches = extract_horizontal_branches(all_verts, z_shoulder_min, z_shoulder_max)
    print(f"Arm branches: {len(arm_branches)}")

    if not vert_branches and not arm_branches:
        print("===SKELETON_ERROR=== No branches found")
        return

    # 5. Создать арматуру
    arm_obj = create_armature(vert_branches, arm_branches, all_verts)
    bone_count = len(arm_obj.data.bones)

    # 6. Привязать меши
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type == 'MESH':
            obj.select_set(True)

    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    except RuntimeError:
        bpy.ops.object.parent_set(type='ARMATURE')

    bpy.ops.wm.save_as_mainfile(filepath=output_path)
    print(f"===SKELETON_DONE=== {len(vert_branches)} vert + {len(arm_branches)} arm branches, {bone_count} bones")


if __name__ == "__main__":
    main()
