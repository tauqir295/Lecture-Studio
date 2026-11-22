"""Video Studio: slide-range selection, duration targeting, timing preview and MP4 generation."""
import json
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView
)

from src.backend.project_manager import ProjectManager
from src.backend.video import transitions as tx
from src.backend.video import video_types as vt
from src.backend.video.pipeline import layout_preview_frame, list_generated, missing_tools
from src.backend.tts import service as tts
from src.backend.tts.registry import get_engine
from src.backend.video.timing import RenderSettings, TimingPlan, fmt_duration, plan_timing, validate_range
from src.backend.workers.video_worker import TransitionPreviewWorker, VideoRenderWorker
from src.frontend.widgets.status_badge import StatusBadge
from src.models.project import Project

TARGETS = [("Natural length (no target)", None), ("10 minutes", 10), ("20 minutes", 20),
           ("30 minutes", 30), ("45 minutes", 45), ("Custom…", "custom")]


def _dspin(lo, hi, step, val, suffix="", dec=2):
    s = QDoubleSpinBox()
    s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(dec); s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


class VideoStudio(QWidget):
    """Configure and generate one or more videos from a project."""

    export_requested = Signal()
    video_generated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.plan: Optional[TimingPlan] = None
        self.worker: Optional[VideoRenderWorker] = None
        self._loading = False
        self.preview_worker: Optional[TransitionPreviewWorker] = None
        self._anim_frames: list = []
        self._anim_i = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_step)
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.lbl_title = QLabel("Video Studio — Range, Timing & Export")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f3f4f6;")
        top.addWidget(self.lbl_title)
        top.addStretch()
        self.lbl_gate_info = QLabel("")
        self.lbl_gate_info.setStyleSheet("color: #fbbf24; font-weight: bold;")
        self.lbl_gate_info.setWordWrap(True)
        top.addWidget(self.lbl_gate_info, 1)
        self.overall_badge = StatusBadge("video_preview")
        top.addWidget(self.overall_badge)
        root.addLayout(top)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ---- left: preview + timeline
        left = QVBoxLayout()
        self.video_display = QLabel("Preview")
        self.video_display.setAlignment(Qt.AlignCenter)
        self.video_display.setMinimumHeight(300)
        self.video_display.setStyleSheet("background-color: #0c0c10; border-radius: 8px; color: #6b7280;")
        left.addWidget(self.video_display, 3)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.btn_prev.clicked.connect(lambda: self._step_preview(-1))
        self.btn_next.clicked.connect(lambda: self._step_preview(1))
        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet("color: #9ca3af;")
        nav.addWidget(self.btn_prev); nav.addWidget(self.lbl_preview, 1); nav.addWidget(self.btn_next)
        left.addLayout(nav)

        self.timeline_table = QTableWidget()
        self.timeline_table.setColumnCount(7)
        self.timeline_table.setHorizontalHeaderLabels(["Slide", "Title", "Starts", "Enters with", "Narration",
                                                       "Hold", "On screen"])
        self.timeline_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.timeline_table.verticalHeader().setVisible(False)
        self.timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline_table.currentCellChanged.connect(lambda r, *_: self._show_preview(r))
        left.addWidget(self.timeline_table, 2)
        body.addLayout(left, 3)

        # ---- right: settings (scrollable)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setSpacing(10)

        pl.addWidget(self._build_video_type_group())

        g = QGroupBox("Slide range")
        f = QFormLayout(g)
        self.spin_from = QSpinBox(); self.spin_to = QSpinBox()
        for s in (self.spin_from, self.spin_to):
            s.setRange(1, 1)
            s.valueChanged.connect(self._on_settings_changed)
        rng = QHBoxLayout()
        rng.addWidget(QLabel("From")); rng.addWidget(self.spin_from)
        rng.addWidget(QLabel("To")); rng.addWidget(self.spin_to)
        self.btn_all = QPushButton("All")
        self.btn_all.clicked.connect(self._select_all_range)
        rng.addWidget(self.btn_all)
        f.addRow(rng)
        self.lbl_counts = QLabel("")
        f.addRow(self.lbl_counts)
        self.lbl_range_error = QLabel("")
        self.lbl_range_error.setStyleSheet("color: #ef4444;")
        self.lbl_range_error.setWordWrap(True)
        f.addRow(self.lbl_range_error)
        pl.addWidget(g)

        g = QGroupBox("Target duration")
        f = QFormLayout(g)
        self.combo_target = QComboBox()
        for label, _ in TARGETS:
            self.combo_target.addItem(label)
        self.combo_target.currentIndexChanged.connect(self._on_settings_changed)
        f.addRow("Target:", self.combo_target)
        self.spin_custom = _dspin(1, 600, 1, 15, " min", 1)
        self.spin_custom.valueChanged.connect(self._on_settings_changed)
        f.addRow("Custom:", self.spin_custom)
        pl.addWidget(g)

        g = QGroupBox("Narration")
        f = QFormLayout(g)
        self.lbl_voice = QLabel("")
        self.lbl_voice.setWordWrap(True)
        self.lbl_voice.setStyleSheet("color: #93c5fd;")
        f.addRow("Voice:", self.lbl_voice)
        self.lbl_audio_state = QLabel("")
        self.lbl_audio_state.setWordWrap(True)
        self.lbl_audio_state.setStyleSheet("color: #9ca3af;")
        f.addRow("Audio:", self.lbl_audio_state)
        self.chk_regen = QCheckBox("Regenerate outdated audio before rendering")
        f.addRow(self.chk_regen)
        self.spin_wpm = QSpinBox(); self.spin_wpm.setRange(100, 260); self.spin_wpm.setValue(150)
        self.spin_wpm.setSuffix(" wpm")
        self.spin_wpm.setToolTip("Only used to estimate slides that have no generated audio yet.")
        self.spin_wpm.valueChanged.connect(self._on_settings_changed)
        f.addRow("Estimate rate:", self.spin_wpm)
        self.spin_speed = _dspin(0.5, 2.0, 0.05, 1.0, "×")
        self.spin_speed.setToolTip("Tempo applied to the generated narration (pitch preserved). "
                                   "Voice and base speed are set in Narration Studio.")
        self.spin_speed.valueChanged.connect(self._on_settings_changed)
        f.addRow("Speed:", self.spin_speed)
        self.chk_speed_adjust = QCheckBox("Allow speed adjustment to fit the target")
        self.chk_speed_adjust.setChecked(True)
        self.chk_speed_adjust.toggled.connect(self._on_settings_changed)
        f.addRow(self.chk_speed_adjust)
        lim = QHBoxLayout()
        self.spin_min_speed = _dspin(0.5, 1.0, 0.05, 0.85, "×")
        self.spin_max_speed = _dspin(1.0, 2.0, 0.05, 1.20, "×")
        for s in (self.spin_min_speed, self.spin_max_speed):
            s.valueChanged.connect(self._on_settings_changed)
        lim.addWidget(QLabel("min")); lim.addWidget(self.spin_min_speed)
        lim.addWidget(QLabel("max")); lim.addWidget(self.spin_max_speed)
        f.addRow("Limits:", lim)
        note = QLabel("Narration text is never shortened or summarised automatically. "
                      "To shorten content, edit scripts in Narration Studio.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9ca3af; font-size: 11px;")
        f.addRow(note)
        pl.addWidget(g)

        g = QGroupBox("Timing && synchronisation")
        f = QFormLayout(g)
        self.chk_auto_sync = QCheckBox("Automatic timing (slide time follows its narration)")
        self.chk_auto_sync.setChecked(True)
        self.chk_auto_sync.toggled.connect(self._on_settings_changed)
        f.addRow(self.chk_auto_sync)
        self.spin_fixed = _dspin(2, 600, 1, 20, " s", 1)
        self.spin_min_slide = _dspin(0, 60, 0.5, 3, " s", 1)
        self.spin_reading = _dspin(0, 30, 0.5, 1, " s", 1)
        self.spin_max_hold = _dspin(0, 120, 1, 20, " s", 0)
        for s in (self.spin_fixed, self.spin_min_slide, self.spin_reading, self.spin_max_hold):
            s.valueChanged.connect(self._on_settings_changed)
        f.addRow("Fixed slide time:", self.spin_fixed)
        f.addRow("Minimum display:", self.spin_min_slide)
        f.addRow("Extra reading time:", self.spin_reading)
        f.addRow("Max added hold/slide:", self.spin_max_hold)
        pl.addWidget(g)

        pl.addWidget(self._build_transitions_group())

        g = QGroupBox("Estimate")
        f = QVBoxLayout(g)
        self.lbl_total_duration = QLabel("Estimated Duration: –")
        self.lbl_total_duration.setStyleSheet("font-size: 15px; font-weight: bold; color: #93c5fd;")
        self.lbl_breakdown = QLabel("")
        self.lbl_breakdown.setStyleSheet("color: #9ca3af;")
        self.lbl_feasible = QLabel("")
        self.lbl_feasible.setWordWrap(True)
        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setWordWrap(True)
        self.lbl_warnings.setStyleSheet("color: #fbbf24;")
        for w in (self.lbl_total_duration, self.lbl_breakdown, self.lbl_feasible, self.lbl_warnings):
            f.addWidget(w)
        pl.addWidget(g)

        g = QGroupBox("Generate")
        f = QVBoxLayout(g)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Optional video name, e.g. part1")
        f.addWidget(self.edit_name)
        self.btn_export = QPushButton("🎬  Generate Video")
        self.btn_export.setObjectName("primaryBtn")
        self.btn_export.setFixedHeight(40)
        self.btn_export.clicked.connect(self._on_export)
        f.addWidget(self.btn_export)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        self.lbl_progress = QLabel(""); self.lbl_progress.setStyleSheet("color: #9ca3af;")
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_render)
        f.addWidget(self.progress); f.addWidget(self.lbl_progress); f.addWidget(self.btn_cancel)
        pl.addWidget(g)

        g = QGroupBox("Generated videos")
        f = QVBoxLayout(g)
        self.list_videos = QListWidget()
        self.list_videos.itemDoubleClicked.connect(self._open_video)
        f.addWidget(self.list_videos)
        row = QHBoxLayout()
        b1 = QPushButton("Open"); b1.clicked.connect(lambda: self._open_video(self.list_videos.currentItem()))
        b2 = QPushButton("Show folder"); b2.clicked.connect(self._open_folder)
        b3 = QPushButton("Reuse settings"); b3.clicked.connect(self._reuse_settings)
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3)
        f.addLayout(row)
        pl.addWidget(g)
        pl.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(400)
        body.addWidget(scroll, 2)

    # ------------------------------------------------------------------ project
    def load_project(self, project: Project) -> None:
        first = self.project is not project
        self.project = project
        self.lbl_title.setText(f"Video Studio — {project.project_name}")
        total = max(len(project.slides), 1)
        self._loading = True
        for s in (self.spin_from, self.spin_to):
            s.setRange(1, total)
        if first:
            self.spin_from.setValue(1)
            self.spin_to.setValue(total)
            self._apply_settings(self._load_last_settings())
        self._load_transitions()
        self._load_video_type()
        self._loading = False
        self._refresh_videos()
        self._on_settings_changed()

    def showEvent(self, event) -> None:  # refresh estimate whenever the page becomes visible
        super().showEvent(event)
        if self.project:
            self._on_settings_changed()

    # ------------------------------------------------------------------ settings
    def current_settings(self) -> RenderSettings:
        tgt = TARGETS[self.combo_target.currentIndex()][1]
        target = self.spin_custom.value() * 60 if tgt == "custom" else (tgt * 60 if tgt else None)
        return RenderSettings(
            start=self.spin_from.value(), end=self.spin_to.value(), target_seconds=target,
            base_wpm=self.spin_wpm.value(), speed=self.spin_speed.value(),
            allow_speed_adjust=self.chk_speed_adjust.isChecked(),
            min_speed=self.spin_min_speed.value(), max_speed=self.spin_max_speed.value(),
            auto_sync=self.chk_auto_sync.isChecked(), fixed_slide_seconds=self.spin_fixed.value(),
            min_slide_seconds=self.spin_min_slide.value(), reading_seconds=self.spin_reading.value(),
            max_extra_hold=self.spin_max_hold.value(),
            transition_seconds=self.project.settings.transition_duration if self.project else 0.5,
            regenerate_outdated=self.chk_regen.isChecked(), name=self.edit_name.text().strip())

    def _apply_settings(self, cfg: Optional[RenderSettings]) -> None:
        if not cfg:
            return
        self._loading = True
        total = len(self.project.slides) if self.project else 1
        self.spin_from.setValue(min(max(cfg.start, 1), total))
        self.spin_to.setValue(min(max(cfg.end, 1), total))
        idx = len(TARGETS) - 1
        if cfg.target_seconds is None:
            idx = 0
        else:
            for i, (_, v) in enumerate(TARGETS):
                if isinstance(v, int) and abs(v * 60 - cfg.target_seconds) < 1:
                    idx = i
            self.spin_custom.setValue(cfg.target_seconds / 60)
        self.combo_target.setCurrentIndex(idx)
        self.spin_wpm.setValue(cfg.base_wpm); self.spin_speed.setValue(cfg.speed)
        self.chk_speed_adjust.setChecked(cfg.allow_speed_adjust)
        self.spin_min_speed.setValue(cfg.min_speed); self.spin_max_speed.setValue(cfg.max_speed)
        self.chk_auto_sync.setChecked(cfg.auto_sync); self.spin_fixed.setValue(cfg.fixed_slide_seconds)
        self.spin_min_slide.setValue(cfg.min_slide_seconds); self.spin_reading.setValue(cfg.reading_seconds)
        self.spin_max_hold.setValue(cfg.max_extra_hold)
        self.chk_regen.setChecked(cfg.regenerate_outdated)
        self._loading = False

    def _settings_file(self) -> Optional[Path]:
        return Path(self.project.project_dir) / "video" / "last_settings.json" if self.project else None

    def _load_last_settings(self) -> Optional[RenderSettings]:
        p = self._settings_file()
        try:
            return RenderSettings.from_dict(json.loads(p.read_text())) if p and p.is_file() else None
        except (OSError, ValueError, TypeError):
            return None

    def _select_all_range(self) -> None:
        if self.project:
            self.spin_from.setValue(1)
            self.spin_to.setValue(len(self.project.slides))

    # ------------------------------------------------------------------ estimate
    def _on_settings_changed(self, *_) -> None:
        if self._loading or not self.project:
            return
        cfg = self.current_settings()
        custom = TARGETS[self.combo_target.currentIndex()][1] == "custom"
        self.spin_custom.setEnabled(custom)
        self.spin_fixed.setEnabled(not cfg.auto_sync)
        self.spin_reading.setEnabled(cfg.auto_sync)
        lim = cfg.allow_speed_adjust
        self.spin_min_speed.setEnabled(lim); self.spin_max_speed.setEnabled(lim)

        total = len(self.project.slides)
        err = validate_range(cfg.start, cfg.end, total)
        sel = 0 if err else cfg.end - cfg.start + 1
        self.lbl_counts.setText(f"Total slides: {total}   ·   Selected: {sel}")
        self.lbl_range_error.setText(err or "")
        if err:
            self.plan = None
            self.timeline_table.setRowCount(0)
            self.lbl_total_duration.setText("Estimated Duration: –")
            self.lbl_feasible.setText(""); self.lbl_warnings.setText(""); self.lbl_breakdown.setText("")
        else:
            ids = [s.slide_id for s in self.project.slides if cfg.start <= s.slide_number <= cfg.end]
            self.plan = plan_timing(self.project.slides, self.project.narrations, cfg,
                                    measured=self._measured_audio(cfg),
                                    transitions=tx.incoming(self.project.settings, ids))
            self._render_plan(cfg)
        self._check_gates()

    def _measured_audio(self, cfg: RenderSettings) -> dict:
        """Real audio lengths of slides in range that already have narration audio."""
        p = self.project
        measured, counts = {}, {"ready": 0, "outdated": 0, "none": 0}
        for n in p.narrations:
            if not (cfg.start <= n.slide_number <= cfg.end):
                continue
            state = tts.audio_state(p, n)
            if state in (tts.READY, tts.OUTDATED) and n.audio_duration:
                measured[n.slide_id] = n.audio_duration
                counts["ready" if state == tts.READY else "outdated"] += 1
            else:
                counts["none"] += 1
        eng = get_engine(p.settings.tts_engine)
        mode = "per-slide speakers" if p.settings.speaker_mode == "per_slide" else p.settings.voice_id
        self.lbl_voice.setText(f"{eng.name} · {mode} · {p.settings.speech_speed:.2f}× (change in Narration Studio)")
        self.lbl_audio_state.setText(f"{counts['ready']} ready · {counts['outdated']} outdated · "
                                     f"{counts['none']} not generated yet (generated during rendering)")
        return measured

    def _render_plan(self, cfg: RenderSettings) -> None:
        p = self.plan
        self.lbl_total_duration.setText(f"Estimated Duration: {fmt_duration(p.total_seconds)}")
        holds = sum(s.hold_seconds for s in p.slides)
        trans = sum(s.transition_seconds for s in p.slides)
        self.lbl_breakdown.setText(
            f"Narration {fmt_duration(p.narration_seconds)} · holds {fmt_duration(holds)} · "
            f"transitions {fmt_duration(trans)} · speed {p.speed:.2f}× ({p.wpm} wpm)")
        if cfg.target_seconds:
            reach = f"Reachable: {fmt_duration(p.min_achievable)} – {fmt_duration(p.max_achievable)}"
            if p.feasible:
                self.lbl_feasible.setText(f"✓ Target {fmt_duration(cfg.target_seconds)} is achievable. {reach}")
                self.lbl_feasible.setStyleSheet("color: #10b981; font-weight: bold;")
            else:
                self.lbl_feasible.setText(f"✗ Target {fmt_duration(cfg.target_seconds)} is not realistic. {reach}")
                self.lbl_feasible.setStyleSheet("color: #ef4444; font-weight: bold;")
        else:
            self.lbl_feasible.setText("Natural length: timing follows the narration.")
            self.lbl_feasible.setStyleSheet("color: #9ca3af;")
        self.lbl_warnings.setText("\n".join(f"⚠ {w}" for w in p.warnings))

        cur = max(self.timeline_table.currentRow(), 0)
        self.timeline_table.setRowCount(len(p.slides))
        t = 0.0
        for i, st in enumerate(p.slides):
            enters = ("start of video" if i == 0 else
                      f"{tx.label(st.transition_type)}" + (f" {st.transition_seconds:g}s" if st.transition_seconds else ""))
            vals = [f"#{st.slide_number}", st.title, fmt_duration(t), enters, f"{st.narration_seconds:.1f}s",
                    f"{st.hold_seconds:.1f}s", f"{st.display_seconds:.1f}s"]
            for c, v in enumerate(vals):
                self.timeline_table.setItem(i, c, QTableWidgetItem(v))
            t += st.display_seconds
        if p.slides:
            self.timeline_table.setCurrentCell(min(cur, len(p.slides) - 1), 0)
            self._show_preview(self.timeline_table.currentRow())

    # ------------------------------------------------------------------ preview
    def _show_preview(self, row: int) -> None:
        self._stop_animation()
        if not self.plan or not (0 <= row < len(self.plan.slides)):
            return
        st = self.plan.slides[row]
        slide = self.project.get_slide_by_id(st.slide_id)
        start = sum(s.display_seconds for s in self.plan.slides[:row])
        self.lbl_preview.setText(f"Slide {st.slide_number} ({row + 1}/{len(self.plan.slides)}) · "
                                 f"{fmt_duration(start)} → {fmt_duration(start + st.display_seconds)} · {st.title}")
        img = Path(self.project.project_dir) / (slide.image_path or "") if slide else None
        if img and slide.image_path and img.is_file():
            pix = QPixmap(str(img))
            self.video_display.setPixmap(pix.scaled(self.video_display.width() or 640,
                                                    self.video_display.height() or 360,
                                                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.video_display.setText(f"Slide {st.slide_number}")

    def _step_preview(self, delta: int) -> None:
        r = self.timeline_table.currentRow() + delta
        if 0 <= r < self.timeline_table.rowCount():
            self.timeline_table.setCurrentCell(r, 0)

    # ------------------------------------------------------------------ video type
    def _build_video_type_group(self) -> QGroupBox:
        g = QGroupBox("Video type")
        f = QFormLayout(g)
        self.combo_type = QComboBox()
        for t in vt.types():
            self.combo_type.addItem(t.label, t.key)
        self.combo_type.currentIndexChanged.connect(self._on_video_type_changed)
        f.addRow("Type:", self.combo_type)
        self.lbl_type_info = QLabel("")
        self.lbl_type_info.setWordWrap(True)
        self.lbl_type_info.setStyleSheet("color: #9ca3af; font-size: 11px;")
        f.addRow(self.lbl_type_info)
        self.combo_aspect = QComboBox()
        for a, (w, h) in vt.ASPECTS.items():
            self.combo_aspect.addItem(f"{a}  ({w}×{h})", a)
        self.combo_layout = QComboBox()
        for k, label in vt.LAYOUTS.items():
            self.combo_layout.addItem(label, k)
        self.combo_overlay = QComboBox()
        for k, label in vt.OVERLAYS.items():
            self.combo_overlay.addItem(label, k)
        for c in (self.combo_aspect, self.combo_layout, self.combo_overlay):
            c.currentIndexChanged.connect(self._on_frame_settings_changed)
        f.addRow("Frame:", self.combo_aspect)
        f.addRow("Layout:", self.combo_layout)
        f.addRow("Overlay:", self.combo_overlay)
        self.btn_preview_frame = QPushButton("Preview frame")
        self.btn_preview_frame.setToolTip("Show the selected slide with this frame shape, layout and overlay.")
        self.btn_preview_frame.clicked.connect(self._preview_layout)
        f.addRow(self.btn_preview_frame)
        note = QLabel("A type sets defaults for frame, layout, transitions, pacing and delivery style. "
                      "Everything stays editable; slides and narration text are not changed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9ca3af; font-size: 11px;")
        f.addRow(note)
        return g

    def _type_info(self, t) -> str:
        from src.backend.tts import emotion
        return (f"{t.description}\nTip: {t.tips}\nDefaults: {t.aspect}, {vt.LAYOUTS[t.layout].lower()}, "
                f"{tx.label(t.transition).lower()} transitions, {emotion.get(t.emotion).label.lower()} delivery.")

    def _load_video_type(self) -> None:
        vc = self.project.settings
        was = self._loading
        self._loading = True
        self._set_combo(self.combo_type, vt.get(vc.video_type).key)
        self._set_combo(self.combo_aspect, vc.aspect_ratio if vc.aspect_ratio in vt.ASPECTS else "16:9")
        self._set_combo(self.combo_layout, vc.layout if vc.layout in vt.LAYOUTS else "fit")
        self._set_combo(self.combo_overlay, vc.overlay if vc.overlay in vt.OVERLAYS else "none")
        self.lbl_type_info.setText(self._type_info(vt.get(vc.video_type)))
        self._loading = was

    def _on_video_type_changed(self, *_) -> None:
        if self._loading or not self.project:
            return
        t = vt.apply_to_config(self.project.settings, self.combo_type.currentData())
        self._loading = True
        self.spin_reading.setValue(t.reading_seconds)
        self.spin_min_slide.setValue(t.min_slide_seconds)
        self.spin_speed.setValue(t.speed)
        self._loading = False
        self._load_video_type()
        self._load_transitions()
        self._transitions_changed()          # saves the project and refreshes the estimate

    def _on_frame_settings_changed(self, *_) -> None:
        if self._loading or not self.project:
            return
        vc = self.project.settings
        vt.set_aspect(vc, self.combo_aspect.currentData())
        vc.layout = self.combo_layout.currentData()
        vc.overlay = self.combo_overlay.currentData()
        self._transitions_changed()

    def _preview_layout(self) -> None:
        if not self.plan or not self.plan.slides:
            return
        row = max(self.timeline_table.currentRow(), 0)
        st = self.plan.slides[min(row, len(self.plan.slides) - 1)]
        self._stop_animation()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data, w, h = layout_preview_frame(self.project, st.slide_id, 640)
        except Exception as exc:
            QMessageBox.warning(self, "Preview Failed", str(exc))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._preview_bytes = data                      # QImage does not copy the buffer
        img = QImage(data, w, h, w * 3, QImage.Format_RGB888)
        self.video_display.setPixmap(QPixmap.fromImage(img).scaled(
            self.video_display.width() or 640, self.video_display.height() or 360,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        vc = self.project.settings
        self.lbl_preview.setText(f"Frame preview · slide {st.slide_number} · {vc.aspect_ratio} · "
                                 f"{vt.LAYOUTS.get(vc.layout, vc.layout)} · overlay: {vt.OVERLAYS.get(vc.overlay, vc.overlay)}")

    # ------------------------------------------------------------------ transitions
    @staticmethod
    def _type_combo() -> QComboBox:
        c = QComboBox()
        for t in tx.types():
            c.addItem(t.label, t.key)
        return c

    @staticmethod
    def _duration_combo() -> QComboBox:
        c = QComboBox()
        for d in tx.DURATIONS:
            c.addItem(f"{d:g} s", d)
        return c

    @staticmethod
    def _set_combo(c: QComboBox, value) -> None:
        i = c.findData(value)
        if i < 0 and isinstance(value, float):     # durations outside the preset list
            c.addItem(f"{value:g} s", value)
            i = c.count() - 1
        c.setCurrentIndex(max(i, 0))

    def _build_transitions_group(self) -> QGroupBox:
        g = QGroupBox("Slide transitions")
        v = QVBoxLayout(g)
        f = QFormLayout()
        self.combo_trans_default = self._type_combo()
        self.combo_trans_default_dur = self._duration_combo()
        for c in (self.combo_trans_default, self.combo_trans_default_dur):
            c.currentIndexChanged.connect(self._on_default_transition_changed)
        row = QHBoxLayout()
        row.addWidget(self.combo_trans_default, 1); row.addWidget(self.combo_trans_default_dur)
        f.addRow("Default:", row)
        row = QHBoxLayout()
        self.btn_trans_all = QPushButton("Apply to all slides")
        self.btn_trans_all.setToolTip("Use the default for every slide.")
        self.btn_trans_all.clicked.connect(self._apply_transition_all)
        self.chk_trans_override = QCheckBox("Override per-slide settings")
        self.chk_trans_override.setToolTip("When ticked, 'Apply to all' also removes every per-slide transition.")
        row.addWidget(self.btn_trans_all); row.addWidget(self.chk_trans_override)
        f.addRow(row)
        v.addLayout(f)

        self.trans_table = QTableWidget()
        self.trans_table.setColumnCount(4)
        self.trans_table.setHorizontalHeaderLabels(["Slide", "Title", "Enters with", "Duration"])
        self.trans_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.trans_table.verticalHeader().setVisible(False)
        self.trans_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trans_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.trans_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trans_table.setMinimumHeight(180)
        self.trans_table.itemSelectionChanged.connect(self._on_trans_selection)
        self.trans_table.cellDoubleClicked.connect(lambda *_: self._preview_transition())
        v.addWidget(self.trans_table)

        f = QFormLayout()
        self.combo_trans_sel = self._type_combo()
        self.combo_trans_sel_dur = self._duration_combo()
        row = QHBoxLayout()
        row.addWidget(self.combo_trans_sel, 1); row.addWidget(self.combo_trans_sel_dur)
        f.addRow("Selected:", row)
        row = QHBoxLayout()
        for text, tip, fn in (
                ("Apply", "Set this transition on the selected slide(s).", self._apply_transition_selected),
                ("No transition", "Cut straight to the selected slide(s).", self._no_transition_selected),
                ("Use default", "Remove the per-slide setting.", self._reset_transition_selected),
                ("Vary", "Give the selected slides a varied sequence of transitions.", self._vary_transition_selected)):
            b = QPushButton(text); b.setToolTip(tip); b.clicked.connect(fn)
            row.addWidget(b)
        f.addRow(row)
        v.addLayout(f)

        self.btn_trans_preview = QPushButton("▶  Preview transition")
        self.btn_trans_preview.setToolTip("Shows the previous slide changing into the selected slide "
                                          "with the effect and duration chosen under 'Selected'.")
        self.btn_trans_preview.clicked.connect(self._preview_transition)
        v.addWidget(self.btn_trans_preview)
        note = QLabel("A transition is how a slide enters from the previous one. It is silent and added "
                      "before the slide's narration, so speech and subtitles are never cut. The first "
                      "slide of a rendered range starts without one.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9ca3af; font-size: 11px;")
        v.addWidget(note)
        return g

    def _load_transitions(self) -> None:
        vc = self.project.settings
        was = self._loading
        self._loading = True
        self._set_combo(self.combo_trans_default, vc.transition if vc.transition in {t.key for t in tx.types()} else tx.NONE)
        self._set_combo(self.combo_trans_default_dur, float(vc.transition_duration))
        self._loading = was
        self._refresh_trans_table()

    def _refresh_trans_table(self) -> None:
        if not self.project:
            return
        vc = self.project.settings
        rows = {i.row() for i in self.trans_table.selectionModel().selectedRows()} if self.trans_table.selectionModel() else set()
        self.trans_table.setRowCount(len(self.project.slides))
        for r, s in enumerate(self.project.slides):
            key, dur = tx.resolve(vc, s.slide_id)
            custom = s.slide_id in (vc.slide_transitions or {})
            vals = [f"#{s.slide_number}", s.title, tx.label(key) + ("" if custom else "  (default)"),
                    f"{dur:g} s" if key != tx.NONE else "–"]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if custom:
                    item.setForeground(QColor("#67e8f9"))
                self.trans_table.setItem(r, c, item)
        sm = self.trans_table.selectionModel()
        for r in rows:
            if r < self.trans_table.rowCount():
                sm.select(self.trans_table.model().index(r, 0),
                          QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _selected_slide_ids(self) -> List[str]:
        rows = sorted(i.row() for i in self.trans_table.selectionModel().selectedRows())
        return [self.project.slides[r].slide_id for r in rows if r < len(self.project.slides)]

    def _on_trans_selection(self) -> None:
        ids = self._selected_slide_ids() if self.project else []
        if ids:
            key, dur = tx.resolve(self.project.settings, ids[0])
            self._set_combo(self.combo_trans_sel, key)
            self._set_combo(self.combo_trans_sel_dur, float(dur or self.project.settings.transition_duration))

    def _transitions_changed(self) -> None:
        """Persist with the project and refresh estimate + tables."""
        try:
            ProjectManager(self.project.project_dir).save_project(self.project)
        except Exception:   # saving must never break editing; main window can save again
            pass
        self._refresh_trans_table()
        self._on_settings_changed()

    def _on_default_transition_changed(self, *_) -> None:
        if self._loading or not self.project:
            return
        self.project.settings.transition = self.combo_trans_default.currentData()
        self.project.settings.transition_duration = float(self.combo_trans_default_dur.currentData())
        self._transitions_changed()

    def _apply_transition_all(self) -> None:
        if not self.project:
            return
        self._on_default_transition_changed()
        if self.chk_trans_override.isChecked():
            self.project.settings.slide_transitions = {}
            self._transitions_changed()

    def _set_overrides(self, ids: List[str], make) -> None:
        if not self.project:
            return
        if not ids:
            QMessageBox.information(self, "No Slides Selected", "Select one or more slides in the transitions list.")
            return
        st = dict(self.project.settings.slide_transitions or {})
        for i, sid in enumerate(ids):
            val = make(i)
            if val is None:
                st.pop(sid, None)
            else:
                st[sid] = val
        self.project.settings.slide_transitions = st
        self._transitions_changed()

    def _apply_transition_selected(self) -> None:
        val = {"type": self.combo_trans_sel.currentData(), "duration": float(self.combo_trans_sel_dur.currentData())}
        self._set_overrides(self._selected_slide_ids(), lambda i: dict(val))

    def _no_transition_selected(self) -> None:
        self._set_overrides(self._selected_slide_ids(), lambda i: {"type": tx.NONE, "duration": 0.0})

    def _reset_transition_selected(self) -> None:
        self._set_overrides(self._selected_slide_ids(), lambda i: None)

    def _vary_transition_selected(self) -> None:
        dur = float(self.combo_trans_sel_dur.currentData())
        cyc = tx.VARY_CYCLE
        self._set_overrides(self._selected_slide_ids(), lambda i: {"type": cyc[i % len(cyc)], "duration": dur})

    def _preview_transition(self) -> None:
        if not self.project:
            return
        ids = self._selected_slide_ids()
        if not ids:
            QMessageBox.information(self, "Preview Transition", "Select the slide whose entry you want to preview.")
            return
        idx = next(i for i, s in enumerate(self.project.slides) if s.slide_id == ids[0])
        if idx == 0:
            QMessageBox.information(self, "Preview Transition",
                                    "Slide 1 has no previous slide. Select a later slide to preview its entry.")
            return
        prev, cur = self.project.slides[idx - 1], self.project.slides[idx]
        if self.preview_worker and self.preview_worker.isRunning():
            return
        key = self.combo_trans_sel.currentData()
        dur = float(self.combo_trans_sel_dur.currentData())
        self._stop_animation()
        self.video_display.setText("Rendering preview…")
        self.lbl_preview.setText(f"Preview: slide {prev.slide_number} → {cur.slide_number} · {tx.label(key)}"
                                 + (f" · {dur:g}s" if key != tx.NONE else ""))
        self.btn_trans_preview.setEnabled(False)
        width = max(min(self.video_display.width(), 960), 320)
        self.preview_worker = TransitionPreviewWorker(self.project, prev.slide_id, cur.slide_id, key, dur, width)
        self.preview_worker.ready.connect(self._play_preview)
        self.preview_worker.failed.connect(self._preview_failed)
        self.preview_worker.finished.connect(lambda: self.btn_trans_preview.setEnabled(True))
        self.preview_worker.start()

    def _play_preview(self, frames, w: int, h: int, fps: float) -> None:
        # Keep the bytes alive alongside each QImage (QImage does not copy the buffer).
        self._anim_frames = [(fr, QImage(fr, w, h, w * 3, QImage.Format_RGB888)) for fr in frames]
        self._anim_i = 0
        self._anim_timer.start(max(int(1000 / fps), 1))

    def _preview_failed(self, msg: str) -> None:
        self.video_display.setText("Preview failed")
        QMessageBox.warning(self, "Preview Failed", msg)

    def _anim_step(self) -> None:
        if self._anim_i >= len(self._anim_frames):
            self._anim_timer.stop()
            return
        img = self._anim_frames[self._anim_i][1]
        self.video_display.setPixmap(QPixmap.fromImage(img).scaled(
            self.video_display.width() or 640, self.video_display.height() or 360,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._anim_i += 1

    def _stop_animation(self) -> None:
        self._anim_timer.stop()
        self._anim_frames = []

    # ------------------------------------------------------------------ gates
    def gate_problems(self) -> List[str]:
        """What prevents generation right now (empty = ready). Approvals are NOT required."""
        if not self.project or not self.project.slides:
            return ["No project with slides is loaded."]
        return missing_tools(self.project)

    @staticmethod
    def _fmt(nums) -> str:
        return ", ".join(f"#{n}" for n in nums[:12]) + (f" … (+{len(nums) - 12} more)" if len(nums) > 12 else "")

    def _check_gates(self) -> None:
        problems = self.gate_problems()
        busy = self.worker is not None and self.worker.isRunning()
        if problems:
            self.lbl_gate_info.setText(f"Cannot generate: {problems[0]}")
            self.lbl_gate_info.setStyleSheet("color: #ef4444; font-weight: bold;")
            self.btn_export.setToolTip("\n".join(problems))
        else:
            self.lbl_gate_info.setText("Ready to generate ✓")
            self.lbl_gate_info.setStyleSheet("color: #10b981; font-weight: bold;")
            self.btn_export.setToolTip("")
        self.btn_export.setEnabled(not problems and self.plan is not None and not busy)

    # ------------------------------------------------------------------ generate
    def _on_export(self) -> None:
        if not self.project:
            return
        problems = self.gate_problems()
        if problems:
            QMessageBox.critical(self, "Cannot Generate Video", "Cannot generate video:\n\n• " + "\n• ".join(problems))
            return
        cfg = self.current_settings()
        err = validate_range(cfg.start, cfg.end, len(self.project.slides))
        if err:
            QMessageBox.warning(self, "Invalid Slide Range", err)
            return
        if self.plan and not self.plan.feasible:
            ans = QMessageBox.question(
                self, "Target Duration Not Reachable",
                "\n".join(self.plan.warnings) + f"\n\nGenerate anyway at about {fmt_duration(self.plan.total_seconds)}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        try:
            f = self._settings_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(cfg.to_dict(), indent=2))
        except OSError:
            pass
        self.worker = VideoRenderWorker(self.project, cfg)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.progress.setValue(0); self.progress.setVisible(True); self.btn_cancel.setVisible(True)
        self.lbl_progress.setText(f"Generating slides {cfg.start}–{cfg.end}…")
        self.worker.start()
        self._check_gates()

    def _cancel_render(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.lbl_progress.setText("Cancelling…")

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.lbl_progress.setText(msg)

    def _finish(self) -> None:
        self.progress.setVisible(False); self.btn_cancel.setVisible(False)
        if self.worker:
            self.worker.wait(2000)
        self.worker = None
        self._check_gates()

    def _on_done(self, report: dict) -> None:
        self._finish()
        self._refresh_videos()
        self.lbl_progress.setText(f"✓ {report['video']} · {fmt_duration(report['total_seconds'])}")
        warn = ("\n\nWarnings:\n• " + "\n• ".join(report["warnings"])) if report.get("warnings") else ""
        QMessageBox.information(self, "Video Generated",
                                f"Created {report['video']}\nSlides {report['settings']['start']}–"
                                f"{report['settings']['end']} · {fmt_duration(report['total_seconds'])} · "
                                f"speed {report['speed_used']:.2f}×{warn}")
        self.video_generated.emit(report)
        self.export_requested.emit()

    def _on_failed(self, msg: str) -> None:
        self._finish()
        self.lbl_progress.setText(f"✗ {msg}")
        QMessageBox.critical(self, "Video Generation Failed", msg)

    # ------------------------------------------------------------------ generated list
    def _refresh_videos(self) -> None:
        self.list_videos.clear()
        if not self.project:
            return
        for r in list_generated(self.project):
            s = r.get("settings", {})
            item = QListWidgetItem(f"{r['video']}\n   slides {s.get('start')}–{s.get('end')} · "
                                   f"{fmt_duration(r.get('total_seconds', 0))} · {r.get('created', '')}")
            item.setData(Qt.UserRole, r)
            self.list_videos.addItem(item)

    def _open_video(self, item) -> None:
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)["path"]))

    def _open_folder(self) -> None:
        if self.project:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.project.project_dir) / "video")))

    def _reuse_settings(self) -> None:
        item = self.list_videos.currentItem()
        if item:
            self._apply_settings(RenderSettings.from_dict(item.data(Qt.UserRole).get("settings", {})))
            self._on_settings_changed()
