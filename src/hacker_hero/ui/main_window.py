"""Main window (PySide6)."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hacker_hero.core.document import SongDocument
from hacker_hero.core.errors import ValidationError
from hacker_hero.core.hashing import score_hash


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("::Hacker Hero::")
        self.setFixedSize(520, 560)

        self.document = None
        self.last_dir = None
        self._populating = False
        self._picking_color = False

        self._build_ui()
        self._connect_signals()
        self._set_song_controls_enabled(False)
        self._set_score_editors_enabled(False)

    # ---------- UI ----------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Song Configurations
        song_box = QGroupBox("Song Configurations")
        sg = QVBoxLayout(song_box)
        grid = _grid()
        self.artist_edit = QLineEdit()
        self.color_edit = QLineEdit()
        self.color_edit.setReadOnly(True)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 2147483647)
        self.name_edit = QLineEdit()

        grid.addRow("artist", self.artist_edit)
        grid.addRow("cassettecolor", self.color_edit)
        grid.addRow("count", self.count_spin)
        grid.addRow("name", self.name_edit)
        sg.addLayout(grid)
        root.addWidget(song_box)

        # Difficulties + Scores
        mid = QHBoxLayout()
        diff_box = QGroupBox("Difficulties")
        dv = QVBoxLayout(diff_box)
        self.radio_supaeasy = QRadioButton("Supaeasy")
        self.radio_easy = QRadioButton("Easy")
        self.radio_medium = QRadioButton("Medium")
        self.radio_amazing = QRadioButton("Amazing")
        for r in (self.radio_supaeasy, self.radio_easy, self.radio_medium, self.radio_amazing):
            dv.addWidget(r)
        self.diff_group = QButtonGroup(self)
        self.diff_group.addButton(self.radio_supaeasy, 3)
        self.diff_group.addButton(self.radio_easy, 2)
        self.diff_group.addButton(self.radio_medium, 1)
        self.diff_group.addButton(self.radio_amazing, 0)

        scores_box = QGroupBox("Scores")
        sv = QVBoxLayout(scores_box)
        self.scores_list = QListWidget()
        sv.addWidget(self.scores_list)

        mid.addWidget(diff_box)
        mid.addWidget(scores_box)
        root.addLayout(mid)

        # Edit Score
        edit_box = QGroupBox("Edit Score")
        eg = _grid()
        self.player_name_edit = QLineEdit()
        self.stars_spin = QSpinBox()
        self.stars_spin.setRange(0, 6)
        self.score_edit = QLineEdit()
        self.score_edit.setValidator(QIntValidator(0, 2147483647, self))
        eg.addRow("Name", self.player_name_edit)
        eg.addRow("Stars", self.stars_spin)
        eg.addRow("Score", self.score_edit)
        edit_box.setLayout(eg)
        root.addWidget(edit_box)

        # Menu
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        self.act_open = file_menu.addAction("Open")
        self.act_open.setShortcut("Ctrl+O")
        self.act_save = file_menu.addAction("Save")
        self.act_save.setShortcut("Ctrl+S")
        file_menu.addAction("Save As…", self.save_as)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About", self.about)

    def _connect_signals(self):
        self.act_open.triggered.connect(self.open_file)
        self.act_save.triggered.connect(lambda: self.save_file())

        self.artist_edit.textEdited.connect(self._on_metadata_edited)
        self.name_edit.textEdited.connect(self._on_metadata_edited)
        self.count_spin.valueChanged.connect(self._on_metadata_edited)
        self.color_edit.textChanged.connect(self._on_color_changed)

        for r in (self.radio_supaeasy, self.radio_easy, self.radio_medium, self.radio_amazing):
            r.toggled.connect(self._on_difficulty_toggled)

        self.scores_list.currentRowChanged.connect(self._on_score_selected)

        self.player_name_edit.textEdited.connect(self._on_score_field_edited)
        self.stars_spin.valueChanged.connect(self._on_score_field_edited)
        self.score_edit.textEdited.connect(self._on_score_field_edited)

        # color picker on click (avoid focus recursion/conflicts with file dialogs)
        self.color_edit.mousePressEvent = self._color_mouse

    # ---------- helpers ----------

    def _set_song_controls_enabled(self, enabled):
        for w in (self.artist_edit, self.color_edit, self.count_spin, self.name_edit):
            w.setEnabled(enabled)
        for r in (self.radio_supaeasy, self.radio_easy, self.radio_medium, self.radio_amazing):
            r.setEnabled(enabled and False)  # radios enabled per difficulty later
        self.scores_list.setEnabled(enabled)

    def _enable_radio_for_difficulties(self):
        for r in (self.radio_supaeasy, self.radio_easy, self.radio_medium, self.radio_amazing):
            r.setEnabled(False)
        if self.document is None or self.document.scores is None:
            return
        id_to_radio = {3: self.radio_supaeasy, 2: self.radio_easy, 1: self.radio_medium, 0: self.radio_amazing}
        for k in self.document.scores.keys():
            if k in id_to_radio:
                id_to_radio[k].setEnabled(True)

    def _set_score_editors_enabled(self, enabled):
        for w in (self.player_name_edit, self.stars_spin, self.score_edit):
            w.setEnabled(enabled)

    def _current_difficulty(self):
        for radio, rid in ((self.radio_amazing, 0), (self.radio_medium, 1), (self.radio_easy, 2), (self.radio_supaeasy, 3)):
            if radio.isChecked():
                return rid
        return None

    def _load_scores_for(self, diff):
        self.scores_list.clear()
        if self.document is None or self.document.scores is None or diff is None:
            return
        for e in self.document.scores.get(diff, []):
            self.scores_list.addItem(e.name)

    # ---------- slots ----------

    def _on_metadata_edited(self, *args):
        if self._populating or self.document is None:
            return
        self.document.artist = self.artist_edit.text()
        self.document.name = self.name_edit.text()
        self.document.count = self.count_spin.value()
        self.document.cassettecolor = self.color_edit.text()
        self.document.dirty = True

    def _on_color_changed(self, text):
        if self._populating or self.document is None:
            return
        self.document.cassettecolor = text
        self.document.dirty = True

    def _on_difficulty_toggled(self, checked):
        if not checked or self._populating:
            return
        diff = self._current_difficulty()
        self._load_scores_for(diff)
        self._set_score_editors_enabled(False)
        self.scores_list.clearSelection()

    def _on_score_selected(self, row):
        if self._populating or self.document is None or self.document.scores is None:
            if row < 0:
                self._set_score_editors_enabled(False)
            return
        if row < 0:
            self._set_score_editors_enabled(False)
            return
        diff = self._current_difficulty()
        if diff is None:
            self._set_score_editors_enabled(False)
            return
        entries = self.document.scores.get(diff, [])
        if row >= len(entries):
            self._set_score_editors_enabled(False)
            return
        e = entries[row]
        self._populating = True
        self.player_name_edit.setText(e.name)
        self.stars_spin.setValue(e.stars)
        self.score_edit.setText(str(e.score))
        self._populating = False
        self._set_score_editors_enabled(True)

    def _on_score_field_edited(self, *args):
        if self._populating or self.document is None or self.document.scores is None:
            return
        diff = self._current_difficulty()
        if diff is None:
            return
        idx = self.scores_list.currentRow()
        if idx < 0:
            return
        entries = self.document.scores.get(diff, [])
        if idx >= len(entries):
            return
        score_text = self.score_edit.text().strip()
        score = int(score_text) if score_text else 0
        stars = self.stars_spin.value()
        name = self.player_name_edit.text()
        # update listbox row text if name changed
        item = self.scores_list.item(idx)
        if item is not None and item.text() != name:
            item.setText(name)
        try:
            h = score_hash(diff, score, stars, name)
        except (UnicodeEncodeError, ValueError):
            QMessageBox.warning(self, "Validation", "Name must be latin-1 encodable.")
            return
        self.document.scores[diff][idx] = _entry(score, stars, name, h)
        self.document.dirty = True

    def _color_mouse(self, event):
        if not self._picking_color:
            self._picking_color = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._open_color_dialog)
        QLineEdit.mousePressEvent(self.color_edit, event)

    def _color_focus(self, event):
        if getattr(self, "_picking_color", False):
            QLineEdit.focusInEvent(self.color_edit, event)
            return
        self._picking_color = True
        QLineEdit.focusInEvent(self.color_edit, event)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._open_color_dialog)

    def _open_color_dialog(self):
        try:
            current = self.color_edit.text().strip()
            qcolor = QColor(current) if current else QColor("white")
            new = QColorDialog.getColor(qcolor, self, "Choose color")
            if new.isValid():
                hexstr = new.name().lower()
                r, g, b = new.red(), new.green(), new.blue()
                fg = "black" if (r + g + b) / 3 > 127 else "white"
                self.color_edit.setStyleSheet(f"background-color: {hexstr}; color: {fg};")
                self._populating = True
                self.color_edit.setText(hexstr)
                self._populating = False
                if self.document is not None:
                    self.document.cassettecolor = hexstr
                    self.document.dirty = True
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, self._reset_picking_color)

    def _reset_picking_color(self):
        self._picking_color = False

    # ---------- file ops ----------

    def open_file(self):
        if self.document is not None and self.document.dirty:
            res = QMessageBox.question(
                self, "::Hacker Hero::", "Save file?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Cancel:
                return
            if res == QMessageBox.StandardButton.Save:
                if not self.save_file():
                    return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", self.last_dir or "", "Configuration files (*.ini);;All files (*.*)"
        )
        if not path:
            return
        self.last_dir = os.path.dirname(path)
        try:
            doc = SongDocument.load(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        if doc.scores_load_warning:
            QMessageBox.warning(self, "Warning", f"Could not decode scores: {doc.scores_load_warning}")
        self.document = doc
        self._populating = True
        self.artist_edit.setText(doc.artist or "")
        self.name_edit.setText(doc.name or "")
        self.count_spin.setValue(doc.count or 0)
        self.color_edit.setText(doc.cassettecolor or "")
        # color style
        if doc.cassettecolor:
            self._apply_color_style(doc.cassettecolor)
        else:
            self.color_edit.setStyleSheet("")
        self._populating = False

        self._set_song_controls_enabled(True)
        self._enable_radio_for_difficulties()
        # select difficulty
        chosen = None
        if doc.scores:
            if 1 in doc.scores:
                chosen = 1
            else:
                for k in (0, 2, 3):
                    if k in doc.scores:
                        chosen = k
                        break
            if chosen is None:
                chosen = next(iter(doc.scores))
        if chosen is not None:
            id_to_radio = {3: self.radio_supaeasy, 2: self.radio_easy, 1: self.radio_medium, 0: self.radio_amazing}
            id_to_radio[chosen].setChecked(True)
        self._load_scores_for(chosen)
        self._set_score_editors_enabled(False)
        self.scores_list.clearSelection()
        self.document.dirty = False

    def _apply_color_style(self, hexstr):
        try:
            c = QColor(hexstr)
        except Exception:
            return
        if not c.isValid():
            return
        r, g, b = c.red(), c.green(), c.blue()
        fg = "black" if (r + g + b) / 3 > 127 else "white"
        self.color_edit.setStyleSheet(f"background-color: {hexstr}; color: {fg};")

    def save_file(self, force_confirm=True):
        if self.document is None:
            QMessageBox.warning(self, "Warning", "Please open a file")
            return False
        if force_confirm and self.document.save_path is None and self.document.path is not None:
            res = QMessageBox.question(
                self, "Save", "Are you sure you want to rewrite this file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return False
        # apply ui
        if self.document is not None:
            self.document.artist = self.artist_edit.text()
            self.document.name = self.name_edit.text()
            self.document.count = self.count_spin.value()
            self.document.cassettecolor = self.color_edit.text()
        try:
            self.document.save()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return False
        self.document.dirty = False
        return True

    def save_as(self):
        if self.document is None:
            QMessageBox.warning(self, "Warning", "Please open a file")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", self.last_dir or "", "Configuration files (*.ini);;All files (*.*)"
        )
        if not path:
            return
        if not path.lower().endswith(".ini"):
            path += ".ini"
        self.last_dir = os.path.dirname(path)
        self.document.save_path = Path(path)
        self.save_file(force_confirm=False)

    def about(self):
        QMessageBox.about(
            self,
            "About",
            "Hacker Hero\n\n"
            "Author: Filipe Teixeira\n"
            "E-mail: shuantsu@gmail.com\n\n"
            f"Python {sys.version.split()[0]}\n"
            f"PySide6 {__import__('PySide6').__version__}",
        )

    def closeEvent(self, event):
        if self.document is not None and self.document.dirty:
            res = QMessageBox.question(
                self, "::Hacker Hero::", "Save file?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if res == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if res == QMessageBox.StandardButton.Save:
                if not self.save_file():
                    event.ignore()
                    return
        event.accept()


def _grid():
    from PySide6.QtWidgets import QFormLayout
    return QFormLayout()


def _entry(score, stars, name, h):
    from hacker_hero.core.document import ScoreEntry
    return ScoreEntry(score, stars, name, h)
