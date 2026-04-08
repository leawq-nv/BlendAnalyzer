"""
Окно настроек приложения.
"""

import json
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QHeaderView,
    QCheckBox, QGroupBox, QFormLayout,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor


CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "line_of_animation": False,
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            # Merge with defaults
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# === Определения биндов ===

GENERAL_KEYBINDINGS = [
    ("G", "Вкл/выкл вращение модели", "3D-превью"),
    ("Alt + G", "Сброс камеры + остановка вращения", "3D-превью"),
    ("ЛКМ + перетаскивание", "Вращение камеры вокруг модели", "3D-превью"),
    ("Колёсико мыши", "Приближение / отдаление", "3D-превью"),
    ("ЛКМ (клик без движения)", "Снять подсветку выделения", "3D-превью"),
    ("ПКМ", "Снять фиксированную подсветку ошибок", "3D-превью"),
    ("ПКМ (нет подсветки)", "Переключить режим (Каркас/Solid/Материалы)", "3D-превью"),
    ("СКМ (клик колёсиком)", "Снять всю подсветку", "3D-превью"),
    ("Двойной клик", "Сброс камеры", "3D-превью"),
    ("Space + Enter", "Развернуть превью на весь экран", "3D-превью"),
    ("Escape", "Выйти из полноэкранного режима", "3D-превью (фуллскрин)"),
    ("", "", ""),
    ("Клик по объекту", "Выделить объект (подсветка в превью)", "Дерево объектов"),
    ("Shift + клик", "Мульти-выделение объектов", "Дерево объектов"),
    ("Двойной клик по имени", "Переименовать объект в .blend файле", "Дерево объектов"),
    ("Двойной клик по тегу", "Назначить тег части тела (для скелета)", "Дерево объектов"),
    ("Клик по глазику", "Скрыть/показать объект в превью", "Дерево объектов"),
    ("", "", ""),
    ("Наведение на ошибку", "Подсветить связанные объекты в превью", "Панель проблем"),
    ("Клик по ошибке", "Зафиксировать подсветку (🔒)", "Панель проблем"),
    ("Наведение на диаграмму", "Подсветить объекты с этим типом ошибки", "Диаграмма"),
    ("Клик по сегменту", "Зафиксировать подсветку от диаграммы", "Диаграмма"),
    ("", "", ""),
    ("1", "Режим Каркас", "3D-превью / Фуллскрин"),
    ("2", "Режим Solid", "3D-превью / Фуллскрин"),
    ("3", "Режим Материалы", "3D-превью / Фуллскрин"),
    ("", "", ""),
    ("H", "Скрыть выделенные объекты", "3D-превью"),
    ("ЛКМ на мэше", "Выделить объект (+ выделение в дереве)", "3D-превью"),
    ("Shift + ЛКМ на мэше", "Добавить к выделению", "3D-превью"),
    ("", "", ""),
    ("Drag & drop .blend", "Открыть файл в новой вкладке", "3D-превью / Drop-зона"),
]

ANIMATION_KEYBINDINGS = [
    ("Space", "Воспроизвести / пауза анимации", "3D-превью / Фуллскрин"),
    ("Space + 1", "Воспроизвести / пауза (альтернатива)", "3D-превью / Фуллскрин"),
    ("←", "Предыдущий кадр", "3D-превью / Фуллскрин"),
    ("→", "Следующий кадр", "3D-превью / Фуллскрин"),
    ("Home", "Перейти к первому кадру", "3D-превью / Фуллскрин"),
    ("End", "Перейти к последнему кадру", "3D-превью / Фуллскрин"),
]


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки — Blend Analyzer")
        self.setMinimumSize(650, 550)
        self.config = load_config()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._create_settings_tab(), "Настройки")
        tabs.addTab(self._create_keybindings_tab("Основные", GENERAL_KEYBINDINGS), "Бинды")
        tabs.addTab(self._create_keybindings_tab("Анимация", ANIMATION_KEYBINDINGS), "Animation")
        tabs.addTab(self._create_about_tab(), "О программе")
        layout.addWidget(tabs)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_save = QPushButton("Сохранить")
        btn_save.setFixedHeight(32)
        btn_save.clicked.connect(self._save_and_close)
        btn_layout.addWidget(btn_save)
        btn_close = QPushButton("Закрыть")
        btn_close.setFixedHeight(32)
        btn_close.setStyleSheet("background-color: #3c3c3c;")
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)
        btn_layout.setContentsMargins(8, 4, 8, 8)
        layout.addLayout(btn_layout)

        self._apply_style()

    def _create_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)

        # Группа анимации
        anim_group = QGroupBox("Анимация")
        anim_group.setStyleSheet("QGroupBox { font-weight: bold; color: #ccc; border: 1px solid #3c3c3c; border-radius: 4px; margin-top: 8px; padding-top: 16px; }")
        anim_layout = QVBoxLayout(anim_group)

        self.chk_animation = QCheckBox("LineOfAnimation — Показывать таймлайн анимации")
        self.chk_animation.setChecked(self.config.get("line_of_animation", False))
        self.chk_animation.setStyleSheet("QCheckBox { color: #d4d4d4; font-size: 13px; }")
        anim_layout.addWidget(self.chk_animation)

        anim_hint = QLabel(
            "Если включено — под 3D-превью появляется таймлайн с дорожками анимаций.\n"
            "Можно воспроизводить анимации прямо в приложении."
        )
        anim_hint.setStyleSheet("color: #888; font-size: 11px; margin-left: 20px;")
        anim_hint.setWordWrap(True)
        anim_layout.addWidget(anim_hint)

        layout.addWidget(anim_group)
        layout.addStretch()
        return widget

    def _create_keybindings_tab(self, title, bindings):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        lbl = QLabel(f"{title}:")
        lbl.setStyleSheet("font-size: 12px; color: #aaa; margin-bottom: 4px;")
        layout.addWidget(lbl)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Клавиша / Действие", "Описание", "Где"])
        tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        tree.setColumnWidth(0, 200)
        tree.setColumnWidth(2, 140)
        tree.setIndentation(0)
        tree.setRootIsDecorated(False)

        for key, desc, where in bindings:
            if not key and not desc:
                sep = QTreeWidgetItem(["", "", ""])
                tree.addTopLevelItem(sep)
                continue

            item = QTreeWidgetItem([key, desc, where])
            item.setForeground(0, QColor(100, 200, 255))
            item.setFont(0, QFont("monospace", 10, QFont.Bold))
            item.setForeground(1, QColor(200, 200, 200))
            item.setForeground(2, QColor(120, 120, 120))
            tree.addTopLevelItem(item)

        layout.addWidget(tree)
        return widget

    def _create_about_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)

        about_text = QLabel(
            "<h2>Blend Analyzer</h2>"
            "<p>Приложение для анализа .blend файлов</p>"
            "<p><b>Функции:</b></p>"
            "<ul>"
            "<li>3D-превью с каркасом, solid и материалами</li>"
            "<li>Детекция ошибок (non-manifold, scale, rotation, doubles...)</li>"
            "<li>Система тегов для частей тела</li>"
            "<li>Создание скелета по тегам</li>"
            "<li>Применение модификаторов (Mirror)</li>"
            "<li>Создание Vertex Groups по зонам</li>"
            "<li>Мульти-файловые вкладки</li>"
            "<li>Воспроизведение анимаций</li>"
            "</ul>"
            "<p><b>Требует:</b> Blender (установлен в системе)</p>"
        )
        about_text.setWordWrap(True)
        about_text.setStyleSheet("color: #ccc; font-size: 13px;")
        layout.addWidget(about_text)
        layout.addStretch()

        # Ник в правом нижнем углу
        credit = QLabel("leawq")
        credit.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        credit.setStyleSheet("color: #555; font-size: 11px; font-style: italic;")
        layout.addWidget(credit)

        return widget

    def _save_and_close(self):
        self.config["line_of_animation"] = self.chk_animation.isChecked()
        save_config(self.config)
        self.accept()

    def get_config(self):
        return self.config

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #d4d4d4; }
            QTabWidget::pane { border: 1px solid #3c3c3c; }
            QTabBar::tab {
                background-color: #2d2d2d; color: #888;
                padding: 8px 20px; border: 1px solid #3c3c3c; border-bottom: none;
            }
            QTabBar::tab:selected { background-color: #1e1e1e; color: #d4d4d4; }
            QTreeWidget {
                background-color: #252526; border: 1px solid #3c3c3c; font-size: 12px;
            }
            QTreeWidget::item { padding: 3px 0; }
            QTreeWidget::item:selected { background-color: #264f78; }
            QHeaderView::section {
                background-color: #333; color: #ccc; border: 1px solid #444; padding: 4px;
            }
            QPushButton {
                background-color: #0e639c; color: white;
                border: none; border-radius: 4px; padding: 6px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #1177bb; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QCheckBox::indicator:unchecked { background-color: #3c3c3c; border: 1px solid #555; border-radius: 3px; }
            QCheckBox::indicator:checked { background-color: #4a9eff; border: 1px solid #4a9eff; border-radius: 3px; }
        """)
