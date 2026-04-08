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
    QMenu, QAction, QTabBar, QDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QRectF, QTimer
from PyQt5.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent, QIcon, QPainter, QPen, QBrush

from blend_analyzer import find_blender, save_blender_path, run_blender_extract, format_text_report
from gui.highlight import HighlightManager
from gui.drop_handler import DropHandlerMixin
from gui.settings import SettingsDialog, load_config, save_config
from gui.timeline import TimelineWidget


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
    "zero-area face": {
        "title": "Полигоны с нулевой площадью",
        "description": "Полигоны, площадь которых равна нулю — три или больше вершин в одной точке.",
        "impact": "• Артефакты при рендере\n• Проблемы с нормалями\n• Ломают Subdivision Surface",
        "fix": "1. Edit Mode → Select → All by Trait → Face Area\n2. Установить минимум 0.0001\n3. Удалить: X → Faces",
    },
    "duplicate vertex": {
        "title": "Дубликаты вершин",
        "description": "Несколько вершин в одной точке. Обычно появляются после экструзии или слияния объектов.",
        "impact": "• Видимые швы при Smooth Shading\n• Проблемы с weight painting\n• Увеличивают размер файла",
        "fix": "1. Edit Mode → выделить всё (A)\n2. Mesh → Merge → By Distance\n   (или M → By Distance)\n3. Порог: 0.0001",
    },
    "flipped normal": {
        "title": "Перевёрнутые нормали",
        "description": "Нормали части полигонов направлены внутрь модели, а не наружу.",
        "impact": "• Полигоны невидимы или чёрные при рендере\n• Проблемы с освещением\n• Solidify работает в неправильную сторону",
        "fix": "1. Edit Mode → выделить всё (A)\n2. Mesh → Normals → Recalculate Outside\n   (или Shift+N)",
    },
    "thin face": {
        "title": "Тонкие/вытянутые полигоны",
        "description": "Полигоны с очень большим соотношением сторон (длинные и узкие).",
        "impact": "• Некрасивое затенение\n• Проблемы с UV-развёрткой\n• Артефакты при Subdivision",
        "fix": "1. Edit Mode → найти тонкие полигоны\n2. Добавить edge loops (Ctrl+R) для выравнивания\n3. Или dissolve лишние рёбра (Ctrl+X)",
    },
    "isolated face": {
        "title": "Изолированные полигоны",
        "description": "Полигоны без соседей — не связаны с остальной геометрией.",
        "impact": "• Мусор в модели\n• Мешают при weight painting\n• Увеличивают размер файла",
        "fix": "1. Edit Mode → Select → All by Trait → Interior Faces\n   или Select Linked (Ctrl+L) и инвертировать\n2. Удалить: X → Faces",
    },
    "negative scale": {
        "title": "Отрицательный масштаб",
        "description": "Объект имеет отрицательный масштаб по одной или нескольким осям — это зеркальная трансформация.",
        "impact": "• Нормали перевёрнуты\n• Модификаторы работают неправильно\n• Физика и коллизии сломаны\n• Экспорт в Unity/Unreal будет некорректным",
        "fix": "1. Object Mode → выделить объект\n2. Ctrl+A → Apply Scale\n3. Затем Shift+N в Edit Mode для пересчёта нормалей",
    },
    "non-uniform scale": {
        "title": "Неравномерный масштаб",
        "description": "Масштаб по осям сильно отличается (например X=0.5, Y=1.0, Z=2.0).",
        "impact": "• Bevel будет неравномерным\n• Solidify даст разную толщину\n• Физика деформирована",
        "fix": "1. Object Mode → Ctrl+A → Apply Scale\n   Масштаб станет (1, 1, 1), геометрия сохранится",
    },
    "high poly": {
        "title": "Высокий полигонаж",
        "description": "Объект содержит очень много вершин (>50 000).",
        "impact": "• Тяжёлый для игровых движков\n• Медленный рендер\n• Может тормозить viewport",
        "fix": "1. Добавить Decimate модификатор\n2. Или использовать Remesh для ретопологии\n3. Для игр: ручная ретопология с quad-сеткой",
    },
    "empty material slot": {
        "title": "Пустой слот материала",
        "description": "У объекта есть пустой material slot без назначенного материала.",
        "impact": "• Часть полигонов будет без материала\n• Мусор в настройках",
        "fix": "1. Properties → Material\n2. Удалить пустой слот (кнопка —)\n   или назначить материал",
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
    elif "zero-area" in msg:
        return ISSUE_HELP["zero-area face"]
    elif "duplicate vertex" in msg:
        return ISSUE_HELP["duplicate vertex"]
    elif "flipped normal" in msg:
        return ISSUE_HELP["flipped normal"]
    elif "thin" in msg or "degenerate" in msg:
        return ISSUE_HELP["thin face"]
    elif "isolated face" in msg:
        return ISSUE_HELP["isolated face"]
    elif "negative scale" in msg:
        return ISSUE_HELP["negative scale"]
    elif "non-uniform scale" in msg:
        return ISSUE_HELP["non-uniform scale"]
    elif "high poly" in msg:
        return ISSUE_HELP["high poly"]
    elif "empty material slot" in msg:
        return ISSUE_HELP["empty material slot"]
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
    clicked_group = pyqtSignal(str)    # клик по сегменту — фиксация
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

    def mousePressEvent(self, event):
        """Клик — зафиксировать подсветку."""
        if event.button() == Qt.LeftButton and self.hovered_index >= 0:
            label = self.segments[self.hovered_index][0]
            self.clicked_group.emit(label)

    def leaveEvent(self, event):
        self.hovered_index = -1
        self.update()
        self.hover_left.emit()


class WireframeWidget(DropHandlerMixin, QWidget):
    """3D-превью модели с 3 режимами отображения и drag & drop."""

    MODE_WIREFRAME = 0
    MODE_SOLID = 1
    MODE_MATERIAL = 2
    MODE_NAMES = ["Каркас", "Solid", "Материалы"]

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.init_drop_handler()
        self.highlight = HighlightManager()

        # Кнопки зума поверх превью
        zoom_btn_style = """
            QPushButton {
                background-color: rgba(40, 40, 40, 180);
                color: #ccc;
                border: 1px solid #555;
                border-radius: 4px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(70, 70, 70, 200);
                color: white;
            }
        """
        self.btn_zoom_in = QPushButton("+", self)
        self.btn_zoom_in.setFixedSize(30, 30)
        self.btn_zoom_in.setStyleSheet(zoom_btn_style)
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_step(1.2))

        self.btn_zoom_out = QPushButton("−", self)
        self.btn_zoom_out.setFixedSize(30, 30)
        self.btn_zoom_out.setStyleSheet(zoom_btn_style)
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_step(1 / 1.2))

        self.btn_zoom_reset = QPushButton("⟲", self)
        self.btn_zoom_reset.setFixedSize(30, 30)
        self.btn_zoom_reset.setStyleSheet(zoom_btn_style)
        self.btn_zoom_reset.setToolTip("Сбросить камеру")
        self.btn_zoom_reset.clicked.connect(self._reset_camera)

        self.btn_rotate = QPushButton("▶", self)
        self.btn_rotate.setFixedSize(30, 30)
        self.btn_rotate.setStyleSheet(zoom_btn_style)
        self.btn_rotate.setToolTip("Вращение вкл/выкл")
        self.btn_rotate.clicked.connect(self._toggle_rotation)

        # Данные сцены для отображения
        self.scene_dimensions = [0, 0, 0]
        self.scene_scale = [1, 1, 1]
        self.scene_rotation = [0, 0, 0]

        # Геометрия
        self.verts = []
        self.edges = []
        self.faces = []        # [[verts_list, nx, ny, nz, mat_idx], ...]
        self.mat_colors = []   # [[r, g, b], ...] per object
        self.obj_names = []    # имя объекта для каждого face
        # self.highlight создан выше (HighlightManager)
        self.center = [0, 0, 0]
        self.scale_factor = 1.0

        # Режим отображения
        self.view_mode = self.MODE_WIREFRAME

        # Камера — спереди, перпендикулярно
        self.rot_x = 0.0
        self.rot_y = 270.0
        self.zoom = 1.8

        # Мышь
        self.last_mouse_pos = None
        self.dragging = False

        # Авто-вращение — выключено по умолчанию
        self.auto_rotate = False
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

        # Размеры сцены (все объекты вместе)
        self.scene_dimensions = [
            round(max(xs) - min(xs), 3),
            round(max(ys) - min(ys), 3),
            round(max(zs) - min(zs), 3),
        ]

        # Сохранить базовые вершины для анимации
        self._base_verts = [list(v) for v in all_verts]
        self._obj_vert_ranges = {}    # obj_name → (start, end) в массиве вершин
        self._obj_centers = {}
        self._obj_base_loc = {}

        # Пересчитываем диапазоны вершин по объектам
        vert_pos = 0
        for obj in (data.get("objects", []) if isinstance(data, dict) else []):
            if obj.get("type") != "MESH":
                continue
            if obj.get("name") in (hidden_objects or set()):
                continue
            mesh = obj.get("mesh", {})
            pverts = mesh.get("preview_verts", [])
            n = len(pverts)
            if n > 0:
                name = obj["name"]
                self._obj_vert_ranges[name] = (vert_pos, vert_pos + n)
                t = obj.get("transform", {})
                self._obj_base_loc[name] = t.get("position", [0, 0, 0])
                xs_obj = [v[0] for v in pverts]
                ys_obj = [v[1] for v in pverts]
                zs_obj = [v[2] for v in pverts]
                self._obj_centers[name] = [
                    (min(xs_obj) + max(xs_obj)) / 2,
                    (min(ys_obj) + max(ys_obj)) / 2,
                    (min(zs_obj) + max(zs_obj)) / 2,
                ]
            vert_pos += n

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
        lock_hint = " | 🔒 ПКМ: снять" if self.highlight.is_locked else ""
        painter.drawText(8, h - 8, f"ЛКМ: вращение | Колёсико: зум{lock_hint}")

        # Декартова система координат (левый нижний угол)
        self._draw_axes(painter, w, h)

        # Размеры модели (левый верхний угол)
        self._draw_info_overlay(painter)

        # Оверлей drag & drop
        self.paint_drop_overlay(painter, w, h)

        painter.end()

    def _draw_wireframe(self, painter, projected):
        """Рисовать каркас."""
        highlight_lines = []

        for i, edge in enumerate(self.edges):
            v1_idx, v2_idx = edge
            if v1_idx >= len(projected) or v2_idx >= len(projected):
                continue
            x1, y1, d1 = projected[v1_idx]
            x2, y2, d2 = projected[v2_idx]

            obj_name = self.edge_obj_names[i] if i < len(self.edge_obj_names) else ""
            hl = self.highlight.active
            if hl and obj_name in hl:
                highlight_lines.append((x1, y1, x2, y2, hl[obj_name]))

            avg_depth = (d1 + d2) / 2
            brightness = max(40, min(200, int(140 - avg_depth * 80)))
            color = QColor(brightness, brightness + 20, brightness + 50)
            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Обводка подсвеченных объектов поверх
        if highlight_lines:
            for x1, y1, x2, y2, color in highlight_lines:
                painter.setPen(QPen(color, 1.5))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _calc_lighting(self, nx, ny, nz, for_material=False):
        """Рассчитать освещение."""
        rnx, rny, rnz = self._rotate_normal(nx, ny, nz)

        if for_material:
            # Для материалов — яркий свет, оригинальные цвета хорошо видны
            key = max(0.0, rnz * 0.5 + rny * -0.4 + rnx * 0.2) * 0.6
            fill = max(0.0, rnx * -0.4 + rnz * 0.3 + rny * -0.2) * 0.35
            rim = max(0.0, rny * 0.5 + rnz * 0.2) * 0.25
            ambient = 0.75
        else:
            # Для solid — контрастный свет, хорошо видна форма
            key = max(0.0, rnz * 0.7 + rny * -0.5 + rnx * 0.25)
            fill = max(0.0, rnx * -0.5 + rnz * 0.3 + rny * -0.3) * 0.4
            rim = max(0.0, rny * 0.6 + rnz * 0.2) * 0.35
            ambient = 0.3

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
            # Освещение
            light = self._calc_lighting(nx, ny, nz, for_material=(self.view_mode == self.MODE_MATERIAL))

            if self.view_mode == self.MODE_MATERIAL and mat_idx < len(self.mat_colors):
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
            painter.setPen(QPen(face_color, 1))
            painter.setBrush(QBrush(face_color))
            painter.drawPolygon(poly)

        # Обводка подсвеченных объектов поверх всего
        hl = self.highlight.active
        if hl:
            painter.setBrush(Qt.NoBrush)
            for i, edge in enumerate(self.edges):
                obj_name = self.edge_obj_names[i] if i < len(self.edge_obj_names) else ""
                if obj_name not in hl:
                    continue
                v1_idx, v2_idx = edge
                if v1_idx >= len(projected) or v2_idx >= len(projected):
                    continue
                x1, y1, _ = projected[v1_idx]
                x2, y2, _ = projected[v2_idx]
                painter.setPen(QPen(hl[obj_name], 1.5))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def resizeEvent(self, event):
        """Позиционировать кнопки в правом верхнем углу."""
        super().resizeEvent(event)
        margin = 8
        x = self.width() - 30 - margin
        self.btn_zoom_in.move(x, margin)
        self.btn_zoom_out.move(x, margin + 34)
        self.btn_zoom_reset.move(x, margin + 68)
        self.btn_rotate.move(x, margin + 102)

    def _toggle_rotation(self):
        self.auto_rotate = not self.auto_rotate
        self.btn_rotate.setText("⏸" if self.auto_rotate else "▶")
        self.update()

    def _zoom_step(self, factor):
        self.zoom *= factor
        self.zoom = max(0.2, min(5.0, self.zoom))
        self.update()

    def _reset_camera(self):
        self.rot_x = 0.0
        self.rot_y = 270.0
        self.zoom = 1.8
        self.update()

    def _draw_axes(self, painter, w, h):
        """Нарисовать оси координат в левом нижнем углу."""
        import math

        cx, cy = w - 45, h - 45
        length = 30

        angle_y = math.radians(self.rot_y)
        angle_x = math.radians(self.rot_x)
        cos_y, sin_y = math.cos(angle_y), math.sin(angle_y)
        cos_x, sin_x = math.cos(angle_x), math.sin(angle_x)

        def project_axis(ax, ay, az):
            rx = ax * cos_y - ay * sin_y
            ry = ax * sin_y + ay * cos_y
            rz = az * cos_x - ry * sin_x
            rd = az * sin_x + ry * cos_x
            return cx + int(rx * length), cy - int(rz * length)

        axes = [
            ((1, 0, 0), QColor(220, 60, 60), "X"),   # красный
            ((0, 1, 0), QColor(100, 200, 60), "Y"),   # зелёный
            ((0, 0, 1), QColor(80, 130, 255), "Z"),    # синий
        ]

        # Фон круг
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 30, 160)))
        painter.drawEllipse(cx - 38, cy - 38, 76, 76)

        painter.setFont(QFont("sans-serif", 9, QFont.Bold))
        for (ax, ay, az), color, label in axes:
            ex, ey = project_axis(ax, ay, az)
            painter.setPen(QPen(color, 2))
            painter.drawLine(cx, cy, ex, ey)
            # Буква на конце оси
            painter.setPen(QPen(color))
            painter.drawText(ex - 4, ey + 4, label)

    def _draw_info_overlay(self, painter):
        """Показать размеры, scale, rotation в левом верхнем углу."""
        if not self.verts:
            return

        painter.setFont(QFont("monospace", 9))
        painter.setPen(QPen(QColor(150, 150, 150)))
        x, y = 10, 18

        dims = self.scene_dimensions
        scale = self.scene_scale
        rot = self.scene_rotation

        # Размер в метрах (Blender unit = 1 метр по умолчанию)
        painter.drawText(x, y, f"Размер: {dims[0]:.2f} × {dims[1]:.2f} × {dims[2]:.2f} м")
        y += 16
        if any(abs(s - 1.0) > 0.001 for s in scale):
            painter.setPen(QPen(QColor(220, 160, 30)))
            painter.drawText(x, y, f"Scale: {scale[0]:.3f}, {scale[1]:.3f}, {scale[2]:.3f}")
            y += 16
        if any(abs(r) > 0.01 for r in rot):
            painter.setPen(QPen(QColor(220, 160, 30)))
            painter.drawText(x, y, f"Rot: {rot[0]:.1f}°, {rot[1]:.1f}°, {rot[2]:.1f}°")

    def _auto_rotate_step(self):
        if self.auto_rotate and self.verts:
            self.rot_y += 0.5
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self._drag_started = event.pos()
            self.last_mouse_pos = event.pos()
            self.auto_rotate = False
        elif event.button() == Qt.RightButton:
            if self.highlight.is_locked or self.highlight.has_any:
                self.highlight.clear_all()
                self.update()
            else:
                self.cycle_mode()
        elif event.button() == Qt.MiddleButton:
            self.highlight.clear_all()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Если не двигали мышь — это клик
            if self._drag_started and self.last_mouse_pos:
                dx = abs(event.x() - self._drag_started.x())
                dy = abs(event.y() - self._drag_started.y())
                if dx < 3 and dy < 3:
                    # Попробовать выделить меш под курсором
                    if hasattr(self, '_parent_window'):
                        mesh_name = self._parent_window._find_mesh_at_click(event.x(), event.y())
                        if mesh_name:
                            from PyQt5.QtWidgets import QApplication
                            mods = QApplication.keyboardModifiers()
                            if mods & Qt.ShiftModifier:
                                if mesh_name in self._parent_window.selected_objects:
                                    self._parent_window.selected_objects.discard(mesh_name)
                                else:
                                    self._parent_window.selected_objects.add(mesh_name)
                            else:
                                self._parent_window.selected_objects = {mesh_name}

                            color = QColor(100, 200, 255)
                            sel = {n: color for n in self._parent_window.selected_objects}
                            self.highlight._selection = sel
                            self._parent_window._select_in_tree(mesh_name)
                        else:
                            # Клик в пустоту — снять выделение
                            self.highlight.clear_selection()
                            self.highlight.clear_lock()
                            self._parent_window.selected_objects = set()
                    self.update()
            self.dragging = False
            self._drag_started = None

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

    def _get_timeline(self):
        """Получить таймлайн из родительского окна."""
        if hasattr(self, '_parent_window') and hasattr(self._parent_window, 'timeline'):
            return self._parent_window.timeline
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._space_pressed = True
            # Space без модификатора — play/pause анимацию
            # (отпустим в keyRelease если не было комбо)
            return
        if event.key() == Qt.Key_G and event.modifiers() & Qt.AltModifier:
            self.auto_rotate = False
            self.btn_rotate.setText("▶")
            self._reset_camera()
            self.update()
        elif event.key() == Qt.Key_G and not event.modifiers():
            self._toggle_rotation()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if hasattr(self, '_space_pressed') and self._space_pressed:
                self._toggle_fullscreen()
                self._space_pressed = False
                self._space_used_combo = True
        elif event.key() == Qt.Key_1:
            if hasattr(self, '_space_pressed') and self._space_pressed:
                # Space+1 — play/pause анимацию
                tl = self._get_timeline()
                if tl and tl.isVisible():
                    tl.toggle_play()
                    self._space_used_combo = True
            else:
                # 1 — режим Каркас
                self.view_mode = self.MODE_WIREFRAME
                if hasattr(self, '_parent_window'):
                    self._parent_window._set_view_mode(self.MODE_WIREFRAME)
                self.update()
        elif event.key() == Qt.Key_2 and not (hasattr(self, '_space_pressed') and self._space_pressed):
            # 2 — режим Solid
            self.view_mode = self.MODE_SOLID
            if hasattr(self, '_parent_window'):
                self._parent_window._set_view_mode(self.MODE_SOLID)
            self.update()
        elif event.key() == Qt.Key_3 and not (hasattr(self, '_space_pressed') and self._space_pressed):
            # 3 — режим Материалы
            self.view_mode = self.MODE_MATERIAL
            if hasattr(self, '_parent_window'):
                self._parent_window._set_view_mode(self.MODE_MATERIAL)
            self.update()
        elif event.key() == Qt.Key_Left:
            # ← — кадр назад
            tl = self._get_timeline()
            if tl and tl.isVisible():
                tl._prev_frame()
        elif event.key() == Qt.Key_Right:
            # → — кадр вперёд
            tl = self._get_timeline()
            if tl and tl.isVisible():
                tl._next_frame()
        elif event.key() == Qt.Key_Home:
            tl = self._get_timeline()
            if tl and tl.isVisible():
                tl._go_start()
        elif event.key() == Qt.Key_End:
            tl = self._get_timeline()
            if tl and tl.isVisible():
                tl._go_end()
        elif event.key() == Qt.Key_H:
            # H — скрыть выделенные объекты
            if hasattr(self, '_parent_window'):
                self._parent_window._hide_selected_objects()
        elif event.key() == Qt.Key_Escape:
            if hasattr(self, '_is_fullscreen') and self._is_fullscreen:
                self._toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            # Если Space не был использован в комбо — это одиночный Space = play/pause
            if not getattr(self, '_space_used_combo', False):
                tl = self._get_timeline()
                if tl and tl.isVisible():
                    tl.toggle_play()
            self._space_pressed = False
            self._space_used_combo = False
        super().keyReleaseEvent(event)

    def _toggle_fullscreen(self):
        """Развернуть/свернуть превью на весь экран."""
        if hasattr(self, '_is_fullscreen') and self._is_fullscreen:
            # Вернуть обратно
            self.setWindowFlags(Qt.Widget)
            if hasattr(self, '_original_parent_layout'):
                self._original_parent_layout.insertWidget(self._original_index, self)
            self.showNormal()
            self._is_fullscreen = False
            # Показать кнопки зума
            self.btn_zoom_in.show()
            self.btn_zoom_out.show()
            self.btn_zoom_reset.show()
            self.btn_rotate.show()
        else:
            # Запомнить положение
            parent = self.parent()
            if parent and parent.layout():
                self._original_parent_layout = parent.layout()
                self._original_index = parent.layout().indexOf(self)
            # Развернуть
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.showFullScreen()
            self.setFocus()
            self._is_fullscreen = True
            # Показать кнопки зума
            self.btn_zoom_in.show()
            self.btn_zoom_out.show()
            self.btn_zoom_reset.show()
            self.btn_rotate.show()
            self.btn_zoom_in.raise_()
            self.btn_zoom_out.raise_()
            self.btn_zoom_reset.raise_()
            self.btn_rotate.raise_()

    def mouseDoubleClickEvent(self, event):
        """Двойной клик — сброс камеры."""
        self.rot_x = 0.0
        self.rot_y = 270.0
        self.zoom = 1.8
        self.update()

    def apply_animation_frame(self, frame_num, frame_data):
        """Применить кадр анимации — подставить вершины напрямую."""
        if not frame_data or not self._obj_vert_ranges:
            return

        new_verts = list(self.verts)

        for obj_name, obj_verts in frame_data.items():
            if obj_name not in self._obj_vert_ranges:
                continue
            start, end = self._obj_vert_ranges[obj_name]
            n = end - start
            # Подставляем вершины из кадра
            for i, v in enumerate(obj_verts[:n]):
                new_verts[start + i] = v

        self.verts = new_verts
        self.update()

    def cleanup(self):
        self.auto_timer.stop()
        self.verts = []
        self.edges = []
        self.faces = []
        self.obj_names = []
        self.edge_obj_names = []
        self.highlight.clear_all()


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

        self.app_config = load_config()
        self._setup_ui()
        self._apply_dark_theme()
        self._apply_config()
        self._restore_window_state()

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

        self.btn_widgets = QPushButton("Виджеты")
        self.btn_widgets.setFixedHeight(36)
        self.btn_widgets.clicked.connect(self._show_widgets_menu)
        top_bar.addWidget(self.btn_widgets)

        self.btn_tools = QPushButton("Инструменты")
        self.btn_tools.setFixedHeight(36)
        self.btn_tools.clicked.connect(self._show_tools_menu)
        top_bar.addWidget(self.btn_tools)

        self.btn_settings = QPushButton("Настройки")
        self.btn_settings.setFixedHeight(36)
        self.btn_settings.clicked.connect(self._show_settings)
        top_bar.addWidget(self.btn_settings)

        main_layout.addLayout(top_bar)

        # === Вкладки файлов ===
        self.file_tabs = QTabBar()
        self.file_tabs.setTabsClosable(True)
        self.file_tabs.setMovable(True)
        self.file_tabs.setExpanding(False)
        self.file_tabs.tabCloseRequested.connect(self._close_file_tab)
        self.file_tabs.currentChanged.connect(self._switch_file_tab)
        self.file_tabs.setVisible(False)

        # Кнопка "+" для новой вкладки
        btn_add_tab = QPushButton("+")
        btn_add_tab.setFixedSize(28, 28)
        btn_add_tab.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d; color: #888; border: 1px solid #3c3c3c;
                border-radius: 3px; font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3c3c3c; color: white; }
        """)
        btn_add_tab.clicked.connect(self._open_file)

        # file_tabs добавляется позже в preview_container

        # Хранилище данных по файлам
        self._file_sessions = {}  # tab_index → session dict
        self._current_session_id = None
        self._switching_tab = False

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
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setHeaderLabels(["", "Имя", "Тег", "Тип", "Вершины", "Полигоны"])
        self.tree.setColumnWidth(0, 28)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setColumnWidth(2, 110)
        self.tree.setColumnWidth(3, 60)
        self.tree.setColumnWidth(4, 60)
        self.tree.setColumnWidth(5, 60)
        self.tree.setItemDelegateForColumn(0, EyeDelegate(self.tree))
        self.tree.currentItemChanged.connect(self._on_object_selected)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self.hidden_objects = set()
        self._updating_tree = False
        self._rename_map = {}
        self.selected_objects = set()
        self.object_tags = {}  # mesh_name → body_part_tag  # old_name → new_name
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

        # Вкладки файлов — под кнопками режимов
        file_tabs_row = QHBoxLayout()
        file_tabs_row.setContentsMargins(0, 0, 0, 0)
        file_tabs_row.setSpacing(4)
        file_tabs_row.addWidget(self.file_tabs, 1)
        file_tabs_row.addWidget(btn_add_tab)
        preview_layout.addLayout(file_tabs_row)

        self.wireframe = WireframeWidget()
        self.wireframe._parent_window = self
        self.wireframe.file_dropped.connect(self._open_file_in_tab)
        preview_layout.addWidget(self.wireframe, 1)

        # Таймлайн анимации (скрыт по умолчанию, включается в настройках)
        self.timeline = TimelineWidget()
        self.timeline.frame_changed.connect(self._on_animation_frame)
        preview_layout.addWidget(self.timeline)

        center_splitter.addWidget(preview_container)

        # Табы — всё через систему виджетов
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close)


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
        self.pie_chart.clicked_group.connect(self._on_chart_click)
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

        # === Система виджетов ===
        self.widget_panels = {}  # name -> {panel, content, visible}
        self._init_widget_definitions()

    def _init_widget_definitions(self):
        """Определения всех доступных виджетов."""
        self.widget_defs = {
            "details": {
                "title": "Детали",
                "icon": "◆",
                "default": True,
            },
            "materials": {
                "title": "Материалы",
                "icon": "◈",
                "default": True,
            },
            "report": {
                "title": "Полный отчёт",
                "icon": "▤",
                "default": True,
            },
            "suggestions": {
                "title": "Рекомендации",
                "icon": "★",
                "default": False,
            },
            "stats": {
                "title": "Статистика",
                "icon": "▣",
                "default": False,
            },
        }

        # Открыть дефолтные виджеты
        for wid, defn in self.widget_defs.items():
            if defn.get("default"):
                self._toggle_widget(wid, True)

    def _create_widget_tab(self, widget_id):
        """Создать вкладку-виджет в табах."""
        defn = self.widget_defs[widget_id]

        content = QTextEdit()
        content.setReadOnly(True)
        content.setFont(QFont("Monospace", 10))

        self.widget_panels[widget_id] = {
            "content": content,
            "visible": False,
            "tab_title": f"{defn['icon']} {defn['title']}",
        }

        return content

    def _get_tool_blend_file(self):
        """Получить путь к .blend для инструмента. Если несколько вкладок — спросить."""
        sessions_with_data = []
        for idx, session in self._file_sessions.items():
            if session.get("data"):
                sessions_with_data.append((idx, session))

        if not sessions_with_data:
            QMessageBox.warning(self, "Ошибка", "Нет загруженных файлов")
            return None, None

        if len(sessions_with_data) == 1:
            s = sessions_with_data[0][1]
            return s["data"].get("file", ""), s.get("hidden_objects", set())

        # Несколько файлов — спросить
        from PyQt5.QtWidgets import QInputDialog
        names = []
        for idx, s in sessions_with_data:
            name = os.path.basename(s["data"].get("file", "?"))
            names.append(name)

        chosen, ok = QInputDialog.getItem(
            self, "Выберите файл",
            "Для какого файла применить инструмент?",
            names, 0, False,
        )
        if not ok:
            return None, None

        chosen_idx = names.index(chosen)
        s = sessions_with_data[chosen_idx][1]
        return s["data"].get("file", ""), s.get("hidden_objects", set())

    def _apply_config(self):
        """Применить настройки из конфига."""
        show_timeline = self.app_config.get("line_of_animation", False)
        self.timeline.setVisible(show_timeline and self.data is not None)

    def _show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.app_config = dialog.get_config()
            self._apply_config()

    def _show_tools_menu(self):
        """Показать меню инструментов."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #3c3c3c; padding: 4px;
            }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #264f78; }
            QMenu::item:disabled { color: #555; }
        """)

        has_data = any(s.get("data") for s in self._file_sessions.values())

        act_vgroups = QAction("Создать Vertex Groups по зонам", self)
        act_vgroups.setEnabled(has_data)
        act_vgroups.triggered.connect(self._create_vertex_groups)
        menu.addAction(act_vgroups)

        act_mirror = QAction("Применить Mirror модификаторы", self)
        act_mirror.setEnabled(has_data)
        act_mirror.triggered.connect(self._apply_mirror)
        menu.addAction(act_mirror)

        menu.addSeparator()

        act_bones = QAction("Создать скелет по именам/тегам мешей", self)
        act_bones.setEnabled(has_data)
        act_bones.triggered.connect(self._create_bones)
        menu.addAction(act_bones)

        act_geo_skeleton = QAction("Геом. извл. скелета (авто)", self)
        act_geo_skeleton.setEnabled(has_data)
        act_geo_skeleton.triggered.connect(self._extract_skeleton_geo)
        menu.addAction(act_geo_skeleton)

        menu.exec_(self.btn_tools.mapToGlobal(
            self.btn_tools.rect().bottomLeft()
        ))

    def _create_vertex_groups(self):
        """Создать vertex groups через Blender."""
        blend_file, hidden = self._get_tool_blend_file()
        if not blend_file or not os.path.isfile(blend_file):
            return

        base, ext = os.path.splitext(blend_file)
        output_path = f"{base}_vgroups{ext}"

        self.status.showMessage("Создание Vertex Groups...")
        self.progress.setVisible(True)

        script = Path(__file__).parent / "scripts" / "create_vgroups.py"
        ok, msg = self._run_blender_script(blend_file, script, output_path, "===VGROUPS_DONE===", hidden)

        self.progress.setVisible(False)
        if ok:
            self.status.showMessage(f"Vertex Groups созданы! Сохранено: {os.path.basename(output_path)}", 5000)
            QMessageBox.information(
                self, "Готово",
                f"Vertex Groups созданы по зонам:\n"
                f"• Zone_Top, Zone_Upper, Zone_Middle, Zone_Lower\n"
                f"• Zone_Left, Zone_Right, Zone_Center\n"
                f"• Zone_Front, Zone_Back\n\n"
                f"Сохранено в:\n{output_path}"
            )
        else:
            self.status.showMessage("Ошибка создания Vertex Groups")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать Vertex Groups:\n{msg}")

    def _run_blender_script(self, blend_file, script_path, output_path, done_marker, hidden=None, extra_args=None):
        """Запустить Blender-скрипт и вернуть (success, message)."""
        import subprocess
        ignored = hidden if hidden is not None else self.hidden_objects
        cmd = [
            self.blender_path, "--background", blend_file,
            "--python", str(script_path), "--", output_path,
        ]
        if ignored:
            cmd.extend(["--ignore", ",".join(ignored)])
        if extra_args:
            cmd.extend(extra_args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=120,
            )
            if done_marker in result.stdout:
                return True, result.stdout
            else:
                stderr = result.stderr[:500] if result.stderr else "Неизвестная ошибка"
                return False, stderr
        except subprocess.TimeoutExpired:
            return False, "Blender не ответил за 120 секунд"

    def _apply_mirror(self):
        """Применить все Mirror модификаторы."""
        blend_file, hidden = self._get_tool_blend_file()
        if not blend_file or not os.path.isfile(blend_file):
            return

        base, ext = os.path.splitext(blend_file)
        output_path = f"{base}_mirrored{ext}"

        self.status.showMessage("Применение Mirror модификаторов...")
        self.progress.setVisible(True)

        script = Path(__file__).parent / "scripts" / "apply_mirror.py"
        ok, msg = self._run_blender_script(blend_file, script, output_path, "===MIRROR_DONE===", hidden)

        self.progress.setVisible(False)
        if ok:
            self.status.showMessage(f"Mirror применён! Сохранено: {os.path.basename(output_path)}", 5000)
            # Предложить открыть новый файл
            reply = QMessageBox.question(
                self, "Mirror применён",
                f"Mirror модификаторы применены.\n"
                f"Сохранено в: {output_path}\n\n"
                f"Открыть этот файл в новом окне?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._open_file_in_tab(output_path)
        else:
            self.status.showMessage("Ошибка применения Mirror")
            QMessageBox.critical(self, "Ошибка", f"Не удалось применить Mirror:\n{msg}")


    def _extract_skeleton_geo(self):
        """Геометрическое извлечение скелета — полностью автоматическое."""
        blend_file, hidden = self._get_tool_blend_file()
        if not blend_file or not os.path.isfile(blend_file):
            return

        reply = QMessageBox.warning(
            self, "Геометрическое извлечение скелета",
            "Автоматическое извлечение скелета из геометрии модели.\n\n"
            "Алгоритм:\n"
            "1. Нарезает модель горизонтальными срезами\n"
            "2. Находит ветвления (где геометрия разделяется)\n"
            "3. Прокладывает кости по центру каждой ветки\n"
            "4. Привязывает через Automatic Weights\n\n"
            "⚠ Все модификаторы и трансформации будут применены.\n"
            "⚠ Оригинальный файл НЕ будет изменён!\n\n"
            "Лучше всего работает с гуманоидными моделями.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        base, ext = os.path.splitext(blend_file)
        output_path = f"{base}_skeleton{ext}"

        self.status.showMessage("Геометрическое извлечение скелета...")
        self.progress.setVisible(True)

        script = Path(__file__).parent / "scripts" / "extract_skeleton.py"
        ok, msg = self._run_blender_script(blend_file, script, output_path, "===SKELETON_DONE===", hidden)

        self.progress.setVisible(False)
        if ok:
            self.status.showMessage(f"Скелет извлечён! Сохранено: {os.path.basename(output_path)}", 5000)
            reply = QMessageBox.information(
                self, "Готово",
                f"Скелет извлечён из геометрии!\n\n{msg[:400] if msg else ''}\n\n"
                f"Сохранено в:\n{output_path}\n\n"
                f"Открыть в новой вкладке?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._open_file_in_tab(output_path)
        elif "SKELETON_ERROR" in (msg or ""):
            error_detail = msg.split("SKELETON_ERROR===")[-1].strip() if "SKELETON_ERROR" in msg else msg
            self.status.showMessage("Ошибка извлечения скелета")
            QMessageBox.critical(self, "Ошибка", f"Не удалось извлечь скелет:\n{error_detail}")
        else:
            self.status.showMessage("Ошибка извлечения скелета")
            QMessageBox.critical(self, "Ошибка", f"Не удалось извлечь скелет:\n{msg[:500] if msg else 'Неизвестная ошибка'}")

    def _create_bones(self):
        """Создать кости по тегам или именам мешей."""
        blend_file, hidden = self._get_tool_blend_file()
        if not blend_file or not os.path.isfile(blend_file):
            return

        # Предупреждение
        reply = QMessageBox.warning(
            self, "Создание скелета",
            "Для корректной расстановки костей будут выполнены:\n\n"
            "1. Применены ВСЕ модификаторы (Mirror, SubSurf и др.)\n"
            "2. Применены ВСЕ трансформации (Scale, Rotation)\n"
            "3. Создан скелет по тегам/именам мешей\n"
            "4. Привязка через Automatic Weights\n\n"
            "⚠ Оригинальный файл НЕ будет изменён!\n"
            "Результат сохранится как НОВЫЙ файл.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Передать теги если есть
        extra = ["--apply-all"]
        if self.object_tags:
            tag_str = ",".join(f"{k}={v}" for k, v in self.object_tags.items() if v)
            if tag_str:
                extra.extend(["--tags", tag_str])

        base, ext = os.path.splitext(blend_file)
        output_path = f"{base}_rigged{ext}"

        self.status.showMessage("Применение модификаторов и создание костей...")
        self.progress.setVisible(True)

        script = Path(__file__).parent / "scripts" / "create_bones.py"
        ok, msg = self._run_blender_script(blend_file, script, output_path, "===BONES_DONE===", hidden, extra)

        self.progress.setVisible(False)
        if ok:
            self.status.showMessage(f"Кости созданы! Сохранено: {os.path.basename(output_path)}", 5000)
            QMessageBox.information(
                self, "Готово",
                f"Скелет создан по именам мешей!\n\n"
                f"Кости расставлены с правильной иерархией\n"
                f"и привязаны через Automatic Weights.\n\n"
                f"{msg[:300] if msg else ''}\n\n"
                f"Сохранено в:\n{output_path}"
            )
        elif "BONES_ERROR" in msg:
            self.status.showMessage("Не найдены части тела")
            QMessageBox.warning(
                self, "Не найдены части тела",
                f"Не удалось определить части тела по именам мешей.\n\n"
                f"Назовите меши в Blender, используя ключевые слова:\n"
                f"  head, neck, chest/torso, shoulder.L/R,\n"
                f"  upper_arm.L/R, forearm.L/R, hand.L/R,\n"
                f"  thigh.L/R, shin.L/R, foot.L/R, hips\n\n"
                f"Пример: 'Head', 'UpperArm.L', 'Thigh_R'"
            )
        else:
            self.status.showMessage("Ошибка создания костей")
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать кости:\n{msg}")

    def _create_vgroups_and_bones(self):
        """Создать vertex groups и сразу кости."""
        if not self.data or not self.blender_path:
            return

        blend_file = self.data.get("file", "")
        if not blend_file or not os.path.isfile(blend_file):
            QMessageBox.warning(self, "Ошибка", "Файл модели не найден")
            return

        base, ext = os.path.splitext(blend_file)
        temp_path = f"{base}_vgroups{ext}"
        output_path = f"{base}_rigged{ext}"

        self.status.showMessage("Шаг 1/2: Создание Vertex Groups...")
        self.progress.setVisible(True)

        # Шаг 1: Vertex Groups
        vg_script = Path(__file__).parent / "scripts" / "create_vgroups.py"
        ok, msg = self._run_blender_script(blend_file, vg_script, temp_path, "===VGROUPS_DONE===")

        if not ok:
            self.progress.setVisible(False)
            self.status.showMessage("Ошибка создания Vertex Groups")
            QMessageBox.critical(self, "Ошибка", f"Шаг 1 не удался:\n{msg}")
            return

        # Шаг 2: Кости по созданным группам
        self.status.showMessage("Шаг 2/2: Создание костей...")
        bones_script = Path(__file__).parent / "scripts" / "create_bones.py"
        ok, msg = self._run_blender_script(temp_path, bones_script, output_path, "===BONES_DONE===")

        self.progress.setVisible(False)

        # Удалить промежуточный файл
        if os.path.isfile(temp_path) and temp_path != output_path:
            os.remove(temp_path)

        if ok:
            self.status.showMessage(f"Готово! Сохранено: {os.path.basename(output_path)}", 5000)
            QMessageBox.information(
                self, "Готово",
                f"Vertex Groups + Кости созданы!\n\n"
                f"1. Vertex Groups по зонам (9 зон)\n"
                f"2. Кость на каждую зону\n"
                f"3. Арматура привязана к мешу\n\n"
                f"Сохранено в:\n{output_path}"
            )
        else:
            self.status.showMessage("Ошибка создания костей")
            QMessageBox.critical(self, "Ошибка", f"Шаг 2 не удался:\n{msg}")

    def _show_widgets_menu(self):
        """Показать меню виджетов."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                padding: 4px;
            }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #264f78; }
            QMenu::indicator { width: 16px; height: 16px; }
            QMenu::indicator:checked { background-color: #4a9eff; border-radius: 3px; }
            QMenu::indicator:unchecked { background-color: #3c3c3c; border-radius: 3px; }
        """)

        for wid, defn in self.widget_defs.items():
            is_visible = wid in self.widget_panels and self.widget_panels[wid]["visible"]
            action = QAction(f"{defn['icon']}  {defn['title']}", self)
            action.setCheckable(True)
            action.setChecked(is_visible)
            action.triggered.connect(lambda checked, w=wid: self._toggle_widget(w, checked))
            menu.addAction(action)

        menu.exec_(self.btn_widgets.mapToGlobal(
            self.btn_widgets.rect().bottomLeft()
        ))

    def _toggle_widget(self, widget_id, show):
        """Показать/скрыть виджет как вкладку."""
        if widget_id not in self.widget_panels:
            self._create_widget_tab(widget_id)

        wp = self.widget_panels[widget_id]

        if show:
            # Добавить вкладку если её нет
            tab_index = self._find_widget_tab(widget_id)
            if tab_index == -1:
                self.tabs.addTab(wp["content"], wp["tab_title"])
            wp["visible"] = True
            # Переключиться на неё
            idx = self._find_widget_tab(widget_id)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
            if self.data:
                self._fill_widget(widget_id)
        else:
            # Убрать вкладку
            tab_index = self._find_widget_tab(widget_id)
            if tab_index >= 0:
                self.tabs.removeTab(tab_index)
            wp["visible"] = False

    def _on_tab_close(self, index):
        """Закрытие вкладки через крестик."""
        widget = self.tabs.widget(index)
        # Найти какой виджет это
        for wid, wp in self.widget_panels.items():
            if wp["content"] == widget:
                wp["visible"] = False
                self.tabs.removeTab(index)
                return

    def _find_widget_tab(self, widget_id):
        """Найти индекс вкладки виджета."""
        if widget_id not in self.widget_panels:
            return -1
        content = self.widget_panels[widget_id]["content"]
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) == content:
                return i
        return -1

    def _fill_widget(self, widget_id):
        """Заполнить виджет данными."""
        if widget_id not in self.widget_panels or not self.data:
            return
        content = self.widget_panels[widget_id]["content"]

        if widget_id == "suggestions":
            self._fill_suggestions_widget(content)
        elif widget_id == "stats":
            self._fill_stats_widget(content)
        elif widget_id == "report":
            content.setPlainText(format_text_report(self.data))

    def _fill_suggestions_widget(self, content):
        """Заполнить виджет рекомендаций."""
        suggestions = self.data.get("suggestions", [])
        if not suggestions:
            content.setPlainText("Рекомендаций нет — модель выглядит хорошо!")
            return

        priority_icon = {"high": "★★★", "medium": "★★", "low": "★"}
        priority_order = {"high": 0, "medium": 1, "low": 2}

        from collections import OrderedDict
        by_mod = OrderedDict()
        for s in sorted(suggestions, key=lambda s: priority_order.get(s["priority"], 3)):
            mod = s["modifier"]
            if mod not in by_mod:
                by_mod[mod] = []
            by_mod[mod].append(s)

        lines = []
        for mod_name, items in by_mod.items():
            icon = priority_icon.get(items[0]["priority"], "")
            obj_names = [s["object"] for s in items]
            lines.append(f"{icon}  {mod_name}")
            lines.append(f"   Объекты: {', '.join(obj_names)}")
            lines.append(f"   {items[0]['reason']}")
            lines.append("")

        high = sum(1 for s in suggestions if s["priority"] == "high")
        med = sum(1 for s in suggestions if s["priority"] == "medium")
        low = sum(1 for s in suggestions if s["priority"] == "low")
        lines.append(f"Итого: ★★★ {high}  |  ★★ {med}  |  ★ {low}")

        content.setPlainText("\n".join(lines))

    def _fill_stats_widget(self, content):
        """Заполнить виджет статистики."""
        objects = self.data.get("objects", [])
        meshes = [o for o in objects if o["type"] == "MESH"]
        total_verts = sum(o["mesh"]["vertices"] for o in meshes)
        total_faces = sum(o["mesh"]["faces"] for o in meshes)
        total_tris = sum(o["mesh"]["tris"] for o in meshes)
        total_quads = sum(o["mesh"]["quads"] for o in meshes)
        total_ngons = sum(o["mesh"]["ngons"] for o in meshes)
        issues = len(self.data.get("issues", []))

        lines = [
            f"Объектов:  {len(objects)}  ({len(meshes)} мешей)",
            f"Вершин:   {total_verts:,}",
            f"Полигонов: {total_faces:,}",
            f"  Quads:   {total_quads:,}  ({total_quads / total_faces * 100:.0f}%)" if total_faces else "",
            f"  Tris:    {total_tris:,}  ({total_tris / total_faces * 100:.0f}%)" if total_faces and total_tris else "",
            f"  N-gons:  {total_ngons:,}  ({total_ngons / total_faces * 100:.0f}%)" if total_faces and total_ngons else "",
            f"Проблем:   {issues}",
        ]
        content.setPlainText("\n".join(l for l in lines if l))

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
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #888;
                padding: 6px 14px;
                border: 1px solid #3c3c3c;
                border-bottom: none;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border-bottom: 2px solid #4a9eff;
            }
            QTabBar::tab:hover {
                color: #ccc;
            }
            QTabBar::close-button {
                image: none;
                subcontrol-position: right;
                margin: 2px;
            }
            QTabBar::close-button:hover {
                background-color: #c42b1c;
                border-radius: 3px;
            }
        """)

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть .blend файл", "",
            "Blender Files (*.blend);;All Files (*)"
        )
        if path:
            self._open_file_in_tab(path)

    def _open_file_in_tab(self, path):
        """Открыть файл в новой вкладке."""
        self._save_current_session()

        # Имя вкладки — если дубликат, добавляем номер
        base_name = os.path.basename(path)
        existing_names = [self.file_tabs.tabText(i) for i in range(self.file_tabs.count())]
        tab_name = base_name
        counter = 2
        while tab_name in existing_names:
            tab_name = f"{base_name} ({counter})"
            counter += 1

        tab_idx = self.file_tabs.addTab(tab_name)

        self._file_sessions[tab_idx] = {
            "path": path,
            "data": None,
            "hidden_objects": set(),
            "selected_objects": set(),
            "view_mode": 0,
        }

        self._switching_tab = True
        self.file_tabs.setCurrentIndex(tab_idx)
        self._switching_tab = False
        self.file_tabs.setVisible(True)

        self._load_file(path)

    def _save_current_session(self):
        """Сохранить состояние текущей вкладки."""
        idx = self.file_tabs.currentIndex()
        if idx < 0 or idx not in self._file_sessions:
            return
        session = self._file_sessions[idx]
        session["data"] = self.data
        session["hidden_objects"] = set(self.hidden_objects)
        session["selected_objects"] = set(self.selected_objects)
        session["view_mode"] = self.wireframe.view_mode
        session["tags"] = dict(self.object_tags)

    def _switch_file_tab(self, idx):
        """Переключиться на другую вкладку файла."""
        if self._switching_tab or idx < 0 or idx not in self._file_sessions:
            return

        self._switching_tab = True

        try:
            # Сохранить предыдущую
            prev_idx = getattr(self, '_prev_tab_idx', -1)
            if prev_idx >= 0 and prev_idx != idx and prev_idx in self._file_sessions:
                self._file_sessions[prev_idx]["data"] = self.data
                self._file_sessions[prev_idx]["hidden_objects"] = set(self.hidden_objects)
                self._file_sessions[prev_idx]["selected_objects"] = set(self.selected_objects)
                self._file_sessions[prev_idx]["view_mode"] = self.wireframe.view_mode
                self._file_sessions[prev_idx]["tags"] = dict(self.object_tags)

            self._prev_tab_idx = idx

            # Восстановить сессию
            session = self._file_sessions[idx]
            data = session.get("data")

            if data:
                self.data = data
                self.hidden_objects = session.get("hidden_objects", set())
                self.selected_objects = session.get("selected_objects", set())

                # Восстановить режим отображения
                view_mode = session.get("view_mode", 0)
                self.wireframe.view_mode = view_mode
                self._update_mode_buttons(view_mode)
                self.object_tags = session.get("tags", {})

                blend_name = os.path.basename(data.get("file", "?"))
                self.lbl_file.setText(f"{blend_name} — Blender {data.get('blender_version', '?')}")
                self.lbl_file.setStyleSheet("color: #4ec990; font-size: 13px;")

                self.drop_zone.setVisible(False)
                self.content_splitter.setVisible(True)

                try:
                    self._populate_tree(data)
                    self._populate_issues(data)
                    self.wireframe.load_mesh_data(data, self.hidden_objects)

                    for wid, wp in self.widget_panels.items():
                        if wp["visible"]:
                            self._fill_widget(wid)

                    obj_count = len(data.get("objects", []))
                    issue_count = len(data.get("issues", []))
                    self.lbl_objects.setText(f"Объекты ({obj_count})")
                    self.lbl_issues.setText(f"Проблемы ({issue_count})")
                    self.status.showMessage(f"Загружено: {obj_count} объектов, {issue_count} проблем")
                except RuntimeError:
                    pass  # Виджет был удалён во время переключения
            else:
                # Данные ещё не загружены
                self.lbl_file.setText(f"Загрузка: {os.path.basename(session.get('path', '?'))}...")
                self.lbl_file.setStyleSheet("color: #4a9eff; font-size: 13px;")
        finally:
            self._switching_tab = False

    def _close_file_tab(self, idx):
        """Закрыть вкладку файла."""
        self._switching_tab = True

        # Удалить сессию
        if idx in self._file_sessions:
            del self._file_sessions[idx]

        self.file_tabs.removeTab(idx)

        # Перенумеровать сессии (индексы сдвигаются после удаления)
        old_sessions = dict(self._file_sessions)
        self._file_sessions = {}
        new_idx = 0
        for old_idx in sorted(old_sessions.keys()):
            self._file_sessions[new_idx] = old_sessions[old_idx]
            new_idx += 1

        self._switching_tab = False

        if self.file_tabs.count() == 0:
            self.file_tabs.setVisible(False)
            self.data = None
            self.content_splitter.setVisible(False)
            self.drop_zone.setVisible(True)
            self.lbl_file.setText("Файл не загружен")
            self.lbl_file.setStyleSheet("color: #888; font-size: 13px;")
            self.wireframe.cleanup()
            self.tree.clear()
            self.tree_issues.clear()
        else:
            # Переключиться на оставшуюся вкладку
            new_current = self.file_tabs.currentIndex()
            if new_current >= 0:
                self._switch_file_tab(new_current)

    def _load_file(self, path):
        if not self.blender_path:
            blender, _ = QFileDialog.getOpenFileName(
                self, "Укажите путь к Blender", "",
                "Blender (blender*);;All Files (*)"
            )
            if not blender:
                return
            self.blender_path = blender
            save_blender_path(blender)

        # Создать вкладку если загрузка через drag&drop или первый запуск
        current_idx = self.file_tabs.currentIndex()
        if current_idx < 0 or current_idx not in self._file_sessions:
            name = os.path.basename(path)
            tab_idx = self.file_tabs.addTab(name)
            self._file_sessions[tab_idx] = {
                "path": path,
                "data": None,
                "hidden_objects": set(),
                "selected_objects": set(),
                "view_mode": 0,
            }
            self._switching_tab = True
            self.file_tabs.setCurrentIndex(tab_idx)
            self._switching_tab = False
            self.file_tabs.setVisible(True)

        self.current_blend_path = path
        self.lbl_file.setText(f"Загрузка: {os.path.basename(path)}...")
        self.lbl_file.setStyleSheet("color: #4a9eff; font-size: 13px;")
        self.btn_open.setEnabled(False)
        self.progress.setVisible(True)
        self.status.showMessage("Извлечение данных через Blender...")

        load_tab_idx = self.file_tabs.currentIndex()

        # Остановить предыдущий воркер если есть
        if hasattr(self, '_workers'):
            old_worker = self._workers.get(load_tab_idx)
            if old_worker and old_worker.isRunning():
                try:
                    old_worker.finished.disconnect()
                    old_worker.error.disconnect()
                except Exception:
                    pass
        else:
            self._workers = {}

        worker = BlenderWorker(self.blender_path, path)
        worker.finished.connect(lambda data, idx=load_tab_idx: self._on_data_loaded(data, idx))
        worker.error.connect(self._on_error)
        self._workers[load_tab_idx] = worker
        worker.start()


    def _on_data_loaded(self, data, tab_idx=None):
        try:
            # Сохранить в сессию конкретной вкладки
            if tab_idx is not None and tab_idx in self._file_sessions:
                self._file_sessions[tab_idx]["data"] = data
            elif tab_idx is not None:
                # Вкладка была закрыта пока грузилось — игнорируем
                self.progress.setVisible(False)
                self.btn_open.setEnabled(True)
                return

            # Если эта вкладка сейчас активна — обновляем UI
            current_idx = self.file_tabs.currentIndex()
            if tab_idx is not None and tab_idx != current_idx:
                self.progress.setVisible(False)
                self.btn_open.setEnabled(True)
                return

            self.data = data
        except RuntimeError:
            return
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
        # Обновить все открытые виджеты
        for wid, wp in self.widget_panels.items():
            if wp["visible"]:
                self._fill_widget(wid)

        self.lbl_objects.setText(f"Объекты ({obj_count})")
        self.lbl_issues.setText(f"Проблемы ({issue_count})")

        # Загрузить анимации в таймлайн
        if self.app_config.get("line_of_animation", False):
            self._load_animation_data(data)

    def _load_animation_data(self, data):
        """Загрузить анимацию из Blender."""
        blend_file = data.get("file", "")
        if not blend_file or not self.blender_path:
            self.timeline.setVisible(False)
            return

        import subprocess
        script = Path(__file__).parent / "scripts" / "extract_animation.py"
        cmd = [self.blender_path, "--background", blend_file,
               "--python", str(script), "--"]
        if self.hidden_objects:
            cmd.extend(["--ignore", ",".join(self.hidden_objects)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            stdout = result.stdout

            start = stdout.find("===ANIM_JSON_START===")
            end = stdout.find("===ANIM_JSON_END===")

            if start >= 0 and end >= 0:
                import json
                json_str = stdout[start + len("===ANIM_JSON_START==="):end].strip()
                anim_data = json.loads(json_str)

                actions = anim_data.get("actions", [])
                if actions and any(len(a.get("frames", {})) > 0 for a in actions):
                    self.timeline.set_anim_data(anim_data)
                    self.timeline.setVisible(True)
                    self.status.showMessage(
                        self.status.currentMessage() + f" | {len(actions)} анимация(й)", 5000
                    )
                    return
        except Exception:
            pass

        self.timeline.setVisible(False)

    def _on_animation_frame(self, frame, frame_data):
        """Применить кадр анимации к 3D-превью."""
        self.wireframe.apply_animation_frame(frame, frame_data)

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

            tag = self.object_tags.get(obj["name"], "")

            item = QTreeWidgetItem([
                "",
                f"{icon} {obj['name']}",
                tag,
                obj["type"],
                verts,
                faces,
            ])
            item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
            if tag:
                item.setForeground(2, QColor(78, 201, 144))
            else:
                item.setForeground(2, QColor(80, 80, 80))
            if not visible:
                for col in range(1, 6):
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



    def _select_in_tree(self, obj_name):
        """Выделить объект в дереве по имени."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            name = item.text(1)
            for ic in OBJECT_TYPE_ICONS.values():
                name = name.replace(f"{ic} ", "")
            if name == obj_name:
                self.tree.setCurrentItem(item)
                return
            # Проверить children
            for ci in range(item.childCount()):
                child = item.child(ci)
                cname = child.text(1)
                for ic in OBJECT_TYPE_ICONS.values():
                    cname = cname.replace(f"{ic} ", "")
                if cname == obj_name:
                    self.tree.setCurrentItem(child)
                    return

    def _hide_selected_objects(self):
        """Скрыть все выделенные объекты (H)."""
        if not self.selected_objects:
            return

        for name in list(self.selected_objects):
            self.hidden_objects.add(name)

        self.selected_objects = set()
        self.wireframe.highlight.clear_selection()

        # Обновить дерево и превью
        if self.data:
            self._populate_tree(self.data)
            self._rebuild_preview()

        self.status.showMessage(f"Скрыто объектов: {len(self.hidden_objects)}", 3000)

    def _find_mesh_at_click(self, click_x, click_y):
        """Найти какой меш под курсором в 3D-превью."""
        if not self.wireframe.verts or not self.wireframe.obj_names:
            return None

        projected = [self.wireframe._project(v[0], v[1], v[2]) for v in self.wireframe.verts]

        best_name = None
        best_dist = float('inf')

        # Проверяем каждый face — попадает ли клик внутрь
        for fi, face in enumerate(self.wireframe.faces):
            vert_indices = face[0]
            obj_name = self.wireframe.obj_names[fi] if fi < len(self.wireframe.obj_names) else ""
            if not obj_name:
                continue

            # Проверяем bounding box полигона для быстрого отсечения
            points = []
            depth_sum = 0
            valid = True
            for vi in vert_indices:
                if vi >= len(projected):
                    valid = False
                    break
                sx, sy, d = projected[vi]
                points.append((sx, sy))
                depth_sum += d

            if not valid or len(points) < 3:
                continue

            # Проверяем попадание точки в полигон (ray casting)
            if self._point_in_polygon(click_x, click_y, points):
                avg_depth = depth_sum / len(points)
                if avg_depth < best_dist:
                    best_dist = avg_depth
                    best_name = obj_name

        return best_name

    def _point_in_polygon(self, px, py, polygon):
        """Проверить попадание точки в полигон (ray casting)."""
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _on_object_selected(self, current, previous):
        if not current or not self.data:
            return

        name = current.text(1)
        for ic in OBJECT_TYPE_ICONS.values():
            name = name.replace(f"{ic} ", "")

        # Shift = мульти-выделение
        from PyQt5.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.ShiftModifier:
            if name in self.selected_objects:
                self.selected_objects.discard(name)
            else:
                self.selected_objects.add(name)
        else:
            self.selected_objects = {name}

        # Подсветить все выбранные объекты
        color = QColor(100, 200, 255)
        sel_dict = {n: color for n in self.selected_objects}
        self.wireframe.highlight.clear_selection()
        for n, c in sel_dict.items():
            self.wireframe.highlight._selection[n] = c

        # Обновить scale/rotation для последнего выбранного
        for o in self.data.get("objects", []):
            if o["name"] == name:
                t = o.get("transform", {})
                self.wireframe.scene_scale = t.get("scale", [1, 1, 1])
                self.wireframe.scene_rotation = t.get("rotation_deg", [0, 0, 0])
                if o.get("type") == "MESH":
                    dims = o.get("mesh", {}).get("dimensions", [0, 0, 0])
                    self.wireframe.scene_dimensions = dims
                break

        self.wireframe.update()

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

        if "details" in self.widget_panels:
            self.widget_panels["details"]["content"].setPlainText("\n".join(lines))

    def _set_materials_text(self, text):
        if "materials" in self.widget_panels:
            self.widget_panels["materials"]["content"].setPlainText(text)

    def _show_materials(self, obj):
        mats = obj.get("materials", [])
        if not mats:
            self._set_materials_text("Нет материалов")
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

        self._set_materials_text("\n".join(lines))

    def _on_tree_double_click(self, item, column):
        """Двойной клик: колонка 1 = переименовать, колонка 2 = назначить тег."""
        if column == 2:
            self._assign_tag(item)
            return
        if column != 1:
            return

        from PyQt5.QtWidgets import QDialog, QCompleter, QLineEdit, QDialogButtonBox, QListWidget
        from PyQt5.QtCore import QStringListModel

        # Все поддерживаемые имена для скелета
        BODY_PART_NAMES = [
            # Голова / шея
            "Head", "Neck", "Jaw",
            # Торс
            "Chest", "Torso", "Spine", "Spine.Upper", "Spine.Lower",
            "Hips", "Pelvis", "Abdomen",
            # Плечи / руки (основные)
            "Shoulder.L", "Shoulder.R",
            "UpperArm.L", "UpperArm.R",
            "Forearm.L", "Forearm.R",
            "Hand.L", "Hand.R",
            # Суставы рук
            "Elbow.L", "Elbow.R",
            "Wrist.L", "Wrist.R",
            # Пальцы рук
            "Thumb.L", "Thumb.R",
            "Index.L", "Index.R",
            "Middle.L", "Middle.R",
            "Ring.L", "Ring.R",
            "Pinky.L", "Pinky.R",
            # Вторая пара рук
            "Shoulder2.L", "Shoulder2.R",
            "UpperArm2.L", "UpperArm2.R",
            "Forearm2.L", "Forearm2.R",
            "Hand2.L", "Hand2.R",
            # Ноги
            "Thigh.L", "Thigh.R",
            "Shin.L", "Shin.R",
            "Calf.L", "Calf.R",
            "Foot.L", "Foot.R",
            # Суставы ног
            "Knee.L", "Knee.R",
            "Ankle.L", "Ankle.R",
            # Стопы
            "Toe.L", "Toe.R",
            "Heel.L", "Heel.R",
            # Хвост / крылья / доп
            "Tail", "Tail.Upper", "Tail.Lower",
            "Wing.L", "Wing.R",
            # Броня / одежда / аксессуары
            "Cape", "Belt", "Helmet", "Visor",
            "Pauldron.L", "Pauldron.R",
            "Gauntlet.L", "Gauntlet.R",
            "Boot.L", "Boot.R",
            "Skirt", "Tabard",
        ]

        # Получить текущее имя
        text = item.text(1)
        old_name = text
        for ic in OBJECT_TYPE_ICONS.values():
            old_name = old_name.replace(f"{ic} ", "")

        # Кастомный диалог
        dialog = QDialog(self)
        dialog.setWindowTitle("Переименовать объект")
        dialog.setMinimumWidth(350)
        dlg_layout = QVBoxLayout(dialog)

        lbl = QLabel(f"Текущее имя: {old_name}")
        lbl.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 4px;")
        dlg_layout.addWidget(lbl)

        edit = QLineEdit(old_name)
        edit.selectAll()
        edit.setStyleSheet("font-size: 14px; padding: 6px; background: #252526; color: #d4d4d4; border: 1px solid #3c3c3c;")
        dlg_layout.addWidget(edit)

        # Автодополнение
        completer = QCompleter(BODY_PART_NAMES, dialog)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setStyleSheet("""
            QListView {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #4a9eff; font-size: 13px;
            }
            QListView::item:selected { background-color: #264f78; }
        """)
        edit.setCompleter(completer)

        # Подсказка
        hint_label = QLabel("Части тела для скелета:")
        hint_label.setStyleSheet("color: #666; font-size: 10px; margin-top: 8px;")
        dlg_layout.addWidget(hint_label)

        hint_list = QLabel(
            "Head · Neck · Jaw · Chest · Spine · Hips · Pelvis\n"
            "Shoulder.L/R · UpperArm.L/R · Elbow.L/R · Forearm.L/R · Wrist.L/R · Hand.L/R\n"
            "Shoulder2.L/R · UpperArm2.L/R · Forearm2.L/R · Hand2.L/R  (2-я пара)\n"
            "Thigh.L/R · Knee.L/R · Shin.L/R · Ankle.L/R · Foot.L/R · Toe.L/R\n"
            "Пальцы: Thumb/Index/Middle/Ring/Pinky.L/R\n"
            "Доп: Tail · Wing.L/R · Cape · Belt · Helmet · Boot.L/R"
        )
        hint_list.setStyleSheet("color: #4a9eff; font-size: 10px; padding: 4px; background: #1a1a2e; border-radius: 4px;")
        hint_list.setWordWrap(True)
        dlg_layout.addWidget(hint_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #d4d4d4; }
            QPushButton { background-color: #0e639c; color: white; border: none; border-radius: 4px; padding: 6px 16px; }
            QPushButton:hover { background-color: #1177bb; }
        """)

        if dialog.exec_() != QDialog.Accepted:
            return

        new_name = edit.text().strip()
        if not new_name or new_name == old_name:
            return

        # Переименовать через Blender
        if not self.data or not self.blender_path:
            return

        blend_file = self.data.get("file", "")
        if not blend_file or not os.path.isfile(blend_file):
            return

        import subprocess
        rename_cmd = (
            f"import bpy\n"
            f"obj = bpy.data.objects.get('{old_name}')\n"
            f"if obj:\n"
            f"    obj.name = '{new_name}'\n"
            f"    if obj.data:\n"
            f"        obj.data.name = '{new_name}'\n"
            f"bpy.ops.wm.save_mainfile()\n"
        )

        result = subprocess.run(
            [self.blender_path, "--background", blend_file,
             "--python-expr", rename_cmd],
            capture_output=True, text=True, timeout=30,
        )

        # Обновить UI
        obj_type = item.text(2)
        icon = ""
        for t, ic in OBJECT_TYPE_ICONS.items():
            if t == obj_type:
                icon = ic
                break

        self._updating_tree = True
        item.setText(1, f"{icon} {new_name}" if icon else new_name)
        self._updating_tree = False

        # Обновить данные
        if self.data:
            for obj in self.data.get("objects", []):
                if obj["name"] == old_name:
                    obj["name"] = new_name
                    break

        # Обновить hidden_objects
        if old_name in self.hidden_objects:
            self.hidden_objects.discard(old_name)
            self.hidden_objects.add(new_name)

        self._rename_map[old_name] = new_name
        self.status.showMessage(f"Переименовано: {old_name} → {new_name}", 3000)

    def _assign_tag(self, item):
        """Назначить тег — выпадающее меню с категориями, просто кликай."""
        obj_name = item.text(1)
        for ic in OBJECT_TYPE_ICONS.values():
            obj_name = obj_name.replace(f"{ic} ", "")

        TAG_GROUPS = {
            "Голова": ["Head", "Neck", "Jaw"],
            "Торс": ["Chest", "Spine", "Hips"],
            "Рука .L": ["Shoulder.L", "UpperArm.L", "Forearm.L", "Hand.L", "Elbow.L", "Wrist.L"],
            "Рука .R": ["Shoulder.R", "UpperArm.R", "Forearm.R", "Hand.R", "Elbow.R", "Wrist.R"],
            "Рука2 .L": ["Shoulder2.L", "UpperArm2.L", "Forearm2.L", "Hand2.L"],
            "Рука2 .R": ["Shoulder2.R", "UpperArm2.R", "Forearm2.R", "Hand2.R"],
            "Пальцы .L": ["Thumb.L", "Index.L", "Middle.L", "Ring.L", "Pinky.L"],
            "Пальцы .R": ["Thumb.R", "Index.R", "Middle.R", "Ring.R", "Pinky.R"],
            "Нога .L": ["Thigh.L", "Shin.L", "Foot.L", "Knee.L", "Ankle.L", "Toe.L", "Heel.L"],
            "Нога .R": ["Thigh.R", "Shin.R", "Foot.R", "Knee.R", "Ankle.R", "Toe.R", "Heel.R"],
            "Доп": ["Tail", "Wing.L", "Wing.R", "Cape", "Belt", "Helmet", "Skirt", "Boot.L", "Boot.R"],
        }

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #4ec990; padding: 2px;
            }
            QMenu::item { padding: 4px 16px; }
            QMenu::item:selected { background-color: #264f78; }
            QMenu::separator { height: 1px; background: #3c3c3c; margin: 2px 8px; }
        """)

        def apply_tag(tag):
            self._updating_tree = True
            self.object_tags[obj_name] = tag
            item.setText(2, tag)
            item.setForeground(2, QColor(78, 201, 144))
            self._updating_tree = False
            tagged = sum(1 for v in self.object_tags.values() if v)
            self.status.showMessage(f"{obj_name} → {tag}  |  Тегов: {tagged}", 3000)

        for group_name, tags in TAG_GROUPS.items():
            submenu = menu.addMenu(group_name)
            submenu.setStyleSheet(menu.styleSheet())
            for tag in tags:
                act = QAction(tag, self)
                act.triggered.connect(lambda _, t=tag: apply_tag(t))
                submenu.addAction(act)

        menu.addSeparator()
        act_clear = QAction("✕  Убрать тег", self)
        act_clear.triggered.connect(lambda: self._clear_tag(item, obj_name))
        menu.addAction(act_clear)

        rect = self.tree.visualItemRect(item)
        pos = self.tree.viewport().mapToGlobal(rect.bottomLeft())
        menu.exec_(pos)

    def _clear_tag(self, item, obj_name):
        self._updating_tree = True
        self.object_tags.pop(obj_name, None)
        item.setText(2, "")
        item.setForeground(2, QColor(80, 80, 80))
        self._updating_tree = False
        self.status.showMessage(f"Тег убран: {obj_name}", 3000)

    def _assign_tag_OLD_REMOVE(self, item):
        """УДАЛИТЬ"""
        pass  # placeholder
    def _OLD_END(self):
        from PyQt5.QtWidgets import QDialog, QCompleter, QLineEdit, QDialogButtonBox

        BODY_TAGS = [
            "Head", "Neck", "Jaw",
            "Chest", "Torso", "Spine", "Spine.Upper", "Spine.Lower",
            "Hips", "Pelvis",
            "Shoulder.L", "Shoulder.R",
            "UpperArm.L", "UpperArm.R",
            "Elbow.L", "Elbow.R",
            "Forearm.L", "Forearm.R",
            "Wrist.L", "Wrist.R",
            "Hand.L", "Hand.R",
            "Thumb.L", "Thumb.R", "Index.L", "Index.R",
            "Middle.L", "Middle.R", "Ring.L", "Ring.R",
            "Pinky.L", "Pinky.R",
            "Shoulder2.L", "Shoulder2.R",
            "UpperArm2.L", "UpperArm2.R",
            "Forearm2.L", "Forearm2.R",
            "Hand2.L", "Hand2.R",
            "Thigh.L", "Thigh.R",
            "Knee.L", "Knee.R",
            "Shin.L", "Shin.R",
            "Ankle.L", "Ankle.R",
            "Foot.L", "Foot.R",
            "Toe.L", "Toe.R",
            "Heel.L", "Heel.R",
            "Tail", "Wing.L", "Wing.R",
            "Cape", "Belt", "Helmet", "Skirt",
            "Pauldron.L", "Pauldron.R",
            "Boot.L", "Boot.R",
        ]

        obj_name = item.text(1)
        for ic in OBJECT_TYPE_ICONS.values():
            obj_name = obj_name.replace(f"{ic} ", "")

        current_tag = self.object_tags.get(obj_name, "")

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Тег: {obj_name}")
        dialog.setMinimumWidth(300)
        dlg_layout = QVBoxLayout(dialog)

        lbl = QLabel(f"Назначить тег для «{obj_name}»:")
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        dlg_layout.addWidget(lbl)

        edit = QLineEdit(current_tag)
        edit.setPlaceholderText("Начните вводить... (Head, Thigh.L, ...)")
        edit.selectAll()
        edit.setStyleSheet("font-size: 14px; padding: 6px; background: #252526; color: #4ec990; border: 1px solid #3c3c3c;")
        dlg_layout.addWidget(edit)

        completer = QCompleter(BODY_TAGS, dialog)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setStyleSheet("""
            QListView {
                background-color: #2d2d2d; color: #4ec990;
                border: 1px solid #4ec990; font-size: 13px;
            }
            QListView::item:selected { background-color: #264f78; }
        """)
        edit.setCompleter(completer)

        # Быстрые кнопки для частых тегов
        quick_layout = QHBoxLayout()
        quick_tags = ["Head", "Chest", "Hips", "UpperArm.L", "Thigh.L", "Foot.L"]
        for tag in quick_tags:
            btn = QPushButton(tag)
            btn.setFixedHeight(24)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2d2d2d; color: #4ec990; border: 1px solid #3c3c3c;
                    border-radius: 3px; padding: 2px 6px; font-size: 10px;
                }
                QPushButton:hover { background-color: #3c3c3c; }
            """)
            btn.clicked.connect(lambda _, t=tag: edit.setText(t))
            quick_layout.addWidget(btn)
        dlg_layout.addLayout(quick_layout)

        # Кнопка "Убрать тег"
        buttons_layout = QHBoxLayout()
        btn_clear = QPushButton("Убрать тег")
        btn_clear.setStyleSheet("background-color: #5a2d2d; color: #ddd; border: none; border-radius: 4px; padding: 6px 12px;")
        btn_clear.clicked.connect(lambda: (edit.clear(), dialog.accept()))
        buttons_layout.addWidget(btn_clear)
        buttons_layout.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.setStyleSheet("background-color: #0e639c; color: white; border: none; border-radius: 4px; padding: 6px 16px;")
        btn_ok.clicked.connect(dialog.accept)
        buttons_layout.addWidget(btn_ok)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setStyleSheet("background-color: #3c3c3c; color: #ccc; border: none; border-radius: 4px; padding: 6px 16px;")
        btn_cancel.clicked.connect(dialog.reject)
        buttons_layout.addWidget(btn_cancel)
        dlg_layout.addLayout(buttons_layout)

        dialog.setStyleSheet("QDialog { background-color: #1e1e1e; color: #d4d4d4; }")

        if dialog.exec_() != QDialog.Accepted:
            return

        new_tag = edit.text().strip()

        self._updating_tree = True
        if new_tag:
            self.object_tags[obj_name] = new_tag
            item.setText(2, new_tag)
            item.setForeground(2, QColor(78, 201, 144))
        else:
            self.object_tags.pop(obj_name, None)
            item.setText(2, "")
            item.setForeground(2, QColor(80, 80, 80))
        self._updating_tree = False

        tagged = sum(1 for v in self.object_tags.values() if v)
        self.status.showMessage(f"Тегов назначено: {tagged}", 3000)

    def _on_tree_item_changed(self, item, column):
        """Чекбокс изменён — переключить видимость объекта в превью."""
        if self._updating_tree or column != 0:
            return

        name = item.text(1)
        for ic in OBJECT_TYPE_ICONS.values():
            name = name.replace(f"{ic} ", "")

        checked = item.checkState(0) == Qt.Checked

        if checked:
            self.hidden_objects.discard(name)
            for col in range(1, 6):
                item.setForeground(col, QColor(212, 212, 212))
            # Восстановить цвет тега
            if item.text(2):
                item.setForeground(2, QColor(78, 201, 144))
        else:
            self.hidden_objects.add(name)
            for col in range(1, 6):
                item.setForeground(col, QColor(80, 80, 80))

        self._rebuild_preview()

    def _rebuild_preview(self):
        """Перестроить 3D-превью с учётом скрытых объектов."""
        if not self.data:
            return
        self.wireframe.load_mesh_data(self.data, self.hidden_objects)

    def _on_chart_hover(self, group_label):
        """При наведении на сегмент диаграммы — подсветить связанные объекты цветом сегмента."""
        obj_names = self.pie_chart.group_objects.get(group_label, set())
        # Найти цвет этого сегмента
        color = QColor(255, 60, 60)
        for label, count, c in self.pie_chart.segments:
            if label == group_label:
                color = QColor(
                    min(c.red() + 60, 255),
                    min(c.green() + 60, 255),
                    min(c.blue() + 60, 255),
                )
                break
        self.wireframe.highlight.set_hover({name: color for name in obj_names})
        self.wireframe.update()

    def _on_chart_click(self, group_label):
        """Клик по сегменту — зафиксировать подсветку."""
        obj_names = self.pie_chart.group_objects.get(group_label, set())
        color = QColor(255, 60, 60)
        for label, count, c in self.pie_chart.segments:
            if label == group_label:
                color = QColor(
                    min(c.red() + 60, 255),
                    min(c.green() + 60, 255),
                    min(c.blue() + 60, 255),
                )
                break
        self.wireframe.highlight.set_hover({name: color for name in obj_names})
        self.wireframe.highlight.lock_current()
        self.wireframe.update()

    def _on_chart_leave(self):
        """Мышь ушла с диаграммы — вернуть подсветку выбранного."""
        self.wireframe.highlight.clear_hover()
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
                    self.wireframe.highlight.clear_hover()
                    self.wireframe.update()
        except RuntimeError:
            pass
        return super().eventFilter(obj, event)

    def _on_issue_hover(self, item, column):
        """При наведении на строку ошибки — подсветить объект в превью."""
        if not item or not self.data:
            return
        text = item.text(0) or ""

        # Определяем цвет от корневого элемента группы
        root = item
        while root.parent():
            root = root.parent()
        color = root.foreground(0).color() if root else QColor(255, 60, 60)

        # Ищем имя объекта — строки вида "  ObjectName  —  описание"
        obj_dict = {}
        if "—" in text:
            name = text.split("—")[0].strip()
            if name:
                obj_dict[name] = color
        elif item.parent():
            parent = item.parent() if item.childCount() == 0 else item
            for i in range(parent.childCount()):
                child_text = parent.child(i).text(0)
                if "—" in child_text:
                    name = child_text.split("—")[0].strip()
                    if name:
                        obj_dict[name] = color

        # Если навели на заголовок группы
        if item.childCount() > 0 and not obj_dict:
            for i in range(item.childCount()):
                child_text = item.child(i).text(0)
                if "—" in child_text:
                    name = child_text.split("—")[0].strip()
                    if name:
                        obj_dict[name] = color

        self.wireframe.highlight.set_hover(obj_dict)
        self.wireframe.update()

    def _on_issue_clicked(self, item, column):
        """Клик по ошибке: раскрыть/свернуть + зафиксировать подсветку."""
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())
        # Фиксируем/снимаем подсветку
        self.wireframe.highlight.toggle_lock()
        self.wireframe.update()

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
        """Сохранить размеры и очистить."""
        self._save_window_state()
        self.wireframe.cleanup()
        event.accept()

    def _save_window_state(self):
        """Сохранить размеры окна и сплиттеров в конфиг."""
        geo = self.geometry()
        self.app_config["window"] = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "maximized": self.isMaximized(),
        }
        self.app_config["splitter_main"] = self.content_splitter.sizes()
        save_config(self.app_config)

    def _restore_window_state(self):
        """Восстановить размеры окна из конфига."""
        win = self.app_config.get("window")
        if win:
            if win.get("maximized"):
                self.showMaximized()
            else:
                self.setGeometry(
                    win.get("x", 100), win.get("y", 100),
                    win.get("width", 1200), win.get("height", 750),
                )
        splitter = self.app_config.get("splitter_main")
        if splitter and len(splitter) == self.content_splitter.count():
            self.content_splitter.setSizes(splitter)


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
