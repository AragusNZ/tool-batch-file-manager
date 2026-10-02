"""Look and feel: asset lookup, Windows 11 palettes, the stylesheet, and the light/dark switch.

Colours are lifted from WinUI's Common_themeresources_any.xaml, with its alpha values pre-blended
onto the layer they sit on so Qt gets opaque colours. Two layers: the window is the base
(SolidBackgroundFillColorBase), group boxes are cards on it, controls sit on the cards.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

SCHEMES = {
    "System": Qt.ColorScheme.Unknown,
    "Light": Qt.ColorScheme.Light,
    "Dark": Qt.ColorScheme.Dark,
}

R = QPalette.ColorRole
LIGHT = {
    R.Window: "#F3F3F3",  # SolidBackgroundFillColorBase
    R.AlternateBase: "#FFFFFF",  # card, lifted from CardBackgroundFillColorDefault for contrast
    R.Base: "#FDFDFD",  # ControlFillColorDefault over card
    R.Button: "#FDFDFD",
    R.Midlight: "#F9F9F9",  # ControlFillColorSecondary (hover)
    R.Dark: "#F5F5F5",  # ControlFillColorTertiary (pressed)
    R.Mid: "#DCDCDC",  # Card/ControlStrokeColorDefault, darkened a step
    R.WindowText: "#1B1B1B",  # TextFillColorPrimary
    R.Text: "#1B1B1B",
    R.ButtonText: "#1B1B1B",
    R.PlaceholderText: "#5F5F5F",  # TextFillColorSecondary
    R.Highlight: "#005FB8",  # default accent, Dark1
    R.HighlightedText: "#FFFFFF",
    R.BrightText: "#C42B1C",  # SystemFillColorCritical - the log's error colour
    "disabled": "#A0A0A0",  # TextFillColorDisabled
}
DARK = {
    R.Window: "#202020",
    R.AlternateBase: "#2B2B2B",
    R.Base: "#373737",
    R.Button: "#373737",
    R.Midlight: "#3C3C3C",
    R.Dark: "#323232",
    R.Mid: "#4F4F4F",
    R.WindowText: "#FFFFFF",
    R.Text: "#FFFFFF",
    R.ButtonText: "#FFFFFF",
    R.PlaceholderText: "#CFCFCF",
    R.Highlight: "#60CDFF",  # default accent, Light2
    R.HighlightedText: "#000000",
    R.BrightText: "#FF99A4",
    "disabled": "#787878",
}

# Always on: card surfaces, the section header above each card, and spacing. Safe under any style - it only touches containers.
METRICS = """
QGroupBox {
    background: palette(alternate-base);
    border: 1px solid palette(mid);
    border-radius: 4px;
    margin-top: 24px;
    padding: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0;
    top: 2px;
    padding: 0;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 12px;
    top: -1px;
}
QSplitter::handle { background: transparent; }
QStatusBar::item { border: none; }
"""

# Fusion only. A border/background rule on a control replaces the style's own drawing, and the
# native windows11 style already draws Fluent controls better than a stylesheet can.
LOOK = """
QPushButton {
    min-height: 32px;
    padding: 0 12px;
    border: 1px solid palette(mid);
    border-radius: 4px;
    background: palette(button);
}
QPushButton:hover:enabled { background: palette(midlight); border-color: palette(highlight); }
QPushButton:pressed:enabled { background: palette(dark); }
QPushButton:disabled { border-color: palette(midlight); }
QListWidget, QPlainTextEdit {
    background: palette(base);
    border: 1px solid palette(mid);
    border-radius: 4px;
}
QListWidget::item { padding: 3px 4px; }
QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
"""


def asset_path(name: str) -> Path:
    """Locate a bundled asset. PyInstaller puts them under sys._MEIPASS - the _internal folder
    beside the exe in a --onedir build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "batch_file_manager" / "assets" / name


def stylesheet(style_name: str) -> str:
    return METRICS + (LOOK if style_name.lower() == "fusion" else "")


def _palette(colours: dict) -> QPalette:
    p = QPalette()
    for role, value in colours.items():
        if role != "disabled":
            p.setColor(role, QColor(value))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(colours["disabled"]))
    return p


def apply_scheme(name: str) -> None:
    """Force light or dark, or follow the OS with 'System'.

    setColorScheme alone is enough for the title bar on Windows but draws nothing under X11/Wayland,
    so the palette is always set explicitly too.
    """
    app = QApplication.instance()
    if app is None:
        return
    hints = QGuiApplication.styleHints()
    hints.setColorScheme(SCHEMES.get(name, Qt.ColorScheme.Unknown))
    effective = hints.colorScheme() if name == "System" else SCHEMES[name]
    app.setPalette(_palette(DARK if effective == Qt.ColorScheme.Dark else LIGHT))
    app.setStyleSheet(stylesheet(app.style().name()))
