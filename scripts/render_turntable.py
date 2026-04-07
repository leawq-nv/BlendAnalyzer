"""
Blender-скрипт: рендер turntable — модель вращается на 360°.
Запускается через: blender --background file.blend --python render_turntable.py -- output_dir [frames]
"""

import bpy
import sys
import os
import math


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def setup_scene():
    """Настроить сцену для рендера."""
    scene = bpy.context.scene

    # Используем Workbench для скорости (solid view)
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.studio_light = 'studio.exr'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True

    # Прозрачный фон
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    # Размер рендера
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100


def get_scene_bounds():
    """Получить bounding box всех видимых мешей."""
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3

    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT'):
            continue

        # Учитываем world-space bounding box
        for corner in obj.bound_box:
            world_co = obj.matrix_world @ bpy.mathutils.Vector(corner) if hasattr(bpy, 'mathutils') else None
            if world_co is None:
                import mathutils
                world_co = obj.matrix_world @ mathutils.Vector(corner)

            for i in range(3):
                min_co[i] = min(min_co[i], world_co[i])
                max_co[i] = max(max_co[i], world_co[i])

    if min_co[0] == float('inf'):
        return [0, 0, 0], [1, 1, 1]

    return min_co, max_co


def setup_camera(frame_idx, total_frames):
    """Расположить камеру вокруг модели."""
    min_co, max_co = get_scene_bounds()

    # Центр модели
    center = [(min_co[i] + max_co[i]) / 2 for i in range(3)]

    # Размер модели
    size = max(max_co[i] - min_co[i] for i in range(3))
    distance = size * 2.2

    # Угол вращения
    angle = (frame_idx / total_frames) * 2 * math.pi

    # Позиция камеры (вращение вокруг Z, немного сверху)
    elevation = math.radians(25)
    cam_x = center[0] + distance * math.cos(angle) * math.cos(elevation)
    cam_y = center[1] + distance * math.sin(angle) * math.cos(elevation)
    cam_z = center[2] + distance * math.sin(elevation)

    # Создаём или берём камеру
    cam_name = "_turntable_cam"
    if cam_name in bpy.data.objects:
        cam_obj = bpy.data.objects[cam_name]
    else:
        cam_data = bpy.data.cameras.new(cam_name)
        cam_obj = bpy.data.objects.new(cam_name, cam_data)
        bpy.context.scene.collection.objects.link(cam_obj)

    cam_obj.location = (cam_x, cam_y, cam_z)

    # Направить камеру на центр модели
    import mathutils
    direction = mathutils.Vector(center) - mathutils.Vector((cam_x, cam_y, cam_z))
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()

    # Установить как активную камеру
    bpy.context.scene.camera = cam_obj

    # Настроить FOV
    cam_obj.data.lens = 50

    return cam_obj


def main():
    args = get_args()
    if not args:
        print("Usage: ... -- output_dir [frames]")
        return

    output_dir = args[0]
    total_frames = int(args[1]) if len(args) > 1 else 36

    os.makedirs(output_dir, exist_ok=True)

    setup_scene()

    # Скрыть объекты, которые уже скрыты
    # (Blender в background может показывать всё)

    for i in range(total_frames):
        setup_camera(i, total_frames)
        filepath = os.path.join(output_dir, f"frame_{i:03d}.png")
        bpy.context.scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)

    # Удаляем временную камеру
    cam_name = "_turntable_cam"
    if cam_name in bpy.data.objects:
        cam_obj = bpy.data.objects[cam_name]
        bpy.data.objects.remove(cam_obj, do_unlink=True)

    print(f"===TURNTABLE_DONE=== {output_dir} {total_frames}")


if __name__ == "__main__":
    main()
