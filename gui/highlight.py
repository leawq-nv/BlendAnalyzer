"""
Система подсветки объектов в 3D-превью.
Поддерживает:
  - Подсветка при наведении (hover) на ошибку/диаграмму
  - Фиксация подсветки кликом (lock)
  - Подсветка выбранного объекта в дереве
  - Сброс подсветки
"""

from PyQt5.QtGui import QColor


class HighlightManager:
    """Управляет подсветкой объектов в 3D-превью."""

    def __init__(self):
        # {obj_name: QColor} — текущая подсветка для рендера
        self._hover = {}        # от наведения (временная)
        self._locked = {}       # зафиксированная кликом
        self._selection = {}    # от выбора в дереве объектов

    @property
    def active(self):
        """Текущая подсветка для рендера: locked > hover > selection."""
        if self._locked:
            return dict(self._locked)
        if self._hover:
            return dict(self._hover)
        return dict(self._selection)

    @property
    def has_any(self):
        return bool(self._hover or self._locked or self._selection)

    @property
    def is_locked(self):
        return bool(self._locked)

    # --- Hover (от наведения на ошибки/диаграмму) ---

    def set_hover(self, obj_dict):
        """Установить подсветку от наведения. obj_dict: {name: QColor}"""
        self._hover = dict(obj_dict) if obj_dict else {}

    def clear_hover(self):
        self._hover = {}

    # --- Lock (фиксация кликом) ---

    def lock_current(self):
        """Зафиксировать текущую hover-подсветку."""
        if self._hover:
            self._locked = dict(self._hover)

    def toggle_lock(self):
        """Переключить: если залочено — разлочить, иначе залочить hover."""
        if self._locked:
            self._locked = {}
        elif self._hover:
            self._locked = dict(self._hover)

    def clear_lock(self):
        self._locked = {}

    # --- Selection (от выбора в дереве) ---

    def set_selection(self, obj_names, color=None):
        """Подсветить выбранные объекты. obj_names: str или set/list."""
        c = color or QColor(100, 200, 255)
        if isinstance(obj_names, str):
            self._selection = {obj_names: c} if obj_names else {}
        elif obj_names:
            self._selection = {n: c for n in obj_names}
        else:
            self._selection = {}

    def clear_selection(self):
        self._selection = {}

    # --- Reset ---

    def clear_all(self):
        self._hover = {}
        self._locked = {}
        self._selection = {}
