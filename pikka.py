#!/usr/bin/env python3
"""Pikka — macOS photo sorting & batch renaming app (single-file, PyQt6)."""

from __future__ import annotations

import os
import sys
import shutil
import threading
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
import piexif

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QMimeData, QTimer, QSize, QPoint,
)
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QImage, QDrag, QPalette,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QCheckBox, QScrollArea, QFileDialog, QMessageBox, QDialog,
    QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy, QProgressDialog,
)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    FileSystemEventHandler = object

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff", ".tif", ".bmp", ".gif"}
CONV_LABEL = {
    ".png": "PNG", ".heic": "HEIC", ".webp": "WEBP",
    ".tiff": "TIFF", ".tif": "TIFF", ".bmp": "BMP", ".gif": "GIF",
}
THUMB = 148
PAD = 8
JPEG_Q = 95
WATCH_DB = 1.3

C = {
    "bg":       "#0f1117",
    "panel":    "#181b24",
    "card":     "#1e2130",
    "card_sel": "#2a2f40",
    "border":   "#272c3a",
    "accent":   "#e8a020",
    "accent_d": "#b87818",
    "accent_l": "#f0c878",
    "text":     "#eceaf4",
    "text2":    "#8a88a0",
    "text3":    "#4a4858",
    "badge_png_bg":   "#0e2040", "badge_png_fg":   "#60b8ff",
    "badge_heic_bg":  "#1e1040", "badge_heic_fg":  "#b888ff",
    "badge_webp_bg":  "#0e3020", "badge_webp_fg":  "#60e098",
    "badge_other_bg": "#2a2010", "badge_other_fg": "#d0b060",
}

BADGE_COLORS = {
    ".png":  (C["badge_png_bg"],   C["badge_png_fg"]),
    ".heic": (C["badge_heic_bg"],  C["badge_heic_fg"]),
    ".webp": (C["badge_webp_bg"],  C["badge_webp_fg"]),
    ".tiff": (C["badge_other_bg"], C["badge_other_fg"]),
    ".tif":  (C["badge_other_bg"], C["badge_other_fg"]),
    ".bmp":  (C["badge_other_bg"], C["badge_other_fg"]),
    ".gif":  (C["badge_other_bg"], C["badge_other_fg"]),
}


def menlo(size: int, bold: bool = False) -> QFont:
    f = QFont("Menlo", size)
    if bold:
        f.setBold(True)
    return f


def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setFixedHeight(1)
    ln.setStyleSheet(f"background:{C['border']}; border:none;")
    return ln


def vline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.VLine)
    ln.setFixedWidth(1)
    ln.setStyleSheet(f"background:{C['border']}; border:none;")
    return ln


# ---------------------------------------------------------------------------
# ThumbLoader
# ---------------------------------------------------------------------------
class ThumbLoader(QThread):
    """Loads thumbnails asynchronously; emits one signal per image."""
    thumb_ready = pyqtSignal(int, QPixmap)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths

    def run(self):
        for idx, path in enumerate(self._paths):
            px = self._load(path)
            self.thumb_ready.emit(idx, px)

    @staticmethod
    def _load(path: str) -> QPixmap:
        try:
            img = Image.open(path).convert("RGBA")
            # Respect EXIF orientation
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            # Square-crop centred
            w, h = img.size
            s = min(w, h)
            left = (w - s) // 2
            top = (h - s) // 2
            img = img.crop((left, top, left + s, top + s))
            img = img.resize((THUMB, THUMB), Image.LANCZOS)
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, THUMB, THUMB, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimg)
        except Exception:
            px = QPixmap(THUMB, THUMB)
            px.fill(QColor(C["card"]))
            return px


# ---------------------------------------------------------------------------
# RenameWorker
# ---------------------------------------------------------------------------
class RenameWorker(QThread):
    finished = pyqtSignal(list, list)   # (final_paths, errors)
    progress = pyqtSignal(int, int)     # (current, total)

    def __init__(self, photos: list[str], prefix: str, start: int,
                 digits: int, conv_exts: set[str], delete_orig: bool, parent=None):
        super().__init__(parent)
        self._photos = photos
        self._prefix = prefix
        self._start = start
        self._digits = digits
        self._conv_exts = conv_exts
        self._delete_orig = delete_orig

    def run(self):
        photos = list(self._photos)
        errors: list[str] = []
        total = len(photos)

        # Phase 0: conversion
        converted: dict[str, str] = {}  # old_path -> new_path (temp jpeg)
        for i, p in enumerate(photos):
            ext = Path(p).suffix.lower()
            if ext in self._conv_exts:
                try:
                    new_p = self._convert_to_jpeg(p)
                    converted[p] = new_p
                    photos[i] = new_p
                except Exception as e:
                    errors.append(f"Convert failed: {Path(p).name}: {e}")

        self.progress.emit(0, total)

        folder = Path(self._photos[0]).parent

        # Phase 1: rename to temp names
        temp_names: list[str] = []
        for i, p in enumerate(photos):
            ext = Path(p).suffix.lower()
            tmp = str(folder / f"__ps_{i:06d}{ext}")
            try:
                os.rename(p, tmp)
                temp_names.append(tmp)
            except Exception as e:
                errors.append(f"Temp rename failed: {Path(p).name}: {e}")
                temp_names.append(p)  # keep original path as fallback
            self.progress.emit(i + 1, total)

        # Phase 2: rename to final names
        final_paths: list[str] = []
        for i, tmp in enumerate(temp_names):
            ext = Path(tmp).suffix.lower()
            n = self._start + i
            num = str(n).zfill(self._digits)
            final_name = f"{self._prefix}{num}{ext}"
            final_path = str(folder / final_name)
            try:
                os.rename(tmp, final_path)
                final_paths.append(final_path)
            except Exception as e:
                errors.append(f"Final rename failed: {Path(tmp).name}: {e}")
                final_paths.append(tmp)

        # Delete originals if requested
        if self._delete_orig:
            for orig, _ in converted.items():
                try:
                    if os.path.exists(orig):
                        os.remove(orig)
                except Exception as e:
                    errors.append(f"Delete orig failed: {Path(orig).name}: {e}")

        self.finished.emit(final_paths, errors)

    @staticmethod
    def _convert_to_jpeg(path: str) -> str:
        img = Image.open(path)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                bg.paste(img, mask=img.split()[-1])
            else:
                bg.paste(img)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        folder = Path(path).parent
        stem = Path(path).stem
        out_path = str(folder / f"__conv_{stem}.jpg")
        save_kwargs = {"quality": JPEG_Q, "subsampling": 0}
        img.save(out_path, "JPEG", **save_kwargs)
        return out_path


# ---------------------------------------------------------------------------
# FolderWatcher
# ---------------------------------------------------------------------------
if HAS_WATCHDOG:
    class FolderWatcher(FileSystemEventHandler):
        def __init__(self, signal_obj):
            super().__init__()
            self._signal = signal_obj
            self._timer: Optional[threading.Timer] = None
            self._paused = False

        def pause(self): self._paused = True
        def resume(self): self._paused = False

        def _debounced_emit(self):
            if not self._paused:
                self._signal.emit()

        def _schedule(self):
            if self._paused:
                return
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
            self._timer = threading.Timer(WATCH_DB, self._debounced_emit)
            self._timer.daemon = True
            self._timer.start()

        def on_created(self, event): self._schedule()
        def on_deleted(self, event): self._schedule()
        def on_moved(self, event): self._schedule()
else:
    class FolderWatcher:
        def __init__(self, signal_obj): pass
        def pause(self): pass
        def resume(self): pass


# ---------------------------------------------------------------------------
# ThumbCard
# ---------------------------------------------------------------------------
class ThumbCard(QFrame):
    DRAG_THRESH = 8

    def __init__(self, index: int, path: str, gallery: "GalleryWidget"):
        super().__init__()
        self._index = index
        self._path = path
        self._gallery = gallery
        self._px: Optional[QPixmap] = None
        self._drag_origin: Optional[QPoint] = None

        self.setObjectName("card")
        self.setFixedSize(THUMB + 20, THUMB + 32)
        self.setAcceptDrops(True)
        self._apply_style(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(5)

        # Thumbnail container — badge is overlaid inside it
        thumb_w = QWidget()
        thumb_w.setFixedSize(THUMB, THUMB)
        thumb_w.setStyleSheet("background:transparent;")

        self._img_lbl = QLabel(thumb_w)
        self._img_lbl.setGeometry(0, 0, THUMB, THUMB)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background:transparent;")

        # Format badge overlaid on thumbnail (top-right corner)
        ext = Path(path).suffix.lower()
        if ext in CONV_LABEL:
            badge_text = CONV_LABEL[ext]
            bg, fg = BADGE_COLORS.get(ext, (C["badge_other_bg"], C["badge_other_fg"]))
            self._badge = QLabel(badge_text, thumb_w)
            self._badge.setFont(menlo(8, bold=True))
            self._badge.setStyleSheet(
                f"color:{fg}; background:{bg}; border-radius:3px; padding:1px 5px;"
            )
            self._badge.adjustSize()
            bw = self._badge.sizeHint().width() + 2
            self._badge.setGeometry(THUMB - bw - 5, 5, bw, 16)
            self._badge.raise_()
        else:
            self._badge = None

        layout.addWidget(thumb_w, alignment=Qt.AlignmentFlag.AlignCenter)

        # Filename label
        name = Path(path).name
        self._name_lbl = QLabel(name)
        self._name_lbl.setFont(menlo(9))
        self._name_lbl.setStyleSheet(f"color:{C['text2']}; background:transparent;")
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        max_w = THUMB
        self._name_lbl.setMaximumWidth(max_w)
        fm = self._name_lbl.fontMetrics()
        elided = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, max_w)
        self._name_lbl.setText(elided)
        layout.addWidget(self._name_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

    @property
    def index(self) -> int:
        return self._index

    @index.setter
    def index(self, v: int):
        self._index = v

    @property
    def path(self) -> str:
        return self._path

    @path.setter
    def path(self, v: str):
        self._path = v

    def set_pixmap(self, px: QPixmap):
        self._px = px
        self._img_lbl.setPixmap(px)

    def _apply_style(self, selected: bool):
        ext = Path(self._path).suffix.lower() if hasattr(self, '_path') else ""
        is_jpeg = ext in (".jpg", ".jpeg")
        border_color = C["border"] if is_jpeg else C["accent_d"]
        bg = C["card_sel"] if selected else C["card"]
        self.setStyleSheet(
            f"#card {{ background:{bg}; border:1px solid {border_color};"
            f" border-radius:6px; }}"
        )

    # --- Mouse events ---
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = ev.pos()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag_origin = None
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_origin is None:
            return
        delta = (ev.pos() - self._drag_origin).manhattanLength()
        if delta < self.DRAG_THRESH:
            return
        self._drag_origin = None  # prevent re-triggering
        self._apply_style(True)
        self._start_drag()

    def _start_drag(self):
        drag = QDrag(self)
        md = QMimeData()
        md.setText(str(self._index))
        drag.setMimeData(md)

        if self._px is not None:
            ghost = self._px.scaled(
                80, 80,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            drag.setPixmap(ghost)
            drag.setHotSpot(QPoint(ghost.width() // 2, ghost.height() // 2))

        # Capture path before self may be deleted during drag
        drag_path = self._path
        gallery = self._gallery
        gallery.begin_live_drag(drag_path)

        drag.exec(Qt.DropAction.MoveAction)

        # Restore original order if drag was cancelled (dropped nowhere);
        # committed flag set by ThumbCard.dropEvent on a valid drop.
        gallery.end_live_drag(False)

        # Card may have been deleted by _rebuild() during the nested event loop
        try:
            self._apply_style(False)
        except RuntimeError:
            pass

    # --- Drag/drop target ---
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasText() or ev.mimeData().hasUrls():
            if ev.mimeData().hasText() and self._gallery._live_drag_path:
                self._gallery.live_hover_path(self._path)
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragLeaveEvent(self, ev):
        try:
            self._apply_style(False)
        except RuntimeError:
            pass

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasText() or ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        if md.hasUrls():
            # Forward folder drop to main window
            for url in md.urls():
                local = url.toLocalFile()
                if local:
                    p = Path(local)
                    folder = local if p.is_dir() else str(p.parent)
                    self.window().load_folder(folder)
                    break
            ev.acceptProposedAction()
        elif md.hasText():
            # Live drag already repositioned the photo — nothing to do here
            self._gallery._live_drag_committed = True
            try:
                self._apply_style(False)
            except RuntimeError:
                pass
            ev.acceptProposedAction()


# ---------------------------------------------------------------------------
# GalleryWidget
# ---------------------------------------------------------------------------
class GalleryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._photos: list[str] = []
        self._cards: list[ThumbCard] = []
        self._px_cache: dict[str, QPixmap] = {}  # path -> pixmap
        self._rebuild_pending = False
        self._live_drag_path: Optional[str] = None
        self._live_drag_original: Optional[list[str]] = None
        self._live_drag_committed: bool = False
        self.setAcceptDrops(True)

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(PAD, PAD, PAD, PAD)
        self._layout.setSpacing(PAD)

        self._empty_label = self._make_empty_label()
        self._empty_label.setVisible(True)

    def _make_empty_label(self) -> QLabel:
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t3 = C["text3"]
        t2 = C["text2"]
        lbl.setText(
            "<div style='text-align:center'>"
            f"<div style='font-size:32px; color:{t3}'>⬇</div>"
            f"<div style='font-size:13px; color:{t2}; margin-top:8px;'>Drop a folder here</div>"
            f"<div style='font-size:11px; color:{t3}; margin-top:4px;'>or click Open Folder above</div>"
            "</div>"
        )
        lbl.setStyleSheet(
            f"border:2px dashed {C['border']}; border-radius:12px;"
            f" background:{C['bg']}; min-height:200px;"
        )
        self._layout.addWidget(lbl, 0, 0)
        return lbl

    def load_photos(self, photos: list[str]):
        self._photos = list(photos)
        self._px_cache = {}
        self._rebuild()

    def _cols(self) -> int:
        w = self.width() or 800
        return max(1, (w - PAD) // (THUMB + 24 + PAD))

    def _schedule_rebuild(self):
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        self._rebuild_pending = False
        # Safely detach old cards
        for card in self._cards:
            card.hide()
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        # Remove empty label from layout
        self._layout.removeWidget(self._empty_label)
        self._empty_label.setParent(None)

        if not self._photos:
            self._layout.addWidget(self._empty_label, 0, 0)
            self._empty_label.setVisible(True)
            return

        self._empty_label.setVisible(False)
        cols = self._cols()
        for i, path in enumerate(self._photos):
            card = ThumbCard(i, path, self)
            if path in self._px_cache:
                card.set_pixmap(self._px_cache[path])
            row, col = divmod(i, cols)
            self._layout.addWidget(card, row, col)
            card.show()
            self._cards.append(card)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._schedule_rebuild()

    def move_card(self, src: int, tgt: int):
        if src < 0 or tgt < 0 or src >= len(self._photos) or tgt >= len(self._photos):
            return
        p = self._photos.pop(src)
        self._photos.insert(tgt, p)
        self._schedule_rebuild()

    def update_pixmap(self, idx: int, px: QPixmap):
        if 0 <= idx < len(self._photos):
            self._px_cache[self._photos[idx]] = px
        if idx < len(self._cards):
            self._cards[idx].set_pixmap(px)

    def get_photos(self) -> list[str]:
        return list(self._photos)

    def set_photos(self, photos: list[str]):
        self._photos = list(photos)
        self._schedule_rebuild()

    # --- Live drag support ---
    def begin_live_drag(self, path: str):
        self._live_drag_path = path
        self._live_drag_original = list(self._photos)

    def live_hover_path(self, tgt_path: str):
        """Reorder photos so the dragged card sits where tgt_path currently is."""
        if not self._live_drag_path or self._live_drag_path == tgt_path:
            return
        try:
            cur = self._photos.index(self._live_drag_path)
            tgt = self._photos.index(tgt_path)
        except ValueError:
            return
        if cur == tgt:
            return
        self._photos.pop(cur)
        self._photos.insert(tgt, self._live_drag_path)
        self._schedule_rebuild()

    def end_live_drag(self, accepted: bool):
        if not self._live_drag_committed and self._live_drag_original is not None:
            self._photos = self._live_drag_original
            self._schedule_rebuild()
        self._live_drag_path = None
        self._live_drag_original = None
        self._live_drag_committed = False

    # --- Drag/drop for folder onto gallery background ---
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            local = url.toLocalFile()
            if local:
                p = Path(local)
                folder = local if p.is_dir() else str(p.parent)
                self.window().load_folder(folder)
                break
        ev.acceptProposedAction()


# ---------------------------------------------------------------------------
# NoticeBar
# ---------------------------------------------------------------------------
class NoticeBar(QFrame):
    reload_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(
            "background:#0d2e18; border-bottom:1px solid #1a4d2a;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)

        self._lbl = QLabel()
        self._lbl.setFont(menlo(10))
        self._lbl.setStyleSheet(f"color:#60d080; background:transparent;")
        layout.addWidget(self._lbl)
        layout.addStretch()

        btn = QPushButton("Reload")
        btn.setFont(menlo(10))
        btn.setFixedHeight(24)
        btn.setStyleSheet(
            f"QPushButton{{background:#1a4d2a; color:#60d080; border:1px solid #2a7d4a;"
            f" border-radius:4px; padding:0 10px;}}"
            f"QPushButton:hover{{background:#2a6d3a;}}"
        )
        btn.clicked.connect(self.reload_clicked)
        layout.addWidget(btn)

        self.setVisible(False)

    def show_notice(self, text: str):
        self._lbl.setText(text)
        self.setVisible(True)

    def hide_notice(self):
        self.setVisible(False)


# ---------------------------------------------------------------------------
# ConvPanel
# ---------------------------------------------------------------------------
class ConvPanel(QFrame):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        hdr = QLabel("CONVERT TO JPEG")
        hdr.setFont(menlo(8, bold=True))
        hdr.setStyleSheet(f"color:{C['text3']}; background:transparent;")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hdr)

        self._cb_layout = QVBoxLayout()
        self._cb_layout.setSpacing(3)
        self._cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._cb_layout)

        self._checkboxes: dict[str, QCheckBox] = {}
        self._sep_left: Optional[QFrame] = None
        self._sep_right: Optional[QFrame] = None
        self._del_cb: Optional[QCheckBox] = None

        self.setVisible(False)

    def set_flanking(self, sep_left: QFrame, sep_right: QFrame, del_cb: QCheckBox):
        self._sep_left = sep_left
        self._sep_right = sep_right
        self._del_cb = del_cb

    def rebuild(self, photos: list[str]):
        # Collect present convertible extensions
        exts_present: set[str] = set()
        for p in photos:
            ext = Path(p).suffix.lower()
            if ext in CONV_LABEL:
                exts_present.add(ext)

        # Clear old checkboxes
        for cb in self._checkboxes.values():
            self._cb_layout.removeWidget(cb)
            cb.deleteLater()
        self._checkboxes = {}

        if not exts_present:
            self.setVisible(False)
            if self._sep_left:  self._sep_left.setVisible(False)
            if self._sep_right: self._sep_right.setVisible(False)
            if self._del_cb:
                self._del_cb.setChecked(False)
                self._del_cb.setVisible(False)
            return

        # Create checkboxes sorted by label
        for ext in sorted(exts_present, key=lambda e: CONV_LABEL[e]):
            label = f"{CONV_LABEL[ext]} → JPEG"
            cb = QCheckBox(label)
            cb.setFont(menlo(10))
            cb.setStyleSheet(
                f"QCheckBox{{color:{C['text2']}; background:transparent;}}"
                f"QCheckBox::indicator{{width:12px; height:12px;}}"
                f"QCheckBox::indicator:checked{{background:{C['accent']}; border-radius:2px;}}"
                f"QCheckBox::indicator:unchecked{{background:{C['card']}; border:1px solid {C['border']}; border-radius:2px;}}"
            )
            cb.stateChanged.connect(self._on_state_changed)
            self._cb_layout.addWidget(cb, alignment=Qt.AlignmentFlag.AlignCenter)
            self._checkboxes[ext] = cb

        self.setVisible(True)
        if self._sep_left:  self._sep_left.setVisible(True)
        if self._sep_right: self._sep_right.setVisible(True)
        self._on_state_changed()

    def _on_state_changed(self):
        any_checked = any(cb.isChecked() for cb in self._checkboxes.values())
        if self._del_cb:
            self._del_cb.setVisible(any_checked)
            if not any_checked:
                self._del_cb.setChecked(False)
        self.changed.emit()

    def get_checked_exts(self) -> set[str]:
        return {ext for ext, cb in self._checkboxes.items() if cb.isChecked()}


# ---------------------------------------------------------------------------
# RenameConfirmDialog
# ---------------------------------------------------------------------------
class RenameConfirmDialog(QDialog):
    def __init__(self, photos: list[str], prefix: str, start: int,
                 digits: int, conv_exts: set, delete_orig: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Rename")
        self.setMinimumWidth(640)
        self.setMinimumHeight(300)
        self.setMaximumHeight(600)
        self.setStyleSheet(f"QDialog {{ background:{C['panel']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{C['bg']}; border-bottom:1px solid {C['border']};")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(20, 14, 20, 14)

        title = QLabel(f"Rename {len(photos)} file{'s' if len(photos) != 1 else ''}")
        title.setFont(menlo(13, bold=True))
        title.setStyleSheet(f"color:{C['text']}; background:transparent;")
        hdr_l.addWidget(title)
        hdr_l.addStretch()

        if conv_exts:
            labels = " + ".join(CONV_LABEL[e] for e in sorted(conv_exts))
            conv_badge = QLabel(f"  {labels} → JPEG  ")
            conv_badge.setFont(menlo(9, bold=True))
            conv_badge.setStyleSheet(
                f"color:{C['accent']}; background:{C['card']};"
                f" border:1px solid {C['accent_d']}; border-radius:4px;"
                f" background:transparent;"
            )
            hdr_l.addWidget(conv_badge)
        root.addWidget(hdr)

        # ── Column headers ──
        col_hdr = QFrame()
        col_hdr.setStyleSheet(
            f"background:{C['panel']}; border-bottom:1px solid {C['border']};"
        )
        col_hdr_l = QHBoxLayout(col_hdr)
        col_hdr_l.setContentsMargins(20, 6, 20, 6)
        col_hdr_l.setSpacing(0)
        for text, stretch in [("#", 0), ("Original filename", 1), ("", 0), ("Renamed to", 1)]:
            lbl = QLabel(text)
            lbl.setFont(menlo(8, bold=True))
            lbl.setStyleSheet(f"color:{C['text3']}; background:transparent;")
            if stretch:
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            if text == "":
                lbl.setFixedWidth(36)
            elif text == "#":
                lbl.setFixedWidth(44)
            col_hdr_l.addWidget(lbl)
        root.addWidget(col_hdr)

        # ── Scrollable rows ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{C['panel']}; border:none; }}"
            "QScrollBar:vertical { background: #181b24; width: 7px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #272c3a; border-radius: 3px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: #4a4858; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        content = QWidget()
        content.setStyleSheet(f"background:{C['panel']};")
        rows_l = QVBoxLayout(content)
        rows_l.setContentsMargins(0, 0, 0, 0)
        rows_l.setSpacing(0)

        for i, path in enumerate(photos):
            old_name = Path(path).name
            ext = Path(path).suffix.lower()
            new_ext = ".jpg" if ext in conv_exts else ext
            n = str(start + i).zfill(digits)
            new_name = f"{prefix}{n}{new_ext}"
            converting = ext in conv_exts
            bg = C["card"] if i % 2 == 0 else C["panel"]

            row_w = QFrame()
            row_w.setStyleSheet(f"background:{bg};")
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(20, 5, 20, 5)
            row_l.setSpacing(0)

            num = QLabel(str(start + i))
            num.setFont(menlo(9))
            num.setFixedWidth(44)
            num.setStyleSheet(f"color:{C['text3']}; background:transparent;")
            row_l.addWidget(num)

            old_lbl = QLabel(old_name)
            old_lbl.setFont(menlo(10))
            old_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            old_lbl.setStyleSheet(f"color:{C['text2']}; background:transparent;")
            row_l.addWidget(old_lbl)

            arr = QLabel("→")
            arr.setFixedWidth(36)
            arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            arr.setFont(menlo(10))
            arr.setStyleSheet(
                f"color:{C['accent'] if converting else C['text3']}; background:transparent;"
            )
            row_l.addWidget(arr)

            new_lbl = QLabel(new_name)
            new_lbl.setFont(menlo(10, bold=converting))
            new_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            new_lbl.setStyleSheet(
                f"color:{C['accent'] if converting else C['text']}; background:transparent;"
            )
            row_l.addWidget(new_lbl)

            rows_l.addWidget(row_w)

        rows_l.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ── Footer ──
        footer = QFrame()
        footer.setStyleSheet(
            f"background:{C['bg']}; border-top:1px solid {C['border']};"
        )
        footer_l = QHBoxLayout(footer)
        footer_l.setContentsMargins(20, 12, 20, 12)
        footer_l.setSpacing(10)

        if delete_orig:
            del_note = QLabel("Originals will be deleted after conversion")
            del_note.setFont(menlo(9))
            del_note.setStyleSheet(f"color:{C['text3']}; background:transparent;")
            footer_l.addWidget(del_note)

        footer_l.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(menlo(10))
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background:{C['card']}; color:{C['text2']};"
            f" border:1px solid {C['border']}; border-radius:5px; padding:0 16px; }}"
            f"QPushButton:hover {{ background:{C['card_sel']}; color:{C['text']}; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        footer_l.addWidget(cancel_btn)

        ok_btn = QPushButton("Rename Files ✓")
        ok_btn.setFont(menlo(10, bold=True))
        ok_btn.setFixedHeight(32)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background:{C['accent']}; color:#111; border:none;"
            f" border-radius:5px; padding:0 18px; }}"
            f"QPushButton:hover {{ background:{C['accent_l']}; }}"
        )
        ok_btn.clicked.connect(self.accept)
        footer_l.addWidget(ok_btn)

        root.addWidget(footer)


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    _folder_changed = pyqtSignal()   # thread-safe bridge for watchdog

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pikka")
        self.resize(1100, 780)
        self.setMinimumSize(640, 480)
        self.setAcceptDrops(True)

        self._folder: Optional[str] = None
        self._photos: list[str] = []
        self._loader: Optional[ThumbLoader] = None
        self._rename_worker: Optional[RenameWorker] = None
        self._observer = None
        self._watcher: Optional[FolderWatcher] = None
        self._w_paused = False
        self._sort_key: Optional[str] = None
        self._sort_asc = True

        self._folder_changed.connect(self._on_folder_changed_signal)

        self._build_ui()
        self._apply_global_style()

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 1. Header
        vbox.addWidget(self._build_header())
        vbox.addWidget(hline())

        # 2. Sort toolbar
        vbox.addWidget(self._build_sort_bar())
        vbox.addWidget(hline())

        # 3. Notice bar
        self._notice = NoticeBar()
        self._notice.reload_clicked.connect(self._smart_reload)
        vbox.addWidget(self._notice)

        # 4. Gallery scroll area
        self._gallery = GalleryWidget()
        scroll = QScrollArea()
        scroll.setWidget(self._gallery)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{C['bg']}; border:none;}}"
            "QScrollBar:vertical { background: #181b24; width: 7px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #272c3a; border-radius: 3px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: #4a4858; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        vbox.addWidget(scroll, 1)

        # 5. Bottom bar
        vbox.addWidget(hline())
        vbox.addWidget(self._build_bottom_bar())

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background:{C['panel']}; border:none;")
        frame.setFixedHeight(52)
        h = QHBoxLayout(frame)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(12)

        logo = QLabel("⬡ Pikka")
        logo.setFont(menlo(16, bold=True))
        logo.setStyleSheet(f"color:{C['accent']}; background:transparent;")
        h.addWidget(logo)

        self._folder_lbl = QLabel("No folder open")
        self._folder_lbl.setFont(menlo(10))
        self._folder_lbl.setStyleSheet(f"color:{C['text2']}; background:transparent;")
        h.addWidget(self._folder_lbl)

        h.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(menlo(10))
        self._status_lbl.setStyleSheet(f"color:{C['text2']}; background:transparent;")
        h.addWidget(self._status_lbl)

        btn = QPushButton("Open Folder")
        btn.setFont(menlo(11))
        btn.setFixedHeight(32)
        btn.setStyleSheet(self._accent_btn_style())
        btn.clicked.connect(self._open_folder_dialog)
        h.addWidget(btn)

        return frame

    def _build_sort_bar(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background:{C['panel']}; border:none;")
        frame.setFixedHeight(40)
        h = QHBoxLayout(frame)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(4)

        lbl = QLabel("SORT")
        lbl.setFont(menlo(8, bold=True))
        lbl.setStyleSheet(f"color:{C['text3']}; background:transparent;")
        h.addWidget(lbl)

        self._sort_btns: dict[str, QPushButton] = {}
        for key, display in [("name", "Name"), ("mtime", "Date Modified"),
                               ("exif", "Date Taken"), ("size", "Size")]:
            btn = QPushButton(display)
            btn.setFont(menlo(10))
            btn.setFixedHeight(26)
            btn.setCheckable(True)
            btn.setStyleSheet(self._ghost_btn_style(False))
            btn.clicked.connect(lambda checked, k=key: self._sort_by(k))
            h.addWidget(btn)
            self._sort_btns[key] = btn

        self._dir_btn = QPushButton("↑")
        self._dir_btn.setFont(menlo(11))
        self._dir_btn.setFixedSize(28, 26)
        self._dir_btn.setEnabled(False)
        self._dir_btn.setStyleSheet(self._ghost_btn_style(False))
        self._dir_btn.clicked.connect(self._toggle_direction)
        h.addWidget(self._dir_btn)

        h.addWidget(vline())

        rev_btn = QPushButton("⇅ Reverse")
        rev_btn.setFont(menlo(10))
        rev_btn.setFixedHeight(26)
        rev_btn.setStyleSheet(self._ghost_btn_style(False))
        rev_btn.clicked.connect(self._reverse_order)
        h.addWidget(rev_btn)

        h.addStretch()
        return frame

    def _build_bottom_bar(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"background:{C['panel']}; border:none;")
        frame.setFixedHeight(88)
        h = QHBoxLayout(frame)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(8)

        # Left: rename fields
        fields_w = QWidget()
        fields_w.setStyleSheet("background:transparent;")
        fv = QVBoxLayout(fields_w)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(4)

        fields_h = QHBoxLayout()
        fields_h.setSpacing(8)

        self._prefix_edit = self._make_field("PREFIX", "photo_", 100)
        self._start_edit  = self._make_field("START #", "1", 60)
        self._digits_edit = self._make_field("DIGITS", "3", 50)

        for w in [self._prefix_edit[0], self._start_edit[0], self._digits_edit[0]]:
            fields_h.addWidget(w)

        fv.addLayout(fields_h)

        self._preview_lbl = QLabel("→  photo_001.jpg,  photo_002.jpg …")
        self._preview_lbl.setFont(menlo(9))
        self._preview_lbl.setStyleSheet(f"color:{C['text3']}; background:transparent;")
        fv.addWidget(self._preview_lbl)

        h.addWidget(fields_w)
        h.addWidget(vline())

        # Middle: ConvPanel + flanking separators
        self._conv_sep1 = vline()
        self._conv_sep1.setVisible(False)
        h.addWidget(self._conv_sep1)

        self._conv_panel = ConvPanel()
        h.addWidget(self._conv_panel)

        self._conv_sep2 = vline()
        self._conv_sep2.setVisible(False)
        h.addWidget(self._conv_sep2)

        # Delete originals checkbox
        self._del_orig_cb = QCheckBox("Delete originals after conversion")
        self._del_orig_cb.setFont(menlo(10))
        self._del_orig_cb.setStyleSheet(
            f"QCheckBox{{color:{C['text2']}; background:transparent;}}"
            f"QCheckBox::indicator{{width:12px; height:12px;}}"
            f"QCheckBox::indicator:checked{{background:{C['accent']}; border-radius:2px;}}"
            f"QCheckBox::indicator:unchecked{{background:{C['card']}; border:1px solid {C['border']}; border-radius:2px;}}"
        )
        self._del_orig_cb.setVisible(False)

        self._conv_panel.set_flanking(self._conv_sep1, self._conv_sep2, self._del_orig_cb)
        self._conv_panel.changed.connect(self._update_preview)

        h.addStretch()
        h.addWidget(self._del_orig_cb)

        # Rename button
        self._rename_btn = QPushButton("Rename Files ✓")
        self._rename_btn.setFont(menlo(11, bold=True))
        self._rename_btn.setFixedHeight(40)
        self._rename_btn.setMinimumWidth(140)
        self._rename_btn.setEnabled(False)
        self._rename_btn.setStyleSheet(self._accent_btn_style())
        self._rename_btn.clicked.connect(self._do_rename)
        h.addWidget(self._rename_btn)

        # Wire preview updates
        self._prefix_edit[1].textChanged.connect(self._update_preview)
        self._start_edit[1].textChanged.connect(self._update_preview)
        self._digits_edit[1].textChanged.connect(self._update_preview)

        return frame

    def _make_field(self, label: str, default: str, width: int):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(menlo(8, bold=True))
        lbl.setStyleSheet(f"color:{C['text3']}; background:transparent;")
        v.addWidget(lbl)

        edit = QLineEdit(default)
        edit.setFont(menlo(11))
        edit.setFixedWidth(width)
        edit.setFixedHeight(26)
        edit.setStyleSheet(
            f"QLineEdit{{background:{C['card']}; color:{C['text']}; border:1px solid {C['border']};"
            f" border-radius:4px; padding:0 6px;}}"
            f"QLineEdit:focus{{border:1px solid {C['accent']};}}"
        )
        v.addWidget(edit)
        return w, edit

    # -----------------------------------------------------------------------
    # Styles
    # -----------------------------------------------------------------------
    def _accent_btn_style(self) -> str:
        return (
            f"QPushButton{{background:{C['accent']}; color:#111; border:none;"
            f" border-radius:6px; padding:0 16px; font-weight:bold;}}"
            f"QPushButton:hover{{background:{C['accent_l']};}}"
            f"QPushButton:disabled{{background:{C['border']}; color:{C['text3']};}}"
        )

    def _ghost_btn_style(self, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:{C['card']}; color:{C['accent']}; border:none;"
                f" border-radius:4px; padding:0 10px;}}"
                f"QPushButton:hover{{background:{C['card_sel']};}}"
            )
        return (
            f"QPushButton{{background:transparent; color:{C['text2']}; border:none;"
            f" border-radius:4px; padding:0 10px;}}"
            f"QPushButton:hover{{background:{C['card']};}}"
            f"QPushButton:disabled{{color:{C['text3']};}}"
        )

    def _apply_global_style(self):
        self.setStyleSheet(
            f"QMainWindow{{background:{C['bg']};}}"
            f"QWidget{{background:{C['bg']}; color:{C['text']};}}"
            f"QScrollArea{{border:none;}}"
        )

    # -----------------------------------------------------------------------
    # Folder loading
    # -----------------------------------------------------------------------
    def _open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open Folder")
        if d:
            self.load_folder(d)

    def load_folder(self, folder: str):
        self._folder = folder
        self._folder_lbl.setText(Path(folder).name)
        self._notice.hide_notice()
        self._scan_and_load(folder)
        self._start_watcher(folder)
        self._rename_btn.setEnabled(True)

    def _scan_folder(self, folder: str) -> list[str]:
        result = []
        try:
            for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
                if entry.name.startswith("."):
                    continue
                if entry.is_file():
                    ext = Path(entry.name).suffix.lower()
                    if ext in SUPPORTED:
                        result.append(entry.path)
        except OSError:
            pass
        return result

    def _scan_and_load(self, folder: str):
        photos = self._scan_folder(folder)
        self._photos = photos
        self._gallery.load_photos(photos)
        self._status_lbl.setText(f"{len(photos)} photo{'s' if len(photos) != 1 else ''}")
        self._conv_panel.rebuild(photos)
        self._update_preview()
        self._start_loader(photos)

    def _start_loader(self, photos: list[str]):
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
            self._loader.wait()
        if not photos:
            return
        self._loader = ThumbLoader(photos, self)
        self._loader.thumb_ready.connect(self._gallery.update_pixmap)
        self._loader.start()

    # -----------------------------------------------------------------------
    # Watchdog
    # -----------------------------------------------------------------------
    def _start_watcher(self, folder: str):
        self._stop_watcher()
        if not HAS_WATCHDOG:
            return
        self._watcher = FolderWatcher(self._folder_changed)
        self._observer = Observer()
        self._observer.schedule(self._watcher, folder, recursive=False)
        self._observer.start()

    def _stop_watcher(self):
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None
        self._watcher = None

    def _on_folder_changed_signal(self):
        if not self._folder:
            return
        new_photos = self._scan_folder(self._folder)
        current = self._gallery.get_photos()
        added = len(set(new_photos) - set(current))
        removed = len(set(current) - set(new_photos))
        parts = []
        if added:   parts.append(f"+{added} file{'s' if added != 1 else ''}")
        if removed: parts.append(f"-{removed} file{'s' if removed != 1 else ''}")
        delta = ", ".join(parts) if parts else "changes detected"
        self._notice.show_notice(f"Folder changed ({delta}) — click Reload to sync")

    def _smart_reload(self):
        if not self._folder:
            return
        self._notice.hide_notice()
        new_photos = self._scan_folder(self._folder)
        current = self._gallery.get_photos()
        current_set = set(current)
        new_set = set(new_photos)

        # Preserve existing order, remove deleted, append new
        preserved = [p for p in current if p in new_set]
        added = [p for p in new_photos if p not in current_set]
        merged = preserved + added

        self._photos = merged
        self._gallery.set_photos(merged)
        self._status_lbl.setText(f"{len(merged)} photo{'s' if len(merged) != 1 else ''}")
        self._conv_panel.rebuild(merged)
        self._update_preview()
        # Load only new thumbnails
        if added:
            loader = ThumbLoader(added, self)
            offset = len(preserved)
            loader.thumb_ready.connect(
                lambda idx, px, off=offset: self._gallery.update_pixmap(off + idx, px)
            )
            loader.start()
            self._loader = loader

    # -----------------------------------------------------------------------
    # Sort
    # -----------------------------------------------------------------------
    def _sort_by(self, key: str):
        if self._sort_key == key:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_key = key
            self._sort_asc = True

        # Update button styles
        for k, btn in self._sort_btns.items():
            btn.setStyleSheet(self._ghost_btn_style(k == self._sort_key))

        self._dir_btn.setEnabled(True)
        self._dir_btn.setText("↑" if self._sort_asc else "↓")

        photos = self._gallery.get_photos()
        photos = self._sorted(photos, key, self._sort_asc)
        self._gallery.set_photos(photos)

    def _toggle_direction(self):
        self._sort_asc = not self._sort_asc
        self._dir_btn.setText("↑" if self._sort_asc else "↓")
        if self._sort_key:
            photos = self._gallery.get_photos()
            photos = self._sorted(photos, self._sort_key, self._sort_asc)
            self._gallery.set_photos(photos)

    def _reverse_order(self):
        photos = self._gallery.get_photos()
        self._gallery.set_photos(list(reversed(photos)))

    def _sorted(self, photos: list[str], key: str, asc: bool) -> list[str]:
        def sort_key(p):
            if key == "name":
                try:
                    return Path(p).name.lower()
                except Exception:
                    return ""
            elif key == "mtime":
                try:
                    return os.path.getmtime(p)
                except Exception:
                    return 0.0
            elif key == "size":
                try:
                    return os.path.getsize(p)
                except Exception:
                    return 0
            elif key == "exif":
                # Always returns float (epoch seconds) for consistent comparison
                try:
                    img = Image.open(p)
                    exif_data = img._getexif()
                    if exif_data:
                        dt = exif_data.get(36867) or exif_data.get(36868)
                        if dt:
                            from datetime import datetime
                            try:
                                return datetime.strptime(
                                    str(dt), "%Y:%m:%d %H:%M:%S"
                                ).timestamp()
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    return os.path.getmtime(p)
                except Exception:
                    return 0.0
            return 0.0
        return sorted(photos, key=sort_key, reverse=not asc)

    # -----------------------------------------------------------------------
    # Preview
    # -----------------------------------------------------------------------
    def _update_preview(self):
        prefix = self._prefix_edit[1].text()
        try:
            start = int(self._start_edit[1].text())
        except ValueError:
            start = 1
        try:
            digits = int(self._digits_edit[1].text())
        except ValueError:
            digits = 3

        conv_exts = self._conv_panel.get_checked_exts()
        # Determine ext for preview (use first photo's ext, converted if applicable)
        photos = self._gallery.get_photos()
        if photos:
            ext1 = Path(photos[0]).suffix.lower()
            if ext1 in conv_exts:
                ext1 = ".jpg"
            ext2 = ext1
            if len(photos) > 1:
                ext2 = Path(photos[1]).suffix.lower()
                if ext2 in conv_exts:
                    ext2 = ".jpg"
        else:
            ext1 = ext2 = ".jpg"

        n1 = str(start).zfill(digits)
        n2 = str(start + 1).zfill(digits)
        self._preview_lbl.setText(
            f"→  {prefix}{n1}{ext1},  {prefix}{n2}{ext2} …"
        )

    # -----------------------------------------------------------------------
    # Rename
    # -----------------------------------------------------------------------
    def _do_rename(self):
        photos = self._gallery.get_photos()
        if not photos:
            QMessageBox.warning(self, "Pikka", "No photos loaded.")
            return

        prefix = self._prefix_edit[1].text()
        if not prefix:
            QMessageBox.warning(self, "Pikka", "PREFIX cannot be empty.")
            return

        try:
            start = int(self._start_edit[1].text())
            if start < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Pikka", "START # must be a non-negative integer.")
            return

        try:
            digits = int(self._digits_edit[1].text())
            if digits < 1 or digits > 10:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Pikka", "DIGITS must be between 1 and 10.")
            return

        conv_exts = self._conv_panel.get_checked_exts()
        delete_orig = self._del_orig_cb.isChecked() if self._del_orig_cb.isVisible() else False

        dlg = RenameConfirmDialog(
            photos, prefix, start, digits, conv_exts, delete_orig, self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Pause watcher
        if self._watcher:
            self._watcher.pause()

        self._rename_btn.setEnabled(False)
        self._rename_worker = RenameWorker(
            photos, prefix, start, digits, conv_exts, delete_orig, self
        )
        self._rename_worker.finished.connect(self._on_rename_finished)
        self._rename_worker.start()

    def _on_rename_finished(self, final_paths: list, errors: list):
        if self._watcher:
            QTimer.singleShot(2000, self._watcher.resume)

        self._rename_btn.setEnabled(True)

        if errors:
            QMessageBox.warning(
                self, "Rename Errors",
                "Some errors occurred:\n" + "\n".join(errors[:10])
            )

        # Refresh gallery with new paths
        self._photos = final_paths
        self._gallery.load_photos(final_paths)
        self._status_lbl.setText(f"{len(final_paths)} photo{'s' if len(final_paths) != 1 else ''}")
        self._conv_panel.rebuild(final_paths)
        self._update_preview()
        self._start_loader(final_paths)

    # -----------------------------------------------------------------------
    # Main window drag/drop (folder from Finder)
    # -----------------------------------------------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            local = url.toLocalFile()
            if local:
                p = Path(local)
                folder = local if p.is_dir() else str(p.parent)
                self.load_folder(folder)
                break
        ev.acceptProposedAction()

    def closeEvent(self, ev):
        self._stop_watcher()
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
            self._loader.wait()
        super().closeEvent(ev)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pikka")

    # Global dark stylesheet
    app.setStyleSheet(
        f"* {{ font-family: Menlo; }}"
        f"QMainWindow, QWidget {{ background: {C['bg']}; color: {C['text']}; }}"
        f"QMessageBox {{ background: {C['panel']}; color: {C['text']}; }}"
        f"QMessageBox QPushButton {{ background: {C['accent']}; color: #111; border-radius: 4px;"
        f" padding: 4px 16px; min-width: 60px; }}"
        f"QMessageBox QPushButton:hover {{ background: {C['accent_l']}; }}"
        f"QFileDialog {{ background: {C['panel']}; color: {C['text']}; }}"
    )

    win = MainWindow()
    win.show()

    # Handle drag-onto-dock-icon (sys.argv[1]) on macOS
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.is_dir():
            win.load_folder(str(p))
        elif p.is_file() and p.suffix.lower() in SUPPORTED:
            win.load_folder(str(p.parent))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
