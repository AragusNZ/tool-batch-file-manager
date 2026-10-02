"""The Folder panel: which folder, how deep, which kinds of item, and the name filter."""

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from batch_file_manager.core.scan import KINDS, ScopeSpec

KIND_LABELS = {"files": "Files", "folders": "Folders", "both": "Files and folders"}
DEBOUNCE_MS = 250


class ScopePanel(QGroupBox):
    """Emits ``changed(ScopeSpec)`` shortly after any control moves. Accepts a folder dropped on it."""

    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Folder", parent)
        self.setAcceptDrops(True)
        self.folder = QLineEdit(readOnly=True, placeholderText="Choose a folder, or drop one here")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        self.recurse = QCheckBox("Include subfolders")
        self.kinds = QComboBox()
        for kind in KINDS:
            self.kinds.addItem(KIND_LABELS[kind], kind)
        self.pattern = QLineEdit(placeholderText="e.g. *.jpg or IMG_\\d+", clearButtonEnabled=True)
        self.mode = QComboBox()
        self.mode.addItems(["Glob", "Regex"])
        self.match_case = QCheckBox("Match case")
        self.summary = QLabel("")
        self.summary.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.folder, stretch=1)
        top.addWidget(browse)
        grid = QGridLayout(self)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addLayout(top, 0, 0, 1, 4)
        grid.addWidget(self.recurse, 1, 0)
        grid.addWidget(QLabel("Apply to:"), 1, 1)
        grid.addWidget(self.kinds, 1, 2)
        grid.addWidget(QLabel("Only names matching:"), 2, 0)
        grid.addWidget(self.pattern, 2, 1)
        grid.addWidget(self.mode, 2, 2)
        grid.addWidget(self.match_case, 2, 3)
        grid.addWidget(self.summary, 3, 0, 1, 4)
        grid.setColumnStretch(1, 1)

        self._timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)
        self.folder.textChanged.connect(self._timer.start)
        self.recurse.toggled.connect(self._timer.start)
        self.kinds.currentIndexChanged.connect(self._timer.start)
        self.pattern.textChanged.connect(self._timer.start)
        self.mode.currentIndexChanged.connect(self._timer.start)
        self.match_case.toggled.connect(self._timer.start)

    # --- state -----------------------------------------------------------------
    def spec(self) -> ScopeSpec | None:
        """The current scope, or None while no folder is chosen."""
        if not self.folder.text():
            return None
        return ScopeSpec(
            folder=Path(self.folder.text()), recurse=self.recurse.isChecked(), kinds=self.kinds.currentData(),
            pattern=self.pattern.text(), regex=self.mode.currentIndex() == 1, match_case=self.match_case.isChecked(),
        )

    def set_folder(self, folder: Path) -> bool:
        if not folder.is_dir():
            return False
        self.folder.setText(str(folder))
        return True

    def restore(self, recurse: bool, kinds: str) -> None:
        self.recurse.setChecked(recurse)
        if kinds in KINDS:
            self.kinds.setCurrentIndex(KINDS.index(kinds))

    def show_summary(self, text: str, error: bool = False) -> None:
        self.summary.setForegroundRole(QPalette.ColorRole.BrightText if error else QPalette.ColorRole.PlaceholderText)
        self.summary.setText(text)

    def _emit(self) -> None:
        self.changed.emit(self.spec())

    # --- input -------------------------------------------------------------------
    def browse(self) -> None:
        start = self.folder.text() or str(Path.home())
        name = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if name:
            self.set_folder(Path(name))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(Path(u.toLocalFile()).is_dir() for u in event.mimeData().urls() if u.isLocalFile()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and self.set_folder(Path(url.toLocalFile())):
                event.acceptProposedAction()
                return
