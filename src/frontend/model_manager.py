"""Manage custom (user-imported) local TTS models: import, name, inspect, remove."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from src.backend.tts import registry
from src.backend.tts.custom import CustomModelStore, Detection, ModelStoreError, detect
from src.backend.tts.custom.formats import supported_formats_help


def _mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


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
    """List of imported models. Emits `models_changed` after any change (registry already reloaded)."""

    models_changed = Signal()
    use_model = Signal(str)          # engine id to select in Narration Studio

    def __init__(self, store: Optional[CustomModelStore] = None, in_use: Callable[[], str] = lambda: "",
                 run_task: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.store = store or CustomModelStore()
        self.in_use = in_use                    # engine id used by the open project
        self.run_task = run_task                # (fn(progress, cancel), on_done) -> runs in background
        self.setWindowTitle("Custom TTS Models")
        self.resize(820, 440)
        lay = QVBoxLayout(self)
        intro = QLabel("Import TTS models you have downloaded. They run locally and appear in the TTS Model list "
                       "next to Kokoro-82M, for one speaker or per-slide speakers.")
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
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self.refresh()

    # ------------------------------------------------------------------ list
    def refresh(self) -> None:
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

    # ------------------------------------------------------------------ import
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

    # ------------------------------------------------------------------ manage
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
