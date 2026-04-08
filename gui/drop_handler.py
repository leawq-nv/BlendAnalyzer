"""
Drag & drop поддержка для 3D-превью.
Позволяет перетаскивать .blend файлы прямо на виджет модели.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QFont, QPen


class DropHandlerMixin:
    """Миксин для добавления drag & drop в любой QWidget.

    Виджет, использующий этот миксин, должен:
      - Вызвать init_drop_handler() в __init__
      - Вызвать paint_drop_overlay(painter, w, h) в paintEvent
      - Иметь сигнал file_dropped = pyqtSignal(str)
    """

    def init_drop_handler(self):
        """Инициализировать drag & drop."""
        self.setAcceptDrops(True)
        self._drop_hovering = False

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0].toLocalFile()
            if url.endswith(".blend"):
                event.acceptProposedAction()
                self._drop_hovering = True
                self.update()

    def dragLeaveEvent(self, event):
        self._drop_hovering = False
        self.update()

    def dropEvent(self, event):
        self._drop_hovering = False
        url = event.mimeData().urls()[0].toLocalFile()
        if url.endswith(".blend"):
            self.file_dropped.emit(url)
        self.update()

    def paint_drop_overlay(self, painter, w, h):
        """Рисовать оверлей при перетаскивании файла."""
        if not self._drop_hovering:
            return

        # Затемнение
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 150))

        # Рамка
        painter.setPen(QPen(QColor(74, 158, 255), 3, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        margin = 20
        painter.drawRoundedRect(margin, margin, w - margin * 2, h - margin * 2, 12, 12)

        # Текст
        painter.setPen(QPen(QColor(74, 158, 255)))
        painter.setFont(QFont("sans-serif", 14))
        painter.drawText(0, 0, w, h, Qt.AlignCenter, "Отпустите .blend файл")
