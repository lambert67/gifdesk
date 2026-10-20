"""GifDesk - put animated GIFs on your Windows desktop.

Runs in the system tray. Import GIFs, then drag them anywhere on screen.
Right-click a GIF for its options; scroll over it to resize.
"""
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from string import Template

APP_NAME = "GifDesk"
VERSION = "2.2"
APP_ID = "GifDesk.App"  # Windows AppUserModelID: ties taskbar buttons to our shortcuts


def ensure_pyside():
    """First run: install PySide6 with a small progress window, then restart."""
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} setup")
    root.resizable(False, False)
    tk.Label(root, text=f"Setting up {APP_NAME} for the first time...\n"
                        "This downloads about 70 MB and takes a minute or two.",
             justify="left", padx=24, pady=16).pack()
    bar = ttk.Progressbar(root, mode="indeterminate", length=320)
    bar.pack(padx=24, pady=(0, 20))
    bar.start(12)
    result = {}

    def work():
        result["proc"] = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check",
             "PySide6-Essentials>=6.6"],
            capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        root.after(0, root.destroy)

    threading.Thread(target=work, daemon=True).start()
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.mainloop()

    proc = result.get("proc")
    if proc is None or proc.returncode != 0:
        tk.Tk().withdraw()
        details = (proc.stdout + proc.stderr)[-1500:] if proc else ""
        messagebox.showerror(f"{APP_NAME} setup", "Couldn't download what GifDesk needs. "
                             "Check your internet connection and try again.\n\n" + details)
        sys.exit(1)
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.exit(0)


ensure_pyside()

from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QIODevice, QLockFile, QObject, QPoint, QPointF, QRectF,
                            QSize, QSizeF, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QIcon,
                           QImageReader, QKeySequence, QMovie, QPainter, QPalette, QPen, QPixmap,
                           QTransform)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QDialog, QDoubleSpinBox,
                               QKeySequenceEdit, QScrollArea,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QSlider, QSpinBox, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

GIF_FILTER = "GIF images (*.gif)"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\GifDesk"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share") / "Programs" / APP_NAME
MIN_SCALE, MAX_SCALE = 0.05, 10.0
MIN_FPS, MAX_FPS = 0.5, 120.0


def data_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / APP_NAME
    (path / "library").mkdir(parents=True, exist_ok=True)
    return path


def is_gif(path):
    return Path(path).suffix.lower() == ".gif" and QMovie(str(path)).isValid()


def icon_pixmap(size=64):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setBrush(QColor("#6c5ce7"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 30, QFont.Bold))
    p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "G")
    p.end()
    return pix


def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 256):
        icon.addPixmap(icon_pixmap(size))
    return icon


def write_ico(path):
    """Windows .ico with every size the shell asks for, stored as PNGs."""
    import struct
    images = []
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        icon_pixmap(size).save(buf, "PNG")
        buf.close()
        images.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    Path(path).write_bytes(header + entries + blobs)


# ----- look & feel -----

PALETTES = {
    "dark": {"bg": "#1b1b21", "surface": "#24242c", "raised": "#2d2d37", "border": "#3a3a47",
             "text": "#ececf1", "muted": "#9d9dad", "accent": "#7c6ff0", "accent_hover": "#8f84f4",
             "on_accent": "#ffffff", "danger": "#e5484d", "select": "rgba(124, 111, 240, 0.28)"},
    "light": {"bg": "#f4f4f8", "surface": "#ffffff", "raised": "#ededf3", "border": "#d8d8e2",
              "text": "#1c1c24", "muted": "#6b6b7b", "accent": "#6c5ce7", "accent_hover": "#5a4ad8",
              "on_accent": "#ffffff", "danger": "#d93036", "select": "rgba(108, 92, 231, 0.14)"},
}

STYLESHEET = Template("""
QWidget { color: $text; }
QWidget#Window, QDialog, QMessageBox { background: $bg; }
QLabel#Title { font-size: 15pt; font-weight: 600; }
QLabel#Muted { color: $muted; }
QLabel#Section { color: $muted; font-size: 8pt; font-weight: 700; padding: 2px 2px 0 2px; }
QLabel#FieldLabel { color: $text; min-width: 64px; }
QFrame#Card { background: $surface; border: 1px solid $border; border-radius: 10px; }

QPushButton { background: $raised; border: 1px solid $border; border-radius: 6px;
              padding: 6px 14px; min-height: 20px; }
QPushButton:hover { border-color: $accent; }
QPushButton:pressed { background: $border; }
QPushButton:checked { background: $select; border-color: $accent; color: $text; }
QPushButton:disabled { color: $muted; background: $surface; border-color: $border; }
QPushButton#Primary { background: $accent; color: $on_accent; border-color: $accent; font-weight: 600; }
QPushButton#Primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#Danger:hover:enabled { background: $danger; border-color: $danger; color: #ffffff; }
QPushButton#IconButton { padding: 6px; min-width: 22px; }

QLineEdit, QSpinBox, QDoubleSpinBox { background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 5px 8px; selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }

QSlider { min-height: 22px; }
QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $surface; border: 3px solid $accent; width: 10px; height: 10px;
                             margin: -7px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: $accent; }

QListWidget#Grid { background: transparent; border: none; outline: none; }
QListWidget#Grid::item { background: $surface; border: 1px solid $border; border-radius: 10px;
                         margin: 5px; padding: 10px 6px 8px 6px; color: $text; }
QListWidget#Grid::item:hover { border-color: $accent; }
QListWidget#Grid::item:selected { background: $select; border: 1px solid $accent; color: $text; }

QLabel#DropZone { border: 2px dashed $border; border-radius: 14px; color: $muted; font-size: 11pt;
                  background: $surface; }
QLabel#DropOverlay { border: 2px dashed $accent; border-radius: 14px; color: $accent; font-size: 14pt;
                     font-weight: 600; background: $select; }

QMenu { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 6px 26px 6px 8px; border-radius: 5px; background: transparent; }
QMenu::item:selected { background: $select; color: $text; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }
QMenu::icon { padding-left: 8px; }

QLabel#Toast { padding: 10px 20px; font-size: 11pt; font-weight: 600; }
QLabel#Hint { color: $muted; font-size: 9pt; }
QLabel#Error { color: $danger; font-size: 9pt; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 4px 6px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
""")

# Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10) code points.
GLYPHS = {"import": "\ue8b5", "library": "\ue8f1", "add": "\ue710", "delete": "\ue74d", "search": "\ue721",
          "edit": "\ue70f", "size": "\ue740", "opacity": "\ue706", "rotate": "\ue7ad", "layer": "\ue81e",
          "copy": "\ue8c8", "remove": "\ue711", "eye": "\ue890", "unlock": "\ue785", "pause": "\ue769",
          "power": "\ue7e8", "folder": "\ue838", "close": "\ue8bb", "flip": "\ue8ab",
          "layouts": "\ue8a9", "settings": "\ue713", "monitor": "\ue7f4", "lock": "\ue72e",
          "link": "\ue71b", "download": "\ue896"}


class Theme:
    """Colours, fonts and icons; follows Windows light/dark mode."""

    def __init__(self):
        self.c = PALETTES["light"]
        self.glyph_font = None
        self.mode = "system"  # or "light" / "dark"

    def apply(self, qapp):
        if self.mode == "system":
            try:
                dark = qapp.styleHints().colorScheme() == Qt.ColorScheme.Dark
            except AttributeError:  # Qt older than 6.5
                dark = False
        else:
            dark = self.mode == "dark"
        self.c = PALETTES["dark" if dark else "light"]
        families = set(QFontDatabase.families())
        self.glyph_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), None)
        ui_font = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), None)
        if ui_font:
            qapp.setFont(QFont(ui_font, 10))
        qapp.setStyle("Fusion")
        qapp.setPalette(self.palette())
        qapp.setStyleSheet(STYLESHEET.substitute(self.c))

    def palette(self):
        c = {k: QColor(v) for k, v in self.c.items() if v.startswith("#")}
        pal = QPalette()
        for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "surface"),
                          (QPalette.AlternateBase, "raised"), (QPalette.Text, "text"), (QPalette.Button, "raised"),
                          (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                          (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "surface"),
                          (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted"), (QPalette.Mid, "border"),
                          (QPalette.Link, "accent")):
            pal.setColor(role, c[key])
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(QPalette.Disabled, role, c["muted"])
        return pal

    def icon(self, name, color=None, mirror=False):
        if not self.glyph_font:
            return QIcon()
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.TextAntialiasing)
        font = QFont(self.glyph_font)
        font.setPixelSize(44)
        p.setFont(font)
        p.setPen(QColor(color or self.c["text"]))
        p.drawText(pix.rect(), Qt.AlignCenter, GLYPHS[name])
        p.end()
        if mirror:
            pix = pix.transformed(QTransform().scale(-1, 1))
        return QIcon(pix)

    def check_icon(self, checked=True):
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        if checked:
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(self.c["accent"]), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline([QPointF(14, 34), QPointF(27, 47), QPointF(50, 19)])
            p.end()
        return QIcon(pix)


THEME = Theme()


class Menu(QMenu):
    """A rounded, themed menu."""

    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def sub(self, title, icon=None):
        menu = Menu(title, self)
        if icon is not None:
            menu.setIcon(icon)
        self.addMenu(menu)
        return menu

    def check(self, text, checked, slot):
        """A menu entry with a tick when it's on."""
        act = self.addAction(THEME.check_icon(checked), text)
        act.triggered.connect(slot)
        return act


# ----- Windows install / shortcuts / uninstall -----

def script_path():
    return Path(__file__).resolve()


def is_installed_copy():
    return script_path().parent == INSTALL_DIR.resolve()


def launcher():
    """pyw.exe survives Python upgrades; fall back to this Python's pythonw.exe."""
    found = shutil.which("pyw")
    if found:
        return Path(found)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def launch_command(script=None):
    return f'"{launcher()}" "{script or script_path()}"'


def shell_folder(csidl):
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def shortcut_paths():
    return [shell_folder(0x02) / f"{APP_NAME}.lnk",   # Start menu > Programs
            shell_folder(0x10) / f"{APP_NAME}.lnk"]   # Desktop (follows OneDrive)


AUMID_PROPS = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"  # System.AppUserModel.* property set
IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"


def _com():
    """Just enough COM, via plain ctypes, to make shortcuts and label windows for the taskbar."""
    import ctypes
    from ctypes import HRESULT, POINTER, WINFUNCTYPE, byref, c_ulong, c_void_p
    from types import SimpleNamespace

    class GUID(ctypes.Structure):
        _fields_ = [("d1", c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("value", c_void_p), ("pad", c_void_p)]

    def guid(text):
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(text, byref(g))
        return g

    def call(obj, index, restype, argtypes, *args):
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        return WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[index])(obj, *args)

    def release(obj):
        call(obj, 2, c_ulong, ())

    def query(obj, iid):
        out = c_void_p()
        call(obj, 0, HRESULT, (POINTER(GUID), POINTER(c_void_p)), byref(guid(iid)), byref(out))
        return out

    def set_app_props(store, values):
        """Write {pid: text} into System.AppUserModel.* on an IPropertyStore, then commit."""
        for pid, text in values.items():
            key = PROPERTYKEY(guid(AUMID_PROPS), pid)
            buf = ctypes.create_unicode_buffer(text)
            value = PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, c_void_p), None)  # VT_LPWSTR
            call(store, 6, HRESULT, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(key), byref(value))
        call(store, 7, HRESULT, ())  # Commit

    try:
        ctypes.oledll.ole32.CoInitialize(None)
    except OSError:
        pass  # COM is already set up on this thread
    return SimpleNamespace(GUID=GUID, guid=guid, call=call, release=release, query=query,
                           set_app_props=set_app_props)


def make_shortcut(lnk, target, args, icon, workdir):
    """Create a .lnk with the Shell's IShellLink COM object."""
    import ctypes
    from ctypes import HRESULT, byref, c_int, c_void_p
    from ctypes.wintypes import BOOL, LPCWSTR
    com = _com()
    link = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(com.guid("{00021401-0000-0000-C000-000000000046}")), None, 1,
                                         byref(com.guid("{000214F9-0000-0000-C000-000000000046}")), byref(link))
    try:
        com.call(link, 20, HRESULT, (LPCWSTR,), str(target))             # SetPath
        com.call(link, 11, HRESULT, (LPCWSTR,), args)                    # SetArguments
        com.call(link, 9, HRESULT, (LPCWSTR,), str(workdir))             # SetWorkingDirectory
        com.call(link, 17, HRESULT, (LPCWSTR, c_int), str(icon), 0)      # SetIconLocation
        com.call(link, 7, HRESULT, (LPCWSTR,), "Animated GIFs on your desktop")  # SetDescription
        # Our AppUserModelID, so the running app's windows group under this shortcut.
        store = com.query(link, IID_PROPERTY_STORE)
        try:
            com.set_app_props(store, {5: APP_ID})
        finally:
            com.release(store)
        persist = com.query(link, "{0000010B-0000-0000-C000-000000000046}")  # IPersistFile
        try:
            lnk.parent.mkdir(parents=True, exist_ok=True)
            com.call(persist, 6, HRESULT, (LPCWSTR, BOOL), str(lnk), True)  # Save
        finally:
            com.release(persist)
    finally:
        com.release(link)


def taskbar_icon_file():
    """An .ico the taskbar can show for our windows (written once per version)."""
    installed = INSTALL_DIR / f"GifDesk-{VERSION}.ico"
    if installed.exists():
        return installed
    path = data_dir() / f"GifDesk-{VERSION}.ico"
    if not path.exists():
        write_ico(path)
    return path


def label_for_taskbar(widget):
    """Tell the Windows taskbar this window is GifDesk, not Python.

    Sets the window's app ID, icon, name and relaunch command, so its taskbar button shows
    the GifDesk icon and groups with the pinned GifDesk shortcut."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import byref, c_void_p
        com = _com()
        script = INSTALL_DIR / "GifDesk.pyw"
        store = c_void_p()
        ctypes.oledll.shell32.SHGetPropertyStoreForWindow(
            c_void_p(int(widget.winId())), byref(com.guid(IID_PROPERTY_STORE)), byref(store))
        try:
            # Relaunch command, name and icon go in together; the ID goes last.
            com.set_app_props(store, {2: launch_command(script if script.exists() else None),
                                      4: APP_NAME,
                                      3: f"{taskbar_icon_file()},0",
                                      5: APP_ID})
        finally:
            com.release(store)
    except OSError:
        pass  # cosmetic only; never stop the app over it


def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(enabled, script=None):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command(script))
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def install_app():
    """Copy into %LOCALAPPDATA%\\Programs\\GifDesk and add shortcuts + a Settings > Apps entry.

    Returns a list of problems (empty when everything worked)."""
    import winreg
    problems = []
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    target = INSTALL_DIR / "GifDesk.pyw"
    shutil.copy2(script_path(), target)
    for old in INSTALL_DIR.glob("GifDesk*.ico"):
        old.unlink(missing_ok=True)
    # A new name each version, so Windows' icon cache can't keep showing an old icon.
    icon = INSTALL_DIR / f"GifDesk-{VERSION}.ico"
    write_ico(icon)
    for lnk in shortcut_paths():
        try:
            make_shortcut(lnk, launcher(), f'"{target}"', icon, INSTALL_DIR)
        except OSError as e:
            problems.append(f"Couldn't create {lnk}: {e}")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", VERSION),
                            ("DisplayIcon", str(icon)), ("Publisher", "Personal"),
                            ("InstallLocation", str(INSTALL_DIR)),
                            ("UninstallString", f"{launch_command(target)} --uninstall")):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    if startup_enabled():
        set_startup(True, target)
    return problems


def offer_install(icon):
    """When run from a download, offer to install. Returns True if the installed copy was launched."""
    if sys.platform != "win32" or is_installed_copy():
        return False
    box = QMessageBox()
    box.setWindowTitle(APP_NAME)
    box.setWindowIcon(icon)
    box.setIconPixmap(icon_pixmap(64))
    updating = (INSTALL_DIR / "GifDesk.pyw").exists()
    box.setText(f"{'Update' if updating else 'Install'} {APP_NAME}?")
    box.setInformativeText("Adds GifDesk to your Start menu and desktop so you can open it like any other app "
                           "(and pin it to the taskbar). Afterwards you can delete the downloaded files.\n\n"
                           "Your GIFs and layout are kept.")
    install = box.addButton("Update" if updating else "Install", QMessageBox.AcceptRole)
    box.addButton("Just run it", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not install:
        return False
    try:
        problems = install_app()
    except OSError as e:
        QMessageBox.warning(None, APP_NAME, f"Install failed, running from here instead:\n{e}")
        return False
    msg = f"{APP_NAME} is installed. Find it in the Start menu or on your desktop."
    if problems:
        msg += "\n\nSome shortcuts couldn't be made:\n" + "\n".join(problems)
    QMessageBox.information(None, APP_NAME, msg)
    return True


def uninstall_app(release=None):
    """Ask, then remove shortcuts, startup entry, Settings > Apps entry and program files."""
    import winreg
    answer = QMessageBox.question(None, APP_NAME, f"Uninstall {APP_NAME}?")
    if answer != QMessageBox.Yes:
        return False
    keep = QMessageBox.question(None, APP_NAME, "Keep your imported GIFs and layout, in case you reinstall later?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
    if release:
        release()
    for lnk in shortcut_paths():
        lnk.unlink(missing_ok=True)
    set_startup(False)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    if not keep:
        shutil.rmtree(data_dir(), ignore_errors=True)
    QMessageBox.information(None, APP_NAME, f"{APP_NAME} has been uninstalled.")
    return True


class Store:
    """Layout and settings, saved as JSON with a backup copy.

    Imported GIFs are copied into the library folder, so moving or deleting
    the original file never breaks the desktop.
    """

    def __init__(self):
        self.dir = data_dir()
        self.lib = self.dir / "library"
        self.path = self.dir / "layout.json"
        self.backup = self.dir / "layout.json.bak"
        self.data = {"layouts": {"Default": []}, "settings": {}}
        for p in (self.path, self.backup):
            try:
                loaded = json.loads(p.read_text("utf-8"))
                if isinstance(loaded.get("items"), list) and "layouts" not in loaded:
                    loaded["layouts"] = {"Default": loaded.pop("items")}  # from before layouts existed
                if isinstance(loaded.get("layouts"), dict) and loaded["layouts"]:
                    self.data = loaded
                    break
            except (OSError, ValueError, AttributeError):
                continue
        self.data.setdefault("settings", {})
        if self.settings.get("current_layout") not in self.layouts:
            self.settings["current_layout"] = next(iter(self.layouts))
        self._purge_pending_deletes()

    @property
    def layouts(self):
        return self.data["layouts"]

    @property
    def current_layout(self):
        return self.settings["current_layout"]

    @property
    def items(self):
        """The GIFs in the current layout."""
        return self.layouts[self.current_layout]

    @property
    def settings(self):
        return self.data["settings"]

    def save(self):
        tmp = self.dir / "layout.json.tmp"
        tmp.write_text(json.dumps(self.data, indent=2), "utf-8")
        if self.path.exists():
            shutil.copy2(self.path, self.backup)
        os.replace(tmp, self.path)

    def import_gif(self, src):
        src = Path(src)
        name = f"{uuid.uuid4().hex[:8]}_{src.name}"
        shutil.copy2(src, self.lib / name)
        return name

    def import_bytes(self, data, filename):
        name = f"{uuid.uuid4().hex[:8]}_{filename}"
        (self.lib / name).write_bytes(data)
        return name

    def library_files(self):
        return sorted((p.name for p in self.lib.glob("*.gif")), key=lambda n: n[9:].lower())

    def delete_file(self, name):
        try:
            (self.lib / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Windows can keep the file locked briefly; finish on next start.
            self.settings.setdefault("pending_delete", []).append(name)

    def _purge_pending_deletes(self):
        still = []
        for name in self.settings.get("pending_delete", []):
            try:
                (self.lib / name).unlink(missing_ok=True)
            except OSError:
                still.append(name)
        self.settings["pending_delete"] = still


class GifWindow(QWidget):
    """One GIF floating on the desktop."""

    def __init__(self, app, item):
        super().__init__(None)
        self.app = app
        self.item = item
        self.drag_offset = None
        self.hover = False
        self.editor = None

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.ClickFocus)  # so arrow keys can nudge it
        self.setWindowTitle(self.display_name())
        self.setWindowIcon(app.icon)

        self.movie = QMovie(str(app.store.lib / item["file"]), parent=self)
        self.movie.setCacheMode(QMovie.CacheAll)
        self.movie.jumpToFrame(0)
        size = self.movie.currentImage().size()
        self.base_size = size if size.isValid() and not size.isEmpty() else QSize(200, 200)
        self.native_fps = self.measure_fps()
        self.movie.jumpToFrame(0)
        old_speed = item.pop("speed", 100)  # older layouts stored a speed % instead of FPS
        if old_speed != 100 and item["fps"] is None:
            item["fps"] = round(self.native_fps * old_speed / 100, 1)
        self.movie.frameChanged.connect(self.update)
        self.apply_speed()
        if not item["paused"]:
            self.movie.start()

        self.apply_flags()
        self.apply_geometry(keep_center=False)
        self.setWindowOpacity(item["opacity"])
        self.move(item["x"], item["y"])

    def display_name(self):
        return self.item["file"][9:]

    def measure_fps(self):
        delays = []
        for i in range(max(1, self.movie.frameCount())):
            if not self.movie.jumpToFrame(i):
                break
            delay = self.movie.nextFrameDelay()
            delays.append(delay if delay > 0 else 100)
        return 1000 * len(delays) / sum(delays) if delays else 10.0

    def current_fps(self):
        return self.item["fps"] or self.native_fps

    # ----- state -----
    def changed(self):
        self.app.schedule_save()

    def apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if self.item["layer"] == "top":
            flags |= Qt.WindowStaysOnTopHint
        elif self.item["layer"] == "bottom":
            flags |= Qt.WindowStaysOnBottomHint
        if self.item["locked"]:
            flags |= Qt.WindowTransparentForInput
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def content_size(self):
        s = self.item["scale"]
        return QSizeF(self.base_size.width() * s, self.base_size.height() * s)

    def apply_geometry(self, keep_center=True):
        center = self.geometry().center()
        box = QTransform().rotate(self.item["rotation"]).mapRect(QRectF(QPointF(0, 0), self.content_size()))
        self.setFixedSize(max(8, math.ceil(box.width() - 0.01)), max(8, math.ceil(box.height() - 0.01)))
        if keep_center:
            self.move(center - QPoint(self.width() // 2, self.height() // 2))
            self.remember_pos()

    def remember_pos(self):
        """Save the position, plus which monitor it's on and where on that monitor."""
        self.item["x"], self.item["y"] = self.x(), self.y()
        center = self.geometry().center()
        screen = QGuiApplication.screenAt(center) or self.screen()
        g = screen.geometry()
        self.item["screen"] = screen.name()
        self.item["rel"] = [round((center.x() - g.x()) / max(1, g.width()), 4),
                            round((center.y() - g.y()) / max(1, g.height()), 4)]

    def move_to_screen(self, screen):
        here = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        g, t = here.geometry(), screen.geometry()
        c = self.geometry().center()
        rel_x, rel_y = (c.x() - g.x()) / max(1, g.width()), (c.y() - g.y()) / max(1, g.height())
        target = QPoint(t.x() + round(rel_x * t.width()), t.y() + round(rel_y * t.height()))
        self.move(target - QPoint(self.width() // 2, self.height() // 2))
        self.remember_pos()
        self.changed()

    def apply_speed(self):
        self.movie.setSpeed(max(1, round(self.current_fps() / self.native_fps * 100)))

    def set_scale(self, scale):
        self.set_option("scale", min(MAX_SCALE, max(MIN_SCALE, scale)))

    def rotate_by(self, degrees):
        r = (self.item["rotation"] + degrees) % 360
        self.set_option("rotation", r - 360 if r > 180 else r)

    def set_option(self, key, value):
        self.item[key] = value
        if key in ("scale", "rotation", "flip", "flip_v"):
            self.apply_geometry()
        elif key in ("layer", "locked"):
            self.apply_flags()
        elif key == "opacity":
            self.setWindowOpacity(value)
        elif key == "fps":
            self.apply_speed()
        elif key == "paused":
            if not value and self.movie.state() == QMovie.NotRunning:
                self.movie.start()
            else:
                self.movie.setPaused(value)
        self.update()
        self.changed()

    def open_editor(self):
        if self.editor is None:
            self.editor = EditDialog(self)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def release(self):
        if self.editor is not None:
            self.editor.close()
        self.movie.stop()
        self.movie.setFileName("")
        self.close()
        self.deleteLater()

    # ----- painting -----
    def paintEvent(self, _event):
        p = QPainter(self)
        # Nearly invisible fill so the whole box can be grabbed, not just opaque pixels.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        frame = self.movie.currentPixmap()
        size = self.content_size()
        p.setRenderHint(QPainter.SmoothPixmapTransform, not self.item["pixel_art"])
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self.item["rotation"])
        p.scale(-1 if self.item["flip"] else 1, -1 if self.item["flip_v"] else 1)
        p.drawPixmap(QRectF(-size.width() / 2, -size.height() / 2, size.width(), size.height()),
                     frame, QRectF(frame.rect()))
        p.resetTransform()
        if self.hover and not self.item["locked"]:
            p.setPen(QPen(QColor(108, 92, 231, 220), 1, Qt.DashLine))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    # ----- mouse -----
    def enterEvent(self, _event):
        self.hover = True
        self.update()

    def leaveEvent(self, _event):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag_offset is not None and e.buttons() & Qt.LeftButton:
            pos = e.globalPosition().toPoint() - self.drag_offset
            if not e.modifiers() & Qt.AltModifier:  # hold Alt to place freely
                pos = self.app.snap(self, pos)
            self.move(pos)

    def keyPressEvent(self, e):
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        delta = {Qt.Key_Left: QPoint(-step, 0), Qt.Key_Right: QPoint(step, 0),
                 Qt.Key_Up: QPoint(0, -step), Qt.Key_Down: QPoint(0, step)}.get(e.key())
        if delta is None:
            return super().keyPressEvent(e)
        self.move(self.pos() + delta)
        self.remember_pos()
        self.changed()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            self.remember_pos()
            self.changed()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_option("paused", not self.item["paused"])

    def wheelEvent(self, e):
        delta = e.angleDelta().y() or e.angleDelta().x()  # Windows turns Shift+wheel sideways
        if not delta:
            return
        step = 1.1 if delta > 0 else 1 / 1.1
        if e.modifiers() & Qt.ShiftModifier:
            self.rotate_by(15 if delta > 0 else -15)
        elif e.modifiers() & Qt.ControlModifier:
            self.set_option("opacity", round(min(1.0, max(0.1, self.item["opacity"] * step)), 2))
        else:
            self.set_scale(self.item["scale"] * step)

    # ----- drag & drop GIF files onto a GIF -----
    def dragEnterEvent(self, e):
        if local_files(e.mimeData()) or web_links(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.app.import_mime(e.mimeData(), place=True, at=e.position().toPoint() + self.pos())

    # ----- right-click menu -----
    def contextMenuEvent(self, e):
        item = self.item
        m = Menu(parent=self)
        title = m.addAction(self.display_name())
        title.setEnabled(False)
        m.addSeparator()
        m.addAction(THEME.icon("edit"), "Edit\u2026", self.open_editor)
        m.addSeparator()

        size = m.sub("Size", THEME.icon("size"))
        for pct in (25, 50, 75, 100, 150, 200, 300):
            size.check(f"{pct}%", abs(item["scale"] * 100 - pct) < 0.5, lambda _=False, v=pct: self.set_scale(v / 100))
        size.addSeparator()
        size.addAction("Custom\u2026", self.ask_custom_size)

        opacity = m.sub("Opacity", THEME.icon("opacity"))
        for pct in (100, 85, 70, 50, 30):
            opacity.check(f"{pct}%", round(item["opacity"] * 100) == pct,
                          lambda _=False, v=pct: self.set_option("opacity", v / 100))

        rotate = m.sub("Rotate", THEME.icon("rotate"))
        rotate.addAction(THEME.icon("rotate"), "90\u00b0 clockwise", lambda: self.rotate_by(90))
        rotate.addAction(THEME.icon("rotate", mirror=True), "90\u00b0 counter-clockwise", lambda: self.rotate_by(-90))
        rotate.addAction("180\u00b0", lambda: self.rotate_by(180))
        rotate.addSeparator()
        rotate.addAction("Reset rotation", lambda: self.set_option("rotation", 0))

        layer = m.sub("Layer", THEME.icon("layer"))
        for text, value in (("Always on top", "top"), ("Normal", "normal"), ("On desktop (behind windows)", "bottom")):
            layer.check(text, item["layer"] == value, lambda _=False, v=value: self.set_option("layer", v))

        screens = QGuiApplication.screens()
        if len(screens) > 1:
            here = QGuiApplication.screenAt(self.geometry().center())
            monitors = m.sub("Move to monitor", THEME.icon("monitor"))
            for i, screen in enumerate(screens, start=1):
                size = screen.size()
                text = f"Monitor {i}  ({size.width()} \u00d7 {size.height()})"
                if screen is QGuiApplication.primaryScreen():
                    text += "  \u2013 main"
                monitors.check(text, screen is here, lambda _=False, s=screen: self.move_to_screen(s))

        m.addSeparator()
        for text, key in (("Flip horizontally", "flip"), ("Flip vertically", "flip_v"),
                          ("Pixel-art scaling", "pixel_art"), ("Paused", "paused"), ("Lock (click-through)", "locked")):
            m.check(text, item[key], lambda _=False, k=key: self.set_option(k, not self.item[k]))
        m.addSeparator()
        m.addAction(THEME.icon("copy"), "Duplicate", lambda: self.app.add_to_desktop(
            item["file"], at=self.pos() + QPoint(30, 30), template=item))
        m.addAction(THEME.icon("remove"), "Remove from desktop", lambda: self.app.remove_window(self))
        m.exec(e.globalPos())

    def ask_custom_size(self):
        pct, ok = QInputDialog.getInt(self, APP_NAME, "Size (%):", round(self.item["scale"] * 100),
                                      round(MIN_SCALE * 100), round(MAX_SCALE * 100))
        if ok:
            self.set_scale(pct / 100)


# ----- getting GIFs from the web -----

USER_AGENT = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) GifDesk/{VERSION}"
MAX_GIF_BYTES = 40 * 1024 * 1024
GIF_MAGIC = (b"GIF87a", b"GIF89a")


def http_get(url, limit=MAX_GIF_BYTES):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"That file is too big (over {limit // (1024 * 1024)} MB).")
        return data, resp.headers.get("Content-Type", ""), resp.geturl()


def safe_filename(text, fallback="gif"):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", text or "").strip(" .")[:60]
    return (text or fallback) + ".gif"


def name_from_url(url):
    from urllib.parse import unquote, urlparse
    stem = Path(unquote(urlparse(url).path)).stem
    return safe_filename("" if stem.lower() in ("giphy", "tenor", "giphy-downsized", "") else stem)


def gif_candidates(url, page=None):
    """Likely direct .gif URLs for a link: known GIPHY/Tenor patterns, then the page's preview image."""
    from urllib.parse import urljoin
    found = []
    m = re.search(r"giphy\.com/media/(?:v1\.[^/]+/)?([A-Za-z0-9]+)/", url) or \
        re.search(r"giphy\.com/(?:gifs|stickers|embed)/(?:[^/?#]*-)?([A-Za-z0-9]+)(?:[/?#]|$)", url)
    if m:
        found.append(f"https://media.giphy.com/media/{m.group(1)}/giphy.gif")
    m = re.match(r"(https?://media\d*\.tenor\.com/(?:m/)?)([A-Za-z0-9_-]+?)[A-Za-z0-9]{5}/([^/?#]+?)\.\w+(?:$|\?)", url)
    if m:
        found.append(f"{m.group(1)}{m.group(2)}AAAAC/{m.group(3)}.gif")  # Tenor's code for the GIF rendition
    if page:
        metas = re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\'][^>]*'
                           r'content=["\']([^"\']+)', page, re.I)
        metas += re.findall(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']'
                            r'(?:og:image(?::url)?|twitter:image)["\']', page, re.I)
        anywhere = re.findall(r'https?://[^"\'\s<>()]+?\.gif(?:\?[^"\'\s<>()]*)?', page)
        for link in metas + anywhere:
            found.append(urljoin(url, html.unescape(link)))
    unique = []
    for link in found:
        if link not in unique:
            unique.append(link)
    return unique[:6]


def page_title(page):
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)', page, re.I) or \
        re.search(r"<title>([^<]+)</title>", page, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def download_gif(url):
    """Get GIF bytes from a direct link, a GIPHY/Tenor link, or a web page showing a GIF.

    Returns (data, suggested file name)."""
    tried = set()
    for candidate in gif_candidates(url) + [url]:
        tried.add(candidate)
        try:
            data, ctype, final = http_get(candidate)
        except Exception:
            if candidate == url:
                raise
            continue
        if data[:6] in GIF_MAGIC:
            return data, name_from_url(final)
        if candidate == url and ("html" in ctype or b"<html" in data[:4000].lower()):
            page = data.decode("utf-8", "ignore")
            for link in gif_candidates(url, page):
                if link in tried:
                    continue
                tried.add(link)
                try:
                    found, _ctype, final = http_get(link)
                except Exception:
                    continue
                if found[:6] in GIF_MAGIC:
                    title = page_title(page)
                    return found, safe_filename(title) if title else name_from_url(final)
    raise ValueError("Couldn't find a GIF at that link.")


class _Relay(QObject):
    done = Signal(object, object, object)  # callback, result, error

    def __init__(self):
        super().__init__()
        self.done.connect(lambda callback, result, error: callback(result, error))


_RELAY = []
_POOL = []


def run_async(fn, callback, *args):
    """Run fn(*args) on a worker thread, then callback(result, error) back on the UI thread."""
    from concurrent.futures import ThreadPoolExecutor
    if not _RELAY:
        _RELAY.append(_Relay())
        _POOL.append(ThreadPoolExecutor(max_workers=6))

    def job():
        try:
            result, error = fn(*args), None
        except Exception as e:  # reported to the callback
            result, error = None, e
        _RELAY[0].done.emit(callback, result, error)

    _POOL[0].submit(job)


def shutdown_workers():
    if _POOL:
        _POOL[0].shutdown(wait=False, cancel_futures=True)


def web_links(mime):
    """http(s) links in dropped/pasted data."""
    urls = [u.toString() for u in (mime.urls() if mime.hasUrls() else []) if u.scheme() in ("http", "https")]
    if not urls and mime.hasText():
        text = mime.text().strip()
        if re.match(r"https?://\S+$", text):
            urls = [text]
    return urls


def local_files(mime):
    return [u.toLocalFile() for u in (mime.urls() if mime.hasUrls() else []) if u.isLocalFile()]


def card_icon(frame, size):
    canvas = QPixmap(size, size)  # same-size icons keep the cards aligned
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.drawPixmap((size - frame.width()) // 2, (size - frame.height()) // 2, frame)
    p.end()
    return QIcon(canvas)


class Toast(QLabel):
    """A short message near the bottom of the screen, e.g. after a hotkey."""

    def __init__(self):
        super().__init__(None)
        self.setObjectName("Toast")
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAlignment(Qt.AlignCenter)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(THEME.c["border"]), 1))
        p.setBrush(QColor(THEME.c["surface"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.end()
        super().paintEvent(e)

    def flash(self, text, ms=1500):
        self.setText(text)
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 56)
        self.show()
        self.raise_()
        self.timer.start(ms)


HOTKEY_ACTIONS = [("toggle_hidden", "Show / hide all GIFs", "Ctrl+Alt+G"),
                  ("toggle_lock", "Lock / unlock all GIFs", "Ctrl+Alt+L"),
                  ("next_layout", "Next layout", "Ctrl+Alt+N")]
WIN_MODS = ((Qt.AltModifier, 0x1), (Qt.ControlModifier, 0x2), (Qt.ShiftModifier, 0x4), (Qt.MetaModifier, 0x8))
MOD_NOREPEAT = 0x4000


def hotkey_to_win(text):
    """'Ctrl+Alt+G' -> (modifiers, virtual-key) for RegisterHotKey, or None if unsupported."""
    seq = QKeySequence(text)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key = combo.key().value
    mods = 0
    for qt_mod, win_mod in WIN_MODS:
        if combo.keyboardModifiers() & qt_mod:
            mods |= win_mod
    K = Qt.Key
    if K.Key_A.value <= key <= K.Key_Z.value or K.Key_0.value <= key <= K.Key_9.value:
        vk = key  # same as ASCII
    elif K.Key_F1.value <= key <= K.Key_F24.value:
        vk = 0x70 + key - K.Key_F1.value
    else:
        vk = {K.Key_Space: 0x20, K.Key_PageUp: 0x21, K.Key_PageDown: 0x22, K.Key_End: 0x23, K.Key_Home: 0x24,
              K.Key_Left: 0x25, K.Key_Up: 0x26, K.Key_Right: 0x27, K.Key_Down: 0x28, K.Key_Insert: 0x2D,
              K.Key_Delete: 0x2E, K.Key_Pause: 0x13}.get(combo.key())
        if vk is None:
            return None
    if not mods and not (0x70 <= vk <= 0x87):
        return None  # a bare letter would steal normal typing
    return mods | MOD_NOREPEAT, vk


def hotkey_label(text):
    return QKeySequence(text).toString(QKeySequence.NativeText) if text else ""


class Hotkeys(QWidget):
    """System-wide hotkeys via RegisterHotKey on a hidden window."""

    def __init__(self, handlers):
        super().__init__(None)
        self.handlers = handlers
        self.ids = {}

    def register(self, bindings):
        """bindings: {action: 'Ctrl+Alt+G'}. Returns the key texts that couldn't be registered."""
        self.unregister_all()
        if sys.platform != "win32":
            return []
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = ctypes.c_void_p(int(self.winId()))
        failed = []
        for i, (action, text) in enumerate(bindings.items(), start=1):
            if not text or action not in self.handlers:
                continue
            parsed = hotkey_to_win(text)
            if parsed and user32.RegisterHotKey(hwnd, i, parsed[0], parsed[1]):
                self.ids[i] = action
            else:
                failed.append(text)
        return failed

    def unregister_all(self):
        if sys.platform == "win32" and self.ids:
            import ctypes
            hwnd = ctypes.c_void_p(int(self.winId()))
            for i in self.ids:
                ctypes.windll.user32.UnregisterHotKey(hwnd, i)
        self.ids.clear()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.ids:  # WM_HOTKEY
                QTimer.singleShot(0, self.handlers[self.ids[msg.wParam]])
                return True, 0
        return super().nativeEvent(event_type, message)


def first_frame(path, size):
    img = QImageReader(str(path)).read()
    if img.isNull():
        return QPixmap(), QSize()
    pix = QPixmap.fromImage(img)
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation), img.size()


def label(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    return widget


def button(text, name=None, icon=None, slot=None):
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    if icon is not None:
        btn.setIcon(icon)
    if slot is not None:
        btn.clicked.connect(slot)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class EditDialog(QDialog):
    """Live editor for one GIF on the desktop. Cancel puts everything back."""

    KEYS = ("scale", "rotation", "flip", "flip_v", "fps", "opacity")

    def __init__(self, win):
        super().__init__(None)
        self.win = win
        self.original = {k: win.item[k] for k in self.KEYS}
        self.sliders = {}
        self.setWindowTitle(f"Edit \u2013 {win.display_name()}")
        self.setWindowIcon(win.app.icon)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(460)

        # Header: thumbnail, name, facts about the file
        thumb = QLabel()
        self.thumb_movie = QMovie(parent=self)
        self.thumb_movie.setScaledSize(win.base_size.scaled(56, 56, Qt.KeepAspectRatio))
        thumb.setMovie(self.thumb_movie)
        thumb.setFixedSize(60, 60)
        thumb.setAlignment(Qt.AlignCenter)
        name = label(QFontMetrics(self.font()).elidedText(win.display_name(), Qt.ElideMiddle, 320), "Title")
        frames = max(1, win.movie.frameCount())
        facts = label(f"{win.base_size.width()} \u00d7 {win.base_size.height()} px  \u00b7  "
                      f"{frames} frame{'s' if frames != 1 else ''}  \u00b7  {win.native_fps:.1f} fps", "Muted")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(name)
        titles.addWidget(facts)
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(thumb)
        header.addLayout(titles, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addSpacing(8)

        # Transform
        form = self.card(layout, "TRANSFORM")
        row, self.scale = self.linked(round(MIN_SCALE * 100), round(MAX_SCALE * 100), "%",
                                      lambda v: win.set_scale(v / 100))
        self.field(form, "Scale", row)
        row, self.rotation = self.linked(-180, 180, "\u00b0", lambda v: win.set_option("rotation", v))
        for deg, mirror, tip in ((-90, True, "Rotate 90\u00b0 counter-clockwise"), (90, False, "Rotate 90\u00b0 clockwise")):
            btn = button("" if THEME.glyph_font else ("\u27f2" if mirror else "\u27f3"), "IconButton",
                         THEME.icon("rotate", mirror=mirror), lambda _=False, d=deg: self.turn(d))
            btn.setToolTip(tip)
            row.addWidget(btn)
        self.field(form, "Rotation", row)
        flips = QHBoxLayout()
        flips.setSpacing(8)
        self.flip = button("Horizontal")
        self.flip.setCheckable(True)
        self.flip.toggled.connect(lambda v: win.set_option("flip", v))
        self.flip_v = button("Vertical")
        self.flip_v.setCheckable(True)
        self.flip_v.toggled.connect(lambda v: win.set_option("flip_v", v))
        flips.addWidget(self.flip, 1)
        flips.addWidget(self.flip_v, 1)
        self.field(form, "Flip", flips)

        # Playback
        form = self.card(layout, "PLAYBACK")
        fps_row = QHBoxLayout()
        fps_row.setSpacing(8)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(MIN_FPS, MAX_FPS)
        self.fps.setDecimals(1)
        self.fps.setSuffix(" fps")
        self.fps.setAlignment(Qt.AlignRight)
        self.fps.valueChanged.connect(self.fps_changed)
        fps_row.addWidget(self.fps, 1)
        fps_row.addWidget(button(f"Original ({win.native_fps:.1f})", slot=lambda: self.fps.setValue(win.native_fps)))
        self.field(form, "Speed", fps_row)

        # Appearance
        form = self.card(layout, "APPEARANCE")
        row, self.opacity = self.linked(10, 100, "%", lambda v: win.set_option("opacity", v / 100))
        self.field(form, "Opacity", row)

        footer = QHBoxLayout()
        footer.addWidget(button("Reset all", slot=self.reset_all))
        footer.addStretch()
        footer.addWidget(button("Cancel", slot=self.reject))
        done = button("Done", "Primary", slot=self.accept)
        done.setDefault(True)
        footer.addWidget(done)
        layout.addSpacing(10)
        layout.addLayout(footer)
        self.load()

    @staticmethod
    def card(layout, title):
        frame = QFrame()
        frame.setObjectName("Card")
        form = QFormLayout(frame)
        form.setContentsMargins(16, 12, 16, 12)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        layout.addSpacing(4)
        layout.addWidget(label(title, "Section"))
        layout.addWidget(frame)
        return form

    @staticmethod
    def field(form, text, row):
        form.addRow(label(text, "FieldLabel"), row)

    def linked(self, lo, hi, suffix, on_change):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSuffix(suffix)
        spin.setAlignment(Qt.AlignRight)
        spin.setFixedWidth(76)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.valueChanged.connect(on_change)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        self.sliders[spin] = slider
        return row, spin

    def load(self):
        """Show the GIF's current values without re-applying them."""
        item = self.win.item
        values = ((self.scale, round(item["scale"] * 100)), (self.rotation, round(item["rotation"])),
                  (self.flip, item["flip"]), (self.flip_v, item["flip_v"]),
                  (self.fps, self.win.current_fps()), (self.opacity, round(item["opacity"] * 100)))
        for widget, value in values:
            for w in (widget, self.sliders.get(widget)):
                if w is None:
                    continue
                w.blockSignals(True)
                if isinstance(w, QAbstractButton):
                    w.setChecked(value)
                else:
                    w.setValue(value)
                w.blockSignals(False)

    def showEvent(self, e):
        label_for_taskbar(self)
        self.original = {k: self.win.item[k] for k in self.KEYS}
        self.load()
        self.thumb_movie.setFileName(str(self.win.app.store.lib / self.win.item["file"]))
        self.thumb_movie.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.thumb_movie.stop()
        self.thumb_movie.setFileName("")  # let go of the file
        super().hideEvent(e)

    def turn(self, degrees):
        r = (self.rotation.value() + degrees) % 360
        self.rotation.setValue(r - 360 if r > 180 else r)

    def fps_changed(self, value):
        self.win.set_option("fps", None if abs(value - self.win.native_fps) < 0.05 else value)

    def reset_all(self):
        self.scale.setValue(100)
        self.rotation.setValue(0)
        self.flip.setChecked(False)
        self.flip_v.setChecked(False)
        self.fps.setValue(self.win.native_fps)
        self.opacity.setValue(100)

    def reject(self):
        for key, value in self.original.items():
            self.win.set_option(key, value)
        super().reject()


class SettingsDialog(QDialog):
    """App-wide settings. Every change applies (and saves) immediately."""

    def __init__(self, desk):
        super().__init__(None)
        self.desk = desk
        st = desk.store.settings
        self.setWindowTitle(f"{APP_NAME} \u2013 Settings")
        self.setWindowIcon(desk.icon)
        self.setMinimumWidth(520)
        self.resize(540, 720)

        body = QWidget()
        body.setObjectName("Window")
        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 8)
        layout.setSpacing(8)
        layout.addWidget(label("Settings", "Title"))
        layout.addSpacing(4)

        form = EditDialog.card(layout, "GENERAL")
        if sys.platform == "win32":
            EditDialog.field(form, "Start with Windows",
                             self.toggle(startup_enabled(), lambda on: set_startup(on)))
        EditDialog.field(form, "Theme", self.segmented(
            [("System", "system"), ("Light", "light"), ("Dark", "dark")], THEME.mode, desk.set_theme))

        form = EditDialog.card(layout, "NEW GIFS")
        EditDialog.field(form, "Layer", self.segmented(
            [("On top", "top"), ("Normal", "normal"), ("Desktop", "bottom")], st.get("default_layer", "top"),
            lambda v: desk.set_setting("default_layer", v)))
        size = QSpinBox()
        size.setRange(round(MIN_SCALE * 100), round(MAX_SCALE * 100))
        size.setSuffix("%")
        size.setFixedWidth(90)
        size.setValue(round(st.get("default_scale", 1.0) * 100))
        size.valueChanged.connect(lambda v: desk.set_setting("default_scale", v / 100))
        row = QHBoxLayout()
        row.addWidget(size)
        row.addStretch()
        EditDialog.field(form, "Size", row)

        form = EditDialog.card(layout, "SNAPPING")
        EditDialog.field(form, "Snap while dragging",
                         self.toggle(st.get("snap", True), lambda on: desk.set_setting("snap", on)))
        dist = QSpinBox()
        dist.setRange(2, 60)
        dist.setSuffix(" px")
        dist.setFixedWidth(90)
        dist.setValue(st.get("snap_distance", 12))
        dist.valueChanged.connect(lambda v: desk.set_setting("snap_distance", v))
        row = QHBoxLayout()
        row.addWidget(dist)
        row.addStretch()
        EditDialog.field(form, "Snap distance", row)
        hint = label("Snaps to screen edges, the taskbar, screen centres and other GIFs. Hold Alt while "
                     "dragging to place freely. Click a GIF, then use the arrow keys to nudge it "
                     "(Shift = 10 px).", "Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = EditDialog.card(layout, "HOTKEYS")
        self.hotkey_error = label("", "Error")
        self.hotkey_error.setWordWrap(True)
        self.hotkey_error.hide()
        for action, text, _default in HOTKEY_ACTIONS:
            edit = QKeySequenceEdit(QKeySequence(desk.hotkeys_config()[action]))
            try:
                edit.setMaximumSequenceLength(1)
            except AttributeError:  # Qt older than 6.5
                pass
            edit.editingFinished.connect(lambda a=action, e=edit: self.hotkey_changed(a, e))
            clear = button("Clear", slot=lambda _=False, a=action, e=edit: (e.clear(), self.hotkey_changed(a, e)))
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(edit, 1)
            row.addWidget(clear)
            EditDialog.field(form, text, row)
        form.addRow(self.hotkey_error)

        layout.addStretch()

        footer = QHBoxLayout()
        footer.setContentsMargins(20, 10, 20, 16)
        footer.addStretch()
        done = button("Done", "Primary", slot=self.accept)
        done.setDefault(True)
        footer.addWidget(done)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addLayout(footer)

    def toggle(self, checked, on_change):
        btn = button("On" if checked else "Off")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setFixedWidth(70)
        btn.toggled.connect(lambda on: (btn.setText("On" if on else "Off"), on_change(on)))
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch()
        return row

    def segmented(self, options, current, on_change):
        row = QHBoxLayout()
        row.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for text, value in options:
            btn = button(text)
            btn.setCheckable(True)
            btn.setChecked(value == current)
            btn.clicked.connect(lambda _=False, v=value: on_change(v))
            group.addButton(btn)
            row.addWidget(btn, 1)
        return row

    def hotkey_changed(self, action, edit):
        seq = edit.keySequence()
        text = seq[0].toCombined() if not seq.isEmpty() else None
        text = QKeySequence(text).toString(QKeySequence.PortableText) if text is not None else ""
        if text and hotkey_to_win(text) is None:
            self.show_hotkey_error(f"{hotkey_label(text)} can't be used. Use Ctrl, Alt, Shift or Win with a "
                                   "letter, number, F-key or arrow.")
            edit.setKeySequence(QKeySequence(self.desk.hotkeys_config()[action]))
            return
        failed = self.desk.set_hotkey(action, text)
        if failed:
            self.show_hotkey_error("Another app is already using " + ", ".join(hotkey_label(f) for f in failed)
                                   + ". Pick a different combination.")
        else:
            self.hotkey_error.hide()

    def show_hotkey_error(self, text):
        self.hotkey_error.setText(text)
        self.hotkey_error.show()

    def showEvent(self, e):
        label_for_taskbar(self)
        super().showEvent(e)


class LibraryWindow(QWidget):
    """Every GIF you've imported. Double-click one to put it on the desktop."""

    THUMB = 120

    def __init__(self, app):
        super().__init__(None)
        self.app = app
        # Animated thumbnails: one QMovie per card that's on screen.
        self.movies = {}
        self.anim_timer = QTimer(self)
        self.anim_timer.setSingleShot(True)
        self.anim_timer.setInterval(60)
        self.anim_timer.timeout.connect(self.update_animation)
        self.setObjectName("Window")
        self.setWindowTitle(f"{APP_NAME} \u2013 Library")
        self.setWindowIcon(app.icon)
        self.setAcceptDrops(True)
        self.resize(760, 540)
        self.setMinimumSize(500, 380)

        # Header
        logo = QLabel()
        logo.setPixmap(icon_pixmap(44))
        self.subtitle = label("", "Muted")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("Library", "Title"))
        titles.addWidget(self.subtitle)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self.apply_filter)
        self.search_icon = self.search.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.import_btn = button("Import GIFs", "Primary", slot=self.app.import_dialog)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(logo)
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(self.search)
        header.addWidget(self.import_btn)

        # Grid of GIF cards, or an empty-state drop zone
        self.list = QListWidget()
        self.list.setObjectName("Grid")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(self.THUMB, self.THUMB))
        self.list.setGridSize(QSize(self.THUMB + 44, self.THUMB + 84))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.item_menu)
        self.list.itemDoubleClicked.connect(lambda it: self.app.add_to_desktop(it.data(Qt.UserRole)))
        self.list.itemSelectionChanged.connect(self.update_buttons)
        self.empty = label("", "DropZone")
        self.empty.setAlignment(Qt.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)

        # Footer
        self.add_btn = button("Add to desktop", slot=self.add_selected)
        self.del_btn = button("Delete", "Danger", slot=self.delete_selected)
        footer = QHBoxLayout()
        footer.addWidget(label("Double-click a GIF to put it on your desktop  \u00b7  Ctrl+V pastes a GIF link",
                               "Muted"))
        footer.addStretch()
        footer.addWidget(self.add_btn)
        footer.addWidget(self.del_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)
        layout.addLayout(footer)

        self.overlay = label("Drop to import", "DropOverlay")
        self.overlay.setParent(self)
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.hide()

        self.list.verticalScrollBar().valueChanged.connect(lambda _: self.anim_timer.start())

        self.apply_icons()
        self.refresh()

    def apply_icons(self):
        self.import_btn.setIcon(THEME.icon("add", THEME.c["on_accent"]))
        self.add_btn.setIcon(THEME.icon("import"))
        self.del_btn.setIcon(THEME.icon("delete"))
        self.search_icon.setIcon(THEME.icon("search", THEME.c["muted"]))

    def refresh(self):
        selected = set(self.selected_files())
        self.stop_movies()
        self.list.clear()
        counts = {}
        for item in self.app.store.items:
            counts[item["file"]] = counts.get(item["file"], 0) + 1
        files = self.app.store.library_files()
        metrics = QFontMetrics(self.list.font())
        for name in files:
            thumb, size = first_frame(self.app.store.lib / name, self.THUMB)
            shown = metrics.elidedText(name[9:], Qt.ElideMiddle, self.THUMB)
            detail = f"On desktop \u00d7{counts[name]}" if counts.get(name) else \
                f"{size.width()} \u00d7 {size.height()}"
            it = QListWidgetItem(card_icon(thumb, self.THUMB), f"{shown}\n{detail}")
            it.setData(Qt.UserRole, name)
            it.setData(Qt.UserRole + 1, size)
            it.setData(Qt.UserRole + 2, QImageReader(str(self.app.store.lib / name)).imageCount() != 1)
            it.setToolTip(name[9:])
            self.list.addItem(it)
            it.setSelected(name in selected)
        placed = sum(counts.values())
        self.subtitle.setText(f"{len(files)} GIF{'' if len(files) == 1 else 's'}  \u00b7  {placed} on desktop")
        self.apply_filter()

    def apply_filter(self):
        query = self.search.text().strip().lower()
        visible = 0
        for i in range(self.list.count()):
            it = self.list.item(i)
            hidden = query not in it.data(Qt.UserRole)[9:].lower()
            it.setHidden(hidden)
            visible += not hidden
        if self.list.count() == 0:
            self.empty.setText("Drop GIF files here\n\nor click Import GIFs to get started")
            self.stack.setCurrentWidget(self.empty)
        elif visible == 0:
            self.empty.setText(f"No GIFs match \u201c{self.search.text().strip()}\u201d")
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.list)
        self.update_buttons()
        self.anim_timer.start()

    def update_animation(self):
        """Play the cards that are on screen; stop the rest."""
        showing = self.isVisible() and not self.isMinimized() and self.stack.currentWidget() is self.list
        view = self.list.viewport().rect()
        for i in range(self.list.count()):
            it = self.list.item(i)
            name = it.data(Qt.UserRole)
            on_screen = (showing and it.data(Qt.UserRole + 2) and not it.isHidden()
                         and self.list.visualItemRect(it).intersects(view))
            movie = self.movies.get(name)
            if on_screen and movie is None:
                movie = QMovie(str(self.app.store.lib / name), parent=self)
                movie.setScaledSize(it.data(Qt.UserRole + 1).scaled(self.THUMB, self.THUMB, Qt.KeepAspectRatio))
                movie.frameChanged.connect(lambda _=0, it=it, m=movie: it.setIcon(card_icon(m.currentPixmap(), self.THUMB)))
                movie.start()
                self.movies[name] = movie
            elif not on_screen and movie is not None:
                self.drop_movie(name)

    def drop_movie(self, name):
        movie = self.movies.pop(name)
        movie.stop()
        movie.setFileName("")  # let go of the file so it can be deleted
        movie.deleteLater()

    def stop_movies(self):
        for name in list(self.movies):
            self.drop_movie(name)

    def showEvent(self, e):
        label_for_taskbar(self)
        super().showEvent(e)
        self.anim_timer.start()

    def hideEvent(self, e):
        self.stop_movies()
        super().hideEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self.anim_timer.start()  # minimised or restored

    def update_buttons(self):
        n = len(self.selected_files())
        self.add_btn.setEnabled(n > 0)
        self.del_btn.setEnabled(n > 0)
        self.add_btn.setText(f"Add {n} to desktop" if n > 1 else "Add to desktop")

    def selected_files(self):
        return [it.data(Qt.UserRole) for it in self.list.selectedItems() if not it.isHidden()]

    def item_menu(self, pos):
        if not self.list.itemAt(pos):
            return
        m = Menu(parent=self)
        m.addAction(THEME.icon("import"), "Add to desktop", self.add_selected)
        m.addSeparator()
        m.addAction(THEME.icon("delete"), "Delete from library", self.delete_selected)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def add_selected(self):
        for name in self.selected_files():
            self.app.add_to_desktop(name)

    def delete_selected(self):
        names = self.selected_files()
        if not names:
            return
        what = "this GIF" if len(names) == 1 else f"{len(names)} GIFs"
        answer = QMessageBox.question(self, APP_NAME, f"Delete {what} from your library?\n\n"
                                                      "Copies on your desktop will be removed too.")
        if answer == QMessageBox.Yes:
            self.app.delete_from_library(names)

    def resizeEvent(self, e):
        self.overlay.setGeometry(self.rect().adjusted(14, 14, -14, -14))
        self.anim_timer.start()
        super().resizeEvent(e)

    def dragEnterEvent(self, e):
        if local_files(e.mimeData()) or web_links(e.mimeData()):
            e.acceptProposedAction()
            self.overlay.show()
            self.overlay.raise_()

    def dragLeaveEvent(self, _e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        self.app.import_mime(e.mimeData(), place=False)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste) and not self.search.hasFocus():
            if not self.app.import_mime(QGuiApplication.clipboard().mimeData(), place=False):
                self.app.toast.flash("Copy a GIF file or a link to a GIF first")
            return
        super().keyPressEvent(e)


class GifDesk:
    DEFAULTS = {"scale": 1.0, "rotation": 0, "opacity": 1.0, "fps": None, "layer": "top", "flip": False,
                "flip_v": False, "pixel_art": False, "paused": False, "locked": False}

    def __init__(self, qapp):
        self.qapp = qapp
        self.icon = app_icon()
        self.store = Store()
        self.windows = []
        self.library = None
        self.settings_dialog = None
        self.toast = Toast()
        self.uninstalled = False
        THEME.mode = self.store.settings.get("theme", "system")
        THEME.apply(qapp)
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.store.save)
        qapp.aboutToQuit.connect(self.flush)

        self.hotkeys = Hotkeys({"toggle_hidden": lambda: self.set_hidden(not self.store.settings.get("hidden")),
                                "toggle_lock": self.toggle_lock_all,
                                "next_layout": self.next_layout})
        failed = self.hotkeys.register(self.hotkeys_config())

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self.on_tray_click)
        self.build_tray_menu()
        self.tray.show()

        self.load_layout()
        if not self.store.items and not self.store.library_files():
            self.open_library()
        if failed:
            QTimer.singleShot(800, lambda: self.toast.flash(
                f"Hotkey {', '.join(hotkey_label(f) for f in failed)} is taken \u2013 change it in Settings", 4000))

        # Put GIFs back on the right monitor when monitors are plugged in, removed or rearranged.
        self.screens_timer = QTimer()
        self.screens_timer.setSingleShot(True)
        self.screens_timer.setInterval(700)
        self.screens_timer.timeout.connect(self.place_all)
        qapp.screenAdded.connect(self.watch_screen)
        qapp.screenRemoved.connect(lambda _s: self.screens_timer.start())
        for screen in qapp.screens():
            self.watch_screen(screen, initial=True)

    # ----- tray -----
    def build_tray_menu(self):
        keys = {a: hotkey_label(t) for a, t in self.hotkeys_config().items()}
        tab = lambda action: f"\t{keys[action]}" if keys.get(action) else ""
        m = Menu()
        title = m.addAction(QIcon(icon_pixmap(32)), APP_NAME)
        title.setEnabled(False)
        m.addSeparator()
        m.addAction(THEME.icon("add"), "Import GIFs\u2026", self.import_dialog)
        m.addAction(THEME.icon("library"), "Library", self.open_library)

        layouts = m.sub(f"Layout: {self.store.current_layout}", THEME.icon("layouts"))
        for name in self.store.layouts:
            layouts.check(name, name == self.store.current_layout, lambda _=False, n=name: self.switch_layout(n))
        layouts.addSeparator()
        if len(self.store.layouts) > 1:
            layouts.addAction(f"Next layout{tab('next_layout')}", self.next_layout)
        layouts.addAction(THEME.icon("copy"), "Save as new layout\u2026", lambda: self.new_layout(copy=True))
        layouts.addAction(THEME.icon("add"), "New empty layout\u2026", lambda: self.new_layout(copy=False))
        layouts.addAction(THEME.icon("edit"), "Rename this layout\u2026", self.rename_layout)
        delete = layouts.addAction(THEME.icon("delete"), "Delete this layout\u2026", self.delete_layout)
        delete.setEnabled(len(self.store.layouts) > 1)

        m.addSeparator()
        hidden = self.store.settings.get("hidden")
        m.addAction(THEME.icon("eye"), f"{'Show' if hidden else 'Hide'} all GIFs{tab('toggle_hidden')}",
                    lambda: self.set_hidden(not self.store.settings.get("hidden")))
        m.addAction(THEME.icon("pause"), "Pause / resume all", self.toggle_pause_all)
        m.addAction(THEME.icon("lock"), f"Lock / unlock all{tab('toggle_lock')}", self.toggle_lock_all)
        m.addSeparator()
        m.addAction(THEME.icon("settings"), "Settings\u2026", self.open_settings)
        if sys.platform == "win32":
            m.addAction(THEME.icon("folder"), "Open data folder", self.open_data_folder)
            if is_installed_copy():
                m.addAction(THEME.icon("delete"), f"Uninstall {APP_NAME}\u2026", self.uninstall)
        m.addSeparator()
        m.addAction(THEME.icon("close"), "Quit", self.qapp.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.setToolTip(f"{APP_NAME} \u2013 {self.store.current_layout}")

    def on_theme_changed(self):
        self.build_tray_menu()
        if self.library is not None:
            self.library.apply_icons()

    # ----- settings -----
    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def set_setting(self, key, value):
        self.store.settings[key] = value
        self.schedule_save()

    def set_theme(self, mode):
        self.set_setting("theme", mode)
        THEME.mode = mode
        THEME.apply(self.qapp)
        self.on_theme_changed()

    def hotkeys_config(self):
        saved = self.store.settings.get("hotkeys", {})
        return {action: saved.get(action, default) for action, _text, default in HOTKEY_ACTIONS}

    def set_hotkey(self, action, text):
        config = self.hotkeys_config()
        config[action] = text
        self.set_setting("hotkeys", config)
        failed = self.hotkeys.register(config)
        self.build_tray_menu()
        return failed

    # ----- layouts -----
    def load_layout(self):
        for item in list(self.store.items):
            if (self.store.lib / item.get("file", "")).is_file():
                self.spawn(item)
            else:
                self.store.items.remove(item)
        if not self.store.settings.get("hidden"):
            self.show_all()

    def clear_windows(self):
        for w in self.windows:
            w.release()
        self.windows.clear()

    def switch_layout(self, name):
        if name == self.store.current_layout or name not in self.store.layouts:
            return
        self.clear_windows()
        self.store.settings["current_layout"] = name
        self.load_layout()
        self.schedule_save()
        self.build_tray_menu()
        self.refresh_library()
        self.toast.flash(f"Layout: {name}")

    def next_layout(self):
        names = list(self.store.layouts)
        if len(names) < 2:
            self.toast.flash("Only one layout \u2013 make more from the tray menu")
            return
        self.switch_layout(names[(names.index(self.store.current_layout) + 1) % len(names)])

    def ask_layout_name(self, title, text=""):
        name, ok = QInputDialog.getText(None, APP_NAME, title, text=text)
        name = name.strip()
        if not ok or not name:
            return None
        if name in self.store.layouts and name != self.store.current_layout:
            QMessageBox.information(None, APP_NAME, f"There's already a layout called \u201c{name}\u201d.")
            return None
        return name

    def new_layout(self, copy):
        name = self.ask_layout_name("Name for the new layout:")
        if not name or name == self.store.current_layout:
            return
        self.store.layouts[name] = [dict(item, id=uuid.uuid4().hex) for item in self.store.items] if copy else []
        self.switch_layout(name)

    def rename_layout(self):
        old = self.store.current_layout
        new = self.ask_layout_name("New name for this layout:", old)
        if not new or new == old:
            return
        self.store.data["layouts"] = {(new if k == old else k): v for k, v in self.store.layouts.items()}
        self.store.settings["current_layout"] = new
        self.schedule_save()
        self.build_tray_menu()

    def delete_layout(self):
        name = self.store.current_layout
        if len(self.store.layouts) < 2:
            return
        if QMessageBox.question(None, APP_NAME, f"Delete the layout \u201c{name}\u201d?\n\n"
                                "The GIFs stay in your library.") != QMessageBox.Yes:
            return
        names = list(self.store.layouts)
        self.switch_layout(names[names.index(name) - 1] if names.index(name) else names[1])
        del self.store.layouts[name]
        self.schedule_save()
        self.build_tray_menu()

    # ----- monitors & snapping -----
    def watch_screen(self, screen, initial=False):
        screen.geometryChanged.connect(lambda _g: self.screens_timer.start())
        if not initial:
            self.screens_timer.start()

    def place(self, w):
        """Position a GIF from what was saved, without changing what was saved.

        Uses the saved spot if its monitor is still there and still covers it; otherwise the same
        relative spot on that monitor, or on the main monitor while that one is unplugged."""
        item = w.item
        half = QPoint(w.width() // 2, w.height() // 2)
        center = QPoint(item["x"], item["y"]) + half
        screens = self.qapp.screens()
        named = next((s for s in screens if s.name() == item.get("screen")), None)
        if named is not None and named.geometry().contains(center):
            pass
        elif item.get("screen") is None and any(s.geometry().contains(center) for s in screens):
            pass  # saved before monitors were tracked, and still on screen
        else:
            g = (named or self.qapp.primaryScreen()).geometry()
            rel = item.get("rel") or [0.5, 0.5]
            center = QPoint(g.x() + round(rel[0] * g.width()), g.y() + round(rel[1] * g.height()))
        w.move(center - half)

    def place_all(self):
        for w in self.windows:
            if w.drag_offset is None:
                self.place(w)

    def snap(self, w, pos):
        """Pull a dragged GIF onto nearby screen edges, screen centres and other GIFs' edges."""
        if not self.store.settings.get("snap", True):
            return pos
        reach = self.store.settings.get("snap_distance", 12)
        xs, ys, cxs, cys = [], [], [], []
        for screen in self.qapp.screens():
            for r in (screen.availableGeometry(), screen.geometry()):  # available = above the taskbar
                xs += [r.x(), r.x() + r.width()]
                ys += [r.y(), r.y() + r.height()]
            g = screen.availableGeometry()
            cxs.append(g.x() + g.width() // 2)
            cys.append(g.y() + g.height() // 2)
        for other in self.windows:
            if other is not w and other.isVisible():
                g = other.geometry()
                xs += [g.x(), g.x() + g.width()]
                ys += [g.y(), g.y() + g.height()]
                cxs.append(g.x() + g.width() // 2)
                cys.append(g.y() + g.height() // 2)

        def best(start, size, edges, centers):
            options = [c for e in edges for c in (e, e - size)] + [c - size // 2 for c in centers]
            near = min(options, key=lambda c: abs(c - start), default=start)
            return near if abs(near - start) <= reach else start

        return QPoint(best(pos.x(), w.width(), xs, cxs), best(pos.y(), w.height(), ys, cys))

    def on_tray_click(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_library()

    # ----- saving -----
    def schedule_save(self):
        self.save_timer.start()

    def flush(self):
        if self.uninstalled:
            return
        self.hotkeys.unregister_all()
        shutdown_workers()
        self.save_timer.stop()
        self.store.save()

    # ----- windows -----
    def spawn(self, item):
        for key, value in self.DEFAULTS.items():
            item.setdefault(key, value)
        item.setdefault("id", uuid.uuid4().hex)
        w = GifWindow(self, item)
        self.place(w)
        self.windows.append(w)
        return w

    def add_to_desktop(self, name, at=None, template=None):
        item = dict(template or {}, file=name, id=uuid.uuid4().hex, x=0, y=0, paused=False)
        if template is None:
            item.update(self.DEFAULTS)
            item["layer"] = self.store.settings.get("default_layer", "top")
            item["scale"] = self.store.settings.get("default_scale", 1.0)
        self.store.items.append(item)
        w = self.spawn(item)
        if at is None:
            area = self.qapp.primaryScreen().availableGeometry()
            shift = (len(self.windows) % 8) * 28
            at = area.center() - QPoint(w.width() // 2, w.height() // 2) + QPoint(shift, shift)
        w.move(at)
        w.remember_pos()
        if self.store.settings.get("hidden"):
            self.set_hidden(False)
        w.show()
        self.schedule_save()
        self.refresh_library()
        return w

    def remove_window(self, w):
        self.windows.remove(w)
        self.store.items.remove(w.item)
        w.release()
        self.schedule_save()
        self.refresh_library()

    def show_all(self):
        for w in self.windows:
            w.show()

    def set_hidden(self, hidden):
        self.store.settings["hidden"] = hidden
        for w in self.windows:
            w.setVisible(not hidden)
        self.build_tray_menu()
        self.schedule_save()

    def toggle_lock_all(self):
        lock = any(not w.item["locked"] for w in self.windows)
        for w in self.windows:
            if w.item["locked"] != lock:
                w.set_option("locked", lock)
        self.toast.flash("GIFs locked (click-through)" if lock else "GIFs unlocked")

    def toggle_pause_all(self):
        pause = any(not w.item["paused"] for w in self.windows)
        for w in self.windows:
            w.set_option("paused", pause)

    # ----- library -----
    def import_dialog(self):
        last = self.store.settings.get("last_dir", str(Path.home() / "Pictures"))
        paths, _ = QFileDialog.getOpenFileNames(None, "Import GIFs", last, GIF_FILTER)
        if paths:
            self.store.settings["last_dir"] = str(Path(paths[0]).parent)
            self.import_paths(paths)

    def import_mime(self, mime, place=False, at=None):
        """Import dropped or pasted files and links. Returns False if there was nothing usable."""
        files, links = local_files(mime), web_links(mime)
        if files:
            self.import_paths(files, place=place, at=at)
        for i, link in enumerate(links):
            self.import_remote(link, place=place, at=None if at is None else at + QPoint(i * 30, i * 30))
        return bool(files or links)

    def import_remote(self, url, filename=None, place=False, at=None):
        """Download a GIF from a link in the background, then add it."""
        self.toast.flash("Downloading GIF\u2026", 20000)
        run_async(download_gif, lambda result, error: self.remote_done(result, error, filename, place, at), url)

    def remote_done(self, result, error, filename, place, at):
        if error is not None:
            reason = str(error) if isinstance(error, ValueError) else "Check the link and your internet connection."
            self.toast.flash(f"Couldn't add that GIF. {reason}", 4000)
            return
        data, suggested = result
        name = self.store.import_bytes(data, filename or suggested)
        if not is_gif(self.store.lib / name):
            self.store.delete_file(name)
            self.toast.flash("That link isn't a GIF GifDesk can play.", 4000)
            return
        if place:
            self.add_to_desktop(name, at=at)
        self.schedule_save()
        self.refresh_library()
        self.toast.flash(f"Added {name[9:]}" + ("" if place else " to your library"))

    def import_paths(self, paths, place=True, at=None):
        good, bad = [], []
        for path in paths:
            (good if path and is_gif(path) else bad).append(path)
        for i, path in enumerate(good):
            name = self.store.import_gif(path)
            if place:
                self.add_to_desktop(name, at=None if at is None else at + QPoint(i * 30, i * 30))
        if bad:
            QMessageBox.warning(None, APP_NAME, "These aren't GIFs (or can't be read), so they were skipped:\n\n"
                                + "\n".join(Path(p).name or p for p in bad))
        self.schedule_save()
        self.refresh_library()

    def delete_from_library(self, names):
        if self.library is not None:
            self.library.stop_movies()
        for w in [w for w in self.windows if w.item["file"] in names]:
            self.windows.remove(w)
            self.store.items.remove(w.item)
            w.release()
        for items in self.store.layouts.values():  # other layouts too
            items[:] = [it for it in items if it["file"] not in names]
        # Let the GIF windows finish releasing their file handles first.
        QTimer.singleShot(200, lambda: self._finish_delete(names))

    def _finish_delete(self, names):
        for name in names:
            self.store.delete_file(name)
        self.schedule_save()
        self.refresh_library()

    def open_library(self):
        if self.library is None:
            self.library = LibraryWindow(self)
        self.library.refresh()
        self.library.show()
        self.library.raise_()
        self.library.activateWindow()

    def refresh_library(self):
        if self.library is not None and self.library.isVisible():
            self.library.refresh()

    def open_data_folder(self):
        if sys.platform == "win32":
            os.startfile(self.store.dir)

    def uninstall(self):
        def release():
            self.uninstalled = True
            self.save_timer.stop()
            self.hotkeys.unregister_all()
            for w in list(self.windows):
                w.release()
            self.windows.clear()
            self.tray.hide()
        if uninstall_app(release):
            self.qapp.quit()


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    icon = app_icon()
    qapp.setWindowIcon(icon)
    THEME.apply(qapp)

    lock = QLockFile(str(data_dir() / "gifdesk.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running - look for its icon in the "
                                                "system tray (bottom-right, you may need to click the ^ arrow).\n\n"
                                                "To install or update, quit it from the tray icon first.")
        return 0

    if "--uninstall" in sys.argv:
        uninstall_app()
        return 0

    if offer_install(icon):
        lock.unlock()
        subprocess.Popen([str(launcher()), str(INSTALL_DIR / "GifDesk.pyw")])
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(None, APP_NAME, "No system tray was found, so GifDesk can't show its menu.")

    desk = GifDesk(qapp)
    try:
        qapp.styleHints().colorSchemeChanged.connect(
            lambda _: THEME.mode == "system" and (THEME.apply(qapp), desk.on_theme_changed()))
    except AttributeError:  # Qt older than 6.5
        pass
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
