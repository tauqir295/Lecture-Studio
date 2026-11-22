"""TTS Model Manager: manage downloadable neural models (Kokoro-82M, Qwen3-TTS) and imported custom models."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from src.backend.tts import registry
from src.backend.tts.custom import CustomModelStore, Detection, ModelStoreError, detect
from src.backend.tts.custom.formats import supported_formats_help
from src.backend.tts.qwen3_manager import MODEL_SPECS, Qwen3Manager, format_bytes, _dir_size


def _mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


class DownloadProgressDialog(QDialog):
    """Visual progress dialog for downloading model components."""

    cancelled = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self._is_cancelled = False
        lay = QVBoxLayout(self)
        self.lbl_status = QLabel("Preparing download...")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        bb = QHBoxLayout()
        bb.addStretch()
        bb.addWidget(self.btn_cancel)
        lay.addLayout(bb)

    def set_progress(self, pct: int, msg: str) -> None:
        self.bar.setValue(max(0, min(100, pct)))
        self.lbl_status.setText(msg)
        QGuiApplication.processEvents()

    def _on_cancel(self) -> None:
        self._is_cancelled = True
        self.lbl_status.setText("Cancelling download...")
        self.btn_cancel.setEnabled(False)
        self.cancelled.emit()

    def is_cancelled(self) -> bool:
        return self._is_cancelled


class Qwen3SettingsDialog(QDialog):
    """Model-specific settings for Qwen3-TTS instruction and voice design controls."""

    def __init__(self, manager: Qwen3Manager, model_id: str, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.model_id = model_id
        spec = MODEL_SPECS.get(model_id)
        name = spec.name if spec else model_id
        self.setWindowTitle(f"Settings — {name}")
        self.setMinimumWidth(500)
        self.settings = self.manager.load_settings(model_id)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        info = QLabel(
            "Qwen3-TTS models follow natural-language instructions for emotion, tone, speaking style, and prosody. "
            "You can specify global instruction preferences below."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9ca3af; font-size: 11px;")
        lay.addWidget(info)

        self.edit_instruct = QTextEdit()
        self.edit_instruct.setPlaceholderText(
            "e.g. 'Speak in a calm academic tone with clear diction and measured pauses.'"
        )
        self.edit_instruct.setPlainText(self.settings.get("custom_instruction", ""))
        self.edit_instruct.setMaximumHeight(80)
        form.addRow("Custom Instruction:", self.edit_instruct)

        self.edit_voice_design = None
        if spec and spec.is_voice_design:
            self.edit_voice_design = QTextEdit()
            self.edit_voice_design.setPlaceholderText(
                "e.g. 'A clear, warm, and articulate female academic lecturer with calm, confident pacing.'"
            )
            self.edit_voice_design.setPlainText(self.settings.get("voice_design_prompt", ""))
            self.edit_voice_design.setMaximumHeight(80)
            form.addRow("Voice Design Prompt:", self.edit_voice_design)

        self.combo_device = QComboBox()
        self.combo_device.addItems(["CPU (Offline)", "Auto (MPS / GPU if available)"])
        cur_dev = self.settings.get("device", "cpu")
        self.combo_device.setCurrentIndex(1 if "auto" in cur_dev.lower() or "mps" in cur_dev.lower() else 0)
        form.addRow("Compute Device:", self.combo_device)

        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(0.5, 2.0)
        self.spin_rate.setSingleStep(0.05)
        self.spin_rate.setValue(float(self.settings.get("speaking_rate", 1.0)))
        self.spin_rate.setSuffix("×")
        form.addRow("Speaking Rate:", self.spin_rate)

        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self) -> None:
        self.settings["custom_instruction"] = self.edit_instruct.toPlainText().strip()
        if self.edit_voice_design:
            self.settings["voice_design_prompt"] = self.edit_voice_design.toPlainText().strip()
        self.settings["device"] = "auto" if self.combo_device.currentIndex() == 1 else "cpu"
        self.settings["speaking_rate"] = round(self.spin_rate.value(), 2)
        self.manager.save_settings(self.model_id, self.settings)
        self.accept()


class ImportModelDialog(QDialog):
    """Name the detected model, choose copy vs. reference, add a licence note."""

    def __init__(self, det: Detection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import TTS Model")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_name = QLineEdit(det.suggested_name)
        form.addRow("Name:", self.edit_name)
        form.addRow("Format:", QLabel(det.format_label))
        info = QLabel(det.message); info.setWordWrap(True)
        form.addRow("Detected:", info)
        files = QLabel("\n".join(f"{role}: {p}" for role, p in det.files.items()))
        files.setWordWrap(True); files.setStyleSheet("color: #9ca3af; font-size: 11px;")
        files.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Files:", files)
        self.chk_copy = QCheckBox(f"Copy files into the model library ({_mb(det.size_bytes)})")
        self.chk_copy.setToolTip("Copy: the model keeps working if you move or delete the originals.\n"
                                 "Unticked: the files are used where they are (no extra disk space).")
        form.addRow("", self.chk_copy)
        self.edit_license = QLineEdit()
        self.edit_license.setPlaceholderText("Optional, e.g. 'MIT – see model card'")
        form.addRow("Licence note:", self.edit_license)
        lay.addLayout(form)
        self.lbl_deps = QLabel("")
        self.lbl_deps.setWordWrap(True)
        if not det.deps_ok:
            self.lbl_deps.setText(f"⚠ Cannot run this model yet: {det.deps_message}")
            self.lbl_deps.setStyleSheet("color: #ef4444;")
        lay.addWidget(self.lbl_deps)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Import")
        bb.button(QDialogButtonBox.Ok).setEnabled(det.deps_ok)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> Dict:
        return {"name": self.edit_name.text().strip(), "copy": self.chk_copy.isChecked(),
                "license_note": self.edit_license.text().strip()}


class ModelManagerDialog(QDialog):
    """TTS Model Manager supporting downloadable neural engines (Kokoro-82M, Qwen3-TTS) and imported models."""

    models_changed = Signal()
    use_model = Signal(str)          # engine id to select in Narration Studio

    def __init__(self, store: Optional[CustomModelStore] = None, in_use: Callable[[], str] = lambda: "",
                 run_task: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.store = store or CustomModelStore()
        self.in_use = in_use                    # engine id used by open project
        self.run_task = run_task                # (fn(progress, cancel), on_done) -> runs in background
        self.tts_root = registry.models_root() / "tts"
        self.qwen3_mgr = Qwen3Manager(self.tts_root)

        self.setWindowTitle("TTS Model Manager")
        self.resize(880, 520)
        root_lay = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root_lay.addWidget(self.tabs, 1)

        # Tab 1: Managed Neural Models (Kokoro & Qwen3-TTS)
        self.tabs.addTab(self._build_managed_tab(), "TTS Models Library")

        # Tab 2: User-Imported Custom Models (Piper & ONNX)
        self.tabs.addTab(self._build_custom_tab(), "Imported Custom Models")

        # Bottom Close Row
        close_row = QHBoxLayout()
        self.lbl_storage_info = QLabel("")
        self.lbl_storage_info.setStyleSheet("color: #9ca3af; font-size: 11px;")
        close_row.addWidget(self.lbl_storage_info)
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root_lay.addLayout(close_row)

        self.refresh()

    # ================================================================== Tab 1: Managed Models
    def _build_managed_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel(
            "Select, download, verify and configure local TTS models. Once downloaded, all models run "
            "100% offline without sending audio or data to external servers."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.managed_table = QTableWidget(0, 5)
        self.managed_table.setHorizontalHeaderLabels(["Model Name", "Variant", "Model Size", "Disk Usage", "Status"])
        hh = self.managed_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.managed_table.verticalHeader().setVisible(False)
        self.managed_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.managed_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.managed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.managed_table.itemSelectionChanged.connect(self._update_managed_buttons)
        self.managed_table.cellDoubleClicked.connect(lambda *_: self._use_selected_managed())
        lay.addWidget(self.managed_table, 1)

        self.lbl_managed_detail = QLabel("")
        self.lbl_managed_detail.setWordWrap(True)
        self.lbl_managed_detail.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.lbl_managed_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_managed_detail)

        row = QHBoxLayout()
        self.btn_download_managed = QPushButton("Download / Install")
        self.btn_download_managed.clicked.connect(self._download_selected_managed)
        self.btn_verify_managed = QPushButton("Verify Integrity")
        self.btn_verify_managed.clicked.connect(self._verify_selected_managed)
        self.btn_use_managed = QPushButton("Use in Narration Studio")
        self.btn_use_managed.clicked.connect(self._use_selected_managed)
        self.btn_settings_managed = QPushButton("Model Settings…")
        self.btn_settings_managed.clicked.connect(self._settings_selected_managed)
        self.btn_remove_managed = QPushButton("Remove / Free Space")
        self.btn_remove_managed.clicked.connect(self._remove_selected_managed)

        for b in (self.btn_download_managed, self.btn_verify_managed, self.btn_use_managed,
                  self.btn_settings_managed, self.btn_remove_managed):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    # ================================================================== Tab 2: Custom Models
    def _build_custom_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel("Import Piper voices or Kokoro-compatible ONNX models you have downloaded.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Format", "Speakers", "Storage", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(lambda *_: self._use_selected())
        lay.addWidget(self.table, 1)

        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.lbl_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_detail)

        row = QHBoxLayout()
        self.btn_file = QPushButton("Import File…"); self.btn_file.clicked.connect(self._import_file)
        self.btn_folder = QPushButton("Import Folder…"); self.btn_folder.clicked.connect(self._import_folder)
        self.btn_use = QPushButton("Use in Narration Studio"); self.btn_use.clicked.connect(self._use_selected)
        self.btn_rename = QPushButton("Rename…"); self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_remove = QPushButton("Remove…"); self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_help = QPushButton("Supported Formats")
        self.btn_help.clicked.connect(lambda: QMessageBox.information(self, "Supported Formats", supported_formats_help()))
        for b in (self.btn_file, self.btn_folder, self.btn_use, self.btn_rename, self.btn_remove):
            row.addWidget(b)
        row.addStretch(); row.addWidget(self.btn_help)
        lay.addLayout(row)
        return w

    # ================================================================== refresh & state
    def refresh(self) -> None:
        self._refresh_managed()
        self._refresh_custom()

    def _refresh_managed(self) -> None:
        managed_list = [
            ("kokoro-82m", "Kokoro-82M", "82M Neural TTS", "~353 MB"),
            ("qwen3-tts-0.6b-customvoice", "Qwen3-TTS 0.6B CustomVoice", "0.6B Multilingual + Style Instruct", "1.2 GB"),
            ("qwen3-tts-1.7b-customvoice", "Qwen3-TTS 1.7B CustomVoice", "1.7B Multilingual + Style Instruct", "3.4 GB"),
            ("qwen3-tts-1.7b-voicedesign", "Qwen3-TTS 1.7B VoiceDesign", "1.7B Zero-Shot Voice Design", "3.4 GB"),
        ]

        self.managed_table.setRowCount(len(managed_list))
        for r, (mid, name, variant, sz) in enumerate(managed_list):
            eng = registry.get_engine(mid)
            in_use = (mid == self.in_use())
            name_txt = name + ("  (in use)" if in_use else "")
            ok, why = eng.is_installed() if eng else (False, "Not available")

            if ok:
                status = "ready to use"
            elif eng and eng.downloadable:
                status = "not installed"
            else:
                status = "cannot run"

            if mid == "kokoro-82m":
                kdir = self.tts_root / "kokoro-82m"
                usage = _dir_size(kdir) if kdir.is_dir() else 0
            else:
                usage = self.qwen3_mgr.disk_usage(mid)

            vals = [name_txt, variant, sz, format_bytes(usage) if usage > 0 else "—", status]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, mid)
                self.managed_table.setItem(r, c, it)

        # Storage summary
        tot = self.qwen3_mgr.total_disk_usage()
        kdir = self.tts_root / "kokoro-82m"
        if kdir.is_dir():
            tot += _dir_size(kdir)
        self.lbl_storage_info.setText(f"💾 Local TTS Models Storage: {format_bytes(tot)} in {self.tts_root}")
        self._update_managed_buttons()

    def _refresh_custom(self) -> None:
        entries = self.store.entries()
        engines = {e.id: e for e in registry.engines()}
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            eng = engines.get(e["id"])
            missing = self.store.missing_files(e)
            if missing:
                status = "files missing"
            elif eng is None:
                status = "error"
            else:
                ok, why = eng.is_installed()
                status = "ready to use" if ok else "cannot run"
            n = len(eng.speakers()) if eng and not missing else 0
            vals = [e["name"] + ("  (in use)" if e["id"] == self.in_use() else ""), e["format"], str(n),
                    "library copy" if e.get("managed") else "in place", status]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.UserRole, e["id"])
                self.table.setItem(r, c, it)
        self._update_buttons()

    # ================================================================== Managed Model Actions
    def selected_managed_id(self) -> Optional[str]:
        rows = self.managed_table.selectionModel().selectedRows()
        return self.managed_table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _update_managed_buttons(self) -> None:
        mid = self.selected_managed_id()
        for b in (self.btn_download_managed, self.btn_verify_managed, self.btn_use_managed,
                  self.btn_settings_managed, self.btn_remove_managed):
            b.setEnabled(mid is not None)

        if not mid:
            self.lbl_managed_detail.setText("")
            return

        eng = registry.get_engine(mid)
        ok, why = eng.is_installed() if eng else (False, "Not available")

        if ok:
            self.btn_download_managed.setText("Re-install / Update")
        else:
            self.btn_download_managed.setText("Download / Install")

        self.btn_settings_managed.setVisible(mid.startswith("qwen3"))

        detail_lines = [f"**{eng.name}**"]
        detail_lines.append(eng.description)
        if mid.startswith("qwen3"):
            spec = MODEL_SPECS.get(mid)
            tok_ok, tok_msg = self.qwen3_mgr.is_tokenizer_installed()
            detail_lines.append(f"• Components: {len(spec.required_files) if spec else 3} model files + Qwen3 Tokenizer ({'ready' if tok_ok else 'missing'}).")
            detail_lines.append("• Emotion & Tone: Genuine instruction-based delivery tags ([happy], [sad], [whispering], [calm], etc.).")
            detail_lines.append(f"• Offline location: {self.qwen3_mgr.model_dir(mid)}")
        elif mid == "kokoro-82m":
            detail_lines.append("• Components: kokoro-v1.0.onnx + voices-v1.0.bin (54 voices).")
            detail_lines.append(f"• Offline location: {self.tts_root / 'kokoro-82m'}")

        if not ok and why:
            detail_lines.append(f"⚠ Status: {why}")

        self.lbl_managed_detail.setText("\n".join(detail_lines))

    def _download_selected_managed(self) -> None:
        mid = self.selected_managed_id()
        if not mid:
            return
        eng = registry.get_engine(mid)
        if not eng or not eng.downloadable:
            QMessageBox.warning(self, "Download", "This engine does not support automatic downloading.")
            return

        dlg = DownloadProgressDialog(f"Download {eng.name}", self)

        def do_download():
            eng.download(progress=dlg.set_progress, cancel=dlg.is_cancelled)

        if self.run_task:
            self.run_task(lambda p, c: eng.download(p, c), lambda _r: self._changed())
        else:
            try:
                do_download()
                QMessageBox.information(self, "Download Complete", f"✓ {eng.name} installed and ready for offline use.")
            except Exception as exc:
                QMessageBox.critical(self, "Download Failed", str(exc))
            finally:
                self._changed()

    def _verify_selected_managed(self) -> None:
        mid = self.selected_managed_id()
        if not mid:
            return
        eng = registry.get_engine(mid)
        if not eng:
            return

        ok, msg = eng.verify()
        if ok:
            QMessageBox.information(self, "Model Verification", f"✓ {msg}")
        else:
            QMessageBox.warning(self, "Model Verification", f"⚠ Verification failed:\n\n{msg}")

    def _use_selected_managed(self) -> None:
        mid = self.selected_managed_id()
        if mid:
            self.use_model.emit(mid)
            self.accept()

    def _settings_selected_managed(self) -> None:
        mid = self.selected_managed_id()
        if mid and mid.startswith("qwen3"):
            dlg = Qwen3SettingsDialog(self.qwen3_mgr, mid, self)
            dlg.exec()

    def _remove_selected_managed(self) -> None:
        mid = self.selected_managed_id()
        if not mid:
            return
        eng = registry.get_engine(mid)
        if not eng:
            return

        used = (mid == self.in_use())
        warn = "\n\n⚠ This model is currently in use by the open project. Removing it will switch the project to Kokoro-82M." if used else ""
        ans = QMessageBox.question(
            self, "Remove Model Files",
            f"Remove local files for “{eng.name}” to free disk space?{warn}",
            QMessageBox.Yes | QMessageBox.No
        )
        if ans == QMessageBox.Yes:
            if mid.startswith("qwen3"):
                self.qwen3_mgr.remove_model(mid, remove_tokenizer_if_unused=True)
            elif mid == "kokoro-82m":
                kdir = self.tts_root / "kokoro-82m"
                if kdir.is_dir():
                    import shutil
                    shutil.rmtree(kdir, ignore_errors=True)
            self._changed()

    # ================================================================== Custom Model Actions
    def selected_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _update_buttons(self) -> None:
        mid = self.selected_id()
        for b in (self.btn_use, self.btn_rename, self.btn_remove):
            b.setEnabled(mid is not None)
        e = self.store.get(mid) if mid else None
        if not e:
            self.lbl_detail.setText("")
            return
        eng = next((x for x in registry.engines() if x.id == mid), None)
        why = ""
        if eng:
            ok, why = eng.is_installed()
        files = "\n".join(f"{k}: {v}" for k, v in e["files"].items())
        self.lbl_detail.setText(f"{files}\nImported {e.get('imported', '')}"
                                + (f" · Licence: {e['license']}" if e.get("license") else "")
                                + (f"\n⚠ {why}" if why else ""))

    def _changed(self) -> None:
        registry.reload()
        self.refresh()
        self.models_changed.emit()

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import TTS Model File", str(Path.home()),
                                              "TTS models (*.onnx *.json *.bin *.npz);;All files (*)")
        if path:
            self.import_path(path)

    def _import_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Import TTS Model Folder", str(Path.home()))
        if path:
            self.import_path(path)

    def choose_candidate(self, cands: List[Detection]) -> Optional[Detection]:
        if len(cands) == 1:
            return cands[0]
        labels = [f"{d.format_label}: {Path(d.files.get('model', '')).name} — {d.message}" for d in cands]
        item, ok = QInputDialog.getItem(self, "Several Models Found", "Choose the model to import:", labels, 0, False)
        return cands[labels.index(item)] if ok else None

    def ask_import_options(self, det: Detection) -> Optional[Dict]:
        dlg = ImportModelDialog(det, self)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def show_problem(self, title: str, det: Detection) -> None:
        box = QMessageBox(QMessageBox.Warning, title, det.message, QMessageBox.Ok, self)
        if det.instructions:
            box.setInformativeText(det.instructions)
        box.exec()

    def import_path(self, path: str) -> Optional[Dict]:
        """Detect → choose → name → register. Returns the new store entry (or None)."""
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = detect(path)
        finally:
            QGuiApplication.restoreOverrideCursor()
        usable = [d for d in found if d.ok]
        if not usable:
            self.show_problem("Model Not Supported", found[0])
            return None
        det = self.choose_candidate(usable)
        if det is None:
            return None
        if not det.deps_ok:
            self.show_problem("Missing Dependencies", Detection(False, message=det.deps_message,
                                                                instructions=det.instructions))
        while True:
            opts = self.ask_import_options(det)
            if not opts:
                return None
            try:
                self.store._check_name(opts["name"])
                break
            except ModelStoreError as exc:
                QMessageBox.warning(self, "Import Model", str(exc))
                det.suggested_name = opts["name"]
        if opts["copy"] and self.run_task:
            self.run_task(lambda p, c: self.store.add(det, opts["name"], True, opts["license_note"], p),
                          lambda _r: self._changed())
            return None
        try:
            entry = self.store.add(det, opts["name"], opts["copy"], opts["license_note"])
        except ModelStoreError as exc:
            QMessageBox.critical(self, "Import Failed", str(exc))
            return None
        self._changed()
        return entry

    def _use_selected(self) -> None:
        mid = self.selected_id()
        if mid:
            self.use_model.emit(mid)
            self.accept()

    def _rename_selected(self) -> None:
        mid = self.selected_id()
        e = self.store.get(mid) if mid else None
        if not e:
            return
        name, ok = QInputDialog.getText(self, "Rename Model", "Name:", text=e["name"])
        if ok:
            self.rename_model(mid, name)

    def rename_model(self, mid: str, name: str) -> bool:
        try:
            self.store.rename(mid, name)
        except ModelStoreError as exc:
            QMessageBox.warning(self, "Rename Model", str(exc))
            return False
        self._changed()
        return True

    def ask_remove(self, e: Dict) -> Optional[str]:
        """'list' (unregister), 'files' (unregister + delete library copy) or None."""
        box = QMessageBox(QMessageBox.Question, "Remove Model", f"Remove “{e['name']}”?", parent=self)
        used = e["id"] == self.in_use()
        info = "Projects using it will switch to Kokoro-82M." if used else ""
        if e.get("managed"):
            box.setInformativeText(info + "\nThe library copy can be deleted to free disk space.")
            b_list = box.addButton("Remove, Keep Library Copy", QMessageBox.AcceptRole)
            b_files = box.addButton("Remove and Delete Copy", QMessageBox.DestructiveRole)
        else:
            box.setInformativeText(info + "\nYour original model files are not deleted.")
            b_list = box.addButton("Remove from List", QMessageBox.AcceptRole)
            b_files = None
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        return "list" if clicked is b_list else ("files" if b_files is not None and clicked is b_files else None)

    def _remove_selected(self) -> None:
        mid = self.selected_id()
        e = self.store.get(mid) if mid else None
        if e:
            choice = self.ask_remove(e)
            if choice:
                self.remove_model(mid, delete_files=(choice == "files"))

    def remove_model(self, mid: str, delete_files: bool = False) -> None:
        self.store.remove(mid, delete_files=delete_files)
        self._changed()
