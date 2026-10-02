import logging
import logging.handlers
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction, QActionGroup, QCloseEvent, QDesktopServices, QFont, QFontDatabase, QGuiApplication, QIcon, QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QStyleFactory, QTabWidget, QVBoxLayout,
    QWidget,
)

from batch_file_manager import __version__
from batch_file_manager.core.scan import ScopeSpec, scan
from batch_file_manager.core.update import RELEASES_URL, is_newer, latest_version
from batch_file_manager.tools.rename import RenamePage
from batch_file_manager.ui.scope import ScopePanel
from batch_file_manager.ui.settings import settings
from batch_file_manager.ui.theme import apply_scheme, asset_path
from batch_file_manager.ui.worker import Worker

APP_NAME = "Batch File Manager"
LOG_FILE = Path(tempfile.gettempdir()) / "BatchFileManager.log"  # tracebacks land here; the exe has no console
TOOLS = [("Rename", RenamePage)]  # tab label, page class; a page has set_items(paths, root) and job_requested
log = logging.getLogger(__name__)
job_log = logging.getLogger("batch_file_manager.job")  # every job line, so the file holds the full transcript


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1000, 860)  # no setMinimumSize: the layout's own minimum is the floor, so nothing can crop
        if geometry := settings().value("geometry"):
            self.restoreGeometry(geometry)
        self._worker: Worker | None = None
        self._scan_worker: Worker | None = None
        self._update_worker: Worker | None = None
        self._paths: list[Path] = []
        self._spec: ScopeSpec | None = None
        self._job_lines: list[str] = []  # the running job's transcript, shown in full when it fails
        self._job_error = ""
        self._job_cancelled = False

        self.scope = ScopePanel()
        self.scope.restore(settings().value("recurse", False, type=bool), settings().value("kinds", "files"))
        self.scope.changed.connect(self._scope_changed)
        self.tabs = QTabWidget()
        self.pages: list = []
        for label, cls in TOOLS:
            page = cls()
            page.job_requested.connect(self.run_job)
            self.tabs.addTab(page, label)
            self.pages.append(page)

        self._build_menus()
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)  # Fluent: 16epx surface to edge, 12 between cards
        layout.setSpacing(12)
        layout.addWidget(self.scope)
        layout.addWidget(self.tabs)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)

        self.result = QLabel("")  # the last job's outcome; permanent, so the rescan's count does not replace it
        self.statusBar().addPermanentWidget(self.result)
        self.progress = QProgressBar(maximumWidth=140, textVisible=False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().showMessage("Choose a folder")
        if last := settings().value("last_dir", ""):
            self.scope.set_folder(Path(last))

    # --- construction ------------------------------------------------------
    def _build_menus(self) -> None:
        theme_menu = self.menuBar().addMenu("&View").addMenu("&Theme")
        group = QActionGroup(self)
        current = settings().value("theme", "System")
        for name in ("System", "Light", "Dark"):
            action = QAction(name, self, checkable=True, checked=(name == current))
            action.triggered.connect(partial(self._set_theme, name))
            group.addAction(action)
            theme_menu.addAction(action)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction("Check for &Updates...", self, triggered=lambda: self._check_updates(manual=True)))
        self.startup_check = QAction("Check on &Startup", self, checkable=True, checked=check_on_startup())
        self.startup_check.toggled.connect(lambda on: settings().setValue("check_updates", on))
        help_menu.addAction(self.startup_check)
        help_menu.addSeparator()
        help_menu.addAction(QAction("Open &Log File", self, triggered=self._open_log))
        help_menu.addAction(QAction("&About", self, triggered=self._about))

    def _set_theme(self, name: str) -> None:
        settings().setValue("theme", name)
        apply_scheme(name)

    def _open_log(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, f"{APP_NAME} {__version__}\n\nLog file: {LOG_FILE}")

    # --- updates -----------------------------------------------------------
    def _check_updates(self, manual: bool) -> None:
        """Ask GitHub off the UI thread; a startup check (manual=False) stays silent unless there is news."""
        if self._update_worker is not None:
            return
        result: dict = {}
        self._update_worker = Worker(lambda: result.update(latest=latest_version()), parent=self)
        if manual:
            self._update_worker.failed.connect(lambda m: QMessageBox.warning(self, APP_NAME, f"Update check failed: {m}"))
        self._update_worker.finished.connect(lambda: self._on_update_checked(result.get("latest"), manual))
        self._update_worker.start()

    def _on_update_checked(self, latest: str | None, manual: bool) -> None:
        if self._update_worker is not None:
            self._update_worker.deleteLater()
        self._update_worker = None
        if latest is None:
            return  # failed: already reported if manual
        if is_newer(latest, __version__):
            answer = QMessageBox.question(
                self, APP_NAME, f"{APP_NAME} {latest} is available (you have {__version__}).\n\nOpen the download page?"
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(RELEASES_URL))
        elif manual:
            QMessageBox.information(self, APP_NAME, f"{APP_NAME} {__version__} is up to date.")

    # --- scope -------------------------------------------------------------
    def _scope_changed(self, spec: ScopeSpec | None) -> None:
        self._spec = spec
        if spec is not None:
            settings().setValue("last_dir", str(spec.folder))
            settings().setValue("recurse", spec.recurse)
            settings().setValue("kinds", spec.kinds)
        self.rescan()

    def rescan(self) -> None:
        """Scan the scope on a worker and hand the result to every tool page."""
        if self._spec is None or self._scan_worker is not None:
            return
        spec, found = self._spec, []
        self._scan_worker = Worker(lambda: found.extend(scan(spec)), parent=self)
        self._scan_worker.failed.connect(lambda m: self.scope.show_summary(m, error=True))
        self._scan_worker.finished.connect(lambda: self._on_scanned(spec, found))
        self._scan_worker.start()

    def _on_scanned(self, spec: ScopeSpec, found: list[Path]) -> None:
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
        self._scan_worker = None
        if spec != self._spec:  # the controls moved again while we were scanning
            self.rescan()
            return
        self._paths = found
        if not self.scope.summary.text().startswith("invalid"):
            self.scope.show_summary(f"{len(found)} item(s) in scope")
        self.statusBar().showMessage(f"{len(found)} item(s) in scope")
        for page in self.pages:
            page.set_items(found, spec.folder)

    # --- jobs --------------------------------------------------------------
    @Slot(str, object, object)
    def run_job(self, label: str, fn: Callable, done: Callable | None) -> None:
        """Run ``fn(log, progress, cancelled)`` off the UI thread, then ``done()`` on it, then rescan.

        ``done`` may return a string, the outcome for the status bar; otherwise "<label> finished" is shown.
        """
        if self._worker is not None:
            return
        self._job_lines, self._job_error, self._job_cancelled = [], "", False
        self.result.clear()
        job_log.info("--- %s ---", label)
        self._worker = Worker(lambda: fn(self._worker.message.emit, self._worker.progress.emit,
                                         self._worker.isInterruptionRequested), parent=self)
        self._worker.message.connect(self.log)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self._on_finished(label, done))
        self._set_busy(True)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.scope.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)  # spinning until the job reports its first count
            self.progress.setTextVisible(False)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(True)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.statusBar().showMessage("Working...")
        else:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()  # rescan reports the count

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._job_error = message  # reported by _on_finished, which always follows

    def _on_finished(self, label: str, done: Callable | None) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        self._set_busy(False)
        text = (done() if done is not None else None) or f"{label} finished"
        if self._job_error:
            text = f"{label} failed: {self._job_error}"
        elif self._job_cancelled:
            text = f"{label} cancelled - {text}"
        self.result.setForegroundRole(QPalette.ColorRole.BrightText if self._job_error else QPalette.ColorRole.WindowText)
        self.result.setText(text)
        if self._job_error:
            self._report_failure(label, self._job_error)
        self.rescan()

    def _report_failure(self, label: str, message: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, f"{label} failed: {message}\n\nFull details: {LOG_FILE}", parent=self)
        box.setDetailedText("\n".join(self._job_lines))
        box.exec()

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat("%v of %m")
        self.progress.setTextVisible(True)

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._job_cancelled = True
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling after the current folder...")

    def closeEvent(self, event: QCloseEvent) -> None:
        # Destroying a running QThread aborts the process; refuse to close until the job is done.
        if self._worker is not None:
            self.statusBar().showMessage("Still working - press Cancel or wait for it to finish")
            event.ignore()
            return
        for worker in (self._update_worker, self._scan_worker):
            if worker is not None:
                worker.wait()
        settings().setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    # --- logging -----------------------------------------------------------
    @Slot(str)
    def log(self, message: str) -> None:
        """A line from the running job: into the log file, and kept for the failure dialog."""
        (job_log.error if message.startswith("ERROR") else job_log.info)(message)
        self._job_lines.append(message)


def check_on_startup() -> bool:
    return settings().value("check_updates", True, type=bool)


def _follow_system_scheme(_scheme) -> None:
    """Repaint when the OS flips light/dark, but only while the app is set to follow it."""
    if settings().value("theme", "System") == "System":
        apply_scheme("System")


def _excepthook(exc_type, exc, tb) -> None:
    logging.getLogger("batch_file_manager").critical("unhandled exception", exc_info=(exc_type, exc, tb))
    QMessageBox.critical(None, APP_NAME, f"{exc}\n\nDetails: {LOG_FILE}")


def main() -> None:
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(asset_path("icon.ico"))))
    # The native Windows 11 style draws Fluent controls properly; Fusion is the fallback elsewhere.
    app.setStyle("windows11" if "windows11" in QStyleFactory.keys() else "Fusion")
    if "Segoe UI Variable Text" in QFontDatabase.families():
        font = QFont("Segoe UI Variable Text")
        font.setPointSizeF(10.5)  # Windows 11 Body: 14px regular
        app.setFont(font)
    apply_scheme(settings().value("theme", "System"))  # also installs the stylesheet
    QGuiApplication.styleHints().colorSchemeChanged.connect(_follow_system_scheme)
    window = MainWindow()
    window.show()
    # A folder from Send To or the command line opens the app scoped to it. arguments() has Qt's own flags stripped.
    for arg in app.arguments()[1:]:
        if window.scope.set_folder(Path(arg)):
            break
    if check_on_startup():
        QTimer.singleShot(1500, lambda: window._check_updates(manual=False))  # after the window has painted
    sys.exit(app.exec())
