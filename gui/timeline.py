"""
Виджет таймлайна анимации.
Загружает ключевые кадры из Blender, воспроизводит трансформации в 3D-превью.
"""

import math
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QComboBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal


class TimelineWidget(QWidget):
    """Таймлайн анимации с воспроизведением."""

    frame_changed = pyqtSignal(int, dict)  # (frame_num, {obj_name: {loc, rot, scale}})

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(90)
        self.setVisible(False)

        self.anim_data = None  # данные анимации
        self.current_action_idx = 0
        self.current_frame = 0
        self.playing = False
        self.fps = 24

        self._setup_ui()

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._tick)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)

        self.combo_action = QComboBox()
        self.combo_action.setStyleSheet("""
            QComboBox {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #3c3c3c; border-radius: 3px;
                padding: 2px 8px; font-size: 11px; min-width: 150px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #3c3c3c; selection-background-color: #264f78;
            }
        """)
        self.combo_action.currentIndexChanged.connect(self._on_action_changed)
        top.addWidget(self.combo_action)

        btn_style = """
            QPushButton {
                background-color: #2d2d2d; color: #ccc;
                border: 1px solid #3c3c3c; border-radius: 3px;
                font-size: 14px; padding: 0px;
            }
            QPushButton:hover { background-color: #3c3c3c; color: white; }
        """

        self.btn_start = QPushButton("⏮")
        self.btn_start.setFixedSize(28, 24)
        self.btn_start.setStyleSheet(btn_style)
        self.btn_start.clicked.connect(self._go_start)
        top.addWidget(self.btn_start)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(28, 24)
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.clicked.connect(self._prev_frame)
        top.addWidget(self.btn_prev)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(28, 24)
        self.btn_play.setStyleSheet(btn_style)
        self.btn_play.clicked.connect(self.toggle_play)
        top.addWidget(self.btn_play)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(28, 24)
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.clicked.connect(self._next_frame)
        top.addWidget(self.btn_next)

        self.btn_end = QPushButton("⏭")
        self.btn_end.setFixedSize(28, 24)
        self.btn_end.setStyleSheet(btn_style)
        self.btn_end.clicked.connect(self._go_end)
        top.addWidget(self.btn_end)

        self.lbl_frame = QLabel("0 / 0")
        self.lbl_frame.setStyleSheet("color: #888; font-size: 11px; min-width: 70px;")
        self.lbl_frame.setAlignment(Qt.AlignCenter)
        top.addWidget(self.lbl_frame)

        top.addStretch()
        layout.addLayout(top)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2d2d2d; height: 6px; border-radius: 3px;
                border: 1px solid #3c3c3c;
            }
            QSlider::handle:horizontal {
                background: #4a9eff; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
            QSlider::sub-page:horizontal { background: #264f78; border-radius: 3px; }
        """)
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

    def set_anim_data(self, anim_data):
        """Загрузить данные анимации."""
        self.anim_data = anim_data
        self.combo_action.clear()

        # FPS из Blender файла
        self.fps = anim_data.get("fps", 24) if anim_data else 24

        actions = anim_data.get("actions", []) if anim_data else []

        if not actions:
            self.combo_action.addItem("Нет анимаций")
            self.slider.setRange(0, 0)
            self.lbl_frame.setText("—")
            return

        for act in actions:
            name = act["name"]
            fs = act["frame_start"]
            fe = act["frame_end"]
            nframes = len(act.get("frames", {}))
            self.combo_action.addItem(f"{name}  [{fs}–{fe}]  ({nframes} кадров)")

        self._on_action_changed(0)

    def _get_current_action(self):
        if not self.anim_data:
            return None
        actions = self.anim_data.get("actions", [])
        idx = self.combo_action.currentIndex()
        if 0 <= idx < len(actions):
            return actions[idx]
        return None

    def _on_action_changed(self, idx):
        act = self._get_current_action()
        if not act:
            return
        fs = act["frame_start"]
        fe = act["frame_end"]
        self.slider.setRange(fs, fe)
        self.current_frame = fs
        self.slider.setValue(fs)
        self.lbl_frame.setText(f"{fs} / {fe}")

    def _on_slider(self, value):
        self.current_frame = value
        act = self._get_current_action()
        if act:
            self.lbl_frame.setText(f"{value} / {act['frame_end']}")
            self._emit_frame(value)

    def _emit_frame(self, frame):
        """Отправить вершины для данного кадра."""
        act = self._get_current_action()
        if not act:
            return

        frames = act.get("frames", {})
        if not frames:
            return

        frame_str = str(frame)
        if frame_str in frames:
            self.frame_changed.emit(frame, frames[frame_str])
        else:
            # Кадр не экспортирован — найти ближайший предыдущий
            # (сохраняем позу, не пропускаем)
            keys = sorted(int(k) for k in frames.keys())
            prev = keys[0]
            for k in keys:
                if k <= frame:
                    prev = k
                else:
                    break
            self.frame_changed.emit(frame, frames[str(prev)])

    def toggle_play(self):
        self.playing = not self.playing
        if self.playing:
            self.btn_play.setText("⏸")
            interval = max(1, int(1000 / self.fps))
            self.play_timer.start(interval)
        else:
            self.btn_play.setText("▶")
            self.play_timer.stop()

    def _tick(self):
        act = self._get_current_action()
        if not act:
            return
        self.current_frame += 1
        if self.current_frame > act["frame_end"]:
            self.current_frame = act["frame_start"]
        self.slider.setValue(self.current_frame)

    def _prev_frame(self):
        act = self._get_current_action()
        if act:
            self.current_frame = max(act["frame_start"], self.current_frame - 1)
            self.slider.setValue(self.current_frame)

    def _next_frame(self):
        act = self._get_current_action()
        if act:
            self.current_frame = min(act["frame_end"], self.current_frame + 1)
            self.slider.setValue(self.current_frame)

    def _go_start(self):
        act = self._get_current_action()
        if act:
            self.slider.setValue(act["frame_start"])

    def _go_end(self):
        act = self._get_current_action()
        if act:
            self.slider.setValue(act["frame_end"])

    def stop(self):
        self.playing = False
        self.btn_play.setText("▶")
        self.play_timer.stop()

    def set_actions(self, actions):
        """Обратная совместимость — просто показать список."""
        if actions:
            self.set_anim_data({"actions": [
                {"name": a["name"], "frame_start": a["frame_range"][0],
                 "frame_end": a["frame_range"][1], "frames": {}}
                for a in actions
            ]})
