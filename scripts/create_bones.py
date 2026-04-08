"""
Blender-скрипт: создание гуманоидного скелета по именам мешей.

Имена мешей должны содержать ключевые слова:
  head, neck, spine/chest/torso, shoulder, upper_arm, forearm/lower_arm,
  hand, thigh/upper_leg, shin/lower_leg/calf, foot

Суффиксы стороны: .L / .R / _L / _R / left / right / _l / _r

Запускается: blender --background file.blend --python create_bones.py -- output_path [--ignore name1,name2]
"""

import bpy
import sys
import os
from mathutils import Vector


def get_args():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    return []


# Маппинг ключевых слов → часть тела
BODY_PART_KEYWORDS = {
    # Голова/шея
    "head": "head", "jaw": "jaw", "neck": "neck",
    # Торс
    "spine": "spine", "chest": "chest", "torso": "chest",
    "body": "chest", "abdomen": "spine",
    "hips": "hips", "pelvis": "hips",
    # Руки (основные)
    "shoulder": "shoulder",
    "upper_arm": "upper_arm", "upperarm": "upper_arm", "bicep": "upper_arm",
    "elbow": "elbow",
    "forearm": "forearm", "lower_arm": "forearm", "lowerarm": "forearm",
    "wrist": "wrist",
    "hand": "hand", "palm": "hand",
    # Вторая пара рук
    "shoulder2": "shoulder2",
    "upper_arm2": "upper_arm2", "upperarm2": "upper_arm2",
    "forearm2": "forearm2", "lower_arm2": "forearm2",
    "hand2": "hand2",
    # Пальцы
    "thumb": "thumb", "index": "index", "middle": "middle_finger",
    "ring": "ring_finger", "pinky": "pinky",
    # Ноги
    "thigh": "thigh", "upper_leg": "thigh", "upperleg": "thigh",
    "knee": "knee",
    "shin": "shin", "lower_leg": "shin", "lowerleg": "shin", "calf": "shin",
    "ankle": "ankle",
    "foot": "foot", "feet": "foot",
    "toe": "toe", "heel": "heel",
    # Доп
    "tail": "tail", "wing": "wing",
    "cape": "cape", "belt": "belt",
    "helmet": "helmet", "visor": "visor",
    "pauldron": "pauldron", "gauntlet": "gauntlet", "boot": "boot",
    "skirt": "skirt", "tabard": "tabard",
}

# Иерархия костей (parent → children)
BONE_HIERARCHY = {
    # Торс
    "hips": ["spine"],
    "spine": ["chest"],
    "chest": ["neck", "shoulder.L", "shoulder.R", "shoulder2.L", "shoulder2.R"],
    "neck": ["head"],
    "head": ["jaw"],
    # Руки основные
    "shoulder.L": ["upper_arm.L"], "shoulder.R": ["upper_arm.R"],
    "upper_arm.L": ["elbow.L", "forearm.L"], "upper_arm.R": ["elbow.R", "forearm.R"],
    "forearm.L": ["wrist.L", "hand.L"], "forearm.R": ["wrist.R", "hand.R"],
    "hand.L": ["thumb.L", "index.L", "middle_finger.L", "ring_finger.L", "pinky.L"],
    "hand.R": ["thumb.R", "index.R", "middle_finger.R", "ring_finger.R", "pinky.R"],
    # Вторая пара рук
    "shoulder2.L": ["upper_arm2.L"], "shoulder2.R": ["upper_arm2.R"],
    "upper_arm2.L": ["forearm2.L"], "upper_arm2.R": ["forearm2.R"],
    "forearm2.L": ["hand2.L"], "forearm2.R": ["hand2.R"],
    # Ноги
    "thigh.L": ["knee.L", "shin.L"], "thigh.R": ["knee.R", "shin.R"],
    "shin.L": ["ankle.L", "foot.L"], "shin.R": ["ankle.R", "foot.R"],
    "foot.L": ["toe.L", "heel.L"], "foot.R": ["toe.R", "heel.R"],
    # Доп
    "hips_tail": [],  # hips → tail устанавливается отдельно
}


def detect_side(name):
    """Определить сторону (.L / .R / None) по имени."""
    low = name.lower()
    # Проверяем суффиксы
    for marker in [".l", "_l", " l", "left", ".л", "лев"]:
        if marker in low:
            return "L"
    for marker in [".r", "_r", " r", "right", ".п", "прав"]:
        if marker in low:
            return "R"
    return None


def detect_body_part(name):
    """Определить часть тела по имени меша."""
    low = name.lower().replace("-", "_").replace(" ", "_")

    # Ищем самое длинное совпадение (чтобы "upper_arm" не стало "arm")
    best_match = None
    best_len = 0
    for keyword, part in BODY_PART_KEYWORDS.items():
        if keyword in low and len(keyword) > best_len:
            best_match = part
            best_len = len(keyword)

    return best_match


def get_mesh_bounds(obj):
    """Получить центр и границы меша в world space."""
    bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]

    min_pos = Vector((
        min(c.x for c in bbox_corners),
        min(c.y for c in bbox_corners),
        min(c.z for c in bbox_corners),
    ))
    max_pos = Vector((
        max(c.x for c in bbox_corners),
        max(c.y for c in bbox_corners),
        max(c.z for c in bbox_corners),
    ))
    center = (min_pos + max_pos) / 2

    return center, min_pos, max_pos


def create_humanoid_armature(body_parts):
    """Создать арматуру с правильной иерархией."""

    arm_data = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode='EDIT')

    created_bones = {}

    # Создаём кости для найденных частей тела
    for bone_name, info in body_parts.items():
        center = info["center"]
        min_pos = info["min"]
        max_pos = info["max"]

        bone = arm_data.edit_bones.new(bone_name)

        size = max_pos - min_pos
        height = size.z

        # Кость направлена вверх (по Z) для большинства частей
        if bone_name in ("head", "neck", "spine", "chest", "hips"):
            bone.head = Vector((center.x, center.y, min_pos.z))
            bone.tail = Vector((center.x, center.y, max_pos.z))
        elif "thigh" in bone_name or "upper_leg" in bone_name:
            bone.head = Vector((center.x, center.y, max_pos.z))
            bone.tail = Vector((center.x, center.y, min_pos.z))
        elif "shin" in bone_name or "calf" in bone_name:
            bone.head = Vector((center.x, center.y, max_pos.z))
            bone.tail = Vector((center.x, center.y, min_pos.z))
        elif "foot" in bone_name:
            bone.head = Vector((center.x, center.y, max_pos.z))
            bone.tail = Vector((center.x, min_pos.y, min_pos.z))
        elif "upper_arm" in bone_name:
            if ".L" in bone_name:
                bone.head = Vector((max_pos.x, center.y, center.z))
                bone.tail = Vector((min_pos.x, center.y, center.z))
            else:
                bone.head = Vector((min_pos.x, center.y, center.z))
                bone.tail = Vector((max_pos.x, center.y, center.z))
        elif "forearm" in bone_name:
            if ".L" in bone_name:
                bone.head = Vector((max_pos.x, center.y, center.z))
                bone.tail = Vector((min_pos.x, center.y, center.z))
            else:
                bone.head = Vector((min_pos.x, center.y, center.z))
                bone.tail = Vector((max_pos.x, center.y, center.z))
        elif "hand" in bone_name:
            if ".L" in bone_name:
                bone.head = Vector((max_pos.x, center.y, center.z))
                bone.tail = Vector((min_pos.x, center.y, center.z))
            else:
                bone.head = Vector((min_pos.x, center.y, center.z))
                bone.tail = Vector((max_pos.x, center.y, center.z))
        elif "shoulder" in bone_name:
            if ".L" in bone_name:
                bone.head = Vector((min_pos.x, center.y, center.z))
                bone.tail = Vector((max_pos.x, center.y, center.z))
            else:
                bone.head = Vector((max_pos.x, center.y, center.z))
                bone.tail = Vector((min_pos.x, center.y, center.z))
        else:
            bone.head = Vector((center.x, center.y, min_pos.z))
            bone.tail = Vector((center.x, center.y, max_pos.z))

        # Минимальная длина
        if (bone.tail - bone.head).length < 0.01:
            bone.tail = bone.head + Vector((0, 0, 0.05))

        created_bones[bone_name] = bone

    # Устанавливаем иерархию
    for parent_name, children_names in BONE_HIERARCHY.items():
        if parent_name not in created_bones:
            continue
        parent_bone = created_bones[parent_name]
        for child_name in children_names:
            if child_name in created_bones:
                created_bones[child_name].parent = parent_bone

    # hips — родитель ног и хвоста
    if "hips" in created_bones:
        for side in (".L", ".R"):
            thigh_name = f"thigh{side}"
            if thigh_name in created_bones:
                created_bones[thigh_name].parent = created_bones["hips"]
        if "tail" in created_bones:
            created_bones["tail"].parent = created_bones["hips"]

    bpy.ops.object.mode_set(mode='OBJECT')

    return arm_obj


def main():
    args = get_args()
    if not args:
        print("Usage: ... -- output_path [--ignore name1,name2]")
        return

    output_path = args[0]

    ignore_names = set()
    tags_map = {}  # mesh_name → tag

    for i, a in enumerate(args):
        if a == "--ignore" and i + 1 < len(args):
            ignore_names = set(args[i + 1].split(","))
        elif a == "--tags" and i + 1 < len(args):
            for pair in args[i + 1].split(","):
                if "=" in pair:
                    mesh_name, tag = pair.split("=", 1)
                    tags_map[mesh_name] = tag

    # Убедиться в Object Mode
    if bpy.context.active_object and bpy.context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Анализируем мешей — сначала по тегам, потом по именам
    body_parts = {}
    unmatched = []

    for obj in bpy.context.scene.objects:
        if obj.hide_viewport or obj.hide_get():
            continue
        if obj.name in ignore_names:
            continue
        if obj.type != 'MESH':
            continue

        # Сначала проверяем тег, потом имя
        if obj.name in tags_map:
            tag = tags_map[obj.name]
            part = detect_body_part(tag)
            side = detect_side(tag)
        else:
            part = detect_body_part(obj.name)
            side = detect_side(obj.name)

        if part is None:
            unmatched.append(obj.name)
            continue

        # Формируем имя кости
        if side and part not in ("head", "neck", "spine", "chest", "hips"):
            bone_name = f"{part}.{side}"
        else:
            bone_name = part

        center, min_pos, max_pos = get_mesh_bounds(obj)

        if bone_name not in body_parts:
            body_parts[bone_name] = {
                "center": center,
                "min": min_pos,
                "max": max_pos,
                "meshes": [obj],
            }
        else:
            # Объединяем bounding box если несколько мешей на одну кость
            bp = body_parts[bone_name]
            bp["meshes"].append(obj)
            bp["min"] = Vector((
                min(bp["min"].x, min_pos.x),
                min(bp["min"].y, min_pos.y),
                min(bp["min"].z, min_pos.z),
            ))
            bp["max"] = Vector((
                max(bp["max"].x, max_pos.x),
                max(bp["max"].y, max_pos.y),
                max(bp["max"].z, max_pos.z),
            ))
            bp["center"] = (bp["min"] + bp["max"]) / 2

    if not body_parts:
        print(f"===BONES_ERROR=== No body parts found. Unmatched meshes: {', '.join(unmatched)}")
        return

    # Создаём арматуру
    arm_obj = create_humanoid_armature(body_parts)

    # Привязываем меши к арматуре с Automatic Weights
    bpy.ops.object.select_all(action='DESELECT')

    for bone_name, info in body_parts.items():
        for mesh_obj in info["meshes"]:
            mesh_obj.select_set(True)

    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj

    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    except RuntimeError:
        # Fallback без auto weights
        bpy.ops.object.parent_set(type='ARMATURE')

    bpy.ops.wm.save_as_mainfile(filepath=output_path)

    matched_names = []
    for bn, info in body_parts.items():
        matched_names.append(f"{bn}: {', '.join(m.name for m in info['meshes'])}")

    print(f"===BONES_DONE=== {len(body_parts)} bones")
    print(f"Matched: {'; '.join(matched_names)}")
    if unmatched:
        print(f"Unmatched: {', '.join(unmatched)}")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
