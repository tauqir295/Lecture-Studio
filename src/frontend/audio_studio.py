"""Audio Studio: standalone expressive narration (no slides or video project needed)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.backend.audio import studio as st
from src.backend.audio import tag_registry
from src.backend.audio.script import known_tags
from src.backend.tts import base as tb
from src.backend.tts import emotion, registry
from src.backend.workers.tts_worker import TTSTaskWorker
from src.frontend.widgets.audio_player import AudioPlayer

EXAMPLE = ("[storytelling] It was late at night when the build finally finished.\n\n"
           "[excited] Every test passed! [satisfied] The team could finally rest.\n\n"
           "[whispering] But somewhere, a single warning remained. [pause 1s] [hopeful] Tomorrow, they would fix it.")
COLORS = {
    "neutral": "#64748b", "happy": "#facc15", "excited": "#f97316", "enthusiastic": "#fb923c",
    "sad": "#60a5fa", "angry": "#ef4444", "fearful": "#a78bfa", "whispering": "#94a3b8",
    "whispers": "#94a3b8", "calm": "#34d399", "serious": "#cbd5e1", "storytelling": "#c084fc",
    "dramatic": "#f43f5e", "hopeful": "#86efac", "satisfied": "#2dd4bf", "friendly": "#fde047",
    "inspirational": "#38bdf8",
    # Additional exact emotions
    "amazed": "#38bdf8", "sarcastic": "#a855f7", "curious": "#06b6d4", "bored": "#78716c",
    "tired": "#9ca3af", "scornful": "#e11d48", "panicked": "#f43f5e", "mischievously": "#ec4899",
    "empathetic": "#10b981", "reluctantly": "#d97706", "crying": "#3b82f6", "trembling": "#8b5cf6",
    # Delivery styles
    "shouting": "#dc2626", "deep and loud shouting": "#991b1b", "asmr": "#67e8f9",
    "very slowly": "#64748b", "very fast": "#f59e0b", "like dracula": "#7c3aed",
    # Nonverbal sounds
    "gasp": "#f97316", "sighing": "#6b7280", "clears throat": "#eab308", "giggles": "#f472b6",
    "laughing": "#fbbf24", "cough": "#d97706", "snorts": "#a1a1aa",
}


class WaveformView(QWidget):
    """Waveform of the assembled narration with coloured segment regions; click selects a segment."""
    segment_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.peaks = None
        self.timeline: List[st.TimelineItem] = []
        self.total = 0.0
        self.selected: set = set()

    def set_data(self, peaks, timeline, total: float) -> None:
        self.peaks, self.timeline, self.total = peaks, timeline, total
        self.update()

    def clear(self) -> None:
        self.set_data(None, [], 0.0)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0f1115"))
        w, h = self.width(), self.height()
        if self.peaks is None or self.total <= 0:
            p.setPen(QColor("#6b7280"))
            p.drawText(self.rect(), Qt.AlignCenter, "Generate audio to see the waveform")
            return
        for it in self.timeline:
            x0, x1 = it.start / self.total * w, it.end / self.total * w
            c = QColor(COLORS.get(it.emotion, "#64748b"))
            c.setAlpha(90 if it.index in self.selected else 35)
            p.fillRect(QRectF(x0, 0, max(x1 - x0, 1), h), c)
        p.setPen(QColor("#e5e7eb"))
        n = len(self.peaks)
        mid = h / 2
        for i, v in enumerate(self.peaks):
            x = i / n * w
            p.drawLine(int(x), int(mid - v * mid * 0.95), int(x), int(mid + v * mid * 0.95))

    def mousePressEvent(self, ev) -> None:
        if self.total <= 0:
            return
        t = ev.position().x() / max(self.width(), 1) * self.total
        for it in self.timeline:
            if it.start <= t <= it.end:
                self.segment_clicked.emit(it.index)
                return


class AudioStudio(QWidget):
    def __init__(self, workspace_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.library = st.AudioLibrary(Path(workspace_root or Path.cwd()))
        self.doc: Optional[st.AudioDocument] = None
        self.worker: Optional[TTSTaskWorker] = None
        self._busy = False
        self.player = AudioPlayer(self)
        self.player.started.connect(lambda lbl: self.lbl_status.setText(f"▶ Playing {lbl}"))
        self.player.stopped.connect(lambda: self.lbl_status.setText(""))
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(400)
        self._parse_timer.timeout.connect(self._on_text_settled)
        self._build_ui()
        self._loaded = False              # documents are read when the page is first shown

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self.refresh_documents()

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        title = QLabel("Audio Studio — Expressive Narration")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #f3f4f6;")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(QLabel("Document:"))
        self.combo_doc = QComboBox()
        self.combo_doc.setMinimumWidth(220)
        self.combo_doc.currentIndexChanged.connect(self._on_doc_selected)
        top.addWidget(self.combo_doc)
        for text, fn in (("New", self.new_document), ("Rename…", self._rename_doc), ("Delete…", self._delete_doc),
                         ("Import Text…", self._import_text)):
            b = QPushButton(text); b.clicked.connect(fn); top.addWidget(b)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ---- left: text, segments, waveform
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        tags = QHBoxLayout()
        tags.addWidget(QLabel("Tag:"))
        self.combo_tag = QComboBox()
        self._refresh_tag_combo()
        tags.addWidget(self.combo_tag)
        b = QPushButton("Insert / wrap selection"); b.clicked.connect(self.insert_tag); tags.addWidget(b)
        b = QPushButton("Insert pause"); b.clicked.connect(lambda: self._insert_text("[pause 1s] ")); tags.addWidget(b)
        tags.addStretch()
        lv.addLayout(tags)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Type or paste narration. Add tags like [happy], [sad], [whispering], "
                                       "[pause 2s]. A tag applies until the next tag or the end of the paragraph.")
        self.editor.textChanged.connect(lambda: self._parse_timer.start())
        lv.addWidget(self.editor, 3)
        self.lbl_warnings = QLabel("")
        self.lbl_warnings.setWordWrap(True)
        self.lbl_warnings.setStyleSheet("color: #fbbf24;")
        lv.addWidget(self.lbl_warnings)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Style", "Text", "Length", "Audio"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for c in (0, 1, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_segment_selection)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.play_segment(r))
        lv.addWidget(self.table, 2)
        self.wave = WaveformView()
        self.wave.segment_clicked.connect(self._select_segment)
        lv.addWidget(self.wave)

        row = QHBoxLayout()
        self.btn_generate = QPushButton("Generate Audio"); self.btn_generate.setObjectName("primaryBtn")
        self.btn_generate.setToolTip("Synthesize segments that have no audio yet (edited sentences only).")
        self.btn_generate.clicked.connect(self.generate_missing)
        self.btn_regen = QPushButton("Regenerate Selected")
        self.btn_regen.setToolTip("Make a new take of the selected segments.")
        self.btn_regen.clicked.connect(self.regenerate_selected)
        self.btn_play_seg = QPushButton("▶ Selected"); self.btn_play_seg.clicked.connect(lambda: self.play_segment())
        self.btn_play_all = QPushButton("▶ Play All"); self.btn_play_all.clicked.connect(self.play_all)
        self.btn_stop = QPushButton("■ Stop"); self.btn_stop.clicked.connect(self.player.stop)
        for b in (self.btn_generate, self.btn_regen, self.btn_play_seg, self.btn_play_all, self.btn_stop):
            row.addWidget(b)
        lv.addLayout(row)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        self.lbl_status = QLabel(""); self.lbl_status.setStyleSheet("color: #34d399;")
        lv.addWidget(self.progress); lv.addWidget(self.lbl_status)
        split.addWidget(left)

        # ---- right: voice, speech, export
        panel = QWidget()
        pv = QVBoxLayout(panel)
        g = QGroupBox("Voice")
        f = QFormLayout(g)
        self.combo_engine = QComboBox(); self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        f.addRow("TTS model:", self.combo_engine)
        self.lbl_engine = QLabel(""); self.lbl_engine.setWordWrap(True)
        self.lbl_engine.setStyleSheet("color: #9ca3af; font-size: 11px;")
        f.addRow(self.lbl_engine)
        b = QPushButton("Manage Models…"); b.clicked.connect(self._manage_models); f.addRow(b)
        self.combo_speaker = QComboBox(); self.combo_speaker.currentIndexChanged.connect(self._on_settings_changed)
        f.addRow("Speaker:", self.combo_speaker)
        self.btn_sample = QPushButton("▶ Play Sample"); self.btn_sample.clicked.connect(self.play_sample)
        f.addRow(self.btn_sample)
        pv.addWidget(g)

        g = QGroupBox("Delivery")
        self.speech_form = QFormLayout(g)
        self.combo_default = QComboBox()
        for s in emotion.styles():
            self.combo_default.addItem(s.label, s.key)
        self.combo_default.currentIndexChanged.connect(self._on_settings_changed)
        self.speech_form.addRow("Untagged text:", self.combo_default)
        self.lbl_support = QLabel(""); self.lbl_support.setWordWrap(True)
        self.lbl_support.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.speech_form.addRow(self.lbl_support)
        self.spin_speed = self._dspin(0.5, 2.0, 0.05, 1.0, "×")
        self.spin_sent = self._dspin(0.0, 2.0, 0.05, 0.3, " s")
        self.spin_clause = self._dspin(0.0, 1.0, 0.05, 0.1, " s")
        self.spin_sgap = self._dspin(0.0, 3.0, 0.05, 0.35, " s")
        self.spin_pgap = self._dspin(0.0, 5.0, 0.1, 0.9, " s")
        self.speech_form.addRow("Speed:", self.spin_speed)
        self.speech_form.addRow("Pause after sentence:", self.spin_sent)
        self.speech_form.addRow("Pause after comma:", self.spin_clause)
        self.speech_form.addRow("Gap between sentences:", self.spin_sgap)
        self.speech_form.addRow("Gap between paragraphs:", self.spin_pgap)
        self.lbl_caps = QLabel(""); self.lbl_caps.setWordWrap(True)
        self.lbl_caps.setStyleSheet("color: #6b7280; font-size: 11px;")
        self.speech_form.addRow(self.lbl_caps)
        b = QPushButton("Pronunciations…"); b.clicked.connect(self._edit_pronunciations)
        self.speech_form.addRow(b)
        pv.addWidget(g)

        g = QGroupBox("Export")
        f = QFormLayout(g)
        self.combo_fmt = QComboBox(); self.combo_fmt.currentIndexChanged.connect(self._on_format_changed)
        self.combo_quality = QComboBox(); self.combo_rate = QComboBox()
        self.combo_channels = QComboBox(); self.combo_channels.addItem("Mono", 1); self.combo_channels.addItem("Stereo", 2)
        self.chk_normalize = QCheckBox("Normalize loudness (-16 LUFS)"); self.chk_normalize.setChecked(True)
        f.addRow("Format:", self.combo_fmt); f.addRow("Quality:", self.combo_quality)
        f.addRow("Sample rate:", self.combo_rate); f.addRow("Channels:", self.combo_channels)
        f.addRow(self.chk_normalize)
        row = QHBoxLayout()
        self.btn_export = QPushButton("Export…"); self.btn_export.clicked.connect(self._export_dialog)
        b = QPushButton("Show Folder"); b.clicked.connect(self._open_exports)
        row.addWidget(self.btn_export); row.addWidget(b)
        f.addRow(row)
        pv.addWidget(g)
        pv.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(panel); scroll.setMinimumWidth(340)
        split.addWidget(scroll)
        split.setSizes([800, 360])

        for w in (self.spin_speed, self.spin_sent, self.spin_clause, self.spin_sgap, self.spin_pgap):
            w.valueChanged.connect(self._on_settings_changed)
        for fmt in st.available_formats():
            self.combo_fmt.addItem(fmt.label, fmt.key)
        self._fill_engines()

    @staticmethod
    def _dspin(lo, hi, step, val, suffix):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(2); s.setValue(val)
        s.setSuffix(suffix)
        return s

    # ================================================================== documents
    def refresh_documents(self, select: Optional[str] = None) -> None:
        self._loaded = True
        docs = self.library.list()
        self._busy = True
        self.combo_doc.clear()
        for d in docs:
            self.combo_doc.addItem(d.name, d.folder)
        self._busy = False
        if not docs:
            self.doc = None
            self.new_document(name="My narration", text=EXAMPLE)
            return
        i = self.combo_doc.findData(select) if select else 0
        self.combo_doc.setCurrentIndex(max(i, 0))
        self._on_doc_selected()

    def new_document(self, *_, name: Optional[str] = None, text: str = "") -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "New Narration", "Name:", text="Narration")
            if not ok:
                return
        settings = st.AudioSettings(**self.doc.settings.__dict__) if self.doc else st.AudioSettings()
        doc = self.library.create(name, text, settings)
        self.refresh_documents(select=doc.folder)

    def _rename_doc(self) -> None:
        if not self.doc:
            return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=self.doc.name)
        if ok and name.strip():
            self.doc.name = name.strip()
            self.save()
            self.refresh_documents(select=self.doc.folder)

    def _delete_doc(self) -> None:
        if not self.doc:
            return
        if QMessageBox.question(self, "Delete Narration",
                                f"Delete “{self.doc.name}” with its generated audio and exports?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.player.stop()
            self.library.delete(self.doc)
            self.doc = None
            self.refresh_documents()

    def _import_text(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Narration Text", str(Path.home()),
                                              "Text (*.txt *.md *.markdown *.text);;All files (*)")
        if path:
            self.import_text_file(Path(path))

    def import_text_file(self, path: Path) -> None:
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                text = path.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        self.editor.setPlainText(text)
        self._on_text_settled()

    def _on_doc_selected(self, *_) -> None:
        if self._busy or self.combo_doc.currentIndex() < 0:
            return
        self.player.stop()
        self.doc = self.library.load(Path(self.combo_doc.currentData()))
        s = self.doc.settings
        self._busy = True
        self.editor.setPlainText(self.doc.text)
        self.combo_engine.setCurrentIndex(max(self.combo_engine.findData(registry.get_engine(s.engine).id), 0))
        self._fill_speakers()
        self.combo_default.setCurrentIndex(max(self.combo_default.findData(emotion.get(s.default_emotion).key), 0))
        for w, v in ((self.spin_speed, s.speed), (self.spin_sent, s.sentence_pause), (self.spin_clause, s.clause_pause),
                     (self.spin_sgap, s.sentence_gap), (self.spin_pgap, s.paragraph_gap)):
            w.setValue(v)
        self._busy = False
        self._apply_capabilities()
        self.refresh_segments()

    def save(self) -> None:
        if self.doc:
            self.library.save(self.doc)

    # ================================================================== voice / settings
    def _fill_engines(self) -> None:
        cur = self.combo_engine.currentData()
        was, self._busy = self._busy, True
        self.combo_engine.clear()
        for e in registry.engines():
            self.combo_engine.addItem(e.name + ("  · custom" if getattr(e, "custom", False) else ""), e.id)
        self.combo_engine.setCurrentIndex(max(self.combo_engine.findData(cur), 0))
        self._busy = was

    def engine(self):
        return registry.get_engine(self.combo_engine.currentData())

    def _fill_speakers(self) -> None:
        eng = self.engine()
        want = self.doc.settings.speaker if self.doc else ""
        was, self._busy = self._busy, True
        self.combo_speaker.clear()
        for sp in eng.speakers():
            self.combo_speaker.addItem(sp.label, sp.id)
        i = self.combo_speaker.findData(want)
        if i < 0:
            i = self.combo_speaker.findData(eng.default_speaker())
        self.combo_speaker.setCurrentIndex(max(i, 0))
        self._busy = was

    def _apply_capabilities(self) -> None:
        eng = self.engine()
        st_ = eng.status()
        self.lbl_engine.setText(f"Status: {st_.state}" + (f" — {st_.message}" if st_.message else ""))
        caps = eng.capabilities
        for w in (self.spin_sent, self.spin_clause):
            w.setVisible(caps.pauses)
            self.speech_form.labelForField(w).setVisible(caps.pauses)
        self.spin_speed.setRange(*caps.speed_range)
        self.lbl_support.setText(emotion.describe_support(eng))
        self.lbl_caps.setText("" if caps.emphasis else
                              "Emphasis (*word*) is not supported by this model; the asterisks are removed.")

    def _refresh_tag_combo(self, model_id: Optional[str] = None) -> None:
        was_block = self.combo_tag.blockSignals(True)
        self.combo_tag.clear()
        categorized = tag_registry.get_categorized_tags(model_id)
        first_valid_idx = -1
        for cat_name in [tag_registry.CATEGORY_EMOTIONS, tag_registry.CATEGORY_DELIVERY_STYLES, tag_registry.CATEGORY_NONVERBAL_SOUNDS]:
            tags = categorized.get(cat_name, [])
            if not tags:
                continue
            self.combo_tag.addItem(f"── {cat_name} ──", "")
            h_idx = self.combo_tag.count() - 1
            model = self.combo_tag.model()
            item = model.item(h_idx) if hasattr(model, "item") else None
            if item:
                item.setEnabled(False)
            for t in tags:
                self.combo_tag.addItem(f"  [{t.tag}]", t.tag)
                idx = self.combo_tag.count() - 1
                self.combo_tag.setItemData(idx, f"[{t.tag}] ({t.category}): {t.description}", Qt.ToolTipRole)
                if first_valid_idx == -1:
                    first_valid_idx = idx
        if first_valid_idx >= 0:
            self.combo_tag.setCurrentIndex(first_valid_idx)
        self.combo_tag.blockSignals(was_block)

    def _on_engine_changed(self, *_) -> None:
        if self._busy:
            return
        eng_id = self.engine().id
        self._refresh_tag_combo(eng_id)
        self._fill_speakers()
        self._apply_capabilities()
        self._on_settings_changed()

    def _on_settings_changed(self, *_) -> None:
        if self._busy or not self.doc:
            return
        s = self.doc.settings
        s.engine = self.engine().id
        s.speaker = self.combo_speaker.currentData() or ""
        s.default_emotion = self.combo_default.currentData()
        s.speed, s.sentence_pause, s.clause_pause = self.spin_speed.value(), self.spin_sent.value(), self.spin_clause.value()
        s.sentence_gap, s.paragraph_gap = self.spin_sgap.value(), self.spin_pgap.value()
        self.save()
        self.refresh_segments()

    def _manage_models(self) -> None:
        from src.frontend.model_manager import ModelManagerDialog
        dlg = ModelManagerDialog(in_use=lambda: self.doc.settings.engine if self.doc else "",
                                 run_task=lambda fn, done: self._run("import", fn, done), parent=self)
        dlg.use_model.connect(lambda mid: self.combo_engine.setCurrentIndex(max(self.combo_engine.findData(mid), 0)))
        dlg.models_changed.connect(self._models_changed)
        dlg.exec()

    def _models_changed(self) -> None:
        registry.reload()
        self._fill_engines()
        self._on_engine_changed()

    def _edit_pronunciations(self) -> None:
        from src.frontend.narration_studio import PronunciationDialog
        if not self.doc:
            return
        dlg = PronunciationDialog(self.doc.settings.pronunciations, self)
        if dlg.exec() == QDialog.Accepted:
            self.doc.settings.pronunciations = dlg.mapping()
            self.save()
            self.refresh_segments()

    # ================================================================== text / segments
    def _insert_text(self, text: str) -> None:
        self.editor.textCursor().insertText(text)
        self.editor.setFocus()

    def insert_tag(self) -> None:
        tag = self.combo_tag.currentData()
        cur = self.editor.textCursor()
        sel = cur.selectedText().replace(" ", "\n")
        cur.insertText(f"[{tag}] {sel} [/]" if sel else f"[{tag}] ")
        self.editor.setTextCursor(cur)

    def _on_text_settled(self) -> None:
        if self._busy or not self.doc:
            return
        if self.doc.text != self.editor.toPlainText():
            self.doc.text = self.editor.toPlainText()
            self.save()
        self.refresh_segments()

    def segments(self):
        return self.doc.parsed().segments if self.doc else []

    def refresh_segments(self) -> None:
        if not self.doc:
            return
        pr = self.doc.parsed(self.engine().id)
        if pr.warnings:
            self.lbl_warnings.setText("\n".join(f"⚠ {w}" for w in pr.warnings))
            self.lbl_warnings.setVisible(True)
        else:
            self.lbl_warnings.setText("")
            self.lbl_warnings.setVisible(False)
        import soundfile as sf
        sel = self._selected_rows()
        self.table.setRowCount(len(pr.segments))
        ready_n = 0
        for r, seg in enumerate(pr.segments):
            ok = st.segment_ready(self.doc, seg)
            ready_n += ok
            length = ""
            if ok:
                try:
                    info = sf.info(str(st.segment_path(self.doc, seg)))
                    length = f"{info.frames / info.samplerate:.1f}s"
                except Exception:
                    pass
            vals = [str(seg.index + 1), seg.label + (f"  (+{seg.pause_before:g}s pause)" if seg.pause_before else ""),
                    seg.text, length, "ready" if ok else "not generated"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1:
                    it.setForeground(QColor(COLORS.get(seg.emotion, "#9ca3af")))
                self.table.setItem(r, c, it)
        for r in sel:
            if r < self.table.rowCount():
                self.table.selectRow(r) if len(sel) == 1 else None
        self.lbl_status.setText(f"{ready_n}/{len(pr.segments)} segments have audio")
        self._refresh_waveform(complete=ready_n == len(pr.segments) and ready_n > 0)

    def _refresh_waveform(self, complete: bool) -> None:
        if not complete:
            self.wave.clear()
            return
        try:
            audio, sr, timeline = st.assemble(self.doc)
        except Exception:
            self.wave.clear()
            return
        self.wave.set_data(st.peaks(audio, 900), timeline, len(audio) / sr)

    def _selected_rows(self) -> List[int]:
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()}) if self.table.selectionModel() else []

    def selected_segments(self):
        segs = self.segments()
        return [segs[r] for r in self._selected_rows() if r < len(segs)]

    def _on_segment_selection(self) -> None:
        self.wave.selected = {s.index for s in self.selected_segments()}
        self.wave.update()

    def _select_segment(self, index: int) -> None:
        self.table.selectRow(index)
        self.play_segment(index)

    # ================================================================== generate / play
    def _run(self, kind: str, fn, on_done) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Please wait for the current task to finish.")
            return
        self.player.stop()
        self.worker = TTSTaskWorker(kind, fn)
        self.worker.progress.connect(lambda p, m: (self.progress.setValue(p), self.lbl_status.setText(m)))
        self.worker.finished_ok.connect(lambda _k, r: self._done(on_done, r))
        self.worker.failed.connect(self._failed)
        self.progress.setValue(0); self.progress.setVisible(True)
        if self.engine().status().state != tb.READY:
            self.lbl_status.setText("Loading TTS model (first use takes a few seconds)…")
        self.worker.start()

    def _done(self, on_done, result) -> None:
        self.progress.setVisible(False)
        on_done(result)

    def _failed(self, msg: str) -> None:
        self.progress.setVisible(False)
        self.lbl_status.setText(f"✗ {msg}")
        QMessageBox.critical(self, "Audio Studio", msg)

    def generate_missing(self) -> None:
        if not self.doc:
            return
        self._on_text_settled()
        ok, errors = st.validate_document(self.doc, self.engine().id)
        if not ok:
            QMessageBox.warning(self, "Unsupported Tag", "Cannot generate audio:\n\n" + "\n".join(f"• {e}" for e in errors))
            return
        doc = self.doc
        self._run("generate", lambda p, c: st.generate(doc, None, p, c), lambda _r: self.refresh_segments())

    def regenerate_selected(self) -> None:
        segs = self.selected_segments()
        if not segs:
            QMessageBox.information(self, "Regenerate", "Select one or more segments in the list.")
            return
        ok, errors = st.validate_document(self.doc, self.engine().id)
        if not ok:
            QMessageBox.warning(self, "Unsupported Tag", "Cannot regenerate audio:\n\n" + "\n".join(f"• {e}" for e in errors))
            return
        doc = self.doc
        self._run("generate", lambda p, c: (st.regenerate(doc, segs, p, c), self.library.save(doc))[0],
                  lambda _r: self.refresh_segments())

    def play_segment(self, row: Optional[int] = None) -> None:
        segs = self.segments()
        if row is None:
            rows = self._selected_rows()
            row = rows[0] if rows else None
        if row is None or row >= len(segs):
            return
        ok, errors = st.validate_document(self.doc, self.engine().id)
        if not ok:
            QMessageBox.warning(self, "Unsupported Tag", "Cannot synthesize segment:\n\n" + "\n".join(f"• {e}" for e in errors))
            return
        seg, doc = segs[row], self.doc
        self._run("preview", lambda p, c: (p(20, f"Preparing segment {seg.index + 1}…"), st.segment_preview(doc, seg))[1],
                  lambda path: (self.refresh_segments(), self.player.play(path, f"segment {seg.index + 1} · {seg.label}")))

    def play_all(self) -> None:
        if not self.doc:
            return
        ok, errors = st.validate_document(self.doc, self.engine().id)
        if not ok:
            QMessageBox.warning(self, "Unsupported Tag", "Cannot synthesize:\n\n" + "\n".join(f"• {e}" for e in errors))
            return
        doc = self.doc

        def work(p, c):
            st.generate(doc, None, p, c)
            return st.write_master(doc)[0]
        self._run("generate", work, lambda path: (self.refresh_segments(), self.player.play(path, doc.name)))

    def play_sample(self) -> None:
        if not self.doc:
            return
        from src.backend.tts import service as tts
        eng, spk = self.engine(), self.combo_speaker.currentData()
        style = self.combo_default.currentData()
        opts = tts.TTSOptions(eng.id, spk or eng.default_speaker(), self.spin_speed.value(),
                              self.spin_sent.value() if eng.capabilities.pauses else 0.0,
                              self.spin_clause.value() if eng.capabilities.pauses else 0.0, style)
        cache = self.doc.cache / "samples"
        self._run("sample", lambda p, c: tts.synthesize_cached(eng.sample_sentence(opts.speaker), opts, cache),
                  lambda path: self.player.play(path, f"sample · {opts.speaker}"))

    # ================================================================== export
    def _on_format_changed(self, *_) -> None:
        key = self.combo_fmt.currentData()
        if not key:
            return
        f = st.get_format(key)
        self.combo_quality.clear()
        for label, _args in f.qualities:
            self.combo_quality.addItem(label)
        self.combo_rate.clear()
        for r in f.rates:
            self.combo_rate.addItem(f"{r} Hz", r)
        i = self.combo_rate.findData(44100)
        self.combo_rate.setCurrentIndex(i if i >= 0 else max(self.combo_rate.findData(48000), 0))

    def _export_dialog(self) -> None:
        if not self.doc:
            return
        f = st.get_format(self.combo_fmt.currentData())
        self.doc.exports.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Export Audio", str(self.doc.exports / f"{self.doc.doc_id}.{f.ext}"),
                                              f"{f.label} (*.{f.ext})")
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> None:
        if not self.doc:
            return
        ok, errors = st.validate_document(self.doc, self.engine().id)
        if not ok:
            QMessageBox.warning(self, "Unsupported Tag", "Cannot export audio:\n\n" + "\n".join(f"• {e}" for e in errors))
            return
        doc, fmt = self.doc, self.combo_fmt.currentData()
        q, rate = self.combo_quality.currentIndex(), self.combo_rate.currentData()
        ch, norm = self.combo_channels.currentData(), self.chk_normalize.isChecked()

        def work(p, c):
            st.generate(doc, None, p, c)
            p(95, "Encoding…")
            return st.export(doc, fmt, q, rate, ch, norm, path)
        self._run("generate", work, lambda out: (self.refresh_segments(),
                                                 self.lbl_status.setText(f"✓ Exported {Path(out).name}")))

    def _open_exports(self) -> None:
        if self.doc:
            self.doc.exports.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.doc.exports)))
