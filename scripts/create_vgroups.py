"""
Blender-скрипт: создание vertex groups по зонам модели.
Запускается через: blender --background file.blend --python create_vgroups.py -- output_path
"""

import bpy
import sys
import os


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def create_zone_vertex_groups(obj):
    """Создать vertex groups по зонам для одного объекта."""
    if obj.type != 'MESH':
        return

    mesh = obj.data
    verts = mesh.vertices

    if len(verts) == 0:
        return

    # Получаем координаты в local space
    coords = [(float(v.co.x), float(v.co.y), float(v.co.z)) for v in verts]

    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)

    x_center = (x_min + x_max) / 2
    y_center = (y_min + y_max) / 2
    z_range = z_max - z_min
    x_range = x_max - x_min
    y_range = y_max - y_min

    if z_range < 0.001:
        z_range = 0.001

    def safe_add(vg, index, weight):
        """Безопасное добавление вершины в группу."""
        w = float(max(0.001, min(1.0, weight)))
        vg.add([index], w, 'REPLACE')

    def get_or_create_vgroup(name):
        if name in obj.vertex_groups:
            obj.vertex_groups.remove(obj.vertex_groups[name])
        return obj.vertex_groups.new(name=name)

    # === Зоны по высоте (Z) ===
    z_zones = [
        ("Zone_Top", 0.75, 1.0),
        ("Zone_Upper", 0.5, 0.75),
        ("Zone_Middle", 0.25, 0.5),
        ("Zone_Lower", 0.0, 0.25),
    ]

    for zone_name, z_low_pct, z_high_pct in z_zones:
        z_low = z_min + z_range * z_low_pct
        z_high = z_min + z_range * z_high_pct
        vg = get_or_create_vgroup(zone_name)

        for i, (x, y, z) in enumerate(coords):
            if z_low <= z <= z_high:
                zone_center = (z_low + z_high) / 2
                zone_half = (z_high - z_low) / 2
                if zone_half > 0.0001:
                    dist = abs(z - zone_center) / zone_half
                    weight = 1.0 - dist * 0.5
                else:
                    weight = 1.0
                safe_add(vg, i, weight)

    # === Зоны по сторонам (X) ===
    if x_range > 0.01:
        vg_left = get_or_create_vgroup("Zone_Left")
        vg_right = get_or_create_vgroup("Zone_Right")
        vg_center = get_or_create_vgroup("Zone_Center")

        center_threshold = x_range * 0.1

        for i, (x, y, z) in enumerate(coords):
            if x < x_center - center_threshold:
                weight = 0.5 + 0.5 * abs(x - x_center) / (x_range / 2)
                safe_add(vg_left, i, weight)
            elif x > x_center + center_threshold:
                weight = 0.5 + 0.5 * abs(x - x_center) / (x_range / 2)
                safe_add(vg_right, i, weight)
            else:
                safe_add(vg_center, i, 1.0)

    # === Фронт / Спина (Y) ===
    if y_range > 0.01:
        vg_front = get_or_create_vgroup("Zone_Front")
        vg_back = get_or_create_vgroup("Zone_Back")

        for i, (x, y, z) in enumerate(coords):
            if y >= y_center:
                weight = 0.3 + 0.7 * (y - y_center) / (y_range / 2)
                safe_add(vg_front, i, weight)
            else:
                weight = 0.3 + 0.7 * (y_center - y) / (y_range / 2)
                safe_add(vg_back, i, weight)


def main():
    args = get_args()
    if not args:
        print("Usage: ... -- output_path")
        return

    output_path = args[0]

    # Парсим --ignore
    ignore_names = set()
    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))

    # Убедиться что мы в Object Mode
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    count = 0
    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type == 'MESH':
            bpy.context.view_layer.objects.active = obj
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            create_zone_vertex_groups(obj)
            count += 1

    # Сохранить в новый файл
    bpy.ops.wm.save_as_mainfile(filepath=output_path)

    print(f"===VGROUPS_DONE=== {count} objects, saved to {output_path}")


if __name__ == "__main__":
    main()
