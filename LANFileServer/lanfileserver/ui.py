#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LANFileServer

局域网文件服务器：
- 临时模式：内置 Python HTTP 服务，适合临时下载。
- Nginx 模式：使用本机 Nginx，适合长期运行、多用户访问和目录浏览。
"""

from __future__ import annotations

import errno
import html
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

try:
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QFileInfo,
        QMimeData,
        QObject,
        QPoint,
        QPropertyAnimation,
        QRectF,
        QSettings,
        QSize,
        Qt,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QCloseEvent,
        QColor,
        QCursor,
        QDesktopServices,
        QDrag,
        QIcon,
        QPainter,
        QPalette,
        QPixmap,
        QResizeEvent,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QGraphicsOpacityEffect,
        QFileIconProvider,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QStyle,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:
    print("缺少 PySide6，请双击启动脚本自动安装依赖，或执行：python3 -m pip install -r requirements.txt")
    print(error)
    sys.exit(1)


def theme_palette(dark: bool) -> QPalette:
    colors = (
        {
            "window": "#17191d",
            "window_text": "#f2f4f7",
            "base": "#20242a",
            "alternate_base": "#292e35",
            "button": "#2a2f36",
            "button_text": "#f2f4f7",
            "tooltip_base": "#30363d",
            "tooltip_text": "#f2f4f7",
            "link": "#5aa7ff",
            "link_visited": "#b28cff",
            "highlight": "#0a84ff",
            "highlighted_text": "#ffffff",
            "placeholder": "#8b949e",
            "light": "#3a414a",
            "midlight": "#343a42",
            "mid": "#515964",
            "dark": "#111317",
            "shadow": "#08090b",
            "disabled_text": "#727983",
            "disabled_base": "#1c1f24",
            "disabled_button": "#24282e",
        }
        if dark
        else {
            "window": "#f5f7fa",
            "window_text": "#20242a",
            "base": "#ffffff",
            "alternate_base": "#eef2f6",
            "button": "#ffffff",
            "button_text": "#20242a",
            "tooltip_base": "#ffffff",
            "tooltip_text": "#20242a",
            "link": "#006ee6",
            "link_visited": "#7147b8",
            "highlight": "#0a6fe8",
            "highlighted_text": "#ffffff",
            "placeholder": "#7a838d",
            "light": "#ffffff",
            "midlight": "#e7ebef",
            "mid": "#c6cdd5",
            "dark": "#8c96a1",
            "shadow": "#5f6872",
            "disabled_text": "#929aa3",
            "disabled_base": "#f1f3f5",
            "disabled_button": "#eceff2",
        }
    )
    palette = QPalette()
    role_colors = {
        QPalette.Window: colors["window"],
        QPalette.WindowText: colors["window_text"],
        QPalette.Base: colors["base"],
        QPalette.AlternateBase: colors["alternate_base"],
        QPalette.ToolTipBase: colors["tooltip_base"],
        QPalette.ToolTipText: colors["tooltip_text"],
        QPalette.Text: colors["window_text"],
        QPalette.Button: colors["button"],
        QPalette.ButtonText: colors["button_text"],
        QPalette.BrightText: "#ffffff",
        QPalette.Link: colors["link"],
        QPalette.LinkVisited: colors["link_visited"],
        QPalette.Light: colors["light"],
        QPalette.Midlight: colors["midlight"],
        QPalette.Mid: colors["mid"],
        QPalette.Dark: colors["dark"],
        QPalette.Shadow: colors["shadow"],
        QPalette.Highlight: colors["highlight"],
        QPalette.HighlightedText: colors["highlighted_text"],
        QPalette.PlaceholderText: colors["placeholder"],
    }
    if hasattr(QPalette.ColorRole, "Accent"):
        role_colors[QPalette.ColorRole.Accent] = colors["highlight"]
    for role, color in role_colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
        palette.setColor(QPalette.Disabled, role, QColor(colors["disabled_text"]))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor(colors["disabled_base"]))
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor(colors["disabled_button"]))
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(colors["mid"]))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor(colors["disabled_text"]))
    return palette


class ThemeManager(QObject):
    themeChanged = Signal(str, bool)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self.settings = QSettings()
        self.mode = self.normalize_mode(self.settings.value(THEME_SETTING_KEY, THEME_SYSTEM))
        self.system_dark = self.palette_is_dark(app.palette())
        self.style_hints = app.styleHints()
        color_scheme_changed = getattr(self.style_hints, "colorSchemeChanged", None)
        if color_scheme_changed is not None:
            color_scheme_changed.connect(self.system_color_scheme_changed)
        self.apply_mode()

    @staticmethod
    def normalize_mode(value: object) -> str:
        mode = str(value)
        return mode if mode in (THEME_SYSTEM, THEME_LIGHT, THEME_DARK) else THEME_SYSTEM

    @staticmethod
    def palette_is_dark(palette: QPalette) -> bool:
        return palette.color(QPalette.Window).lightness() < 128

    def set_mode(self, mode: str) -> None:
        normalized = self.normalize_mode(mode)
        if normalized == self.mode:
            return
        self.mode = normalized
        self.settings.setValue(THEME_SETTING_KEY, normalized)
        self.settings.sync()
        self.apply_mode()

    def apply_mode(self) -> None:
        self.request_platform_color_scheme()
        if self.mode == THEME_SYSTEM:
            self.refresh_system_scheme()
        self.apply_palette()

    def request_platform_color_scheme(self) -> None:
        set_color_scheme = getattr(self.style_hints, "setColorScheme", None)
        if set_color_scheme is None or not hasattr(Qt, "ColorScheme"):
            return
        target = {
            THEME_SYSTEM: Qt.ColorScheme.Unknown,
            THEME_LIGHT: Qt.ColorScheme.Light,
            THEME_DARK: Qt.ColorScheme.Dark,
        }[self.mode]
        try:
            set_color_scheme(target)
        except (RuntimeError, TypeError):
            pass

    def refresh_system_scheme(self) -> None:
        color_scheme = getattr(self.style_hints, "colorScheme", None)
        if color_scheme is None or not hasattr(Qt, "ColorScheme"):
            return
        scheme = color_scheme()
        if scheme == Qt.ColorScheme.Dark:
            self.system_dark = True
        elif scheme == Qt.ColorScheme.Light:
            self.system_dark = False

    def effective_dark(self) -> bool:
        if self.mode == THEME_DARK:
            return True
        if self.mode == THEME_LIGHT:
            return False
        return self.system_dark

    def apply_palette(self) -> None:
        dark = self.effective_dark()
        self.app.setProperty("theme", THEME_DARK if dark else THEME_LIGHT)
        self.app.setPalette(theme_palette(dark))
        self.themeChanged.emit(self.mode, dark)

    def system_color_scheme_changed(self, scheme) -> None:  # noqa: ANN001
        if self.mode != THEME_SYSTEM or not hasattr(Qt, "ColorScheme"):
            return
        if scheme == Qt.ColorScheme.Dark:
            self.system_dark = True
        elif scheme == Qt.ColorScheme.Light:
            self.system_dark = False
        else:
            return
        self.apply_palette()


from .models import (  # noqa: E402
    APP_NAME,
    HELP_TEXT,
    INTERNAL_ITEM_MIME,
    STATUS_HELP_TEXT,
    THEME_DARK,
    THEME_LIGHT,
    THEME_OPTIONS,
    THEME_SETTING_KEY,
    THEME_SYSTEM,
    ShareItem,
)
from .network import current_time_text, get_lan_ips, get_public_ip_info, now_text  # noqa: E402
from .servers import NginxShareServer, PythonShareServer  # noqa: E402
from .web import item_allows_upload  # noqa: E402


class HelpPopup(QWidget):
    def __init__(self, help_text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("helpPopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        label = QLabel(help_text)
        label.setWordWrap(False)
        layout.addWidget(label)
        self.setStyleSheet(
            "QWidget#helpPopup{border:1px solid palette(mid);background:palette(window);"
            "color:palette(window-text);} QLabel{color:palette(window-text);}"
        )

    def show_at(self, position: QPoint) -> None:
        self.adjustSize()
        target = QPoint(position)
        screen = QApplication.screenAt(position)
        if screen:
            area = screen.availableGeometry()
            width = self.sizeHint().width()
            height = self.sizeHint().height()
            if target.x() + width > area.right():
                target.setX(position.x() - width - 6)
            if target.y() + height > area.bottom():
                target.setY(position.y() - height - 6)
            target.setX(max(area.left(), target.x()))
            target.setY(max(area.top(), target.y()))
        self.move(target)
        self.show()
        self.raise_()


class HelpButton(QToolButton):
    def __init__(
        self,
        help_text: str = HELP_TEXT,
        accent: bool = False,
        diameter: int = 24,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.popup = HelpPopup(help_text, self)
        self.left_at: Optional[float] = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(80)
        self.hide_timer.timeout.connect(self.hide_popup_if_left)
        self.setMouseTracking(True)
        self.setText("?")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(diameter, diameter)
        radius = diameter // 2
        if accent:
            self.setStyleSheet(
                f"QToolButton{{border:2px solid #ef4444;border-radius:{radius}px;background:transparent;"
                "color:#ef4444;font-weight:700;padding:0;} QToolButton:hover{background:palette(light);}"
            )
        else:
            self.setStyleSheet(
                f"QToolButton{{border:1px solid palette(mid);border-radius:{radius}px;background:palette(button);"
                "color:palette(button-text);font-weight:700;padding:0;} QToolButton:hover{background:palette(light);}"
            )

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.show_popup()
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        self.show_popup()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self.left_at = time.monotonic()
        super().leaveEvent(event)

    def show_popup(self) -> None:
        self.left_at = None
        self.popup.show_at(QCursor.pos() + QPoint(6, 6))
        if not self.hide_timer.isActive():
            self.hide_timer.start()

    def hide_popup_if_left(self) -> None:
        if not self.popup.isVisible():
            self.hide_timer.stop()
            return
        cursor = QCursor.pos()
        inside_button = self.rect().contains(self.mapFromGlobal(cursor))
        inside_popup = self.popup.geometry().contains(cursor)
        if inside_button or inside_popup:
            self.left_at = None
            return
        if self.left_at is None:
            self.left_at = time.monotonic()
            return
        if time.monotonic() - self.left_at >= 0.18:
            self.popup.hide()
            self.hide_timer.stop()


class AccessHeader(QHeaderView):
    def __init__(self, status_column: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self.status_column = status_column
        self.status_help = HelpButton(STATUS_HELP_TEXT, accent=True, diameter=18, parent=self.viewport())
        self.sectionResized.connect(self.position_status_help)
        self.sectionMoved.connect(self.position_status_help)
        self.geometriesChanged.connect(self.position_status_help)
        QTimer.singleShot(0, self.position_status_help)

    def position_status_help(self, *_args) -> None:
        section_x = self.sectionViewportPosition(self.status_column)
        section_width = self.sectionSize(self.status_column)
        if section_x < 0 or section_width <= 0:
            self.status_help.hide()
            return
        x = section_x + section_width - self.status_help.width() - 6
        y = max(0, (self.height() - self.status_help.height()) // 2)
        self.status_help.move(x, y)
        self.status_help.show()
        self.status_help.raise_()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self.position_status_help()


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ShareCard(QFrame):
    clicked = Signal(int, object)
    contextRequested = Signal(int, QPoint)
    deleteRequested = Signal()
    modeChanged = Signal(int, bool)
    uploadChanged = Signal(int, bool)
    reorderDragStarted = Signal(int)
    reorderDragEnded = Signal(int)

    def __init__(self, share_item: ShareItem, icon_provider: QFileIconProvider) -> None:
        super().__init__()
        self.item_id = share_item.item_id
        self.path = share_item.path
        self.selected = False
        self.running = share_item.running
        self.press_position = QPoint()
        self.drag_ready = False
        self.drag_started = False
        self.dragging = False
        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.setInterval(350)
        self.long_press_timer.timeout.connect(self.enable_drag_after_hold)
        self.setObjectName("shareCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setToolTip(str(self.path))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(icon_provider.icon(QFileInfo(str(self.path))).pixmap(QSize(48, 48)))
        self.icon_label.setFixedSize(56, 56)
        layout.addWidget(self.icon_label, 0)

        text_box = QWidget()
        text_box.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        self.name_label = QLabel(self.path.name or str(self.path))
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.name_label.setWordWrap(True)
        text_layout.addWidget(self.name_label)

        self.path_label = QLabel(str(self.path))
        self.path_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.path_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.path_label.setWordWrap(True)
        text_layout.addWidget(self.path_label)
        layout.addWidget(text_box, 1)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.mode_checkbox = QCheckBox("临时")
        self.mode_checkbox.setChecked(share_item.temporary)
        self.mode_checkbox.setToolTip("勾选使用 Python 临时服务；不勾选使用 Nginx")
        self.mode_checkbox.toggled.connect(lambda checked: self.modeChanged.emit(self.item_id, checked))
        right_layout.addWidget(self.mode_checkbox, 0, Qt.AlignTop)

        self.upload_checkbox = QCheckBox("允许上传")
        self.upload_checkbox.setChecked(item_allows_upload(share_item))
        self.upload_checkbox.setToolTip("只对文件夹生效，上传会写入共享目录下的 Uploads 文件夹")
        self.upload_checkbox.toggled.connect(lambda checked: self.uploadChanged.emit(self.item_id, checked))
        right_layout.addWidget(self.upload_checkbox, 0, Qt.AlignTop)

        self.state_label = QLabel()
        self.state_label.setObjectName("itemStateLabel")
        self.state_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.state_label, 0, Qt.AlignTop)
        right_layout.addStretch()
        layout.addWidget(right_box, 0, Qt.AlignTop)
        self.sync_state()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.sync_state()
        self.style().unpolish(self)
        self.style().polish(self)

    def sync_state(self) -> None:
        self.setFrameShape(QFrame.StyledPanel)
        self.setLineWidth(1)
        self.setProperty("running", "true" if self.running else "false")
        self.state_label.setText("已启动" if self.running else "未启动")

    def set_mode_enabled(self, enabled: bool) -> None:
        self.mode_checkbox.setEnabled(enabled)

    def set_upload_enabled(self, enabled: bool) -> None:
        self.upload_checkbox.setEnabled(enabled and self.path.is_dir())

    def set_upload_allowed(self, allowed: bool) -> None:
        blocked = self.upload_checkbox.blockSignals(True)
        self.upload_checkbox.setChecked(allowed and self.path.is_dir())
        self.upload_checkbox.blockSignals(blocked)

    def set_running(self, running: bool) -> None:
        self.running = running
        self.sync_state()
        self.style().unpolish(self)
        self.style().polish(self)

    def set_dragging(self, dragging: bool) -> None:
        self.dragging = dragging
        self.setProperty("dragging", "true" if dragging else "false")
        if dragging:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.35)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)
        self.style().unpolish(self)
        self.style().polish(self)

    def enable_drag_after_hold(self) -> None:
        self.drag_ready = True

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.press_position = event.position().toPoint()
            self.drag_ready = False
            self.drag_started = False
            self.long_press_timer.start()
            self.clicked.emit(self.item_id, event.modifiers())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.buttons() & Qt.LeftButton and self.drag_ready and not self.drag_started:
            distance = (event.position().toPoint() - self.press_position).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self.start_reorder_drag()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        self.long_press_timer.stop()
        self.drag_ready = False
        self.drag_started = False
        super().mouseReleaseEvent(event)

    def start_reorder_drag(self) -> None:
        self.drag_started = True
        self.long_press_timer.stop()
        mime_data = QMimeData()
        mime_data.setData(INTERNAL_ITEM_MIME, str(self.item_id).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self.press_position)
        self.reorderDragStarted.emit(self.item_id)
        self.set_dragging(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.set_dragging(False)
            self.reorderDragEnded.emit(self.item_id)

    def contextMenuEvent(self, event) -> None:  # noqa: ANN001
        self.contextRequested.emit(self.item_id, event.globalPos())
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class DropListWidget(QScrollArea):
    pathsDropped = Signal(list)
    itemContextRequested = Signal(int, QPoint)
    blankContextRequested = Signal(QPoint)
    removeRequested = Signal()
    selectionChanged = Signal()
    modeChanged = Signal(int, bool)
    uploadChanged = Signal(int, bool)
    orderChanged = Signal(list)

    def __init__(self, icon_provider: QFileIconProvider) -> None:
        super().__init__()
        self.setObjectName("shareList")
        self.icon_provider = icon_provider
        self.cards: dict[int, ShareCard] = {}
        self.card_order: list[int] = []
        self.selected: set[int] = set()
        self.reorder_animations: list[QPropertyAnimation] = []
        self.drag_source_id: Optional[int] = None
        self.drag_original_order: list[int] = []
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)
        self.setWidgetResizable(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        self.content = QWidget()
        self.content.setObjectName("shareListContent")
        self.content.setAcceptDrops(True)
        self.content.installEventFilter(self)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(8, 8, 8, 8)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.placeholder = QLabel("拖入文件 / 文件夹")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setMinimumHeight(180)
        self.list_layout.addWidget(self.placeholder)
        self.list_layout.addStretch(1)
        self.setWidget(self.content)

    def eventFilter(self, source, event) -> bool:  # noqa: ANN001
        if source in (self.viewport(), self.content) and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if self.handle_reorder_event(event, None):
                return True
            return self.handle_drop_event(event)
        if source in (self.viewport(), self.content) and event.type() == QEvent.ContextMenu:
            self.blankContextRequested.emit(event.globalPos())
            event.accept()
            return True
        if isinstance(source, ShareCard) and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if self.handle_reorder_event(event, source.item_id):
                return True
            return self.handle_drop_event(event)
        return super().eventFilter(source, event)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        if self.handle_reorder_event(event, None):
            return
        self.handle_drop_event(event)

    def handle_drop_event(self, event) -> bool:  # noqa: ANN001
        if event.type() in (QEvent.DragEnter, QEvent.DragMove):
            if event.mimeData().hasUrls():
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return True
            event.ignore()
            return True
        if event.type() != QEvent.Drop:
            return False
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.pathsDropped.emit(paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()
        return True

    def handle_reorder_event(self, event, target_id: Optional[int]) -> bool:  # noqa: ANN001
        mime_data = event.mimeData()
        if not mime_data.hasFormat(INTERNAL_ITEM_MIME):
            return False
        if event.type() not in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            return False
        source_id = self.dragged_item_id(mime_data)
        if source_id is None or source_id not in self.cards:
            event.ignore()
            return True
        self.begin_drag_session(source_id)
        if event.type() == QEvent.DragMove:
            self.preview_reorder(source_id, target_id, self.drop_after_target(event, target_id))
        elif event.type() == QEvent.Drop:
            self.preview_reorder(source_id, target_id, self.drop_after_target(event, target_id))
            self.finish_drag_session(source_id)
        event.setDropAction(Qt.MoveAction)
        event.accept()
        return True

    def begin_drag_session(self, source_id: int) -> None:
        if self.drag_source_id == source_id:
            return
        self.drag_source_id = source_id
        self.drag_original_order = list(self.card_order)

    def finish_drag_session(self, source_id: int) -> None:
        if self.drag_source_id != source_id:
            return
        changed = self.card_order != self.drag_original_order
        self.drag_source_id = None
        self.drag_original_order = []
        if changed:
            self.orderChanged.emit(list(self.card_order))

    def preview_reorder(self, source_id: int, target_id: Optional[int], insert_after: bool) -> bool:
        return self.reorder_card(source_id, target_id, insert_after)

    def dragged_item_id(self, mime_data: QMimeData) -> Optional[int]:
        try:
            return int(bytes(mime_data.data(INTERNAL_ITEM_MIME)).decode("utf-8"))
        except (TypeError, ValueError):
            return None

    def drop_after_target(self, event, target_id: Optional[int]) -> bool:  # noqa: ANN001
        if target_id is None:
            return True
        card = self.cards.get(target_id)
        if not card:
            return True
        return event.position().toPoint().y() > card.height() // 2

    def reorder_card(self, source_id: int, target_id: Optional[int], insert_after: bool) -> bool:
        if source_id not in self.card_order:
            return False
        if target_id == source_id:
            return False
        before_geometries = self.card_geometries()
        before = list(self.card_order)
        ordered = [item_id for item_id in self.card_order if item_id != source_id]
        if target_id is None or target_id not in ordered:
            insert_index = len(ordered)
        else:
            target_index = ordered.index(target_id)
            insert_index = target_index + (1 if insert_after else 0)
        ordered.insert(insert_index, source_id)
        if ordered == before:
            return False
        self.card_order = ordered
        self.refresh_grid()
        self.animate_reorder_from(before_geometries)
        return True

    def card_geometries(self) -> dict[int, object]:
        return {item_id: card.geometry() for item_id, card in self.cards.items()}

    def animate_reorder_from(self, before_geometries: dict[int, object]) -> None:
        self.list_layout.activate()
        self.content.adjustSize()
        QApplication.processEvents()
        self.reorder_animations.clear()
        for item_id in self.card_order:
            card = self.cards.get(item_id)
            if not card or item_id not in before_geometries:
                continue
            start_geometry = before_geometries[item_id]
            end_geometry = card.geometry()
            if start_geometry == end_geometry:
                continue
            card.setGeometry(start_geometry)
            animation = QPropertyAnimation(card, b"geometry", self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.setStartValue(start_geometry)
            animation.setEndValue(end_geometry)
            animation.finished.connect(lambda animation=animation: self.remove_reorder_animation(animation))
            self.reorder_animations.append(animation)
            animation.start()

    def remove_reorder_animation(self, animation: QPropertyAnimation) -> None:
        if animation in self.reorder_animations:
            self.reorder_animations.remove(animation)

    def add_card(self, share_item: ShareItem) -> None:
        if self.placeholder:
            self.placeholder.setParent(None)
            self.placeholder.deleteLater()
            self.placeholder = None
        card = ShareCard(share_item, self.icon_provider)
        card.clicked.connect(self.set_selected_card)
        card.contextRequested.connect(self.itemContextRequested.emit)
        card.deleteRequested.connect(self.removeRequested.emit)
        card.modeChanged.connect(self.modeChanged.emit)
        card.uploadChanged.connect(self.uploadChanged.emit)
        card.reorderDragStarted.connect(self.begin_drag_session)
        card.reorderDragEnded.connect(self.finish_drag_session)
        card.setAcceptDrops(True)
        card.installEventFilter(self)
        self.cards[share_item.item_id] = card
        self.card_order.append(share_item.item_id)
        self.refresh_grid()

    def remove_cards(self, item_ids: set[int]) -> None:
        for item_id in item_ids:
            card = self.cards.pop(item_id, None)
            if card:
                card.setParent(None)
                card.deleteLater()
        self.card_order = [item_id for item_id in self.card_order if item_id not in item_ids]
        self.selected.difference_update(item_ids)
        self.refresh_grid()
        self.selectionChanged.emit()

    def selected_ids(self) -> set[int]:
        return set(self.selected)

    def set_mode_controls_enabled(self, enabled: bool) -> None:
        for card in self.cards.values():
            card.set_mode_enabled(enabled)

    def set_item_running(self, item_id: int, running: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_running(running)

    def set_item_mode_enabled(self, item_id: int, enabled: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_mode_enabled(enabled)

    def set_item_upload_enabled(self, item_id: int, enabled: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_upload_enabled(enabled)

    def set_item_upload_allowed(self, item_id: int, allowed: bool) -> None:
        card = self.cards.get(item_id)
        if card:
            card.set_upload_allowed(allowed)

    def select_single(self, item_id: int) -> None:
        if item_id not in self.cards:
            return
        self.clear_selection(False)
        self.selected.add(item_id)
        self.cards[item_id].set_selected(True)
        self.selectionChanged.emit()

    def set_selected_card(self, item_id: int, modifiers) -> None:  # noqa: ANN001
        self.setFocus(Qt.MouseFocusReason)
        before = set(self.selected)
        if not (modifiers & Qt.MetaModifier or modifiers & Qt.ControlModifier):
            self.clear_selection(False)
        if item_id in self.selected:
            self.selected.remove(item_id)
            self.cards[item_id].set_selected(False)
        else:
            self.selected.add(item_id)
            self.cards[item_id].set_selected(True)
        if before != self.selected:
            self.selectionChanged.emit()

    def clear_selection(self, emit_signal: bool = True) -> None:
        changed = bool(self.selected)
        for selected_id in list(self.selected):
            card = self.cards.get(selected_id)
            if card:
                card.set_selected(False)
        self.selected.clear()
        if changed and emit_signal:
            self.selectionChanged.emit()

    def refresh_grid(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        if not self.cards:
            self.placeholder = QLabel("拖入文件 / 文件夹")
            self.placeholder.setAlignment(Qt.AlignCenter)
            self.placeholder.setMinimumHeight(180)
            self.list_layout.addWidget(self.placeholder)
            self.list_layout.addStretch(1)
            return
        for item_id in self.card_order:
            card = self.cards.get(item_id)
            if not card:
                continue
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.removeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    accessReceived = Signal(dict)
    publicIpResolved = Signal(dict)
    nginxInstallFinished = Signal(str, str)

    def __init__(self, theme_manager: ThemeManager) -> None:
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowTitle("LANFileServer - 局域网文件服务器")
        self.resize(1120, 720)
        self.setAcceptDrops(True)
        self.icon_provider = QFileIconProvider()
        self.next_id = 0
        self.items: list[ShareItem] = []
        self.python_server: Optional[PythonShareServer] = None
        self.nginx_server: Optional[NginxShareServer] = None
        self.nginx_log_path: Optional[Path] = None
        self.nginx_offset = 0
        self.nginx_installing = False
        self._quitting = False
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.pending_start_item_id: Optional[int] = None
        self.lan_ips = get_lan_ips()
        self.public_ip = "获取中"
        self.public_ip_location = "位置获取中"
        self.status_text = "未启动"
        self.accessReceived.connect(self.add_access_row)
        self.publicIpResolved.connect(self.set_public_ip)
        self.nginxInstallFinished.connect(self.finish_nginx_install)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.read_nginx_log)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.refresh_clock)
        self.build_ui()
        self.apply_style()
        self.setup_system_tray()
        self.theme_manager.themeChanged.connect(self.theme_changed)
        self.refresh_status("未启动")
        self.refresh_clock()
        self.clock_timer.start(1000)
        self.resolve_public_ip_async()

    @staticmethod
    def resource_path(name: str) -> Path:
        source_root = Path(__file__).resolve().parent.parent
        bundle_root = Path(getattr(sys, "_MEIPASS", source_root))
        return bundle_root / name

    def setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(self.resource_path("icon.png")))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
        self.setWindowIcon(icon)
        menu = QMenu(self)
        show_action = QAction("显示 LANFileServer", menu)
        quit_action = QAction("停止服务并退出 LANFileServer", menu)
        show_action.triggered.connect(self.restore_from_system_tray)
        quit_action.triggered.connect(self.quit_application)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(APP_NAME)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.system_tray_activated)
        self.tray_icon.show()

    def hide_to_system_tray(self) -> None:
        if self.tray_icon is not None and self.tray_icon.isVisible():
            self.hide()

    def restore_from_system_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def system_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_from_system_tray()

    def quit_application(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.stop_all_servers(silent=True)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.quit()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.hide_to_system_tray)

    def build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("mainCentralWidget")
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        temp_box = QWidget()
        temp_layout = QVBoxLayout(temp_box)
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.setSpacing(2)
        temp_row = QHBoxLayout()
        temp_row.setContentsMargins(0, 0, 0, 0)
        temp_row.setSpacing(6)
        self.mode_title_label = QLabel()
        temp_row.addWidget(self.mode_title_label)
        temp_row.addWidget(HelpButton())
        temp_row.addStretch()
        temp_layout.addLayout(temp_row)
        self.temp_hint_widget = QWidget()
        temp_hint_layout = QHBoxLayout(self.temp_hint_widget)
        temp_hint_layout.setContentsMargins(0, 0, 0, 0)
        temp_hint_layout.setSpacing(4)
        self.temp_hint_label = ClickableLabel()
        self.temp_hint_label.setObjectName("tempHintLabel")
        self.temp_hint_label.setWordWrap(True)
        self.temp_hint_label.clicked.connect(self.copy_url)
        temp_hint_layout.addWidget(self.temp_hint_label, 1)
        self.temp_hint_widget.setVisible(False)
        temp_layout.addWidget(self.temp_hint_widget)

        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        control_row.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        self.port_spin.setFixedWidth(96)
        self.port_spin.valueChanged.connect(self.refresh_temp_hint)
        control_row.addWidget(self.port_spin)
        self.toggle_button = QPushButton("启动")
        self.toggle_button.clicked.connect(self.toggle_server)
        control_row.addWidget(self.toggle_button)
        control_row.addStretch()
        temp_layout.addLayout(control_row)

        top.addWidget(temp_box, 0, Qt.AlignTop)
        top.addStretch()
        status_box = QWidget()
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(1)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self.show_theme_menu)
        theme_button_layout = QHBoxLayout(self.theme_button)
        theme_button_layout.setContentsMargins(12, 0, 8, 0)
        theme_button_layout.setSpacing(6)
        self.theme_button_label = QLabel()
        self.theme_button_label.setAlignment(Qt.AlignCenter)
        self.theme_button_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        theme_button_layout.addWidget(self.theme_button_label, 1)
        self.theme_arrow_label = QLabel("▼")
        self.theme_arrow_label.setAlignment(Qt.AlignCenter)
        self.theme_arrow_label.setFixedWidth(12)
        self.theme_arrow_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        theme_button_layout.addWidget(self.theme_arrow_label, 0)
        self.theme_menu = QMenu(self.theme_button)
        self.theme_actions: dict[str, QAction] = {}
        for mode, label in THEME_OPTIONS:
            action = self.theme_menu.addAction(label)
            action.setData(mode)
            action.triggered.connect(lambda _checked=False, selected_mode=mode: self.theme_manager.set_mode(selected_mode))
            self.theme_actions[mode] = action
        self.sync_theme_button(self.theme_manager.mode)
        status_layout.addWidget(self.theme_button, 0, Qt.AlignRight)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_layout.addWidget(self.time_label)
        self.lan_ip_label = ClickableLabel()
        self.lan_ip_label.setObjectName("ipLabel")
        self.lan_ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lan_ip_label.clicked.connect(self.copy_lan_ip)
        status_layout.addWidget(self.lan_ip_label)
        self.public_ip_label = ClickableLabel()
        self.public_ip_label.setObjectName("ipLabel")
        self.public_ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.public_ip_label.clicked.connect(self.copy_public_ip)
        status_layout.addWidget(self.public_ip_label)
        top.addWidget(status_box)
        root.addLayout(top, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(QLabel("对外暴露的文件 / 文件夹（可直接拖入）"))
        self.share_list = DropListWidget(self.icon_provider)
        self.share_list.pathsDropped.connect(self.add_paths)
        self.share_list.itemContextRequested.connect(self.open_share_context_menu)
        self.share_list.blankContextRequested.connect(self.open_blank_share_context_menu)
        self.share_list.removeRequested.connect(self.remove_selected)
        self.share_list.selectionChanged.connect(self.refresh_selection_state)
        self.share_list.modeChanged.connect(self.set_item_temporary)
        self.share_list.uploadChanged.connect(self.set_item_upload_allowed)
        self.share_list.orderChanged.connect(self.reorder_items)
        left_layout.addWidget(self.share_list, 1)
        left_buttons = QHBoxLayout()
        left_buttons.setContentsMargins(0, 0, 0, 0)
        left_buttons.setSpacing(8)
        add_file = QPushButton("添加文件")
        add_file.clicked.connect(self.choose_files)
        left_buttons.addWidget(add_file)
        add_dir = QPushButton("添加文件夹")
        add_dir.clicked.connect(self.choose_dir)
        left_buttons.addWidget(add_dir)
        self.remove_button = QPushButton("移除")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_selected)
        left_buttons.addWidget(self.remove_button)
        left_layout.addLayout(left_buttons)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(QLabel("访问记录"))
        self.access_table = QTableWidget(0, 8)
        self.access_header = AccessHeader(5, self.access_table)
        self.access_table.setHorizontalHeader(self.access_header)
        self.access_table.setHorizontalHeaderLabels(["序号", "时间", "访问人 IP", "引擎", "方法", "状态", "对象", "路径"])
        self.access_table.verticalHeader().setVisible(False)
        for col in range(7):
            self.access_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.access_header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.access_header.resizeSection(0, 58)
        self.access_header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.access_header.resizeSection(5, 82)
        self.access_header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.access_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.access_table.setAlternatingRowColors(True)
        self.access_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.access_table.customContextMenuRequested.connect(self.open_access_context_menu)
        self.access_placeholder = QLabel("启动服务以后查看", self.access_table.viewport())
        self.access_placeholder.setObjectName("accessPlaceholder")
        self.access_placeholder.setAlignment(Qt.AlignCenter)
        self.access_placeholder.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.access_placeholder.hide()
        self.access_table.viewport().installEventFilter(self)
        right_layout.addWidget(self.access_table, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 720])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.toast_label = QLabel(self)
        self.toast_label.setObjectName("toastLabel")
        self.toast_label.setAlignment(Qt.AlignCenter)
        self.toast_label.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_label.hide)
        self.refresh_selection_state()
        self.refresh_access_placeholder()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { color: palette(window-text); font-size: 14px; }
            QMainWindow, QWidget#mainCentralWidget { background: palette(window); }
            QPushButton, QSpinBox {
                min-height: 28px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(button);
                color: palette(button-text);
            }
            QPushButton { padding: 4px 12px; }
            QSpinBox { padding: 3px 6px; }
            QPushButton#themeButton { min-width: 148px; padding: 3px 0; }
            QPushButton#themeButton QLabel { background: transparent; color: palette(button-text); }
            QPushButton:hover, QSpinBox:hover { background: palette(light); }
            QPushButton:pressed { background: palette(midlight); }
            QPushButton:disabled, QSpinBox:disabled {
                background: palette(button);
                color: palette(mid);
            }
            QScrollArea, QTableWidget {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background: palette(base);
                color: palette(text);
            }
            QScrollArea#shareList, QWidget#shareListContent { background: palette(base); }
            QTableWidget {
                alternate-background-color: palette(alternate-base);
                gridline-color: palette(mid);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QTableWidget::item { padding: 4px 8px; }
            QFrame#shareCard { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); color: palette(text); }
            QFrame#shareCard[running="true"] { border-color: palette(link); }
            QFrame#shareCard[selected="true"] { border: 2px solid palette(highlight); background: palette(highlight); color: palette(highlighted-text); }
            QFrame#shareCard[selected="true"] QLabel { color: palette(highlighted-text); }
            QFrame#shareCard[selected="true"] QCheckBox { color: palette(highlighted-text); }
            QFrame#shareCard[dragging="true"] { border: 1px dashed palette(highlight); }
            QLabel#tempHintLabel { color: palette(link); font-size: 12px; }
            QLabel#itemStateLabel { color: palette(link); font-size: 12px; }
            QLabel#tempHintLabel:hover, QLabel#ipLabel:hover { text-decoration: underline; }
            QLabel#ipLabel { color: palette(link); }
            QLabel#accessPlaceholder { color: palette(mid); font-size: 16px; font-weight: 700; background: transparent; }
            QLabel#toastLabel { padding: 8px 14px; border-radius: 6px; background: palette(highlight); color: palette(highlighted-text); }
            QHeaderView::section { padding: 8px; font-weight: 700; background: palette(button); color: palette(button-text); border: none; border-bottom: 1px solid palette(mid); }
            QTableCornerButton::section { background: palette(button); border: none; border-bottom: 1px solid palette(mid); }
            QMenu { border: 1px solid palette(mid); background: palette(base); color: palette(text); }
            QMenu::item { padding: 6px 24px; }
            QMenu::item:selected { background: palette(highlight); color: palette(highlighted-text); }
            QToolTip { border: 1px solid palette(mid); background: palette(tool-tip-base); color: palette(tool-tip-text); }
            """
        )

    def show_theme_menu(self) -> None:
        menu_size = self.theme_menu.sizeHint()
        button_bottom_right = self.theme_button.mapToGlobal(self.theme_button.rect().bottomRight())
        menu_position = QPoint(button_bottom_right.x() - menu_size.width() + 1, button_bottom_right.y() + 1)
        self.theme_menu.popup(menu_position)

    def theme_dot_icon(self, selected: bool) -> QIcon:
        logical_size = 14
        pixel_ratio = max(1.0, self.devicePixelRatioF())
        pixmap = QPixmap(round(logical_size * pixel_ratio), round(logical_size * pixel_ratio))
        pixmap.setDevicePixelRatio(pixel_ratio)
        pixmap.fill(Qt.transparent)
        if selected:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.palette().color(QPalette.WindowText))
            painter.drawEllipse(QRectF(4, 4, 6, 6))
            painter.end()
        return QIcon(pixmap)

    def sync_theme_button(self, mode: str) -> None:
        labels = dict(THEME_OPTIONS)
        self.theme_button_label.setText(f"主题：{labels.get(mode, labels[THEME_SYSTEM])}")
        for action_mode, action in self.theme_actions.items():
            action.setIcon(self.theme_dot_icon(action_mode == mode))

    def theme_changed(self, mode: str, _dark: bool) -> None:
        self.sync_theme_button(mode)
        self.apply_style()

    def add_paths(self, paths: list[str]) -> None:
        if not self.items:
            self.next_id = 0
        existing = {str(item.path.resolve()) for item in self.items if item.path.exists()}
        last_added_id: Optional[int] = None
        for value in paths:
            path = Path(value).expanduser()
            if not path.exists():
                continue
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            item = ShareItem(self.next_id, path, temporary=True)
            self.next_id += 1
            self.items.append(item)
            self.share_list.add_card(item)
            existing.add(resolved)
            last_added_id = item.item_id
        if last_added_id is not None:
            self.share_list.select_single(last_added_id)
        else:
            self.refresh_selection_state()

    def choose_files(self) -> None:
        dialog = QFileDialog(self, "选择要暴露的文件")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setViewMode(QFileDialog.Detail)
        paths = dialog.selectedFiles() if dialog.exec() == QFileDialog.Accepted else []
        if paths:
            self.add_paths(paths)

    def choose_dir(self) -> None:
        dialog = QFileDialog(self, "选择要暴露的文件夹")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setViewMode(QFileDialog.Detail)
        paths = dialog.selectedFiles() if dialog.exec() == QFileDialog.Accepted else []
        if paths:
            self.add_paths(paths)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        self.share_list.handle_drop_event(event)

    def remove_selected(self) -> None:
        selected = self.share_list.selected_ids()
        if not selected:
            return
        removed_running = any(item.running for item in self.items if item.item_id in selected)
        self.items = [item for item in self.items if item.item_id not in selected]
        self.share_list.remove_cards(selected)
        self.select_default_item()
        if removed_running:
            self.rebuild_runtime_safely()
            self.refresh_running_status("已停止")
        if not self.items:
            self.next_id = 0
        self.refresh_selection_state()

    def clear_all_items(self) -> None:
        if not self.items:
            return
        self.stop_runtime()
        self.items.clear()
        self.next_id = 0
        self.share_list.remove_cards(set(self.share_list.cards.keys()))
        self.refresh_status("未启动")
        self.refresh_selection_state()

    def open_blank_share_context_menu(self, global_position: QPoint) -> None:
        menu = QMenu(self)
        clear_action = menu.addAction("全部清除")
        clear_action.setEnabled(bool(self.items))
        if menu.exec(global_position) == clear_action:
            self.clear_all_items()

    def open_share_context_menu(self, item_id: int, global_position: QPoint) -> None:
        self.share_list.clear_selection()
        card = self.share_list.cards.get(item_id)
        if card:
            self.share_list.selected.add(item_id)
            card.set_selected(True)
            self.share_list.selectionChanged.emit()
        share_item = next((item for item in self.items if item.item_id == item_id), None)
        menu = QMenu(self)
        toggle_action = menu.addAction("停止" if share_item and share_item.running else "启动")
        toggle_action.setEnabled(bool(share_item) and not self.nginx_installing)
        copy_url_action = menu.addAction("复制URL")
        copy_url_action.setEnabled(bool(share_item))
        open_url_action = menu.addAction("本机默认浏览器打开")
        open_url_action.setEnabled(bool(share_item and share_item.running))
        show_action = menu.addAction("Show in Finder")
        remove_action = menu.addAction("移除")
        selected_action = menu.exec(global_position)
        if selected_action == toggle_action and share_item:
            self.stop_item(share_item) if share_item.running else self.start_item(share_item)
        elif selected_action == copy_url_action and share_item:
            self.copy_item_url(share_item)
        elif selected_action == open_url_action and share_item:
            self.open_item_url(share_item)
        elif selected_action == show_action:
            self.show_item_in_finder(item_id)
        elif selected_action == remove_action:
            self.remove_selected()

    def open_access_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        clear_action = menu.addAction("清除记录")
        clear_action.setEnabled(self.access_table.rowCount() > 0)
        selected_action = menu.exec(self.access_table.viewport().mapToGlobal(position))
        if selected_action == clear_action:
            self.clear_access_records()

    def clear_access_records(self) -> None:
        self.access_table.setRowCount(0)
        self.refresh_access_placeholder()
        self.show_toast("访问记录已清除")

    def reorder_items(self, item_order: list[int]) -> None:
        items_by_id = {item.item_id: item for item in self.items}
        ordered_items = [items_by_id[item_id] for item_id in item_order if item_id in items_by_id]
        ordered_ids = {item.item_id for item in ordered_items}
        ordered_items.extend(item for item in self.items if item.item_id not in ordered_ids)
        self.items = ordered_items
        if self.active_items():
            self.rebuild_runtime_safely()

    def show_item_in_finder(self, item_id: int) -> None:
        share_item = next((item for item in self.items if item.item_id == item_id), None)
        if not share_item or not share_item.path.exists():
            QMessageBox.warning(self, "路径不存在", "这个文件 / 文件夹已经不存在。")
            return
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(share_item.path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(share_item.path)], check=False)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(share_item.path.parent)))

    def home_url(self) -> str:
        return f"http://{self.lan_ips[0]}:{self.port_spin.value()}/"

    def item_url(self, item: ShareItem) -> str:
        return f"{self.home_url()}items/{item.item_id}/"

    def copy_item_url(self, item: ShareItem) -> None:
        QApplication.clipboard().setText(self.item_url(item))
        self.show_toast("访问地址已复制")

    def open_item_url(self, item: ShareItem) -> None:
        if not item.running:
            self.show_toast("请先启动这个项目")
            return
        QDesktopServices.openUrl(QUrl(self.item_url(item)))

    def selected_share_item(self) -> Optional[ShareItem]:
        selected = self.share_list.selected_ids()
        if len(selected) != 1:
            return None
        selected_id = next(iter(selected))
        return next((item for item in self.items if item.item_id == selected_id), None)

    def current_access_url(self) -> str:
        item = self.selected_share_item()
        return self.item_url(item) if item else ""

    def current_share_item(self) -> Optional[ShareItem]:
        return self.selected_share_item() or (self.items[-1] if self.items else None)

    def select_default_item(self) -> None:
        if self.items and not self.share_list.selected_ids():
            self.share_list.select_single(self.items[-1].item_id)

    def refresh_selection_state(self) -> None:
        self.remove_button.setEnabled(bool(self.share_list.selected_ids()))
        self.refresh_item_cards_state()
        self.refresh_start_button_state()
        self.refresh_mode_title()
        self.refresh_temp_hint()

    def set_item_temporary(self, item_id: int, temporary: bool) -> None:
        item = next((entry for entry in self.items if entry.item_id == item_id), None)
        if item:
            if item.running:
                self.share_list.set_item_mode_enabled(item_id, False)
                return
            item.temporary = temporary
        self.refresh_mode_title()

    def set_item_upload_allowed(self, item_id: int, allowed: bool) -> None:
        item = next((entry for entry in self.items if entry.item_id == item_id), None)
        if item:
            if item.running:
                self.share_list.set_item_upload_allowed(item_id, item_allows_upload(item))
                return
            item.upload_allowed = allowed and item.path.is_dir()
            self.share_list.set_item_upload_allowed(item_id, item.upload_allowed)
        self.refresh_mode_title()

    def item_mode_text(self, item: ShareItem) -> str:
        return "临时（Python）" if item.temporary else "非临时（Nginx）"

    def refresh_mode_title(self) -> None:
        selected_ids = self.share_list.selected_ids()
        if len(selected_ids) == 1:
            item = self.selected_share_item()
            if item:
                self.mode_title_label.setText(f"当前模式：{self.item_mode_text(item)}")
                return
        if len(selected_ids) > 1:
            self.mode_title_label.setText(f"共享模式：已选 {len(selected_ids)} 项")
        elif self.items:
            self.mode_title_label.setText("共享模式：点击左侧项目查看")
        else:
            self.mode_title_label.setText("共享模式：未添加")

    def active_items(self) -> list[ShareItem]:
        return [item for item in self.items if item.running]

    def requires_nginx(self, items: Optional[list[ShareItem]] = None) -> bool:
        targets = items if items is not None else self.active_items()
        return any(not item.temporary for item in targets)

    def server_running(self) -> bool:
        return bool(self.active_items())

    def refresh_start_button_state(self) -> None:
        if self.nginx_installing:
            self.toggle_button.setEnabled(False)
            return
        item = self.selected_share_item()
        self.toggle_button.setText("停止" if item and item.running else "启动")
        can_toggle = item is not None
        self.toggle_button.setEnabled(can_toggle)
        if can_toggle:
            self.toggle_button.setToolTip("")
        elif self.items:
            self.toggle_button.setToolTip("请先点选一个要启动或停止的文件 / 文件夹")
        else:
            self.toggle_button.setToolTip("请先拖入或添加要对外暴露的文件 / 文件夹")

    def refresh_item_cards_state(self) -> None:
        for item in self.items:
            self.share_list.set_item_running(item.item_id, item.running)
            self.share_list.set_item_mode_enabled(item.item_id, not item.running and not self.nginx_installing)
            self.share_list.set_item_upload_enabled(item.item_id, not item.running and not self.nginx_installing)
            self.share_list.set_item_upload_allowed(item.item_id, item_allows_upload(item))

    def refresh_runtime_controls(self) -> None:
        self.port_spin.setEnabled(not self.server_running() and not self.nginx_installing)
        self.refresh_item_cards_state()
        self.refresh_start_button_state()
        self.refresh_temp_hint()
        self.refresh_access_placeholder()

    def refresh_temp_hint(self) -> None:
        if not self.selected_share_item():
            self.temp_hint_label.clear()
            self.temp_hint_widget.setVisible(False)
            return
        self.temp_hint_label.setText(self.current_access_url())
        self.temp_hint_widget.setVisible(True)

    def refresh_status(self, text: str) -> None:
        self.status_text = text
        self.status_label.setText(text)
        self.lan_ip_label.setText(f"内网 IP：{', '.join(self.lan_ips)}")
        self.public_ip_label.setText(f"（目前的）外网 IP：{self.public_ip}｜位置：{self.public_ip_location}")

    def refresh_clock(self) -> None:
        self.time_label.setText(current_time_text())

    def set_public_ip(self, public_info: dict[str, str]) -> None:
        self.public_ip = public_info.get("ip", "获取失败")
        self.public_ip_location = public_info.get("location", "位置获取失败")
        self.refresh_status(self.status_text)

    def resolve_public_ip_async(self) -> None:
        threading.Thread(target=lambda: self.publicIpResolved.emit(get_public_ip_info()), daemon=True).start()

    def toggle_server(self) -> None:
        if self.nginx_installing:
            return
        item = self.selected_share_item()
        if not item:
            return
        if item.running:
            self.stop_item(item)
        else:
            self.start_item(item)

    def start_item(self, item: ShareItem) -> None:
        if not item.path.exists():
            QMessageBox.warning(self, "路径不存在", "这个文件 / 文件夹已经不存在。")
            return
        if not item.temporary and not NginxShareServer.find_nginx():
            self.begin_nginx_install(item.item_id)
            return
        item.running = True
        self.refresh_runtime_controls()
        try:
            self.rebuild_runtime_for_active_items()
        except Exception as error:
            item.running = False
            self.refresh_runtime_controls()
            self.rebuild_runtime_safely()
            QMessageBox.critical(self, "启动失败", str(error))
            self.refresh_status("启动失败")

    def stop_item(self, item: ShareItem, silent: bool = False) -> None:
        item.running = False
        self.refresh_runtime_controls()
        self.rebuild_runtime_safely()
        if not silent:
            self.refresh_running_status("已停止")

    def begin_nginx_install(self, item_id: int) -> None:
        self.nginx_installing = True
        self.pending_start_item_id = item_id
        self.toggle_button.setText("安装中")
        self.toggle_button.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.refresh_item_cards_state()
        self.refresh_status("正在自动准备 Nginx，请稍候")
        threading.Thread(target=self.install_nginx_worker, daemon=True).start()

    def install_nginx_worker(self) -> None:
        try:
            nginx_path = NginxShareServer.install_nginx()
            self.nginxInstallFinished.emit(nginx_path, "")
        except Exception as error:
            self.nginxInstallFinished.emit("", str(error))

    def finish_nginx_install(self, nginx_path: str, error_text: str) -> None:
        self.nginx_installing = False
        pending_item_id = self.pending_start_item_id
        self.pending_start_item_id = None
        self.refresh_runtime_controls()
        if error_text:
            QMessageBox.critical(self, "Nginx 准备失败", error_text)
            self.refresh_status("Nginx 准备失败")
            return
        self.show_toast(f"Nginx 已准备完成：{Path(nginx_path).name}")
        item = next((entry for entry in self.items if entry.item_id == pending_item_id), None)
        if item:
            self.start_item(item)

    def stop_runtime(self) -> None:
        if self.python_server:
            self.python_server.stop()
            self.python_server = None
        if self.nginx_server:
            self.nginx_server.stop()
            self.nginx_server = None
        self.log_timer.stop()
        self.nginx_log_path = None
        self.nginx_offset = 0

    def stop_all_servers(self, silent: bool = False) -> None:
        for item in self.items:
            item.running = False
        self.stop_runtime()
        self.refresh_runtime_controls()
        if not silent:
            self.refresh_status("已停止")

    def rebuild_runtime_safely(self) -> None:
        try:
            self.rebuild_runtime_for_active_items()
        except Exception as error:
            QMessageBox.critical(self, "服务刷新失败", str(error))
            for item in self.items:
                item.running = False
            self.stop_runtime()
            self.refresh_runtime_controls()
            self.refresh_status("启动失败")

    def rebuild_runtime_for_active_items(self) -> None:
        active_items = self.active_items()
        nginx_items = [item for item in active_items if not item.temporary]
        if active_items and not nginx_items and self.python_server and not self.nginx_server:
            self.python_server.refresh_items(active_items)
            self.refresh_running_status()
            self.refresh_runtime_controls()
            return
        self.stop_runtime()
        NginxShareServer.cleanup_stale_instances()
        if not active_items:
            self.refresh_runtime_controls()
            return
        if nginx_items:
            self.python_server = PythonShareServer(lambda payload: self.accessReceived.emit(payload), record_requests=False)
            backend_port = self.python_server.start(active_items, 0, host="127.0.0.1")
            self.nginx_server = NginxShareServer()
            self.nginx_log_path = self.nginx_server.start(active_items, self.port_spin.value(), backend_port)
            self.nginx_offset = 0
            self.log_timer.start(1000)
        else:
            self.python_server = PythonShareServer(lambda payload: self.accessReceived.emit(payload))
            self.python_server.start(active_items, self.port_spin.value())
        self.refresh_running_status()
        self.refresh_runtime_controls()

    def refresh_running_status(self, stopped_text: str = "未启动") -> None:
        active_items = self.active_items()
        if not active_items:
            self.refresh_status(stopped_text)
            return
        if len(active_items) == 1:
            item = active_items[0]
            self.refresh_status(f"{self.item_mode_text(item)} 已启动：{self.item_url(item)}")
            return
        modes = {self.item_mode_text(item) for item in active_items}
        mode_text = "混合模式" if len(modes) > 1 else next(iter(modes))
        self.refresh_status(f"{mode_text} 已启动 {len(active_items)} 个项目")

    def copy_url(self) -> None:
        url = self.current_access_url()
        if not url:
            self.show_toast("请先选择一个项目")
            return
        QApplication.clipboard().setText(url)
        self.show_toast("访问地址已复制")

    def copy_lan_ip(self) -> None:
        text = ", ".join(self.lan_ips)
        QApplication.clipboard().setText(text)
        self.show_toast("内网 IP 已复制")

    def copy_public_ip(self) -> None:
        QApplication.clipboard().setText(f"{self.public_ip} {self.public_ip_location}")
        self.show_toast("外网 IP 已复制")

    def show_toast(self, text: str) -> None:
        self.toast_label.setText(text)
        self.toast_label.adjustSize()
        self.position_toast()
        self.toast_label.show()
        self.toast_label.raise_()
        self.toast_timer.start(1600)

    def position_toast(self) -> None:
        width = self.toast_label.width()
        x = max(10, (self.width() - width) // 2)
        self.toast_label.move(x, 76)

    def position_access_placeholder(self) -> None:
        if not hasattr(self, "access_placeholder"):
            return
        viewport = self.access_table.viewport()
        self.access_placeholder.setGeometry(0, 0, viewport.width(), viewport.height())

    def refresh_access_placeholder(self) -> None:
        if not hasattr(self, "access_placeholder"):
            return
        should_show = self.access_table.rowCount() == 0 and not self.server_running()
        self.access_placeholder.setVisible(should_show)
        if should_show:
            self.position_access_placeholder()
            self.access_placeholder.raise_()

    def eventFilter(self, source, event) -> bool:  # noqa: ANN001
        if hasattr(self, "access_table") and source == self.access_table.viewport() and event.type() == QEvent.Resize:
            self.position_access_placeholder()
        return super().eventFilter(source, event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast_label") and self.toast_label.isVisible():
            self.position_toast()
        self.position_access_placeholder()

    def add_access_row(self, payload: dict[str, str]) -> None:
        if payload.get("path") == "/favicon.ico":
            return
        row = self.access_table.rowCount()
        self.access_table.insertRow(row)
        values = [str(row + 1)]
        values.extend(payload.get(key, "") for key in ["time", "ip", "engine", "method", "status", "item", "path"])
        for column, value in enumerate(values):
            self.access_table.setItem(row, column, QTableWidgetItem(value))
        self.access_table.scrollToBottom()
        self.refresh_access_placeholder()

    def read_nginx_log(self) -> None:
        if not self.nginx_log_path or not self.nginx_log_path.exists():
            return
        with self.nginx_log_path.open("r", encoding="utf-8", errors="replace") as log_file:
            log_file.seek(self.nginx_offset)
            lines = log_file.readlines()
            self.nginx_offset = log_file.tell()
        for line in lines:
            payload = self.parse_nginx_line(line)
            if payload:
                self.accessReceived.emit(payload)

    def parse_nginx_line(self, line: str) -> Optional[dict[str, str]]:
        parts = line.rstrip("\n").split("|", 5)
        if len(parts) < 5:
            return None
        request_match = re.match(r"(?P<method>\S+) (?P<path>\S+)", parts[2])
        path = urllib.parse.unquote(request_match.group("path")) if request_match else parts[2]
        if path == "/favicon.ico":
            return None
        if re.match(r"^/items/\d+/__upload$", path):
            return None
        item_name = ""
        engine = "Python"
        item_match = re.match(r"^/items/(\d+)", path)
        if item_match:
            item = next((entry for entry in self.items if entry.item_id == int(item_match.group(1))), None)
            item_name = item.name if item else ""
            if item and not item.temporary and "/__raw" in path:
                engine = "Nginx"
        return {"time": now_text(), "ip": parts[0], "engine": engine, "method": request_match.group("method") if request_match else "", "status": parts[3], "item": item_name, "path": path, "size": parts[4]}

    def confirm_close_with_active_services(self) -> str:
        active_count = len(self.active_items())
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Question)
        message.setWindowTitle("服务仍在运行")
        message.setText(f"还有 {active_count} 个服务没有结束，是否驻留到顶部菜单栏继续运行？")
        message.setInformativeText("选择驻留后，当前共享服务会继续运行；选择停止并退出会关闭所有服务。")
        minimize_button = message.addButton("驻留到顶部菜单栏", QMessageBox.AcceptRole)
        stop_button = message.addButton("停止服务并退出", QMessageBox.DestructiveRole)
        cancel_button = message.addButton("取消", QMessageBox.RejectRole)
        message.setDefaultButton(minimize_button)
        message.exec()
        clicked_button = message.clickedButton()
        if clicked_button == minimize_button:
            return "minimize"
        if clicked_button == stop_button:
            return "stop"
        if clicked_button == cancel_button:
            return "cancel"
        return "cancel"

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            event.accept()
            return
        if self.active_items():
            action = self.confirm_close_with_active_services()
            if action == "minimize":
                event.ignore()
                if self.tray_icon is not None and self.tray_icon.isVisible():
                    self.hide_to_system_tray()
                else:
                    self.showMinimized()
                return
            if action == "cancel":
                event.ignore()
                return
        self._quitting = True
        self.stop_all_servers(silent=True)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        event.accept()
        QTimer.singleShot(0, QApplication.quit)


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("Jobs")
    app.setApplicationName(APP_NAME)
    theme_manager = ThemeManager(app)
    window = MainWindow(theme_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
