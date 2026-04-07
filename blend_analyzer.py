#!/usr/bin/env python3
"""
blend-analyzer — CLI для извлечения данных из .blend файлов.

Использование:
    python blend_analyzer.py model.blend
    python blend_analyzer.py model.blend --json
    python blend_analyzer.py model.blend --meshes
    python blend_analyzer.py model.blend --object "Body"
    python blend_analyzer.py model.blend -o report.txt
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent / "scripts"
EXTRACT_SCRIPT = SCRIPT_DIR / "extract.py"

# Типичные пути к Blender
BLENDER_SEARCH_PATHS = [
    # Стандартные
    "blender",
    # Linux
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    # Flatpak
    "/var/lib/flatpak/exports/bin/org.blender.Blender",
    # Steam (Linux)
    os.path.expanduser("~/.steam/steam/steamapps/common/Blender/blender"),
    os.path.expanduser("~/.local/share/Steam/steamapps/common/Blender/blender"),
    # Windows
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    # macOS
    "/Applications/Blender.app/Contents/MacOS/Blender",
]


def find_blender():
    """Найти исполняемый файл Blender."""
    # Сначала проверяем переменную окружения
    env_path = os.environ.get("BLENDER_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # Проверяем конфиг-файл
    config_path = Path(__file__).parent / ".blender_path"
    if config_path.exists():
        path = config_path.read_text().strip()
        if os.path.isfile(path):
            return path

    # Ищем в PATH
    found = shutil.which("blender")
    if found:
        return found

    # Ищем по известным путям
    for path in BLENDER_SEARCH_PATHS:
        if os.path.isfile(path):
            return path

    return None


def save_blender_path(path):
    """Сохранить путь к Blender в конфиг."""
    config_path = Path(__file__).parent / ".blender_path"
    config_path.write_text(path)


def run_blender_extract(blender_path, blend_file, extra_args=None):
    """Запустить Blender в фоне и извлечь данные."""
    cmd = [
        blender_path,
        "--background",
        str(blend_file),
        "--python",
        str(EXTRACT_SCRIPT),
        "--",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("Ошибка: Blender не ответил за 120 секунд.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Ошибка: Blender не найден по пути: {blender_path}", file=sys.stderr)
        sys.exit(1)

    # Извлечь JSON из вывода Blender (между маркерами)
    stdout = result.stdout
    start_marker = "===BLEND_ANALYZER_JSON_START==="
    end_marker = "===BLEND_ANALYZER_JSON_END==="

    start_idx = stdout.find(start_marker)
    end_idx = stdout.find(end_marker)

    if start_idx == -1 or end_idx == -1:
        print("Ошибка: не удалось получить данные от Blender.", file=sys.stderr)
        if result.stderr:
            print("Stderr:", result.stderr[:1000], file=sys.stderr)
        sys.exit(1)

    json_str = stdout[start_idx + len(start_marker):end_idx].strip()
    return json.loads(json_str)


def format_number(n):
    """Форматировать число с разделителями: 12450 -> 12,450."""
    return f"{n:,}"


def format_text_report(data):
    """Сформировать человекочитаемый отчёт."""
    lines = []
    blend_name = os.path.basename(data.get("file", "unknown"))
    lines.append(f"=== BLEND ANALYSIS: {blend_name} ===")
    lines.append(f"Blender version: {data.get('blender_version', '?')}")
    lines.append(f"Scene: {data.get('scene', '?')}")
    lines.append("")

    objects = data.get("objects", [])
    mesh_count = sum(1 for o in objects if o["type"] == "MESH")
    armature_count = sum(1 for o in objects if o["type"] == "ARMATURE")
    other_count = len(objects) - mesh_count - armature_count

    lines.append(f"OBJECTS ({len(objects)}): {mesh_count} mesh(es), {armature_count} armature(s), {other_count} other")
    lines.append("")

    for obj in objects:
        indent = "  "
        parent_str = f" (parent: {obj['parent']})" if obj.get("parent") else ""
        lines.append(f"{indent}{obj['name']} [{obj['type']}]{parent_str}")

        t = obj.get("transform", {})
        pos = t.get("position", [0, 0, 0])
        scale = t.get("scale", [1, 1, 1])
        rot = t.get("rotation_deg", [0, 0, 0])
        lines.append(f"{indent}  Position: ({pos[0]}, {pos[1]}, {pos[2]})")
        lines.append(f"{indent}  Rotation: ({rot[0]}°, {rot[1]}°, {rot[2]}°)")
        lines.append(f"{indent}  Scale: ({scale[0]}, {scale[1]}, {scale[2]})")

        if obj["type"] == "MESH":
            m = obj.get("mesh", {})
            total_faces = m.get("faces", 0)
            tris = m.get("tris", 0)
            quads = m.get("quads", 0)
            ngons = m.get("ngons", 0)

            # Процентное соотношение
            parts = []
            if total_faces > 0:
                if quads:
                    parts.append(f"{quads / total_faces * 100:.0f}% quads")
                if tris:
                    parts.append(f"{tris / total_faces * 100:.0f}% tris")
                if ngons:
                    parts.append(f"{ngons / total_faces * 100:.0f}% ngons")
            ratio_str = f" ({', '.join(parts)})" if parts else ""

            lines.append(
                f"{indent}  Geometry: {format_number(m.get('vertices', 0))} verts, "
                f"{format_number(m.get('edges', 0))} edges, "
                f"{format_number(total_faces)} faces{ratio_str}"
            )

            dims = m.get("dimensions", [0, 0, 0])
            lines.append(f"{indent}  Dimensions: {dims[0]:.3f} x {dims[1]:.3f} x {dims[2]:.3f}")

            # Vertex groups
            vgroups = m.get("vertex_groups", [])
            if vgroups:
                lines.append(f"{indent}  Vertex Groups ({len(vgroups)}): {', '.join(vgroups)}")
            else:
                lines.append(f"{indent}  Vertex Groups: (none)")

            # UV
            uv = m.get("uv_layers", [])
            if uv:
                lines.append(f"{indent}  UV Maps ({len(uv)}): {', '.join(uv)}")
            else:
                lines.append(f"{indent}  UV Maps: (none)")

            # Topology density
            density = m.get("density_zones", {})
            if density:
                density_parts = [f"{zone}: {format_number(count)}" for zone, count in density.items()]
                lines.append(f"{indent}  Density by zone: {', '.join(density_parts)}")

            # Loose/non-manifold
            issues_parts = []
            if m.get("loose_vertices", 0):
                issues_parts.append(f"{m['loose_vertices']} loose verts")
            if m.get("loose_edges", 0):
                issues_parts.append(f"{m['loose_edges']} loose edges")
            if m.get("non_manifold_edges", 0):
                issues_parts.append(f"{m['non_manifold_edges']} non-manifold edges")
            if issues_parts:
                lines.append(f"{indent}  Topology issues: {', '.join(issues_parts)}")

            # Materials
            mats = obj.get("materials", [])
            if mats:
                mat_names = [mat.get("name", "?") for mat in mats]
                lines.append(f"{indent}  Materials ({len(mats)}): {', '.join(mat_names)}")

                for mat in mats:
                    if "shader" in mat:
                        lines.append(f"{indent}    {mat['name']}: {mat['shader']}")
                        params = mat.get("params", {})
                        for key, val in params.items():
                            if isinstance(val, list) and len(val) == 4:
                                lines.append(f"{indent}      {key}: rgba({val[0]}, {val[1]}, {val[2]}, {val[3]})")
                            elif isinstance(val, str) and val.startswith("[Texture"):
                                lines.append(f"{indent}      {key}: {val}")
                            elif key in ("Base Color", "Metallic", "Roughness", "Specular IOR Level", "Alpha"):
                                lines.append(f"{indent}      {key}: {val}")

            # Modifiers
            mods = obj.get("modifiers", [])
            if mods:
                lines.append(f"{indent}  Modifiers ({len(mods)}):")
                for mod in mods:
                    extra = {k: v for k, v in mod.items() if k not in ("name", "type")}
                    extra_str = f" — {extra}" if extra else ""
                    lines.append(f"{indent}    {mod['name']} [{mod['type']}]{extra_str}")

        elif obj["type"] == "ARMATURE":
            arm = obj.get("armature", {})
            bone_count = arm.get("bone_count", 0)
            lines.append(f"{indent}  Bones: {bone_count}")

            bones = arm.get("bones", [])
            if bones:
                # Показать дерево костей (только корневые + первый уровень)
                root_bones = [b for b in bones if b["parent"] is None]
                for bone in root_bones:
                    children = bone.get("children", [])
                    children_str = f" → [{', '.join(children[:5])}{'...' if len(children) > 5 else ''}]" if children else ""
                    lines.append(
                        f"{indent}    {bone['name']} "
                        f"(len: {bone['length']:.3f}){children_str}"
                    )

            actions = arm.get("actions", [])
            if actions:
                lines.append(f"{indent}  Actions ({len(actions)}):")
                for act in actions:
                    lines.append(
                        f"{indent}    {act['name']} "
                        f"[frames {act['frame_range'][0]}-{act['frame_range'][1]}, "
                        f"{act['channels']} channels]"
                    )

        lines.append("")

    # Collections
    collections = data.get("collections")
    if collections:
        lines.append("COLLECTIONS:")
        def print_col(col, depth=0):
            prefix = "  " * (depth + 1)
            obj_str = f" ({len(col['objects'])} objects)" if col["objects"] else ""
            lines.append(f"{prefix}{col['name']}{obj_str}")
            for child in col.get("children", []):
                print_col(child, depth + 1)
        print_col(collections)
        lines.append("")

    # Issues
    issues = data.get("issues", [])
    if issues:
        lines.append(f"ISSUES ({len(issues)}):")
        severity_order = {"error": 0, "warning": 1, "info": 2}
        issues_sorted = sorted(issues, key=lambda x: severity_order.get(x["severity"], 3))
        for issue in issues_sorted:
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(issue["severity"], "[?]")
            lines.append(f"  {icon} {issue['object']}: {issue['message']}")
        lines.append("")
    else:
        lines.append("ISSUES: none detected")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Извлечение данных из .blend файлов для анализа",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Примеры:\n"
               "  python blend_analyzer.py model.blend\n"
               "  python blend_analyzer.py model.blend --json\n"
               "  python blend_analyzer.py model.blend --object Body\n"
               "  python blend_analyzer.py model.blend --meshes -o report.txt",
    )
    parser.add_argument("blend_file", help="Путь к .blend файлу")
    parser.add_argument("--json", action="store_true", help="Вывести в формате JSON")
    parser.add_argument("--meshes", action="store_true", help="Только меши")
    parser.add_argument("--object", type=str, help="Анализировать только указанный объект")
    parser.add_argument("-o", "--output", type=str, help="Сохранить отчёт в файл")
    parser.add_argument("--blender", type=str, help="Путь к исполняемому файлу Blender")

    args = parser.parse_args()

    # Проверяем .blend файл
    blend_path = Path(args.blend_file)
    if not blend_path.exists():
        print(f"Ошибка: файл не найден: {blend_path}", file=sys.stderr)
        sys.exit(1)

    if not blend_path.suffix == ".blend":
        print(f"Предупреждение: файл не имеет расширения .blend: {blend_path}", file=sys.stderr)

    # Ищем Blender
    blender_path = args.blender or find_blender()
    if not blender_path:
        print(
            "Ошибка: Blender не найден.\n"
            "Укажите путь к Blender одним из способов:\n"
            "  1. --blender /path/to/blender\n"
            "  2. export BLENDER_PATH=/path/to/blender\n"
            "  3. Создайте файл .blender_path в папке blend-analyzer",
            file=sys.stderr,
        )
        sys.exit(1)

    # Сохраняем найденный путь для будущих запусков
    if not args.blender:
        save_blender_path(blender_path)

    # Формируем аргументы для Blender-скрипта
    extra_args = []
    if args.object:
        extra_args.extend(["--object", args.object])
    if args.meshes:
        extra_args.append("--meshes")

    print(f"Загружаю {blend_path.name} через Blender ({blender_path})...", file=sys.stderr)

    data = run_blender_extract(blender_path, blend_path, extra_args)

    # Форматируем вывод
    if args.json:
        output = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        output = format_text_report(data)

    # Выводим или сохраняем
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Отчёт сохранён: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
