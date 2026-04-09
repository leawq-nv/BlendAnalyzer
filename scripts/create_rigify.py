"""
Blender-скрипт: создание Rigify meta-rig, масштабированного под модель.

1. Включает аддон Rigify
2. Создаёт Human meta-rig
3. Масштабирует и позиционирует по bounding box модели
4. Сохраняет — пользователь подгоняет кости в Blender

Запускается: blender --background file.blend --python create_rigify.py -- output_path [--ignore ...]
"""

import bpy
import sys
from mathutils import Vector


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


def enable_rigify():
    """Включить аддон Rigify."""
    try:
        bpy.ops.preferences.addon_enable(module="rigify")
        print("Rigify enabled")
        return True
    except Exception as e:
        print(f"Rigify enable failed: {e}")
        # Попробуем через preferences
        try:
            import addon_utils
            addon_utils.enable("rigify")
            print("Rigify enabled via addon_utils")
            return True
        except Exception as e2:
            print(f"Rigify addon_utils failed: {e2}")
            return False


def get_model_bounds(ignore_names):
    """Получить bounding box всех видимых мешей."""
    min_co = Vector((float('inf'), float('inf'), float('inf')))
    max_co = Vector((float('-inf'), float('-inf'), float('-inf')))
    has_mesh = False

    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type != 'MESH':
            continue

        has_mesh = True
        world = obj.matrix_world
        for corner in obj.bound_box:
            co = world @ Vector(corner)
            min_co.x = min(min_co.x, co.x)
            min_co.y = min(min_co.y, co.y)
            min_co.z = min(min_co.z, co.z)
            max_co.x = max(max_co.x, co.x)
            max_co.y = max(max_co.y, co.y)
            max_co.z = max(max_co.z, co.z)

    if not has_mesh:
        return None, None, None, None

    center = (min_co + max_co) / 2
    size = max_co - min_co
    return min_co, max_co, center, size


def add_extra_arms(metarig, count=1):
    """Дублировать руки в meta-rig для дополнительных пар."""
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    armature = metarig.data

    # Найти кости рук — ищем по имени (Rigify naming: upper_arm, forearm, hand)
    arm_bone_prefixes_L = []
    arm_bone_prefixes_R = []

    for bone in armature.edit_bones:
        name = bone.name.lower()
        if any(k in name for k in ['upper_arm', 'forearm', 'hand', 'f_index', 'f_middle',
                                      'f_ring', 'f_pinky', 'thumb', 'palm']) and '.l' in name:
            arm_bone_prefixes_L.append(bone.name)
        elif any(k in name for k in ['upper_arm', 'forearm', 'hand', 'f_index', 'f_middle',
                                        'f_ring', 'f_pinky', 'thumb', 'palm']) and '.r' in name:
            arm_bone_prefixes_R.append(bone.name)

    # Также включаем shoulder
    for bone in armature.edit_bones:
        if 'shoulder' in bone.name.lower():
            if '.l' in bone.name.lower():
                arm_bone_prefixes_L.append(bone.name)
            elif '.r' in bone.name.lower():
                arm_bone_prefixes_R.append(bone.name)

    print(f"  Found {len(arm_bone_prefixes_L)} L arm bones, {len(arm_bone_prefixes_R)} R arm bones")

    if not arm_bone_prefixes_L:
        print("  No arm bones found, skipping extra arms")
        bpy.ops.object.mode_set(mode='OBJECT')
        return

    # Находим spine.003 (chest) — к нему привяжем новые руки
    chest_bone = None
    for bone in armature.edit_bones:
        if bone.name == 'spine.003':
            chest_bone = bone
            break

    if not chest_bone:
        # Попробуем найти chest по другому имени
        for bone in armature.edit_bones:
            if 'spine' in bone.name and 'shoulder' not in bone.name:
                chest_bone = bone
        if not chest_bone:
            print("  No chest bone found")
            bpy.ops.object.mode_set(mode='OBJECT')
            return

    for pair_idx in range(count):
        z_offset = -0.15 * (pair_idx + 1)  # Каждая пара чуть ниже
        suffix = f"_extra{pair_idx + 1}"

        # Для каждой стороны
        for side_bones, side in [(arm_bone_prefixes_L, ".L"), (arm_bone_prefixes_R, ".R")]:
            # Маппинг старое имя → новая кость
            bone_map = {}

            for old_name in side_bones:
                src = armature.edit_bones.get(old_name)
                if not src:
                    continue

                new_name = old_name.replace(side, f"{suffix}{side}")
                new_bone = armature.edit_bones.new(new_name)
                new_bone.head = src.head.copy()
                new_bone.tail = src.tail.copy()
                new_bone.roll = src.roll

                # Сдвигаем вниз
                new_bone.head.z += z_offset
                new_bone.tail.z += z_offset

                # Копируем rigify type
                try:
                    new_bone.rigify_type = src.rigify_type
                except Exception:
                    pass

                bone_map[old_name] = new_bone

            # Восстановить иерархию
            for old_name in side_bones:
                src = armature.edit_bones.get(old_name)
                if not src or old_name not in bone_map:
                    continue
                new_bone = bone_map[old_name]

                if src.parent and src.parent.name in bone_map:
                    new_bone.parent = bone_map[src.parent.name]
                    new_bone.use_connect = src.use_connect

            # Привязать shoulder новой пары к chest
            for old_name, new_bone in bone_map.items():
                if 'shoulder' in old_name.lower() and new_bone.parent is None:
                    new_bone.parent = chest_bone

        print(f"  Added extra arm pair {pair_idx + 1}")

    bpy.ops.object.mode_set(mode='OBJECT')


def main():
    args = get_args()
    if not args:
        print("Usage: ... -- output_path [--ignore ...]")
        return

    output_path = args[0]

    ignore_names = set()
    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))

    # Object mode
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Удалить ignored
    for obj in list(bpy.context.scene.objects):
        if obj.name in ignore_names:
            print(f"  Removing: {obj.name}")
            bpy.data.objects.remove(obj, do_unlink=True)

    # Применить модификаторы и трансформации
    bpy.ops.object.select_all(action='DESELECT')
    for obj in list(bpy.context.scene.objects):
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.type != 'MESH':
            continue

        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        for mod in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except Exception:
                pass

        # Fallback
        if obj.modifiers:
            try:
                bpy.ops.object.convert(target='MESH')
            except Exception:
                pass

        try:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        except Exception:
            pass

        obj.select_set(False)

    # Bounding box модели
    min_co, max_co, center, size = get_model_bounds(ignore_names)
    if min_co is None:
        print("===RIGIFY_ERROR=== No mesh found")
        return

    print(f"Model bounds: {min_co} - {max_co}")
    print(f"Model size: {size}")
    print(f"Model center: {center}")

    # Включить Rigify
    if not enable_rigify():
        print("===RIGIFY_ERROR=== Could not enable Rigify addon")
        return

    # Создать meta-rig
    bpy.ops.object.select_all(action='DESELECT')
    try:
        bpy.ops.object.armature_human_metarig_add()
    except Exception as e:
        print(f"===RIGIFY_ERROR=== Could not create metarig: {e}")
        return

    metarig = bpy.context.active_object
    if not metarig or metarig.type != 'ARMATURE':
        print("===RIGIFY_ERROR=== Metarig not created")
        return

    print(f"Metarig created: {metarig.name}")

    # Размеры meta-rig по умолчанию
    metarig_bb = [metarig.matrix_world @ Vector(c) for c in metarig.bound_box]
    meta_min = Vector((min(c.x for c in metarig_bb), min(c.y for c in metarig_bb), min(c.z for c in metarig_bb)))
    meta_max = Vector((max(c.x for c in metarig_bb), max(c.y for c in metarig_bb), max(c.z for c in metarig_bb)))
    meta_size = meta_max - meta_min
    meta_center = (meta_min + meta_max) / 2

    # Масштабируем meta-rig под модель
    # Основной масштаб по высоте (Z)
    if meta_size.z > 0:
        scale_z = size.z / meta_size.z
    else:
        scale_z = 1.0

    # Ширина (X) и глубина (Y) — пропорционально
    if meta_size.x > 0:
        scale_x = size.x / meta_size.x
    else:
        scale_x = scale_z

    if meta_size.y > 0:
        scale_y = size.y / meta_size.y
    else:
        scale_y = scale_z

    # Используем uniform scale по высоте (чтобы пропорции сохранились)
    # но немного корректируем ширину
    uniform_scale = scale_z
    metarig.scale = Vector((uniform_scale, uniform_scale, uniform_scale))

    # Позиционируем — низ meta-rig на низ модели, по центру X
    bpy.ops.object.select_all(action='DESELECT')
    metarig.select_set(True)
    bpy.context.view_layer.objects.active = metarig
    bpy.ops.object.transform_apply(scale=True)

    # Пересчитать bounding box после scale
    metarig_bb = [metarig.matrix_world @ Vector(c) for c in metarig.bound_box]
    new_meta_min = Vector((min(c.x for c in metarig_bb), min(c.y for c in metarig_bb), min(c.z for c in metarig_bb)))

    # Сдвигаем: центр X модели, центр Y модели, низ Z модели
    offset = Vector((
        center.x - (min(c.x for c in metarig_bb) + max(c.x for c in metarig_bb)) / 2,
        center.y - (min(c.y for c in metarig_bb) + max(c.y for c in metarig_bb)) / 2,
        min_co.z - new_meta_min.z,
    ))
    metarig.location += offset

    bpy.ops.object.transform_apply(location=True)

    print(f"Metarig scaled: {uniform_scale:.3f}")
    print(f"Metarig offset: {offset}")

    # Направление модели — повернуть мета-риг
    facing = "-Y"
    for i, a in enumerate(args):
        if a == "--facing" and i + 1 < len(args):
            facing = args[i + 1]

    # Rigify meta-rig по умолчанию смотрит в -Y
    # Если модель смотрит в другую сторону — поворачиваем мета-риг
    import math
    rotation_map = {
        "-Y": 0,       # по умолчанию, не крутим
        "+Y": 180,     # развернуть на 180°
        "+X": -90,     # повернуть на -90°
        "-X": 90,      # повернуть на 90°
    }
    rot_deg = rotation_map.get(facing, 0)

    if rot_deg != 0:
        bpy.ops.object.select_all(action='DESELECT')
        metarig.select_set(True)
        bpy.context.view_layer.objects.active = metarig
        metarig.rotation_euler.z = math.radians(rot_deg)
        bpy.ops.object.transform_apply(rotation=True)
        print(f"Metarig rotated {rot_deg}° for facing {facing}")

    # Доп. пары рук
    extra_arms = 0
    for i, a in enumerate(args):
        if a == "--extra-arms" and i + 1 < len(args):
            extra_arms = int(args[i + 1])

    if extra_arms > 0:
        add_extra_arms(metarig, extra_arms)

    # Сохранить
    bpy.ops.wm.save_as_mainfile(filepath=output_path)

    bone_count = len(metarig.data.bones)
    print(f"===RIGIFY_DONE=== {bone_count} bones, scale {uniform_scale:.3f}, extra arms: {extra_arms}")


if __name__ == "__main__":
    main()
