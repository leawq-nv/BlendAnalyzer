#!/usr/bin/env python3
"""
Blend Analyzer — GUI для анализа .blend файлов.
"""

import sys
import json
import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QPushButton, QLabel,
    QFileDialog, QSplitter, QTabWidget, QMessageBox, QHeaderView,
    QStatusBar, QProgressBar, QStyledItemDelegate, QStyle,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QRectF, QTimer
from PyQt5.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent, QIcon, QPainter, QPen, QBrush

from blend_analyzer import find_blender, save_blender_path, run_blender_extract, format_text_report


# Описания проблем и способы их исправления
ISSUE_HELP = {
    "non-manifold edge": {
        "title": "Non-manifold рёбра",
        "description": (
            "Ребро является non-manifold, если оно принадлежит не ровно 2 полигонам.\n"
            "Это значит, что в меше есть дырки, внутренние грани, двойные полигоны\n"
            "или рёбра, торчащие в никуда."
        ),
        "impact": (
            "• Subdivision Surface будет глючить в этих местах\n"
            "• Weight painting и риггинг могут работать некорректно\n"
            "• При экспорте в игровой движок будут артефакты\n"
            "• Нельзя корректно посчитать нормали"
        ),
        "fix": (
            "1. Выделите объект → Edit Mode\n"
            "2. Select → All by Trait → Non Manifold\n"
            "   (или Shift+Ctrl+Alt+F)\n"
            "3. Blender подсветит проблемные рёбра\n"
            "4. Закройте дырки клавишей F,\n"
            "   удалите лишние грани (X → Faces),\n"
            "   или слейте вершины (M → By Distance)"
        ),
    },
    "loose vertex": {
        "title": "Висячие вершины",
        "description": (
            "Вершины, которые не принадлежат ни одному полигону.\n"
            "Обычно остаются после удаления граней или неудачных операций."
        ),
        "impact": (
            "• Увеличивают размер файла без пользы\n"
            "• Могут мешать при weight painting\n"
            "• Мешают корректной работе модификаторов"
        ),
        "fix": (
            "1. Выделите объект → Edit Mode\n"
            "2. Select → All by Trait → Loose Vertices\n"
            "3. Удалите: X → Vertices\n"
            "Или автоматически: Mesh → Clean Up → Delete Loose"
        ),
    },
    "loose edge": {
        "title": "Висячие рёбра",
        "description": (
            "Рёбра, которые не принадлежат ни одному полигону.\n"
            "Обычно остаются после удаления граней."
        ),
        "impact": (
            "• Увеличивают размер файла без пользы\n"
            "• Могут вызывать артефакты при рендере\n"
            "• Мешают при экспорте в игровые движки"
        ),
        "fix": (
            "1. Выделите объект → Edit Mode\n"
            "2. Select → All by Trait → Loose Edges\n"  # добавить non manifold
            "3. Удалите: X → Edges\n"
            "Или автоматически: Mesh → Clean Up → Delete Loose"
        ),
    },
    "scale not applied": {
        "title": "Неприменённый масштаб (Scale)",
        "description": (
            "Масштаб объекта отличается от (1, 1, 1).\n"
            "Это значит, что объект был масштабирован в Object Mode,\n"
            "но трансформация не была «вжата» в геометрию."
        ),
        "impact": (
            "• Модификаторы (Bevel, Solidify и др.) работают неправильно\n"
            "• Физика и коллизии будут некорректными\n"
            "• При риггинге деформации будут искажены\n"
            "• Проблемы при экспорте в Unity/Unreal"
        ),
        "fix": (
            "1. Выделите объект(ы) в Object Mode\n"
            "2. Ctrl+A → Apply Scale\n"
            "   (или Apply All Transforms для полной очистки)\n"
            "Совет: выделите все объекты (A) и примените сразу ко всем."
        ),
    },
    "rotation not applied": {
        "title": "Неприменённый поворот (Rotation)",
        "description": (
            "Поворот объекта отличается от (0°, 0°, 0°).\n"
            "Объект был повёрнут в Object Mode, но трансформация\n"
            "не была применена к геометрии."
        ),
        "impact": (
            "• Mirror-модификатор может зеркалить не по той оси\n"
            "• При риггинге оси костей могут не совпадать\n"
            "• Проблемы при экспорте — оси будут смещены"
        ),
        "fix": (
            "1. Выделите объект(ы) в Object Mode\n"
            "2. Ctrl+A → Apply Rotation\n"
            "   (или Apply All Transforms)\n"
            "Совет: выделите все объекты (A) и примените сразу ко всем."
        ),
    },
    "no uv map": {
        "title": "Отсутствует UV-развёртка",
        "description": (
            "У объекта нет UV-карты. Без неё невозможно\n"
            "наложить текстуры на модель."
        ),
        "impact": (
            "• Текстуры не будут отображаться\n"
            "• Запекание (baking) невозможно\n"
            "• При экспорте модель будет без текстур"
        ),
        "fix": (
            "1. Выделите объект → Edit Mode\n"
            "2. Выделите все полигоны (A)\n"
            "3. UV → Smart UV Project (быстрый вариант)\n"
            "   или UV → Unwrap (точнее, но нужны швы — Mark Seam)"
        ),
    },
    "no materials": {
        "title": "Нет материалов",
        "description": "У объекта не назначено ни одного материала.",
        "impact": (
            "• Объект будет серым при рендере\n"
            "• Невозможно настроить внешний вид"
        ),
        "fix": (
            "1. Выделите объект\n"
            "2. Properties → Material → New\n"
            "3. Настройте параметры материала"
        ),
    },
    "no vertex groups": {
        "title": "Нет Vertex Groups",
        "description": (
            "У меша нет групп вершин, но в сцене есть арматура.\n"
            "Для риггинга каждая кость должна знать, какие вершины двигать."
        ),
        "impact": (
            "• Модель не будет деформироваться при движении костей\n"
            "• Анимация невозможна без vertex groups"
        ),
        "fix": (
            "1. Выделите меш, затем Shift+выделите арматуру\n"
            "2. Ctrl+P → Armature Deform → With Automatic Weights\n"
            "   Blender автоматически создаст vertex groups\n"
            "3. Доработайте веса в Weight Paint Mode"
        ),
    },
    "n-gon": {
        "title": "N-gon полигоны",
        "description": (
            "Полигоны с более чем 4 вершинами.\n"
            "Большинство движков и инструментов ожидают tris/quads."
        ),
        "impact": (
            "• Могут вызывать артефакты затенения\n"
            "• Subdivision Surface работает хуже\n"
            "• При экспорте всё равно будут разбиты на треугольники"
        ),
        "fix": (
            "1. Выделите объект → Edit Mode\n"
            "2. Select → All by Trait → Faces by Sides → больше 4\n"
            "3. Ctrl+T — разбить на треугольники\n"
            "   или вручную добавить рёбра (J/K) для quad-топологии"
        ),
    },
}


def get_issue_help(message):
    """Подобрать описание проблемы по тексту сообщения."""
    msg = message.lower()
    if "non-manifold" in msg:
        return ISSUE_HELP["non-manifold edge"]
    elif "loose vertex" in msg:
        return ISSUE_HELP["loose vertex"]
    elif "loose edge" in msg:
        return ISSUE_HELP["loose edge"]
    elif "scale not applied" in msg:
        return ISSUE_HELP["scale not applied"]
    elif "rotation not applied" in msg:
        return ISSUE_HELP["rotation not applied"]
    elif "no uv map" in msg:
        return ISSUE_HELP["no uv map"]
    elif "no materials" in msg:
        return ISSUE_HELP["no materials"]
    elif "no vertex groups" in msg or "weight painting" in msg:
        return ISSUE_HELP["no vertex groups"]
    elif "n-gon" in msg:
        return ISSUE_HELP["n-gon"]
    return None


SEVERITY_COLORS = {
    "error": QColor(220, 50, 50),
    "warning": QColor(220, 160, 30),
    "info": QColor(100, 160, 220),
}

OBJECT_TYPE_ICONS = {
    "MESH": "◆",
    "ARMATURE": "♦",
    "EMPTY": "○",
    "CAMERA": "◉",
    "LIGHT": "☀",
    "CURVE": "∿",
}


class EyeDelegate(QStyledItemDelegate):
    """Делегат, рисующий глазик вместо чекбокса в колонке 0."""

    EYE_OPEN = "👁"
    EYE_CLOSED = "ー"

    def paint(self, painter, option, index):
        if index.column() == 0:
            checked = index.data(Qt.CheckStateRole) == Qt.Checked
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)

            rect = option.rect
            cx = rect.center().x()
            cy = rect.center().y()

            if checked:
                # Глаз открыт
                painter.setPen(QPen(QColor(180, 210, 255), 1.5))
                painter.setBrush(Qt.NoBrush)
                # Форма глаза — два дуговых сегмента
                from PyQt5.QtCore import QRectF
                eye_w, eye_h = 14, 8
                eye_rect = QRectF(cx - eye_w / 2, cy - eye_h / 2, eye_w, eye_h)
                painter.drawEllipse(eye_rect)
                # Зрачок
                painter.setBrush(QBrush(QColor(130, 190, 255)))
                painter.drawEllipse(cx - 3, cy - 3, 6, 6)
                # Блик
                painter.setBrush(QBrush(QColor(255, 255, 255)))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(cx - 1, cy - 2, 2, 2)
            else:
                # Глаз закрыт — линия с ресницами
                painter.setPen(QPen(QColor(90, 90, 90), 1.5))
                painter.drawLine(cx - 7, cy, cx + 7, cy)
                # Чёрточки-ресницы
                painter.drawLine(cx - 5, cy, cx - 6, cy + 3)
                painter.drawLine(cx, cy, cx, cy + 4)
                painter.drawLine(cx + 5, cy, cx + 6, cy + 3)

            painter.restore()
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option, index):
        if index.column() == 0:
            from PyQt5.QtCore import QSize
            return QSize(28, 22)
        return super().sizeHint(option, index)


class PieChartWidget(QWidget):
    """Круговая диаграмма ошибок с подсветкой мешей при наведении."""

    hovered_group = pyqtSignal(str)    # имя группы ошибок
    hover_left = pyqtSignal()          # мышь ушла

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setMaximumHeight(250)
        self.segments = []  # [(label, count, QColor), ...]
        self.group_objects = {}  # {label: set(obj_names)}
        self.hovered_index = -1
        self.setMouseTracking(True)

    def set_data(self, segments, group_objects=None):
        """segments: list of (label, count, QColor)"""
        self.segments = segments
        self.group_objects = group_objects or {}
        self.update()

    def paintEvent(self, event):
        if not self.segments:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        total = sum(s[1] for s in self.segments)
        if total == 0:
            return

        # Размеры
        w = self.width()
        h = self.height()
        chart_size = min(w // 2 - 10, h - 30)
        if chart_size < 60:
            return

        cx = chart_size // 2 + 10
        cy = h // 2
        rect = QRectF(cx - chart_size // 2, cy - chart_size // 2, chart_size, chart_size)

        # Рисуем сегменты
        start_angle = 90 * 16  # начинаем сверху
        for i, (label, count, color) in enumerate(self.segments):
            span = int(count / total * 360 * 16)
            if span == 0:
                span = 1 * 16

            painter.setPen(QPen(QColor(30, 30, 30), 2))

            if i == self.hovered_index:
                # Подсветка при наведении
                bright = QColor(
                    min(color.red() + 40, 255),
                    min(color.green() + 40, 255),
                    min(color.blue() + 40, 255),
                )
                painter.setBrush(QBrush(bright))
            else:
                painter.setBrush(QBrush(color))

            painter.drawPie(rect, start_angle, -span)
            start_angle -= span

        # Легенда справа
        legend_x = cx + chart_size // 2 + 20
        legend_y = 20
        painter.setPen(Qt.NoPen)

        for i, (label, count, color) in enumerate(self.segments):
            pct = count / total * 100
            # Цветной квадратик
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(legend_x, legend_y + i * 24, 12, 12, 2, 2)

            # Текст
            painter.setPen(QPen(QColor(200, 200, 200)))
            painter.setFont(QFont("sans-serif", 9))
            painter.drawText(
                legend_x + 18, legend_y + i * 24 + 11,
                f"{label}: {count} ({pct:.0f}%)"
            )
            painter.setPen(Qt.NoPen)

        painter.end()

    def mouseMoveEvent(self, event):
        """Определить на какой сегмент наведена мышь."""
        if not self.segments:
            return

        import math

        total = sum(s[1] for s in self.segments)
        if total == 0:
            return

        w = self.width()
        h = self.height()
        chart_size = min(w // 2 - 10, h - 30)
        cx = chart_size // 2 + 10
        cy = h // 2

        dx = event.x() - cx
        dy = event.y() - cy
        dist = math.sqrt(dx * dx + dy * dy)

        new_hover = -1

        if dist <= chart_size // 2:
            # Навели на сегмент
            angle = math.degrees(math.atan2(dx, -dy)) % 360
            cumulative = 0
            for i, (label, count, color) in enumerate(self.segments):
                cumulative += count / total * 360
                if angle <= cumulative:
                    new_hover = i
                    break
        else:
            # Проверяем наведение на легенду
            legend_x = cx + chart_size // 2 + 20
            legend_y = 20
            mx, my = event.x(), event.y()
            for i in range(len(self.segments)):
                ly = legend_y + i * 24
                if legend_x <= mx <= legend_x + 200 and ly - 2 <= my <= ly + 16:
                    new_hover = i
                    break

        if new_hover != self.hovered_index:
            self.hovered_index = new_hover
            self.update()
            if new_hover >= 0 and new_hover < len(self.segments):
                label = self.segments[new_hover][0]
                self.hovered_group.emit(label)
            else:
                self.hover_left.emit()

    def leaveEvent(self, event):
        self.hovered_index = -1
        self.update()
        self.hover_left.emit()


class WireframeWidget(QWidget):
    """3D-превью модели с 3 режимами отображения."""

    MODE_WIREFRAME = 0
    MODE_SOLID = 1
    MODE_MATERIAL = 2
    MODE_NAMES = ["Каркас", "Solid", "Материалы"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)

        # Геометрия
        self.verts = []
        self.edges = []
        self.faces = []        # [[verts_list, nx, ny, nz, mat_idx], ...]
        self.mat_colors = []   # [[r, g, b], ...] per object
        self.obj_names = []    # имя объекта для каждого face
        self.highlighted_objects = set()  # объекты для подсветки
        self.center = [0, 0, 0]
        self.scale_factor = 1.0

        # Режим отображения
        self.view_mode = self.MODE_WIREFRAME

        # Камера
        self.rot_x = 25.0
        self.rot_y = 45.0
        self.zoom = 1.0

        # Мышь
        self.last_mouse_pos = None
        self.dragging = False

        # Авто-вращение
        self.auto_rotate = True
        self.auto_timer = QTimer()
        self.auto_timer.timeout.connect(self._auto_rotate_step)
        self.auto_timer.start(30)

    def cycle_mode(self):
        """Переключить режим отображения."""
        self.view_mode = (self.view_mode + 1) % 3
        self.update()

    def load_mesh_data(self, data, hidden_objects=None):
        """Загрузить геометрию из данных анализа."""
        if hidden_objects is None:
            hidden_objects = set()

        all_verts = []
        all_edges = []
        all_edge_obj_names = []
        all_faces = []
        all_mat_colors = []
        all_obj_names = []
        vert_offset = 0
        mat_offset = 0

        objects = data.get("objects", [])
        for obj in objects:
            if obj.get("type") != "MESH":
                continue
            if obj.get("name") in hidden_objects:
                continue
            mesh = obj.get("mesh", {})
            pverts = mesh.get("preview_verts", [])
            pedges = mesh.get("preview_edges", [])
            pfaces = mesh.get("preview_faces", [])
            mcols = mesh.get("mat_colors", [[0.5, 0.5, 0.5]])

            obj_name = obj.get("name", "")
            all_verts.extend(pverts)
            for e in pedges:
                all_edges.append([e[0] + vert_offset, e[1] + vert_offset])
                all_edge_obj_names.append(obj_name)
            for f in pfaces:
                verts_shifted = [v + vert_offset for v in f[0]]
                all_faces.append([
                    verts_shifted,
                    f[1], f[2], f[3],
                    f[4] + mat_offset,
                ])
                all_obj_names.append(obj_name)
            all_mat_colors.extend(mcols)
            vert_offset += len(pverts)
            mat_offset += len(mcols)

        if not all_verts:
            return

        self.verts = all_verts
        self.edges = all_edges
        self.edge_obj_names = all_edge_obj_names
        self.faces = all_faces
        self.obj_names = all_obj_names
        self.mat_colors = all_mat_colors

        # Вычислить центр и масштаб
        xs = [v[0] for v in all_verts]
        ys = [v[1] for v in all_verts]
        zs = [v[2] for v in all_verts]
        self.center = [
            (min(xs) + max(xs)) / 2,
            (min(ys) + max(ys)) / 2,
            (min(zs) + max(zs)) / 2,
        ]
        size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        self.scale_factor = 1.0 / size if size > 0 else 1.0

        self.update()

    def _project(self, x, y, z):
        """Проецировать 3D-точку на 2D экран (Blender: Z=вверх)."""
        import math

        x -= self.center[0]
        y -= self.center[1]
        z -= self.center[2]

        x *= self.scale_factor
        y *= self.scale_factor
        z *= self.scale_factor

        angle_y = math.radians(self.rot_y)
        cos_y = math.cos(angle_y)
        sin_y = math.sin(angle_y)
        nx = x * cos_y - y * sin_y
        ny = x * sin_y + y * cos_y

        angle_x = math.radians(self.rot_x)
        cos_x = math.cos(angle_x)
        sin_x = math.sin(angle_x)
        nz = z * cos_x - ny * sin_x
        depth = z * sin_x + ny * cos_x

        w = self.width()
        h = self.height()
        view_size = min(w, h) * 0.38 * self.zoom

        screen_x = w / 2 + nx * view_size
        screen_y = h / 2 - nz * view_size

        return screen_x, screen_y, depth

    def _rotate_normal(self, nx, ny, nz):
        """Повернуть нормаль для расчёта освещения."""
        import math

        angle_y = math.radians(self.rot_y)
        cos_y = math.cos(angle_y)
        sin_y = math.sin(angle_y)
        rx = nx * cos_y - ny * sin_y
        ry = nx * sin_y + ny * cos_y

        angle_x = math.radians(self.rot_x)
        cos_x = math.cos(angle_x)
        sin_x = math.sin(angle_x)
        rz = nz * cos_x - ry * sin_x
        rd = nz * sin_x + ry * cos_x

        return rx, rd, rz

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, QColor(26, 26, 26))

        if not self.verts:
            painter.setPen(QPen(QColor(80, 80, 80)))
            painter.setFont(QFont("sans-serif", 11))
            painter.drawText(0, 0, w, h, Qt.AlignCenter, "3D-превью\nЗагрузите .blend файл")
            painter.end()
            return

        # Проецируем все вершины
        projected = [self._project(v[0], v[1], v[2]) for v in self.verts]

        if self.view_mode == self.MODE_WIREFRAME:
            self._draw_wireframe(painter, projected)
        else:
            self._draw_solid(painter, projected)

        # Подсказка и режим
        painter.setPen(QPen(QColor(80, 80, 80)))
        painter.setFont(QFont("sans-serif", 9))
        mode_name = self.MODE_NAMES[self.view_mode]
        painter.drawText(8, h - 8, f"ЛКМ: вращение | Колёсико: зум | ПКМ: режим [{mode_name}]")

        painter.end()

    def _draw_wireframe(self, painter, projected):
        """Рисовать каркас."""
        for i, edge in enumerate(self.edges):
            v1_idx, v2_idx = edge
            if v1_idx >= len(projected) or v2_idx >= len(projected):
                continue
            x1, y1, d1 = projected[v1_idx]
            x2, y2, d2 = projected[v2_idx]

            obj_name = self.edge_obj_names[i] if i < len(self.edge_obj_names) else ""
            if self.highlighted_objects and obj_name in self.highlighted_objects:
                color = QColor(255, 80, 80)
                painter.setPen(QPen(color, 2))
            else:
                avg_depth = (d1 + d2) / 2
                brightness = max(40, min(200, int(140 - avg_depth * 80)))
                color = QColor(brightness, brightness + 20, brightness + 50)
                painter.setPen(QPen(color, 1))

            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _calc_lighting(self, nx, ny, nz):
        """Рассчитать освещение — яркое, с видимыми цветами."""
        rnx, rny, rnz = self._rotate_normal(nx, ny, nz)

        # Главный свет — очень яркий, спереди-сверху
        key = max(0.0, rnz * 0.6 + rny * -0.5 + rnx * 0.2)
        # Заполняющий — слева-спереди
        fill = max(0.0, rnx * -0.5 + rnz * 0.3 + rny * -0.3) * 0.5
        # Обводной — сзади
        rim = max(0.0, rny * 0.6 + rnz * 0.2) * 0.3
        # Высокий амбиент чтобы тёмные материалы были видны
        ambient = 0.5

        return min(1.0, ambient + key + fill + rim)

    def _draw_solid(self, painter, projected):
        """Рисовать solid/material режим — полигоны без триангуляции, backface culling."""
        from PyQt5.QtGui import QPolygonF
        from PyQt5.QtCore import QPointF

        draw_list = []
        for fi, face in enumerate(self.faces):
            vert_indices = face[0]
            nx, ny, nz = face[1], face[2], face[3]
            mat_idx = face[4]

            if len(vert_indices) < 3:
                continue

            # Проверяем и проецируем вершины
            points = []
            depth_sum = 0.0
            max_depth = float('-inf')
            valid = True
            for vi in vert_indices:
                if vi >= len(projected):
                    valid = False
                    break
                sx, sy, d = projected[vi]
                points.append((sx, sy))
                depth_sum += d
                if d > max_depth:
                    max_depth = d

            if not valid or not points:
                continue

            obj_name = self.obj_names[fi] if fi < len(self.obj_names) else ""
            is_highlighted = self.highlighted_objects and obj_name in self.highlighted_objects

            # Освещение
            light = self._calc_lighting(nx, ny, nz)

            if is_highlighted:
                # Подсветка красным
                r = int(min(255, 200 * light + 80))
                g = int(min(255, 50 * light))
                b = int(min(255, 50 * light))
            elif self.view_mode == self.MODE_MATERIAL and mat_idx < len(self.mat_colors):
                mc = self.mat_colors[mat_idx]
                r = int(min(255, mc[0] * 255 * light))
                g = int(min(255, mc[1] * 255 * light))
                b = int(min(255, mc[2] * 255 * light))
            else:
                val = int(180 * light)
                r, g, b = val, val, val

            avg_depth = depth_sum / len(vert_indices)
            # Смешанный ключ: средняя глубина + макс глубина для разрешения конфликтов
            sort_key = avg_depth * 0.7 + max_depth * 0.3
            draw_list.append((sort_key, points, r, g, b))

        # Сортировка: дальние первыми
        draw_list.sort(key=lambda t: t[0], reverse=True)

        for _, points, r, g, b in draw_list:
            poly = QPolygonF([QPointF(x, y) for x, y in points])
            face_color = QColor(r, g, b)
            # Обводка тем же цветом закрывает щели между полигонами
            painter.setPen(QPen(face_color, 1))
            painter.setBrush(QBrush(face_color))
            painter.drawPolygon(poly)

    def _auto_rotate_step(self):
        if self.auto_rotate and self.verts:
            self.rot_y += 0.5
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.last_mouse_pos = event.pos()
            self.auto_rotate = False
        elif event.button() == Qt.RightButton:
            self.cycle_mode()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def mouseMoveEvent(self, event):
        if self.dragging and self.last_mouse_pos:
            dx = event.x() - self.last_mouse_pos.x()
            dy = event.y() - self.last_mouse_pos.y()

            self.rot_y += dx * 0.5
            self.rot_x += dy * 0.5
            self.rot_x = max(-90, min(90, self.rot_x))

            self.last_mouse_pos = event.pos()
            self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom *= 1.1
        else:
            self.zoom /= 1.1
        self.zoom = max(0.2, min(5.0, self.zoom))
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Двойной клик — сброс камеры и включение авто-вращения."""
        self.rot_x = 25.0
        self.rot_y = 45.0
        self.zoom = 1.0
        self.auto_rotate = True
        self.update()

    def cleanup(self):
        self.auto_timer.stop()
        self.verts = []
        self.edges = []
        self.faces = []
        self.obj_names = []
        self.edge_obj_names = []
        self.highlighted_objects = set()


class BlenderWorker(QThread):
    """Фоновый поток для запуска Blender."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, blender_path, blend_file):
        super().__init__()
        self.blender_path = blender_path
        self.blend_file = blend_file

    def run(self):
        try:
            data = run_blender_extract(self.blender_path, self.blend_file)
            self.finished.emit(data)
        except SystemExit:
            self.error.emit("Не удалось извлечь данные из Blender")
        except Exception as e:
            self.error.emit(str(e))


class DropZone(QLabel):
    """Зона для drag & drop файлов."""
    file_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setText("Перетащите .blend файл сюда\nили нажмите кнопку «Открыть»")
        self.setMinimumHeight(100)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #555;
                border-radius: 10px;
                color: #aaa;
                font-size: 14px;
                padding: 20px;
                background: #2a2a2a;
            }
            QLabel:hover {
                border-color: #888;
                color: #ccc;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0].toLocalFile()
            if url.endswith(".blend"):
                event.acceptProposedAction()
                self.setStyleSheet(self.styleSheet().replace("border: 2px dashed #555", "border: 2px dashed #4a9eff"))

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.styleSheet().replace("border: 2px dashed #4a9eff", "border: 2px dashed #555"))

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.styleSheet().replace("border: 2px dashed #4a9eff", "border: 2px dashed #555"))
        url = event.mimeData().urls()[0].toLocalFile()
        if url.endswith(".blend"):
            self.file_dropped.emit(url)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blend Analyzer")
        self.setMinimumSize(1000, 700)
        self.data = None
        self.worker = None
        self.blender_path = find_blender()

        # Иконка окна (видна в панели задач)
        icon_path = Path(__file__).parent / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._setup_ui()
        self._apply_dark_theme()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # === Верхняя панель ===
        top_bar = QHBoxLayout()

        self.btn_open = QPushButton("Открыть .blend")
        self.btn_open.setFixedHeight(36)
        self.btn_open.clicked.connect(self._open_file)
        top_bar.addWidget(self.btn_open)

        self.lbl_file = QLabel("Файл не загружен")
        self.lbl_file.setStyleSheet("color: #888; font-size: 13px;")
        top_bar.addWidget(self.lbl_file, 1)

        self.btn_copy = QPushButton("Копировать отчёт")
        self.btn_copy.setFixedHeight(36)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_report)
        top_bar.addWidget(self.btn_copy)

        self.btn_copy_json = QPushButton("Копировать JSON")
        self.btn_copy_json.setFixedHeight(36)
        self.btn_copy_json.setEnabled(False)
        self.btn_copy_json.clicked.connect(self._copy_json)
        top_bar.addWidget(self.btn_copy_json)

        main_layout.addLayout(top_bar)

        # === Drop zone (видна пока нет данных) ===
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._load_file)
        main_layout.addWidget(self.drop_zone)

        # === Основной контент (скрыт пока нет данных) ===
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setVisible(False)
        main_layout.addWidget(self.content_splitter, 1)

        # Левая панель — дерево объектов
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_objects = QLabel("Объекты")
        self.lbl_objects.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        left_layout.addWidget(self.lbl_objects)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Имя", "Тип", "Вершины", "Полигоны"])
        self.tree.setColumnWidth(0, 28)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 70)
        self.tree.setColumnWidth(4, 70)
        self.tree.setItemDelegateForColumn(0, EyeDelegate(self.tree))
        self.tree.currentItemChanged.connect(self._on_object_selected)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        self.hidden_objects = set()
        self._updating_tree = False
        left_layout.addWidget(self.tree)

        self.content_splitter.addWidget(left_panel)

        # Центральная панель — превью сверху + табы снизу
        center_splitter = QSplitter(Qt.Vertical)

        # 3D превью с кнопками режимов
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # Кнопки переключения режима
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(2)

        btn_style_active = """
            QPushButton {
                background-color: #264f78;
                color: white;
                border: 1px solid #4a9eff;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: 11px;
            }
        """
        btn_style_inactive = """
            QPushButton {
                background-color: #2d2d2d;
                color: #aaa;
                border: 1px solid #3c3c3c;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3c3c3c;
                color: white;
            }
        """

        self.btn_mode_wire = QPushButton("Каркас")
        self.btn_mode_solid = QPushButton("Solid")
        self.btn_mode_mat = QPushButton("Материалы")

        self.mode_buttons = [self.btn_mode_wire, self.btn_mode_solid, self.btn_mode_mat]
        self._btn_style_active = btn_style_active
        self._btn_style_inactive = btn_style_inactive

        for i, btn in enumerate(self.mode_buttons):
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked, idx=i: self._set_view_mode(idx))
            mode_bar.addWidget(btn)

        self._update_mode_buttons(0)

        mode_bar.addStretch()
        preview_layout.addLayout(mode_bar)

        self.wireframe = WireframeWidget()
        preview_layout.addWidget(self.wireframe, 1)

        center_splitter.addWidget(preview_container)

        # Табы с деталями
        self.tabs = QTabWidget()

        self.txt_details = QTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setFont(QFont("Monospace", 10))
        self.tabs.addTab(self.txt_details, "Детали")

        self.txt_materials = QTextEdit()
        self.txt_materials.setReadOnly(True)
        self.txt_materials.setFont(QFont("Monospace", 10))
        self.tabs.addTab(self.txt_materials, "Материалы")

        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setFont(QFont("Monospace", 9))
        self.tabs.addTab(self.txt_report, "Полный отчёт")

        center_splitter.addWidget(self.tabs)
        center_splitter.setSizes([350, 300])

        self.content_splitter.addWidget(center_splitter)

        # Правая панель — проблемы (закрываемая)
        self.issues_panel = QWidget()
        issues_layout = QVBoxLayout(self.issues_panel)
        issues_layout.setContentsMargins(0, 0, 0, 0)
        issues_layout.setSpacing(4)

        # Заголовок с кнопкой закрытия
        issues_header = QHBoxLayout()
        self.lbl_issues = QLabel("Проблемы")
        self.lbl_issues.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        issues_header.addWidget(self.lbl_issues, 1)

        self.btn_close_issues = QPushButton("✕")
        self.btn_close_issues.setFixedSize(24, 24)
        self.btn_close_issues.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #c42b1c;
                color: white;
            }
        """)
        self.btn_close_issues.clicked.connect(self._toggle_issues_panel)
        issues_header.addWidget(self.btn_close_issues)
        issues_layout.addLayout(issues_header)

        # Круговая диаграмма (с кнопкой закрытия)
        self.chart_container = QWidget()
        chart_container_layout = QVBoxLayout(self.chart_container)
        chart_container_layout.setContentsMargins(0, 0, 0, 0)
        chart_container_layout.setSpacing(0)

        chart_header = QHBoxLayout()
        chart_label = QLabel("Диаграмма ошибок")
        chart_label.setStyleSheet("color: #888; font-size: 11px; padding: 2px 4px;")
        chart_header.addWidget(chart_label, 1)

        btn_close_chart = QPushButton("✕")
        btn_close_chart.setFixedSize(20, 20)
        btn_close_chart.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #666;
                border: none;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #c42b1c;
                color: white;
                border-radius: 3px;
            }
        """)
        btn_close_chart.clicked.connect(lambda: self.chart_container.setVisible(False))
        chart_header.addWidget(btn_close_chart)
        chart_container_layout.addLayout(chart_header)

        self.pie_chart = PieChartWidget()
        self.pie_chart.hovered_group.connect(self._on_chart_hover)
        self.pie_chart.hover_left.connect(self._on_chart_leave)
        chart_container_layout.addWidget(self.pie_chart)

        issues_layout.addWidget(self.chart_container)

        # Дерево проблем — группировка по типу ошибки
        self.tree_issues = QTreeWidget()
        self.tree_issues.setHeaderHidden(True)
        self.tree_issues.setIndentation(20)
        self.tree_issues.setWordWrap(True)
        self.tree_issues.setMouseTracking(True)
        self.tree_issues.itemClicked.connect(self._on_issue_clicked)
        self.tree_issues.itemEntered.connect(self._on_issue_hover)
        self.tree_issues.viewport().installEventFilter(self)
        issues_layout.addWidget(self.tree_issues)

        self.content_splitter.addWidget(self.issues_panel)
        self.content_splitter.setSizes([250, 500, 280])

        # Кнопка показа панели проблем (когда она скрыта)
        self.btn_show_issues = QPushButton("Проблемы ▶")
        self.btn_show_issues.setFixedHeight(36)
        self.btn_show_issues.setVisible(False)
        self.btn_show_issues.clicked.connect(self._toggle_issues_panel)
        top_bar.addWidget(self.btn_show_issues)

        # === Статус бар ===
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)  # indeterminate
        self.status.addPermanentWidget(self.progress)

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
            QTreeWidget {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                font-size: 12px;
            }
            QTreeWidget::item:selected {
                background-color: #264f78;
            }
            QTreeWidget::item:hover {
                background-color: #2a2d2e;
            }
            QHeaderView::section {
                background-color: #333;
                color: #ccc;
                border: 1px solid #444;
                padding: 4px;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                color: #d4d4d4;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:disabled {
                background-color: #3c3c3c;
                color: #666;
            }
            QTabWidget::pane {
                border: 1px solid #3c3c3c;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #888;
                padding: 6px 14px;
                border: 1px solid #3c3c3c;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
            QStatusBar {
                background-color: #007acc;
                color: white;
                font-size: 12px;
            }
            QProgressBar {
                border: none;
                background-color: #005a9e;
                color: white;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #40a0ff;
            }
            QSplitter::handle {
                background-color: #3c3c3c;
            }
        """)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть .blend файл", "",
            "Blender Files (*.blend);;All Files (*)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        if not self.blender_path:
            # Попросить указать путь вручную
            blender, _ = QFileDialog.getOpenFileName(
                self, "Укажите путь к Blender", "",
                "Blender (blender*);;All Files (*)"
            )
            if not blender:
                return
            self.blender_path = blender
            save_blender_path(blender)

        self.current_blend_path = path
        self.lbl_file.setText(f"Загрузка: {os.path.basename(path)}...")
        self.lbl_file.setStyleSheet("color: #4a9eff; font-size: 13px;")
        self.btn_open.setEnabled(False)
        self.progress.setVisible(True)
        self.status.showMessage("Извлечение данных через Blender...")

        self.worker = BlenderWorker(self.blender_path, path)
        self.worker.finished.connect(self._on_data_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.start()


    def _on_data_loaded(self, data):
        self.data = data
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self.btn_copy_json.setEnabled(True)

        blend_name = os.path.basename(data.get("file", "?"))
        obj_count = len(data.get("objects", []))
        issue_count = len(data.get("issues", []))

        self.lbl_file.setText(f"{blend_name} — Blender {data.get('blender_version', '?')}")
        self.lbl_file.setStyleSheet("color: #4ec990; font-size: 13px;")
        self.status.showMessage(f"Загружено: {obj_count} объектов, {issue_count} проблем")

        self.drop_zone.setVisible(False)
        self.content_splitter.setVisible(True)

        self._populate_tree(data)
        self._populate_issues(data)
        self.wireframe.load_mesh_data(data, self.hidden_objects)
        self.txt_report.setPlainText(format_text_report(data))

        self.lbl_objects.setText(f"Объекты ({obj_count})")
        self.lbl_issues.setText(f"Проблемы ({issue_count})")

    def _on_error(self, msg):
        self.progress.setVisible(False)
        self.btn_open.setEnabled(True)
        self.lbl_file.setText("Ошибка загрузки")
        self.lbl_file.setStyleSheet("color: #f44; font-size: 13px;")
        self.status.showMessage(f"Ошибка: {msg}")
        QMessageBox.critical(self, "Ошибка", msg)


    def _populate_tree(self, data):
        self._updating_tree = True
        self.tree.clear()
        objects = data.get("objects", [])

        # Построить дерево parent-child
        obj_map = {obj["name"]: obj for obj in objects}
        items_map = {}

        # Сначала создаём все элементы
        for obj in objects:
            icon = OBJECT_TYPE_ICONS.get(obj["type"], "?")
            verts = ""
            faces = ""
            if obj["type"] == "MESH":
                m = obj.get("mesh", {})
                verts = f"{m.get('vertices', 0):,}"
                faces = f"{m.get('faces', 0):,}"
            elif obj["type"] == "ARMATURE":
                arm = obj.get("armature", {})
                verts = f"{arm.get('bone_count', 0)} bones"

            visible = obj["name"] not in self.hidden_objects

            item = QTreeWidgetItem([
                "",
                f"{icon} {obj['name']}",
                obj["type"],
                verts,
                faces,
            ])
            item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
            if not visible:
                for col in range(1, 5):
                    item.setForeground(col, QColor(80, 80, 80))
            items_map[obj["name"]] = (item, obj)

        # Строим иерархию
        for name, (item, obj) in items_map.items():
            parent_name = obj.get("parent")
            if parent_name and parent_name in items_map:
                parent_item, _ = items_map[parent_name]
                parent_item.addChild(item)
            else:
                self.tree.addTopLevelItem(item)

        self.tree.expandAll()
        self._updating_tree = False

    def _on_object_selected(self, current, previous):
        if not current or not self.data:
            return

        # Извлечь имя без иконки (колонка 1 теперь)
        name = current.text(1)
        for icon in OBJECT_TYPE_ICONS.values():
            name = name.replace(f"{icon} ", "")

        obj = None
        for o in self.data.get("objects", []):
            if o["name"] == name:
                obj = o
                break

        if not obj:
            return

        self._show_details(obj)
        self._show_materials(obj)

    def _show_details(self, obj):
        lines = []
        lines.append(f"{'='*40}")
        lines.append(f"  {obj['name']}  [{obj['type']}]")
        lines.append(f"{'='*40}")

        t = obj.get("transform", {})
        pos = t.get("position", [0, 0, 0])
        rot = t.get("rotation_deg", [0, 0, 0])
        scale = t.get("scale", [1, 1, 1])

        lines.append(f"\nTransform:")
        lines.append(f"  Position:  {pos[0]:>8.4f}  {pos[1]:>8.4f}  {pos[2]:>8.4f}")
        lines.append(f"  Rotation:  {rot[0]:>8.2f}° {rot[1]:>8.2f}° {rot[2]:>8.2f}°")
        lines.append(f"  Scale:     {scale[0]:>8.4f}  {scale[1]:>8.4f}  {scale[2]:>8.4f}")

        if obj.get("parent"):
            lines.append(f"  Parent:    {obj['parent']}")

        if obj["type"] == "MESH":
            m = obj.get("mesh", {})
            lines.append(f"\nGeometry:")
            lines.append(f"  Vertices:  {m.get('vertices', 0):,}")
            lines.append(f"  Edges:     {m.get('edges', 0):,}")
            lines.append(f"  Faces:     {m.get('faces', 0):,}")

            total = m.get("faces", 0)
            if total:
                lines.append(f"    Tris:    {m.get('tris', 0):,}  ({m.get('tris', 0) / total * 100:.1f}%)")
                lines.append(f"    Quads:   {m.get('quads', 0):,}  ({m.get('quads', 0) / total * 100:.1f}%)")
                lines.append(f"    N-gons:  {m.get('ngons', 0):,}  ({m.get('ngons', 0) / total * 100:.1f}%)")

            dims = m.get("dimensions", [0, 0, 0])
            lines.append(f"\n  Dimensions: {dims[0]:.4f} x {dims[1]:.4f} x {dims[2]:.4f}")

            bbox_min = m.get("bounding_box_min", [0, 0, 0])
            bbox_max = m.get("bounding_box_max", [0, 0, 0])
            lines.append(f"  BBox min:  ({bbox_min[0]:.4f}, {bbox_min[1]:.4f}, {bbox_min[2]:.4f})")
            lines.append(f"  BBox max:  ({bbox_max[0]:.4f}, {bbox_max[1]:.4f}, {bbox_max[2]:.4f})")

            # Vertex groups
            vgroups = m.get("vertex_groups", [])
            lines.append(f"\nVertex Groups ({len(vgroups)}):")
            if vgroups:
                for vg in vgroups:
                    lines.append(f"  • {vg}")
            else:
                lines.append("  (нет)")

            # UV
            uv = m.get("uv_layers", [])
            lines.append(f"\nUV Maps ({len(uv)}):")
            if uv:
                for u in uv:
                    lines.append(f"  • {u}")
            else:
                lines.append("  (нет)")

            # Topology issues
            issues = []
            if m.get("loose_vertices", 0):
                issues.append(f"Loose vertices: {m['loose_vertices']}")
            if m.get("loose_edges", 0):
                issues.append(f"Loose edges: {m['loose_edges']}")
            if m.get("non_manifold_edges", 0):
                issues.append(f"Non-manifold edges: {m['non_manifold_edges']}")
            if issues:
                lines.append(f"\nTopology Issues:")
                for iss in issues:
                    lines.append(f"  ⚠ {iss}")

            # Density
            density = m.get("density_zones", {})
            if density:
                lines.append(f"\nVertex Density by Zone:")
                for zone, count in density.items():
                    lines.append(f"  {zone:>8}: {count:,} verts")

            # Modifiers
            mods = obj.get("modifiers", [])
            if mods:
                lines.append(f"\nModifiers ({len(mods)}):")
                for mod in mods:
                    lines.append(f"  [{mod['type']}] {mod['name']}")
                    extras = {k: v for k, v in mod.items() if k not in ("name", "type")}
                    for k, v in extras.items():
                        lines.append(f"    {k}: {v}")

        elif obj["type"] == "ARMATURE":
            arm = obj.get("armature", {})
            bones = arm.get("bones", [])
            lines.append(f"\nBones ({len(bones)}):")
            for bone in bones:
                indent = "  "
                parent_str = f" ← {bone['parent']}" if bone["parent"] else " (root)"
                lines.append(f"{indent}• {bone['name']}{parent_str}")
                lines.append(f"{indent}  length: {bone['length']:.4f}")
                lines.append(f"{indent}  head: {bone['head']}")
                lines.append(f"{indent}  tail: {bone['tail']}")
                if bone["children"]:
                    lines.append(f"{indent}  children: {', '.join(bone['children'])}")

            actions = arm.get("actions", [])
            if actions:
                lines.append(f"\nActions ({len(actions)}):")
                for act in actions:
                    lines.append(f"  • {act['name']} [frames {act['frame_range'][0]}-{act['frame_range'][1]}]")

        self.txt_details.setPlainText("\n".join(lines))

    def _show_materials(self, obj):
        mats = obj.get("materials", [])
        if not mats:
            self.txt_materials.setPlainText("Нет материалов")
            return

        lines = []
        for mat in mats:
            lines.append(f"{'='*40}")
            lines.append(f"  {mat.get('name', '?')}")
            lines.append(f"{'='*40}")

            if "shader" in mat:
                lines.append(f"  Shader: {mat['shader']}")
                params = mat.get("params", {})
                for key, val in params.items():
                    if isinstance(val, list) and len(val) >= 3:
                        if len(val) == 4:
                            lines.append(f"  {key}: rgba({val[0]:.3f}, {val[1]:.3f}, {val[2]:.3f}, {val[3]:.3f})")
                        else:
                            lines.append(f"  {key}: ({', '.join(f'{v:.3f}' for v in val)})")
                    else:
                        lines.append(f"  {key}: {val}")
            lines.append("")

        self.txt_materials.setPlainText("\n".join(lines))

    def _on_tree_item_changed(self, item, column):
        """Чекбокс изменён — переключить видимость объекта в превью."""
        if self._updating_tree or column != 0:
            return

        name = item.text(1)
        for icon in OBJECT_TYPE_ICONS.values():
            name = name.replace(f"{icon} ", "")

        checked = item.checkState(0) == Qt.Checked

        if checked:
            self.hidden_objects.discard(name)
            for col in range(1, 5):
                item.setForeground(col, QColor(212, 212, 212))
        else:
            self.hidden_objects.add(name)
            for col in range(1, 5):
                item.setForeground(col, QColor(80, 80, 80))

        self._rebuild_preview()

    def _rebuild_preview(self):
        """Перестроить 3D-превью с учётом скрытых объектов."""
        if not self.data:
            return
        self.wireframe.load_mesh_data(self.data, self.hidden_objects)

    def _on_chart_hover(self, group_label):
        """При наведении на сегмент диаграммы — подсветить связанные объекты."""
        obj_names = self.pie_chart.group_objects.get(group_label, set())
        self.wireframe.highlighted_objects = obj_names
        self.wireframe.update()

    def _on_chart_leave(self):
        """Мышь ушла с диаграммы — убрать подсветку."""
        self.wireframe.highlighted_objects = set()
        self.wireframe.update()

    def _set_view_mode(self, mode):
        self.wireframe.view_mode = mode
        self._update_mode_buttons(mode)
        self.wireframe.update()

    def _update_mode_buttons(self, active):
        for i, btn in enumerate(self.mode_buttons):
            if i == active:
                btn.setStyleSheet(self._btn_style_active)
            else:
                btn.setStyleSheet(self._btn_style_inactive)

    def _toggle_issues_panel(self):
        """Показать/скрыть панель проблем."""
        visible = self.issues_panel.isVisible()
        self.issues_panel.setVisible(not visible)
        self.btn_show_issues.setVisible(visible)

    def eventFilter(self, obj, event):
        """Отслеживать уход мыши из дерева ошибок — снять подсветку."""
        try:
            if hasattr(self, 'tree_issues') and obj == self.tree_issues.viewport():
                from PyQt5.QtCore import QEvent
                if event.type() == QEvent.Leave:
                    self.wireframe.highlighted_objects = set()
                    self.wireframe.update()
        except RuntimeError:
            pass
        return super().eventFilter(obj, event)

    def _on_issue_hover(self, item, column):
        """При наведении на строку ошибки — подсветить объект в превью."""
        if not item or not self.data:
            return
        text = item.text(0) or ""

        # Ищем имя объекта — строки вида "  ObjectName  —  описание"
        obj_names = set()
        if "—" in text:
            name = text.split("—")[0].strip()
            if name:
                obj_names.add(name)
        elif item.parent():
            # Может это группа — подсветить все объекты в ней
            parent = item.parent() if item.childCount() == 0 else item
            for i in range(parent.childCount()):
                child_text = parent.child(i).text(0)
                if "—" in child_text:
                    name = child_text.split("—")[0].strip()
                    if name:
                        obj_names.add(name)

        # Если навели на заголовок группы — подсветить все объекты этой группы
        if item.childCount() > 0 and not obj_names:
            for i in range(item.childCount()):
                child_text = item.child(i).text(0)
                if "—" in child_text:
                    name = child_text.split("—")[0].strip()
                    if name:
                        obj_names.add(name)

        self.wireframe.highlighted_objects = obj_names
        self.wireframe.update()

    def _on_issue_clicked(self, item, column):
        """Раскрыть/свернуть элемент при клике."""
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())

    def _populate_issues(self, data):
        self.tree_issues.clear()
        issues = data.get("issues", [])

        if not issues:
            item = QTreeWidgetItem(["Проблем не обнаружено"])
            item.setForeground(0, QColor(78, 201, 144))
            self.tree_issues.addTopLevelItem(item)
            self.pie_chart.set_data([])
            self.chart_container.setVisible(False)
            return

        self.chart_container.setVisible(True)

        # Группируем ошибки по типу
        from collections import OrderedDict
        groups = OrderedDict()

        for issue in issues:
            help_info = get_issue_help(issue["message"])
            if help_info:
                key = help_info["title"]
            else:
                key = issue["message"]

            if key not in groups:
                groups[key] = {
                    "help": help_info,
                    "severity": issue["severity"],
                    "objects": [],
                }
            groups[key]["objects"].append(issue)

        # Сортируем: error > warning > info
        severity_order = {"error": 0, "warning": 1, "info": 2}
        sorted_groups = sorted(groups.items(), key=lambda x: severity_order.get(x[1]["severity"], 3))

        for group_name, group_data in sorted_groups:
            severity = group_data["severity"]
            obj_count = len(group_data["objects"])
            color = SEVERITY_COLORS.get(severity, QColor(150, 150, 150))

            sev_icon = {"error": "✖", "warning": "⚠", "info": "ℹ"}.get(severity, "?")

            # Родительский элемент — тип ошибки
            parent = QTreeWidgetItem([
                f"{sev_icon}  {group_name}  ({obj_count})"
            ])
            parent.setForeground(0, color)
            font = parent.font(0)
            font.setBold(True)
            font.setPointSize(11)
            parent.setFont(0, font)

            # Дочерние: описание, объекты, решение
            help_info = group_data["help"]

            if help_info:
                # Описание
                desc_item = QTreeWidgetItem(["Описание:"])
                desc_item.setForeground(0, QColor(140, 140, 140))
                desc_font = desc_item.font(0)
                desc_font.setBold(True)
                desc_item.setFont(0, desc_font)
                parent.addChild(desc_item)

                for line in help_info["description"].strip().split("\n"):
                    line_item = QTreeWidgetItem([f"  {line.strip()}"])
                    line_item.setForeground(0, QColor(180, 180, 180))
                    parent.addChild(line_item)

                # Пустая строка
                parent.addChild(QTreeWidgetItem([""]))

                # Влияние
                impact_item = QTreeWidgetItem(["Влияние:"])
                impact_item.setForeground(0, QColor(140, 140, 140))
                impact_font = impact_item.font(0)
                impact_font.setBold(True)
                impact_item.setFont(0, impact_font)
                parent.addChild(impact_item)

                for line in help_info["impact"].strip().split("\n"):
                    line_item = QTreeWidgetItem([f"  {line.strip()}"])
                    line_item.setForeground(0, QColor(220, 180, 100))
                    parent.addChild(line_item)

                # Пустая строка
                parent.addChild(QTreeWidgetItem([""]))

            # Затронутые объекты
            obj_header = QTreeWidgetItem(["Объекты:"])
            obj_header.setForeground(0, QColor(140, 140, 140))
            obj_font = obj_header.font(0)
            obj_font.setBold(True)
            obj_header.setFont(0, obj_font)
            parent.addChild(obj_header)

            for issue in group_data["objects"]:
                obj_item = QTreeWidgetItem([
                    f"  {issue['object']}  —  {issue['message']}"
                ])
                obj_item.setForeground(0, color)
                parent.addChild(obj_item)

            if help_info:
                # Пустая строка
                parent.addChild(QTreeWidgetItem([""]))

                # Решение
                fix_item = QTreeWidgetItem(["Как исправить:"])
                fix_item.setForeground(0, QColor(140, 140, 140))
                fix_font = fix_item.font(0)
                fix_font.setBold(True)
                fix_item.setFont(0, fix_font)
                parent.addChild(fix_item)

                for line in help_info["fix"].strip().split("\n"):
                    line_item = QTreeWidgetItem([f"  {line.strip()}"])
                    line_item.setForeground(0, QColor(78, 201, 144))
                    parent.addChild(line_item)

            self.tree_issues.addTopLevelItem(parent)

        # Заполняем круговую диаграмму
        chart_colors = [
            QColor(220, 50, 50),     # красный
            QColor(220, 160, 30),    # жёлтый
            QColor(100, 160, 220),   # голубой
            QColor(160, 90, 220),    # фиолетовый
            QColor(50, 180, 100),    # зелёный
            QColor(220, 100, 50),    # оранжевый
            QColor(180, 60, 120),    # розовый
            QColor(80, 200, 200),    # бирюзовый
            QColor(200, 200, 60),    # лайм
        ]
        segments = []
        group_objects = {}
        for i, (group_name, group_data) in enumerate(sorted_groups):
            color = chart_colors[i % len(chart_colors)]
            segments.append((group_name, len(group_data["objects"]), color))
            group_objects[group_name] = set(
                issue["object"] for issue in group_data["objects"]
            )
        self.pie_chart.set_data(segments, group_objects)

    def _copy_report(self):
        if self.data:
            text = format_text_report(self.data)
            QApplication.clipboard().setText(text)
            self.status.showMessage("Отчёт скопирован в буфер обмена!", 3000)

    def _copy_json(self):
        if self.data:
            text = json.dumps(self.data, ensure_ascii=False, indent=2)
            QApplication.clipboard().setText(text)
            self.status.showMessage("JSON скопирован в буфер обмена!", 3000)


    def closeEvent(self, event):
        """Очистка при закрытии."""
        self.wireframe.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Blend Analyzer")
    app.setDesktopFileName("blend-analyzer")

    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    # Если передан аргумент — загрузить файл
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isfile(path) and path.endswith(".blend"):
            window._load_file(path)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
