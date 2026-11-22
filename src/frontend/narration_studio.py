"""Narration Studio: script editing, TTS model & speaker selection, previews and per-slide audio."""
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from src.backend.narration.narration_manager import NarrationManager
from src.backend.project_manager import ProjectManager
from src.backend.tts import base as tb
from src.backend.tts import emotion
from src.backend.tts import service as tts
from src.backend.tts import registry
from src.backend.tts.registry import engines, get_engine, has_engine
from src.backend.workers.tts_worker import TTSTaskWorker
from src.backend.workflow_manager import WorkflowManager
from src.frontend.widgets.audio_player import AudioPlayer
from src.frontend.widgets.status_badge import StatusBadge
from src.models.narration import NarrationStatus, SlideNarration
from src.models.project import Project

AUDIO_ICON = {tts.READY: "🔊 ready", tts.OUTDATED: "⚠ outdated", tts.NONE: "— no audio",
              tts.MISSING: "✗ file missing", "failed": "✗ failed"}


class PronunciationDialog(QDialog):
    """Edit the term → spoken-form dictionary applied before speech synthesis."""

    def __init__(self, mapping: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pronunciations")
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        info = QLabel("Terms are replaced by their spoken form before synthesis (whole words, case-sensitive). "
                      "Example: SQL → sequel, kubectl → cube control. Subtitles keep the original text.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Written term", "Say it as"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for k, v in sorted(mapping.items()):
            self._add(k, v)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_add = QPushButton("Add"); b_add.clicked.connect(lambda: self._add("", ""))
        b_del = QPushButton("Remove"); b_del.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row.addWidget(b_add); row.addWidget(b_del); row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self, k: str, v: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(k))
        self.table.setItem(r, 1, QTableWidgetItem(v))

    def mapping(self) -> dict:
        out = {}
        for r in range(self.table.rowCount()):
            k = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            v = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if k and v:
                out[k] = v
        return out


class NarrationStudio(QWidget):
    """Narration editor with local TTS voice selection, previews and audio generation."""

    narration_approved = Signal()
    CELL_STYLE = "padding: 2px 6px; min-height: 0px; font-size: 12px;"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.current_slide_id: Optional[str] = None
        self._is_populating = False
        self._busy_ui = False
        self.worker: Optional[TTSTaskWorker] = None
        self.player = AudioPlayer(self)
        self.player.started.connect(lambda lbl: self._set_play_status(f"▶ Playing: {lbl}"))
        self.player.stopped.connect(lambda: self._set_play_status(""))
        self._build_ui()

    # ================================================================== UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top_bar = QHBoxLayout()
        self.lbl_title = QLabel("Narration Studio — No Project Loaded")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f3f4f6;")
        top_bar.addWidget(self.lbl_title)
        top_bar.addStretch()
        self.lbl_gate_info = QLabel("Status: In review")
        self.lbl_gate_info.setStyleSheet("color: #fbbf24; font-weight: bold;")
        top_bar.addWidget(self.lbl_gate_info)
        self.overall_badge = StatusBadge("narration_review")
        top_bar.addWidget(self.overall_badge)
        layout.addLayout(top_bar)

        self.splitter = QSplitter(Qt.Horizontal)

        # ---- left: script list (multi-select for batch generation)
        left_panel = QWidget()
        lp = QVBoxLayout(left_panel)
        lp.setContentsMargins(4, 4, 4, 4)
        lp.addWidget(QLabel("Slide Scripts"))
        self.script_list = QListWidget()
        self.script_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.script_list.currentItemChanged.connect(self._on_script_selected)
        self.script_list.itemSelectionChanged.connect(self._update_audio_buttons)
        lp.addWidget(self.script_list, 1)
        hint = QLabel("Shift/Ctrl-click to select several slides")
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        lp.addWidget(hint)
        self.splitter.addWidget(left_panel)

        # ---- center: tabs (script editor / speaker assignment)
        self.tabs = QTabWidget()
        script_tab = QWidget()
        cp = QVBoxLayout(script_tab)
        cp.setContentsMargins(4, 4, 4, 4)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setStyleSheet("background-color: #121216; border-radius: 8px;")
        cp.addWidget(self.preview_label, 2)
        hdr = QHBoxLayout()
        self.lbl_editor_title = QLabel("Slide Script")
        self.lbl_editor_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #93c5fd;")
        hdr.addWidget(self.lbl_editor_title, 1)
        self.lbl_slide_speaker = QLabel("")
        self.lbl_slide_speaker.setStyleSheet("color: #9ca3af;")
        hdr.addWidget(self.lbl_slide_speaker)
        hdr.addWidget(QLabel("Style:"))
        self.combo_slide_style = QComboBox()
        self.combo_slide_style.setAccessibleName("Delivery style for this slide")
        self.combo_slide_style.setToolTip("Delivery style for this slide only. 'Project style' follows the "
                                          "Delivery style setting in the Speech panel.")
        self.combo_slide_style.addItem("Project style", None)
        for st in emotion.styles():
            self.combo_slide_style.addItem(st.label, st.key)
        self.combo_slide_style.currentIndexChanged.connect(self._on_slide_style_changed)
        hdr.addWidget(self.combo_slide_style)
        self.script_status_badge = StatusBadge()
        hdr.addWidget(self.script_status_badge)
        cp.addLayout(hdr)
        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("Enter conversational lecture narration for this slide...")
        self.script_edit.textChanged.connect(self._on_text_changed)
        cp.addWidget(self.script_edit, 3)
        metrics = QHBoxLayout()
        self.lbl_words = QLabel("0 words")
        self.lbl_duration = QLabel("Est: 0.0s")
        for w in (self.lbl_words, self.lbl_duration):
            w.setStyleSheet("color: #9ca3af; font-weight: 500;")
            metrics.addWidget(w)
        metrics.addStretch()
        self.btn_approve_script = QPushButton("✓ Approve Script")
        self.btn_approve_script.setObjectName("successBtn")
        self.btn_approve_script.clicked.connect(self._approve_current_script)
        metrics.addWidget(self.btn_approve_script)
        cp.addLayout(metrics)
        self.tabs.addTab(script_tab, "Script")

        assign_tab = QWidget()
        ap = QVBoxLayout(assign_tab)
        self.lbl_assign_hint = QLabel("")
        self.lbl_assign_hint.setWordWrap(True)
        self.lbl_assign_hint.setStyleSheet("color: #9ca3af;")
        ap.addWidget(self.lbl_assign_hint)
        self.assign_table = QTableWidget(0, 7)
        self.assign_table.setHorizontalHeaderLabels(["#", "Title", "Narration", "Speaker", "Sample", "Preview", "Audio"])
        hh = self.assign_table.horizontalHeader()
        for col, width in ((0, 44), (1, 170), (3, 180), (4, 64), (5, 84), (6, 128)):
            hh.setSectionResizeMode(col, QHeaderView.Interactive)
            self.assign_table.setColumnWidth(col, width)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.assign_table.verticalHeader().setDefaultSectionSize(40)
        self.assign_table.verticalHeader().setVisible(False)
        self.assign_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.assign_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assign_table.cellClicked.connect(self._on_assign_row_clicked)
        ap.addWidget(self.assign_table, 1)
        self.tabs.addTab(assign_tab, "Speaker Assignment")
        self.splitter.addWidget(self.tabs)

        # ---- right: voice & audio panel
        self.splitter.addWidget(self._build_voice_panel())
        self.splitter.setSizes([230, 620, 380])
        layout.addWidget(self.splitter, 1)

        bottom = QFrame()
        bottom.setStyleSheet("background-color: #181820; border-radius: 6px; padding: 4px;")
        bb = QHBoxLayout(bottom)
        bb.setContentsMargins(12, 6, 12, 6)
        self.lbl_approved_count = QLabel("0 / 0 Scripts Approved")
        self.lbl_approved_count.setStyleSheet("color: #34d399; font-weight: bold;")
        bb.addWidget(self.lbl_approved_count)
        self.lbl_audio_count = QLabel("")
        self.lbl_audio_count.setStyleSheet("color: #93c5fd; font-weight: bold;")
        bb.addSpacing(16)
        bb.addWidget(self.lbl_audio_count)
        bb.addStretch()
        self.btn_approve_all_narrations = QPushButton("★ Approve All Narration Scripts")
        self.btn_approve_all_narrations.setObjectName("primaryBtn")
        self.btn_approve_all_narrations.clicked.connect(self._approve_all_narrations)
        bb.addWidget(self.btn_approve_all_narrations)
        layout.addWidget(bottom)

    def _build_voice_panel(self) -> QWidget:
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setSpacing(10)

        # 1. TTS model
        g = QGroupBox("TTS Model")
        f = QVBoxLayout(g)
        self.combo_engine = QComboBox()
        for e in engines():
            self.combo_engine.addItem(e.name, e.id)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        f.addWidget(self.combo_engine)
        row = QHBoxLayout()
        self.lbl_engine_status = QLabel("")
        self.lbl_engine_status.setWordWrap(True)
        row.addWidget(self.lbl_engine_status, 1)
        self.btn_engine_action = QPushButton("Load model")
        self.btn_engine_action.clicked.connect(self._on_engine_action)
        row.addWidget(self.btn_engine_action)
        f.addLayout(row)
        self.btn_manage_models = QPushButton("Manage Models…")
        self.btn_manage_models.setToolTip("Import your own downloaded TTS models (Piper voices, Kokoro-compatible "
                                          "ONNX builds), rename or remove them.")
        self.btn_manage_models.clicked.connect(self._open_model_manager)
        f.addWidget(self.btn_manage_models)
        self.lbl_engine_warning = QLabel("")
        self.lbl_engine_warning.setWordWrap(True)
        self.lbl_engine_warning.setStyleSheet("color: #fbbf24;")
        self.lbl_engine_warning.setVisible(False)
        f.addWidget(self.lbl_engine_warning)
        self.lbl_engine_info = QLabel("")
        self.lbl_engine_info.setWordWrap(True)
        self.lbl_engine_info.setStyleSheet("color: #6b7280; font-size: 11px;")
        f.addWidget(self.lbl_engine_info)
        pl.addWidget(g)

        # 2. Speaker mode
        g = QGroupBox("Speaker Mode")
        f = QVBoxLayout(g)
        self.radio_single = QRadioButton("One speaker for all slides")
        self.radio_per_slide = QRadioButton("Different speaker per slide")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_single)
        self.mode_group.addButton(self.radio_per_slide)
        self.radio_single.setChecked(True)
        self.radio_single.toggled.connect(self._on_mode_changed)
        f.addWidget(self.radio_single)
        f.addWidget(self.radio_per_slide)
        pl.addWidget(g)

        # 3. Speaker selection
        g = QGroupBox("Speaker")
        f = QVBoxLayout(g)
        self.lbl_speaker_scope = QLabel("Applies to: all slides")
        self.lbl_speaker_scope.setStyleSheet("color: #fbbf24;")
        f.addWidget(self.lbl_speaker_scope)
        self.combo_speaker = QComboBox()
        self.combo_speaker.setAccessibleName("Speaker")
        self.combo_speaker.currentIndexChanged.connect(self._on_speaker_changed)
        f.addWidget(self.combo_speaker)
        self.lbl_speaker_info = QLabel("")
        self.lbl_speaker_info.setWordWrap(True)
        self.lbl_speaker_info.setStyleSheet("color: #9ca3af;")
        f.addWidget(self.lbl_speaker_info)
        self.btn_apply_all = QPushButton("Use this speaker for all slides")
        self.btn_apply_all.setToolTip("Switches back to single-speaker mode with this voice.")
        self.btn_apply_all.clicked.connect(self._apply_speaker_to_all)
        f.addWidget(self.btn_apply_all)
        pl.addWidget(g)

        # 4. Listen: sample + narration preview
        g = QGroupBox("Listen")
        f = QVBoxLayout(g)
        row = QHBoxLayout()
        self.btn_sample = QPushButton("▶ Play Sample")
        self.btn_sample.setToolTip("Speak a predefined sentence with the selected speaker.")
        self.btn_sample.clicked.connect(lambda: self._play_sample())
        self.btn_preview = QPushButton("▶ Preview Narration")
        self.btn_preview.setToolTip("Read this slide's current narration text (including unsaved edits).")
        self.btn_preview.clicked.connect(lambda: self._preview_narration())
        row.addWidget(self.btn_sample); row.addWidget(self.btn_preview)
        f.addLayout(row)
        row = QHBoxLayout()
        self.btn_play_audio = QPushButton("▶ Play Slide Audio")
        self.btn_play_audio.setToolTip("Play the generated audio file for this slide.")
        self.btn_play_audio.clicked.connect(self._play_slide_audio)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_stop.clicked.connect(self.player.stop)
        row.addWidget(self.btn_play_audio); row.addWidget(self.btn_stop)
        f.addLayout(row)
        self.lbl_play_status = QLabel("")
        self.lbl_play_status.setStyleSheet("color: #34d399;")
        self.lbl_play_status.setWordWrap(True)
        f.addWidget(self.lbl_play_status)
        pl.addWidget(g)

        # 5. Speech controls (capability-driven)
        g = QGroupBox("Speech")
        self.speech_form = QFormLayout(g)
        self.combo_style = QComboBox()
        self.combo_style.setAccessibleName("Delivery style")
        for st in emotion.styles():
            self.combo_style.addItem(st.label, st.key)
            self.combo_style.setItemData(self.combo_style.count() - 1, st.description, Qt.ToolTipRole)
        self.combo_style.currentIndexChanged.connect(self._on_style_changed)
        self.speech_form.addRow("Delivery style:", self.combo_style)
        self.lbl_style_support = QLabel("")
        self.lbl_style_support.setWordWrap(True)
        self.lbl_style_support.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.speech_form.addRow(self.lbl_style_support)
        self.spin_speed = self._dspin(0.5, 2.0, 0.05, 1.0, "×")
        self.spin_sentence = self._dspin(0.0, 2.0, 0.05, 0.3, " s")
        self.spin_clause = self._dspin(0.0, 1.0, 0.05, 0.1, " s")
        for s in (self.spin_speed, self.spin_sentence, self.spin_clause):
            s.valueChanged.connect(self._on_speech_changed)
        self.speech_form.addRow("Speed:", self.spin_speed)
        self.speech_form.addRow("Pause after sentence:", self.spin_sentence)
        self.speech_form.addRow("Pause after comma:", self.spin_clause)
        self.btn_pron = QPushButton("Pronunciations…")
        self.btn_pron.clicked.connect(self._edit_pronunciations)
        self.speech_form.addRow("Pronunciation:", self.btn_pron)
        self.lbl_caps = QLabel("")
        self.lbl_caps.setWordWrap(True)
        self.lbl_caps.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.speech_form.addRow(self.lbl_caps)
        pl.addWidget(g)

        # 6. Audio generation
        g = QGroupBox("Narration Audio")
        f = QVBoxLayout(g)
        self.lbl_slide_audio = QLabel("")
        self.lbl_slide_audio.setWordWrap(True)
        f.addWidget(self.lbl_slide_audio)
        self.btn_gen_this = QPushButton("Generate this slide")
        self.btn_gen_selected = QPushButton("Generate selected (0)")
        self.btn_gen_pending = QPushButton("Generate missing && outdated")
        self.btn_gen_all = QPushButton("Regenerate all slides")
        self.btn_gen_this.clicked.connect(lambda: self._generate("this"))
        self.btn_gen_selected.clicked.connect(lambda: self._generate("selected"))
        self.btn_gen_pending.clicked.connect(lambda: self._generate("pending"))
        self.btn_gen_all.clicked.connect(lambda: self._generate("all"))
        for b in (self.btn_gen_this, self.btn_gen_selected, self.btn_gen_pending, self.btn_gen_all):
            f.addWidget(b)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        self.lbl_task = QLabel(""); self.lbl_task.setStyleSheet("color: #9ca3af;"); self.lbl_task.setWordWrap(True)
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(lambda: self.worker and self.worker.cancel())
        f.addWidget(self.progress); f.addWidget(self.lbl_task); f.addWidget(self.btn_cancel)
        note = QLabel("Existing audio is kept until you regenerate it. Edited text or a changed voice marks it "
                      "“outdated”.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 11px;")
        f.addWidget(note)
        pl.addWidget(g)
        pl.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(340)
        return scroll

    @staticmethod
    def _dspin(lo, hi, step, val, suffix):
        s = QDoubleSpinBox()
        s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(2); s.setValue(val); s.setSuffix(suffix)
        return s

    # ================================================================== project
    def load_project(self, project: Project) -> None:
        self.project = project
        self.lbl_title.setText(f"Narration Studio — {project.project_name}")
        cfg = project.settings
        self._busy_ui = True
        self._rebuild_engine_combo()
        self._set_engine_warning("")
        if cfg.tts_engine:
            eng = get_engine(cfg.tts_engine)
            if not has_engine(cfg.tts_engine) or (eng.id != registry.DEFAULT_ENGINE and not eng.is_installed()[0]):
                self._fallback_from_missing_engine(cfg.tts_engine)
        eng = get_engine(cfg.tts_engine)
        cfg.tts_engine = eng.id
        self.combo_engine.setCurrentIndex(max(self.combo_engine.findData(eng.id), 0))
        self.radio_per_slide.setChecked(cfg.speaker_mode == "per_slide")
        self.radio_single.setChecked(cfg.speaker_mode != "per_slide")
        self.spin_speed.setValue(cfg.speech_speed)
        self.spin_sentence.setValue(cfg.sentence_pause)
        self.spin_clause.setValue(cfg.clause_pause)
        self.combo_style.setCurrentIndex(max(self.combo_style.findData(emotion.get(cfg.emotion).key), 0))
        self._busy_ui = False
        self._refresh_engine_panel()
        self._refresh_list()
        self._update_gate_status()

    # ================================================================== list / editor
    def _list_text(self, n: SlideNarration) -> str:
        slide = self.project.get_slide_by_id(n.slide_id)
        title = slide.title if slide else f"Slide {n.slide_number}"
        state = AUDIO_ICON.get(tts.audio_state(self.project, n), "")
        return f"#{n.slide_number} {title} [{n.status.value}]  {state}"

    def _refresh_list(self) -> None:
        if not self.project:
            return
        cur = self.current_slide_id
        self.script_list.blockSignals(True)
        self.script_list.clear()
        for n in self.project.narrations:
            item = QListWidgetItem(self._list_text(n))
            item.setData(Qt.UserRole, n.slide_id)
            self.script_list.addItem(item)
        self.script_list.blockSignals(False)
        row = 0
        for i in range(self.script_list.count()):
            if self.script_list.item(i).data(Qt.UserRole) == cur:
                row = i
        if self.script_list.count():
            self.script_list.setCurrentRow(row)
            self._on_script_selected(self.script_list.currentItem(), None)
        self._refresh_assignment_table()
        self._update_audio_counts()

    def _refresh_list_item(self, slide_id: str) -> None:
        for i in range(self.script_list.count()):
            it = self.script_list.item(i)
            if it.data(Qt.UserRole) == slide_id:
                it.setText(self._list_text(self.project.get_narration_by_id(slide_id)))

    def _on_script_selected(self, current: Optional[QListWidgetItem], _) -> None:
        if not current or not self.project:
            return
        slide_id = current.data(Qt.UserRole)
        self.current_slide_id = slide_id
        narration = self.project.get_narration_by_id(slide_id)
        slide = self.project.get_slide_by_id(slide_id)
        if not narration or not slide:
            return
        self._is_populating = True
        self.lbl_editor_title.setText(f"Slide #{slide.slide_number}: {slide.title}")
        self.script_status_badge.set_status(narration.status.value)
        self.script_edit.setText(narration.script)
        self.lbl_words.setText(f"{narration.word_count} words")
        self.lbl_duration.setText(f"Est: {narration.estimated_duration:.1f}s")
        if slide.image_path and self.project.project_dir:
            img_path = Path(self.project.project_dir) / slide.image_path
            if img_path.is_file():
                pix = QPixmap(str(img_path))
                self.preview_label.setPixmap(pix.scaled(560, 315, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.combo_slide_style.setCurrentIndex(max(self.combo_slide_style.findData(narration.emotion), 0))
        self._is_populating = False
        self._sync_speaker_combo()
        self._update_slide_audio_label()

    def _on_text_changed(self) -> None:
        if self._is_populating or not self.project or not self.current_slide_id:
            return
        nm = NarrationManager(self.project)
        narration = nm.update_script(self.current_slide_id, self.script_edit.toPlainText())
        self.lbl_words.setText(f"{narration.word_count} words")
        self.lbl_duration.setText(f"Est: {narration.estimated_duration:.1f}s")
        self.script_status_badge.set_status(narration.status.value)
        self._update_gate_status()
        self._update_slide_audio_label()
        self._refresh_list_item(self.current_slide_id)
        self._save_project()

    def _approve_current_script(self) -> None:
        if not self.project or not self.current_slide_id:
            return
        narration = NarrationManager(self.project).approve_narration(self.current_slide_id)
        self.script_status_badge.set_status(narration.status.value)
        self._refresh_list_item(self.current_slide_id)
        self._save_project()
        self._update_gate_status()

    def _approve_all_narrations(self) -> None:
        if not self.project:
            return
        WorkflowManager(self.project).approve_all_narrations()
        self._save_project()
        self._update_gate_status()
        if self.current_slide_id:
            n = self.project.get_narration_by_id(self.current_slide_id)
            if n:
                self.script_status_badge.set_status(n.status.value)
        for n in self.project.narrations:
            self._refresh_list_item(n.slide_id)
        self.narration_approved.emit()

    def _update_gate_status(self) -> None:
        if not self.project:
            return
        total = len(self.project.narrations)
        approved = sum(1 for n in self.project.narrations if n.status == NarrationStatus.APPROVED)
        self.lbl_approved_count.setText(f"{approved} / {total} Scripts Approved")
        if self.project.narration_approved:
            self.lbl_gate_info.setText("Status: All narration approved ✓")
            self.lbl_gate_info.setStyleSheet("color: #10b981; font-weight: bold;")
            self.overall_badge.set_status("narration_approved")
            self.btn_approve_all_narrations.setEnabled(False)
        else:
            self.lbl_gate_info.setText("Status: In review (optional)")
            self.lbl_gate_info.setStyleSheet("color: #fbbf24; font-weight: bold;")
            self.overall_badge.set_status("narration_review")
            self.btn_approve_all_narrations.setEnabled(True)

    # ================================================================== engine
    def current_engine(self):
        return get_engine(self.combo_engine.currentData())

    def _refresh_engine_panel(self) -> None:
        eng = self.current_engine()
        st = eng.status()
        colors = {tb.READY: "#10b981", tb.INSTALLED: "#93c5fd", tb.LOADING: "#fbbf24",
                  tb.NOT_INSTALLED: "#ef4444", tb.ERROR: "#ef4444", tb.UNAVAILABLE: "#ef4444"}
        label = tb.UNAVAILABLE if st.state == tb.NOT_INSTALLED and not eng.downloadable else st.state
        self.lbl_engine_status.setText(f"Status: {label}" + (f" — {st.message}" if st.message else ""))
        self.lbl_engine_status.setStyleSheet(f"color: {colors.get(st.state, '#9ca3af')}; font-weight: bold;")
        can_download = st.state == tb.NOT_INSTALLED and eng.downloadable
        self.btn_engine_action.setText("Download model" if can_download else "Load model")
        self.btn_engine_action.setVisible(st.state in (tb.INSTALLED, tb.ERROR) or can_download)
        self.lbl_engine_info.setText(f"{eng.description}\nLicence: {eng.license_summary}")
        caps = eng.capabilities
        for w in (self.spin_sentence, self.spin_clause):
            w.setVisible(caps.pauses)
            self.speech_form.labelForField(w).setVisible(caps.pauses)
        self.spin_speed.setRange(*caps.speed_range)
        unsupported = [n for n, ok in (("pause control", caps.pauses), ("emphasis", caps.emphasis)) if not ok]
        self.lbl_caps.setText("Not supported by this model: " + ", ".join(unsupported) if unsupported else "")
        self.lbl_style_support.setText(emotion.describe_support(eng))
        self._refresh_speakers()

    def _on_engine_changed(self) -> None:
        if self._busy_ui:
            return
        if not self.project:
            self._refresh_engine_panel()
            return
        eng = self.current_engine()
        cfg = self.project.settings
        if cfg.tts_engine != eng.id:
            self._set_engine_warning("")
            cfg.tts_engine = eng.id
            cfg.voice_id = eng.default_speaker()
            for n in self.project.narrations:       # per-slide voices belong to the old model
                n.speaker = None
            self._save_project()
        self._refresh_engine_panel()
        self._refresh_list()

    # ---- custom models
    def _rebuild_engine_combo(self) -> None:
        cur = self.project.settings.tts_engine if self.project else self.combo_engine.currentData()
        was = self._busy_ui
        self._busy_ui = True
        self.combo_engine.clear()
        for e in engines():
            self.combo_engine.addItem(e.name + ("  · custom" if getattr(e, "custom", False) else ""), e.id)
        self.combo_engine.setCurrentIndex(max(self.combo_engine.findData(cur), 0))
        self._busy_ui = was

    def _set_engine_warning(self, text: str) -> None:
        self.lbl_engine_warning.setText(text)
        self.lbl_engine_warning.setVisible(bool(text))

    def _fallback_from_missing_engine(self, missing_id: str) -> None:
        """The project's model was removed: switch to the default model and its default voice."""
        cfg = self.project.settings
        eng = get_engine(None)
        cfg.tts_engine, cfg.voice_id = eng.id, eng.default_speaker()
        for n in self.project.narrations:
            n.speaker = None
        self._save_project()
        self._set_engine_warning(f"⚠ The TTS model '{missing_id}' used by this project is no longer available, "
                                 f"so {eng.name} is used instead. Existing audio is kept but marked outdated.")

    def _open_model_manager(self) -> None:
        from src.frontend.model_manager import ModelManagerDialog
        dlg = ModelManagerDialog(in_use=lambda: self.project.settings.tts_engine if self.project else "",
                                 run_task=lambda fn, done: self._run("import", fn, done), parent=self)
        dlg.models_changed.connect(self._on_models_changed)
        dlg.use_model.connect(self.select_engine)
        dlg.exec()

    def _on_models_changed(self) -> None:
        registry.reload()                     # cheap; keeps this correct whoever changed the library
        if self.project:
            eng = get_engine(self.project.settings.tts_engine)
            if not has_engine(self.project.settings.tts_engine) or (eng.id != registry.DEFAULT_ENGINE and not eng.is_installed()[0]):
                self._fallback_from_missing_engine(self.project.settings.tts_engine)
        self._rebuild_engine_combo()
        self._refresh_engine_panel()
        self._refresh_list()

    def select_engine(self, engine_id: str) -> None:
        i = self.combo_engine.findData(engine_id)
        if i >= 0:
            self.combo_engine.setCurrentIndex(i)      # triggers _on_engine_changed

    def _on_engine_action(self) -> None:
        eng = self.current_engine()
        if eng.status().state == tb.NOT_INSTALLED and eng.downloadable:
            sz = getattr(getattr(eng, "spec", None), "approx_size_str", "~350 MB")
            ans = QMessageBox.question(self, "Download model",
                                       f"Download {eng.name} model files ({sz}) once? After that, narration "
                                       "works offline.", QMessageBox.Yes | QMessageBox.No)
            if ans == QMessageBox.Yes:
                self._run("download", lambda p, c: eng.download(p, c), lambda _: self._refresh_engine_panel())
        else:
            self._run("load", lambda p, c: (p(10, f"Loading {eng.name}…"), eng.load()),
                      lambda _: self._refresh_engine_panel())
            self._refresh_engine_panel()

    # ================================================================== speakers
    def _speaker_list(self) -> List[tb.Speaker]:
        return self.current_engine().speakers()

    def _refresh_speakers(self) -> None:
        self._busy_ui, prev = True, self._busy_ui
        self.combo_speaker.clear()
        for s in self._speaker_list():
            self.combo_speaker.addItem(s.label, s.id)
        self._busy_ui = prev
        self._sync_speaker_combo()
        self._refresh_assignment_table()

    def _target_speaker(self) -> str:
        """Speaker the combo currently edits (global, or current slide in per-slide mode)."""
        if not self.project:
            return ""
        n = self.project.get_narration_by_id(self.current_slide_id) if self.current_slide_id else None
        if self.project.settings.speaker_mode == "per_slide" and n:
            return tts.slide_speaker(self.project, n)
        return self.project.settings.voice_id

    def _ensure_speaker_in_combo(self, sid: str) -> int:
        i = self.combo_speaker.findData(sid)
        if i < 0 and sid:
            sp = self.current_engine().find_speaker(sid)
            if sp:
                self.combo_speaker.addItem(sp.label, sp.id)
                i = self.combo_speaker.count() - 1
        return i

    def _sync_speaker_combo(self) -> None:
        if not self.project:
            return
        per = self.project.settings.speaker_mode == "per_slide"
        n = self.project.get_narration_by_id(self.current_slide_id) if self.current_slide_id else None
        self.lbl_speaker_scope.setText(f"Applies to: slide #{n.slide_number} only" if per and n
                                       else "Applies to: all slides")
        self.btn_apply_all.setVisible(per)
        self.lbl_slide_speaker.setText(f"🎙 {tts.slide_speaker(self.project, n)}" if n else "")
        self._busy_ui, prev = True, self._busy_ui
        i = self._ensure_speaker_in_combo(self._target_speaker())
        if i >= 0:
            self.combo_speaker.setCurrentIndex(i)
        self._busy_ui = prev
        self._show_speaker_info()

    def _show_speaker_info(self) -> None:
        sp = self.current_engine().find_speaker(self.combo_speaker.currentData() or "")
        if sp:
            bits = [b for b in (sp.language, sp.gender, sp.style) if b]
            self.lbl_speaker_info.setText(" · ".join(bits) + ("  (recommended)" if sp.recommended else ""))
        else:
            self.lbl_speaker_info.setText("No speakers available — install or load the model.")

    def _on_speaker_changed(self) -> None:
        self._show_speaker_info()
        if self._busy_ui or not self.project:
            return
        sid = self.combo_speaker.currentData()
        if not sid:
            return
        cfg = self.project.settings
        if cfg.speaker_mode == "per_slide" and self.current_slide_id:
            self.project.get_narration_by_id(self.current_slide_id).speaker = sid
            self._refresh_list_item(self.current_slide_id)
        else:
            cfg.voice_id = sid
            for n in self.project.narrations:
                self._refresh_list_item(n.slide_id)
        self.lbl_slide_speaker.setText(f"🎙 {self._target_speaker()}")
        self._save_project()
        self._update_slide_audio_label()
        self._refresh_assignment_table()
        self._update_audio_counts()

    def _on_mode_changed(self) -> None:
        if self._busy_ui or not self.project:
            return
        per = self.radio_per_slide.isChecked()
        self.project.settings.speaker_mode = "per_slide" if per else "single"
        if per:
            for n in self.project.narrations:          # start from the global voice
                n.speaker = n.speaker or self.project.settings.voice_id
            self.tabs.setCurrentIndex(1)
        self._save_project()
        self._sync_speaker_combo()
        self._refresh_assignment_table()
        for n in self.project.narrations:
            self._refresh_list_item(n.slide_id)
        self._update_audio_counts()

    def _apply_speaker_to_all(self) -> None:
        if not self.project:
            return
        sid = self.combo_speaker.currentData()
        self.project.settings.voice_id = sid
        for n in self.project.narrations:
            n.speaker = None
        self.radio_single.setChecked(True)        # triggers _on_mode_changed -> save + refresh

    # ================================================================== assignment table
    def _refresh_assignment_table(self) -> None:
        if not self.project:
            return
        per = self.project.settings.speaker_mode == "per_slide"
        self.tabs.setTabEnabled(1, per)
        self.lbl_assign_hint.setText(
            "Choose a speaker for each slide. Changing one slide never affects the others. "
            "Use 'Use this speaker for all slides' to go back to one speaker." if per else
            "Switch Speaker Mode to 'Different speaker per slide' to assign voices individually.")
        speakers = self._speaker_list()
        t = self.assign_table
        t.setRowCount(len(self.project.narrations))
        for r, n in enumerate(self.project.narrations):
            slide = self.project.get_slide_by_id(n.slide_id)
            t.setItem(r, 0, QTableWidgetItem(str(n.slide_number)))
            t.setItem(r, 1, QTableWidgetItem(slide.title if slide else ""))
            snippet = QTableWidgetItem(n.script[:90] + ("…" if len(n.script) > 90 else ""))
            snippet.setToolTip(n.script)
            t.setItem(r, 2, snippet)
            combo = QComboBox()
            for s in speakers:
                combo.addItem(self._short_label(s), s.id)
                combo.setItemData(combo.count() - 1, s.label, Qt.ToolTipRole)
            cur = tts.slide_speaker(self.project, n)
            if combo.findData(cur) < 0:
                sp = self.current_engine().find_speaker(cur)
                if sp:
                    combo.addItem(self._short_label(sp), sp.id)
            combo.setCurrentIndex(max(combo.findData(cur), 0))
            combo.setEnabled(per)
            combo.setStyleSheet(self.CELL_STYLE)
            combo.currentIndexChanged.connect(lambda _i, sid=n.slide_id, c=combo: self._set_slide_speaker(sid, c.currentData()))
            t.setCellWidget(r, 3, combo)
            b1 = QPushButton("▶"); b1.setToolTip("Play a sample of this slide's speaker")
            b1.clicked.connect(lambda _=False, sid=n.slide_id: self._play_sample(slide_id=sid))
            b2 = QPushButton("▶ Read"); b2.setToolTip("Preview this slide's narration")
            b2.clicked.connect(lambda _=False, sid=n.slide_id: self._preview_narration(slide_id=sid))
            for b in (b1, b2):
                b.setStyleSheet(self.CELL_STYLE)
            t.setCellWidget(r, 4, b1)
            t.setCellWidget(r, 5, b2)
            b3 = QPushButton(AUDIO_ICON.get(tts.audio_state(self.project, n), "") + "  ⟳")
            b3.setToolTip("Generate / regenerate this slide's audio")
            b3.clicked.connect(lambda _=False, sid=n.slide_id: self._generate("ids", [sid]))
            b3.setStyleSheet(self.CELL_STYLE)
            t.setCellWidget(r, 6, b3)
        t.viewport().update()
        t.updateGeometries()

    @staticmethod
    def _short_label(sp: tb.Speaker) -> str:
        lang = sp.language.replace("English ", "").strip("()") if sp.is_english else sp.language
        sex = {"female voice": "F", "male voice": "M"}.get(sp.gender, "")
        star = "★ " if sp.recommended else ""
        return f"{star}{sp.name.split(' (')[0]} · {lang}{' ' + sex if sex else ''}"

    def _set_slide_speaker(self, slide_id: str, speaker: str) -> None:
        n = self.project.get_narration_by_id(slide_id)
        if not n or not speaker or n.speaker == speaker:
            return
        n.speaker = speaker
        self._save_project()
        self._refresh_list_item(slide_id)
        if slide_id == self.current_slide_id:
            self._sync_speaker_combo()
            self._update_slide_audio_label()
        self._refresh_assignment_row_audio(slide_id)
        self._update_audio_counts()

    def _refresh_assignment_row_audio(self, slide_id: str) -> None:
        for r, n in enumerate(self.project.narrations):
            if n.slide_id == slide_id:
                w = self.assign_table.cellWidget(r, 6)
                if w:
                    w.setText(AUDIO_ICON.get(tts.audio_state(self.project, n), "") + "  ⟳")

    def _on_assign_row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < self.script_list.count():
            self.script_list.setCurrentRow(row)

    # ================================================================== speech settings
    def _on_speech_changed(self) -> None:
        if self._busy_ui or not self.project:
            return
        cfg = self.project.settings
        cfg.speech_speed = self.spin_speed.value()
        cfg.sentence_pause = self.spin_sentence.value()
        cfg.clause_pause = self.spin_clause.value()
        self._save_project()
        self._update_slide_audio_label()
        self._update_audio_counts()

    def _on_style_changed(self) -> None:
        if self._busy_ui or not self.project:
            return
        self.project.settings.emotion = self.combo_style.currentData()
        self._save_project()
        self._update_slide_audio_label()
        self._update_audio_counts()

    def _on_slide_style_changed(self) -> None:
        if self._is_populating or not self.project or not self.current_slide_id:
            return
        n = self.project.get_narration_by_id(self.current_slide_id)
        if n:
            n.emotion = self.combo_slide_style.currentData()
            self._save_project()
            self._update_slide_audio_label()
            self._update_audio_counts()

    def _edit_pronunciations(self) -> None:
        if not self.project:
            return
        dlg = PronunciationDialog(self.project.settings.pronunciations, self)
        if dlg.exec() == QDialog.Accepted:
            self.project.settings.pronunciations = dlg.mapping()
            self._save_project()
            self._refresh_list()

    # ================================================================== listen
    def _set_play_status(self, text: str) -> None:
        self.lbl_play_status.setText(text)

    def _play_sample(self, slide_id: Optional[str] = None) -> None:
        if not self.project:
            return
        n = self.project.get_narration_by_id(slide_id) if slide_id else None
        speaker = tts.slide_speaker(self.project, n) if n else self.combo_speaker.currentData()
        engine = self.current_engine().id
        self._run("sample", lambda p, c: (p(20, f"Synthesizing sample for {speaker}…"),
                                           tts.sample_audio(self.project, speaker, engine))[1],
                  lambda path: self.player.play(path, f"sample · {speaker}"))

    def _preview_narration(self, slide_id: Optional[str] = None) -> None:
        if not self.project:
            return
        sid = slide_id or self.current_slide_id
        n = self.project.get_narration_by_id(sid) if sid else None
        if not n:
            return
        text = self.script_edit.toPlainText() if sid == self.current_slide_id else n.script
        if not text.strip():
            QMessageBox.information(self, "Preview", "This slide has no narration text.")
            return
        speaker = (self.combo_speaker.currentData() if sid == self.current_slide_id
                   else tts.slide_speaker(self.project, n))
        style = tts.slide_emotion(self.project, n)
        label = emotion.get(style).label
        self._run("preview", lambda p, c: (p(20, f"Reading slide {n.slide_number} with {speaker} ({label})…"),
                                            tts.preview_audio(self.project, text, speaker, style))[1],
                  lambda path: self.player.play(path, f"slide {n.slide_number} · {speaker} · {label}"))

    def _play_slide_audio(self) -> None:
        n = self.project.get_narration_by_id(self.current_slide_id) if self.project and self.current_slide_id else None
        path = tts.slide_audio_path(self.project, n) if n else None
        if path and path.is_file():
            self.player.play(path, f"slide {n.slide_number} audio")
        else:
            QMessageBox.information(self, "No audio", "This slide has no generated audio yet.")

    # ================================================================== generate
    def _selected_narrations(self) -> List[SlideNarration]:
        ids = {it.data(Qt.UserRole) for it in self.script_list.selectedItems()}
        return [n for n in self.project.narrations if n.slide_id in ids]

    def narrations_for(self, scope: str, ids: Optional[List[str]] = None) -> List[SlideNarration]:
        p = self.project
        if scope == "this":
            n = p.get_narration_by_id(self.current_slide_id)
            return [n] if n else []
        if scope == "selected":
            return self._selected_narrations()
        if scope == "ids":
            return [n for n in p.narrations if n.slide_id in set(ids or [])]
        if scope == "pending":
            return [n for n in p.narrations if tts.audio_state(p, n) != tts.READY and n.script.strip()]
        return [n for n in p.narrations if n.script.strip()]

    def _generate(self, scope: str, ids: Optional[List[str]] = None) -> None:
        if not self.project:
            return
        items = self.narrations_for(scope, ids)
        if not items:
            QMessageBox.information(self, "Nothing to generate", "No slides match (all audio may already be up to date).")
            return
        if scope == "all" and len(items) > 3:
            ans = QMessageBox.question(self, "Regenerate all",
                                       f"Regenerate audio for {len(items)} slides? Existing audio will be replaced.",
                                       QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        proj = self.project
        self._run("generate", lambda p, c: tts.generate_many(proj, items, p, c), self._after_generate)

    def _after_generate(self, done) -> None:
        self._save_project()
        self._refresh_list()
        self.lbl_task.setText(f"✓ Generated audio for {len(done)} slide(s).")

    def _update_slide_audio_label(self) -> None:
        if not self.project or not self.current_slide_id:
            return
        n = self.project.get_narration_by_id(self.current_slide_id)
        st = tts.audio_state(self.project, n)
        dur = f" · {n.audio_duration:.1f}s" if n.audio_duration and st in (tts.READY, tts.OUTDATED) else ""
        self.lbl_slide_audio.setText(f"Slide #{n.slide_number}: {AUDIO_ICON.get(st, st)}{dur}")
        self.btn_play_audio.setEnabled(st in (tts.READY, tts.OUTDATED))
        self._refresh_assignment_row_audio(n.slide_id)

    def _update_audio_counts(self) -> None:
        if not self.project:
            return
        states = [tts.audio_state(self.project, n) for n in self.project.narrations]
        self.lbl_audio_count.setText(f"Audio: {states.count(tts.READY)} ready · {states.count(tts.OUTDATED)} outdated"
                                     f" · {states.count(tts.NONE) + states.count(tts.MISSING)} missing")
        self._update_audio_buttons()

    def _update_audio_buttons(self) -> None:
        n = len(self.script_list.selectedItems())
        self.btn_gen_selected.setText(f"Generate selected ({n})")
        busy = self.worker is not None and self.worker.isRunning()
        for b in (self.btn_gen_this, self.btn_gen_selected, self.btn_gen_pending, self.btn_gen_all,
                  self.btn_sample, self.btn_preview, self.btn_engine_action):
            b.setEnabled(not busy)
        self.btn_gen_selected.setEnabled(not busy and n > 0)

    # ================================================================== background tasks
    def _run(self, kind: str, fn: Callable, on_done: Callable[[object], None]) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Please wait for the current task to finish (or cancel it).")
            return
        self.player.stop()
        self.worker = TTSTaskWorker(kind, fn)
        self.worker.progress.connect(lambda p, m: (self.progress.setValue(p), self.lbl_task.setText(m)))
        self.worker.finished_ok.connect(lambda k, r: self._task_done(on_done, r))
        self.worker.failed.connect(self._task_failed)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.btn_cancel.setVisible(kind in ("generate", "download"))
        if get_engine(self.combo_engine.currentData()).status().state != tb.READY:
            self.lbl_task.setText("Loading TTS model (first use takes a few seconds)…")
        self.worker.start()
        self._update_audio_buttons()
        self._refresh_engine_panel_status_only()

    def _refresh_engine_panel_status_only(self) -> None:
        st = self.current_engine().status()
        self.lbl_engine_status.setText(f"Status: {st.state}" + (f" — {st.message}" if st.message else ""))

    def _finish_task(self) -> None:
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        if self.worker:
            self.worker.wait(3000)
        self.worker = None
        self._update_audio_buttons()
        self._refresh_engine_panel_status_only()

    def _task_done(self, on_done: Callable, result) -> None:
        self._finish_task()
        if not self.lbl_task.text().startswith("✓"):
            self.lbl_task.setText("")
        on_done(result)
        self._refresh_engine_panel_status_only()

    def _task_failed(self, kind: str, msg: str) -> None:
        self._finish_task()
        self.lbl_task.setText(f"✗ {msg}")
        if kind == "generate":
            self._save_project()
            self._refresh_list()
        QMessageBox.warning(self, "TTS", f"{kind.capitalize()} failed:\n{msg}")

    def _save_project(self) -> None:
        if self.project:
            ProjectManager(self.project.project_dir).save_project(self.project)
