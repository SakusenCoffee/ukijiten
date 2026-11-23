#!/usr/bin/env python3
"""Transparent, always-on-top avatar dictionary using the existing Yomitan index."""
import html
from entry_metadata import sources as metadata_sources, MetadataCache
from concurrent.futures import ThreadPoolExecutor
from reading_stats import ReadingStats
from mokuro_browser_feed import MokuroBrowserFeed
from reading_history import query_history,delete_history,history_text
from stats_feed import StatsFeed
from anki_stats_feed import AnkiStatsFeed
from anki_insights import load_insights, kanji_options, clean_kanji_preferences
from stats_refresh import refresh_sources, refresh_configured
from stats_settings import StatsSettings
from anki_stats import available_decks, config_version
import copy
from import_assets import list_assets, import_path, remove as remove_import_asset
from browser_cloud import BrowserCloudConnection
from mokuro_cloud import connection_summary, disconnect_account, connection_update, reset_interrupted_connections
import json
import os
import ctypes
from pathlib import Path
import re
import random
from media_catalog import MediaCatalog
from async_lookup import AsyncLookup
from hover_lookup import HoverLookup
from character_lookup import CharacterLookup, headword_markup, is_character
from translation import Translator, detect_language, load_models, connect_codex, translate
from image_editor import ImageEditDialog, export_edit, source_and_edit, avatar_rect
from image_effects import blur_pixmap,corner_path
from image_edit_library import ImageEditLibrary
from popup_settings import PopupSettings
from entry_fonts import font_choices, normalize_font
from lookup_layout import layout_settings, valid_grid, weights
import subprocess
import sqlite3
import sys
from time import monotonic
from popup_clicks import PopupClicks

import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, Property, QPropertyAnimation, QRect, Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QColor, QIcon, QImageReader, QMovie, QPainter, QPixmap, QRegion, QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QDialog, QFileDialog,
    QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QMenu, QPushButton, QSizeGrip, QGraphicsOpacityEffect, QSlider, QSpinBox, QSplitter,
    QSizePolicy, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from yomitan_goldendict import Window as DictionaryManager, connect, render, search_entries, DB_PATH

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / '.config/yomitan-floating'
CONFIG_FILE = CONFIG_DIR / 'settings.json'
STYLE_FILE = CONFIG_DIR / 'style.css'
DEFAULT_AVATAR = ROOT / 'assets/avatar.svg'
DEFAULT_CSS = (ROOT / 'floating_style.css').read_text(encoding='utf-8')
SOCKET_NAME = f'yomitan-floating-{os.getuid()}'
KWIN_RULES_FILE = Path.home() / '.config/kwinrulesrc'


def read_keep_above_rule():
    try:
        contents = KWIN_RULES_FILE.read_text(encoding='utf-8')
    except OSError:
        return False
    section = re.search(r'(?ms)^\[yomitan-floating-tray\]\s*\n(.*?)(?=^\[|\Z)', contents)
    if not section:
        return False
    values = dict(re.findall(r'(?m)^([^=\n]+)=(.*)$', section.group(1)))
    return values.get('above', '').strip().lower() == 'true'


def write_keep_above_rule(enabled):
    contents = KWIN_RULES_FILE.read_text(encoding='utf-8')
    section = re.search(r'(?ms)^\[yomitan-floating-tray\]\s*\n(.*?)(?=^\[|\Z)', contents)
    if not section:
        raise RuntimeError('The Yomitan KWin window rule is missing.')
    body = section.group(1)
    above = f'above={str(enabled).lower()}'
    if re.search(r'(?m)^above=.*$', body):
        body = re.sub(r'(?m)^above=.*$', above, body, count=1)
    else:
        body = above + '\n' + body
    if not re.search(r'(?m)^aboverule=.*$', body):
        body = body.rstrip('\n') + '\naboverule=2\n'
    updated = contents[:section.start(1)] + body + contents[section.end(1):]
    KWIN_RULES_FILE.write_text(updated, encoding='utf-8')
    result = subprocess.run(
        ['busctl', '--user', 'call', 'org.kde.KWin', '/KWin', 'org.kde.KWin', 'reconfigure'],
        capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'KWin did not reload its window rules.')


def css_rule_defaults():
    rules = {}
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', DEFAULT_CSS, re.S):
        for selector in match.group(1).split(','):
            selector = selector.strip()
            if selector and selector not in rules:
                rules[selector] = match.group(2).strip()
    return rules


CSS_RULES = css_rule_defaults()
CSS_VARIABLES = dict(re.findall(r'(?m)^\s*(--[\w-]+)\s*:\s*([^;]+);', DEFAULT_CSS))
PREVIEW_SELECTORS = ('.definition strong', '.definition b', '.definition em',
                     '.definition li', '.definition ul', '.definition ol',
                     '.definition p', '.definition table', '.definition td',
                     '.definition th', '.definition blockquote')


def css_rule_template(selector):
    if selector in CSS_VARIABLES:
        return f':root {{\n  {selector}: {CSS_VARIABLES[selector].strip()};\n}}'
    declarations = CSS_RULES.get(selector, '')
    if not declarations:
        return f'{selector} {{\n  /* Add your styles here */\n}}'
    lines = [f'  {part.strip()};' for part in declarations.split(';') if part.strip()]
    return f'{selector} {{\n' + '\n'.join(lines) + '\n}'


def find_css_selector(text, selector):
    searchable = re.sub(r'/\*.*?\*/', lambda match: ' ' * len(match.group()), text, flags=re.S)
    if selector.startswith('--'):
        match = re.search(r'(?m)^\s*(' + re.escape(selector) + r')\s*:', searchable)
        return (match.start(1), match.end(1)) if match else None
    for match in re.finditer(r'([^{}]+)\{', searchable):
        header = match.group(1)
        if selector in (piece.strip() for piece in header.split(',')):
            start = searchable.find(selector, match.start(1), match.end(1))
            return start, start + len(selector)
    return None


def kde_blur_function():
    """Use KDE's compositor to blur the desktop behind selected window regions."""
    try:
        library = ctypes.CDLL('libKF6WindowSystem.so.6')
        function = library._ZN14KWindowEffects16enableBlurBehindEP7QWindowbRK7QRegion
        function.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p)
        function.restype = None
        return function
    except (OSError, AttributeError):
        return None


KDE_BLUR = kde_blur_function()


def load_settings():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    geometry = data.get('window_geometry')
    try:
        geometry = {key: int(geometry[key]) for key in ('x', 'y', 'width', 'height')}
        if geometry['width'] < 1 or geometry['height'] < 1:
            geometry = None
    except (TypeError, KeyError, ValueError):
        geometry = None
    avatar_right = bool(data.get('avatar_right', False))
    avatar_top = bool(data.get('avatar_top', False))
    split_orientation = data.get('split_orientation', 'horizontal')
    if split_orientation not in ('horizontal', 'vertical'):
        split_orientation = 'horizontal'
    try:
        splitter_ratio = max(0.1, min(0.9, float(data.get('splitter_ratio', 350 / 990))))
    except (TypeError, ValueError):
        splitter_ratio = 350 / 990
    if 'splitter_ratio' in data and data.get('splitter_ratio_mode') != 'avatar':
        avatar_is_second = (split_orientation == 'horizontal' and avatar_right) or (
            split_orientation == 'vertical' and not avatar_top)
        if avatar_is_second:
            splitter_ratio = 1 - splitter_ratio
    return {'avatar': data.get('avatar', str(DEFAULT_AVATAR)),
            'background_image': data.get('background_image', ''),
            'background_folder': data.get('background_folder', ''),
            'background_crossfade': bool(data.get('background_crossfade', False)),
            'background_fade_ms': max(50, min(10000, int(data.get('background_fade_ms', 600)))),
            'background_order': data.get('background_order', 'default') if data.get('background_order') in ('default', 'reverse', 'random') else 'default',
            'avatar_crossfade': bool(data.get('avatar_crossfade', True)),
            'avatar_fade_ms': max(50, min(10000, int(data.get('avatar_fade_ms', 600)))),
            'avatar_folder': data.get('avatar_folder', ''),
            'avatar_seconds': max(1, min(86400, int(data.get('avatar_seconds', int(data.get('avatar_seconds', 5)) * 60)))),
            'background_seconds': max(1, min(86400, int(data.get('background_seconds', 300)))),
            'avatar_order': data.get('avatar_order', 'default') if data.get('avatar_order', 'default') in ('default', 'reverse', 'random') else 'default',
            'avatar_right': avatar_right,
            'avatar_enabled':bool(data.get('avatar_enabled',True)),
            'avatar_hidden':bool(data.get('avatar_hidden',False)),
            **{key:bool(data.get(key,False)) for key in ('avatar_fill_pane','avatar_mirror_x','avatar_mirror_y','avatar_auto_mirror_sides','avatar_auto_mirror_vertical','background_mirror_x','background_mirror_y','background_auto_mirror_sides','background_auto_mirror_vertical')},
            'avatar_top': avatar_top,
            'split_orientation': split_orientation,
            'avatar_vertical_position': data.get('avatar_vertical_position', 'bottom')
            if data.get('avatar_vertical_position', 'bottom') in ('top', 'bottom') else 'bottom',
            'panel_opacity': max(0, min(100, int(data.get('panel_opacity', 0)))),
            'panel_darkness': max(0, min(100, int(data.get('panel_darkness', 0)))),
            'text_color_mode': data.get('text_color_mode') if data.get('text_color_mode') in ('automatic','black','white') else ('automatic' if data.get('auto_text_contrast',True) else 'white'),
            'panel_color': data.get('panel_color','#000000') if re.fullmatch(r'#[0-9a-fA-F]{6}',str(data.get('panel_color','#000000'))) else '#000000',
            'blur_px': int(data.get('blur_px', 0) > 0 and not Path(data.get('background_image','')).is_file()),
            'avatar_blur': bool(data.get('avatar_blur', False)),
            'avatar_background_opacity': max(0, min(100, int(data.get(
                'avatar_background_opacity', data.get('avatar_opacity', 0))))),
            'avatar_background_color':data.get('avatar_background_color','#000000') if re.fullmatch(r'(?:#[0-9a-fA-F]{6})?',str(data.get('avatar_background_color','#000000'))) else '#000000',
            **{key:max(0,min(40,int(data.get(key,0)))) for key in ('dictionary_image_blur','avatar_image_blur')},
            'dictionary_image_opacity':max(0,min(100,int(data.get('dictionary_image_opacity',100)))),
            **{key:max(0,min(120,int(data.get(key,23)))) for key in ('avatar_corner_radius','dictionary_corner_radius')},
            **{key:data.get(key,'all') if data.get(key,'all') in ('all','top','bottom') else 'all' for key in ('avatar_corner_mode','dictionary_corner_mode')},
            **{'background_show_'+pane:bool(data.get('background_show_'+pane,True)) for pane in ('dictionary','popup','stats','translation','settings')},
            'search_as_you_type': True,
            'navbar_auto_hide': bool(data.get('navbar_auto_hide',False)),
            **layout_settings(data),
            'lookup_ratio': max(.15,min(.85,float(data.get('lookup_ratio',.5)))),
            'font_family': normalize_font(data.get('font_family', '')),
            **{key:max(8,min(72,int(data.get(key,default)))) for key,default in {'font_headword':28,'font_reading':14,'font_definition':15,'font_example':15,'font_frequency':12,'font_pitch':14}.items()},
            'window_geometry': geometry,
            'splitter_ratio': splitter_ratio,
            'splitter_ratio_mode': 'avatar',
            'auto_fade': bool(data.get('auto_fade', True)),
            'fade_avatar': bool(data.get('fade_avatar', False)),
            'fade_only_when_inactive': True,
            'fade_delay_ms': max(100, min(30000, int(data.get('fade_delay_ms', 1000)))),
            'fade_in_ms': max(0, min(10000, int(data.get('fade_in_ms', 280)))),
            'fade_out_ms': max(0, min(10000, int(data.get('fade_out_ms', 420))))}


def send_to_instance(query, prompt=False):
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if not socket.waitForConnected(200):
        return False
    socket.write((json.dumps({'query': query, 'prompt': prompt}, ensure_ascii=False) + '\n').encode('utf-8'))
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def load_css():
    try:
        return STYLE_FILE.read_text(encoding='utf-8')
    except OSError:
        return ''


class AvatarPane(QLabel):
    image_geometry_changed = Signal()

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        self.setMinimumWidth(145)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.setStyleSheet('background: transparent;')
        self.setMouseTracking(True)
        self.original = QPixmap()
        self._render_key=None;self._rendered_pixmap=QPixmap();self._rendered_rect=QRect()
        self.movie = None
        self._image_hovered = False
        self.drag_offset = None
        self._image_opacity = 1.0
        self._opacity_target = 1.0
        self.opacity_animation = QPropertyAnimation(self, b'imageOpacity', self)
        self.previous_avatar = QPixmap()
        self.previous_avatar_rect = QRect()
        self._avatar_progress = 1.0
        self.avatar_transition = QPropertyAnimation(self, b'avatarProgress', self)
        self.avatar_transition.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.avatar_transition.finished.connect(self.finish_avatar_transition)

    def get_image_opacity(self):
        return self._image_opacity

    def set_image_opacity(self, value):
        self._image_opacity = value
        self.update()

    imageOpacity = Property(float, get_image_opacity, set_image_opacity)

    def fade_to(self, opacity, duration):
        if self._opacity_target == opacity and self.opacity_animation.state() == QPropertyAnimation.State.Running:
            return
        if self._opacity_target == opacity and abs(self._image_opacity - opacity) < 0.001:
            return
        self._opacity_target = opacity
        self.opacity_animation.stop()
        self.opacity_animation.setStartValue(self._image_opacity)
        self.opacity_animation.setEndValue(opacity)
        self.opacity_animation.setDuration(duration)
        self.opacity_animation.start()

    def get_avatar_progress(self):
        return self._avatar_progress

    def set_avatar_progress(self, value):
        self._avatar_progress = value
        self.update()

    avatarProgress = Property(float, get_avatar_progress, set_avatar_progress)

    def finish_avatar_transition(self):
        self.avatar_transition.stop()
        self._avatar_progress = 1.0
        self.previous_avatar = QPixmap()
        self.previous_avatar_rect = QRect()
        self.update()
        self.image_geometry_changed.emit()

    def clear_image(self):
        self.avatar_transition.stop()
        self.opacity_animation.stop()
        if self.movie:self.movie.stop();self.movie.deleteLater();self.movie=None
        self.original=QPixmap();self.setPixmap(QPixmap())
        self._render_key=None;self._rendered_pixmap=QPixmap();self._rendered_rect=QRect()
        self.previous_avatar=QPixmap();self.previous_avatar_rect=QRect();self._avatar_progress=1.0
        self.update();self.image_geometry_changed.emit()

    def set_image(self, path):
        previous = QPixmap()
        previous_rect = self.image_rect()
        current = self.display_pixmap()
        if (self.owner.settings.get('avatar_crossfade', False) and current and not current.isNull()
                and self.isVisible() and self.width() > 0 and self.height() > 0):
            previous = QPixmap(self.size())
            previous.fill(Qt.GlobalColor.transparent)
            painter = QPainter(previous)
            self.paint_avatar(painter)
            painter.end()
        self.avatar_transition.stop()
        self.previous_avatar = previous
        self.previous_avatar_rect = previous_rect if not previous.isNull() else QRect()
        self._avatar_progress = 0.0 if not previous.isNull() else 1.0
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        if QImageReader(str(path)).supportsAnimation():
            movie = QMovie(str(path), parent=self)
            if movie.isValid():
                self.original = QPixmap()
                self.setPixmap(QPixmap())
                self.movie = movie
                self.movie.frameChanged.connect(lambda _frame: self.scale_image())
                movie.start()
                self.scale_image()
                return
            movie.deleteLater()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.original = pixmap
            self.scale_image()

    def scale_image(self):
        self._render_key=None
        self.update()
        # The faded window's mask also clips painting. Refresh it in the same
        # turn as the pixmap/frame, rather than waiting for focus or a resize.
        if not self.previous_avatar.isNull() and self.avatar_transition.state() != QPropertyAnimation.State.Running:
            self.avatar_transition.setStartValue(self._avatar_progress)
            self.avatar_transition.setEndValue(1.0)
            self.avatar_transition.setDuration(min(self.owner.settings.get('avatar_fade_ms', 600),
                                                 self.owner.settings.get('avatar_seconds', 30) * 1000))
            self.avatar_transition.start()
        self.image_geometry_changed.emit()

    def display_pixmap(self):
        pixmap=self.movie.currentPixmap() if self.movie else self.original
        if not pixmap or pixmap.isNull() or self.size().isEmpty():return QPixmap()
        settings=self.owner.settings
        mirror_x=settings.get('avatar_mirror_x',False);mirror_y=settings.get('avatar_mirror_y',False)
        rect=avatar_rect(pixmap.size(),self.size(),settings)
        blur=settings.get('avatar_image_blur',0)
        key=(pixmap.cacheKey(),rect.x(),rect.y(),rect.width(),rect.height(),mirror_x,mirror_y,blur)
        if key!=self._render_key:
            if mirror_x or mirror_y:pixmap=QPixmap.fromImage(pixmap.toImage().mirrored(mirror_x,mirror_y))
            self._rendered_pixmap=pixmap.scaled(rect.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self._rendered_pixmap=blur_pixmap(self._rendered_pixmap,blur)
            self._rendered_rect=rect;self._render_key=key
        return self._rendered_pixmap

    def paint_avatar(self, painter):
        if not self.previous_avatar.isNull():
            painter.save()
            painter.setOpacity(painter.opacity() * (1.0 - self._avatar_progress))
            painter.drawPixmap(0, 0, self.previous_avatar)
            painter.restore()
        pixmap = self.display_pixmap()
        if pixmap and not pixmap.isNull():
            painter.save()
            painter.setOpacity(painter.opacity() * self._avatar_progress)
            painter.drawPixmap(self.current_image_rect().topLeft(), pixmap)
            painter.restore()

    def paintEvent(self, event):
        if self.owner.settings.get('avatar_hidden',False):return
        pixmap = self.display_pixmap()
        if self._image_opacity > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipPath(corner_path(self.rect(),self.owner.settings.get('avatar_corner_radius',23),self.owner.settings.get('avatar_corner_mode','all')))
            painter.setOpacity(self._image_opacity)
            background_opacity = self.owner.settings['avatar_background_opacity']
            background_color=self.owner.settings.get('avatar_background_color','#000000')
            if background_opacity and background_color:
                tint = QColor(background_color)
                tint.setAlphaF(background_opacity / 100)
                painter.fillRect(self.rect(), tint)
            self.paint_avatar(painter)

    def image_rect(self):
        if self.owner.settings.get('avatar_hidden',False):return QRect()
        return self.current_image_rect().united(self.previous_avatar_rect).intersected(self.rect())

    def current_image_rect(self):
        pixmap = self.display_pixmap()
        if not pixmap or pixmap.isNull():
            return QRect()
        return QRect(self._rendered_rect)

    def update_image_hover(self, position):
        hovered = self.image_rect().contains(position)
        if hovered == self._image_hovered:
            return
        self._image_hovered = hovered
        if self.owner.page_loaded:
            self.owner.web.page().runJavaScript(f'avatarHover({str(hovered).lower()})')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.finish_avatar_transition()
        self.scale_image()

    def begin_window_drag(self, global_position):
        self.drag_offset = global_position.toPoint() - self.owner.pos()
        handle = self.window().windowHandle()
        if handle and handle.startSystemMove():
            self.drag_offset = None

    def tabletEvent(self, event):
        # Handle the pen directly: mouse-event synthesis varies across Qt apps
        # and Wayland, and may not preserve a usable window-move input serial.
        if event.type() == QEvent.Type.TabletPress and event.button() == Qt.MouseButton.LeftButton:
            self.begin_window_drag(event.globalPosition())
        elif event.type() == QEvent.Type.TabletMove:
            self.update_image_hover(event.position().toPoint())
            if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.owner.move(event.globalPosition().toPoint() - self.drag_offset)
        elif event.type() == QEvent.Type.TabletRelease:
            self.drag_offset = None
        else:
            event.ignore()
            return
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin_window_drag(event.globalPosition())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.update_image_hover(event.position().toPoint())
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self.drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.update_image_hover(event.position().toPoint())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update_image_hover(QPoint(-1, -1))
        super().leaveEvent(event)


class PaneBackground(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.movie = None
        self.image_path = None
        self.pixmap = QPixmap()
        self.darkness = 0
        self.tint = QColor('#000000')
        self.mirror_x=False;self.mirror_y=False
        self.image_blur=0;self.image_opacity=100;self.corner_radius=23;self.corner_mode='all'
        self.scaled_key = None
        self.scaled_frame = QPixmap()
        self.previous_frame = QPixmap()
        self.previous_scaled = QPixmap()
        self.previous_size = None
        self.fade_progress = 1.0
        self.transition = QPropertyAnimation(self, b'fadeProgress', self)
        self.transition.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.transition.finished.connect(self.finish_transition)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def get_fade_progress(self):
        return self.fade_progress

    def set_fade_progress(self, value):
        self.fade_progress = value
        self.update()

    fadeProgress = Property(float, get_fade_progress, set_fade_progress)

    def finish_transition(self):
        self.transition.stop()
        self.previous_frame = QPixmap()
        self.previous_scaled = QPixmap()
        self.previous_size = None
        self.fade_progress = 1.0
        self.update()

    def set_image(self, path, crossfade=False, duration=600):
        if path == self.image_path:
            return
        previous = self.movie.currentPixmap() if self.movie else self.pixmap
        self.finish_transition()
        self.image_path = path
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        reader = QImageReader(path)
        if reader.supportsAnimation():
            self.movie = QMovie(path)
            self.movie.frameChanged.connect(lambda *_: self.update())
            self.movie.start()
            if not self.isVisible():
                self.movie.setPaused(True)
        else:
            self.pixmap = QPixmap(path)
        current = self.movie.currentPixmap() if self.movie else self.pixmap
        if crossfade and self.isVisible() and not previous.isNull() and not current.isNull():
            self.previous_frame = previous
            self.transition.setDuration(duration)
            self.transition.setStartValue(0.0)
            self.transition.setEndValue(1.0)
            self.transition.start()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.movie:
            self.movie.setPaused(False)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.finish_transition()
        if self.movie:
            self.movie.setPaused(True)

    def paintEvent(self, event):
        pixmap = self.movie.currentPixmap() if self.movie else self.pixmap
        if pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(corner_path(self.rect(),self.corner_radius,self.corner_mode))
        if self.mirror_x or self.mirror_y:
            painter.translate(self.width() if self.mirror_x else 0,self.height() if self.mirror_y else 0)
            painter.scale(-1 if self.mirror_x else 1,-1 if self.mirror_y else 1)
        if not self.previous_frame.isNull():
            if self.previous_size != (self.size(),self.image_blur):
                self.previous_scaled = self.previous_frame.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.previous_scaled=blur_pixmap(self.previous_scaled,self.image_blur)
                self.previous_size = (self.size(),self.image_blur)
            previous = self.previous_scaled
            painter.setOpacity((1.0 - self.fade_progress)*self.image_opacity/100)
            painter.drawPixmap((self.width()-previous.width())//2, (self.height()-previous.height())//2, previous)
        painter.setOpacity(self.fade_progress*self.image_opacity/100)
        key = (pixmap.cacheKey(), self.width(), self.height(),self.image_blur)
        if key != self.scaled_key:
            self.scaled_frame = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.scaled_frame=blur_pixmap(self.scaled_frame,self.image_blur)
            self.scaled_key = key
        scaled = self.scaled_frame
        painter.drawPixmap((self.width()-scaled.width())//2, (self.height()-scaled.height())//2, scaled)
        painter.setOpacity(1.0)
        tint=QColor(self.tint);tint.setAlpha(round(self.darkness * 2.55))
        painter.fillRect(self.rect(),tint)


class ResizeEdge(QWidget):
    def __init__(self, owner, edges, cursor):
        super().__init__(owner)
        self.owner = owner
        self.edges = edges
        self.setCursor(cursor)
        self.setStyleSheet('background: transparent;')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.isActiveWindow():
            handle = self.owner.windowHandle()
            if handle and handle.startSystemResize(self.edges):
                event.accept()
                return
        event.ignore()


class Bridge(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    @Slot(str)
    def search(self, query):
        self.owner.search(query)

    @Slot(str)
    def search_secondary(self,query):
        self.owner.secondary_query=query.strip()
        self.owner.secondary_worker.submit(self.owner.secondary_query)

    @Slot(int, str)
    def search_pane(self, pane_id, query):
        self.owner.search_extra_pane(pane_id, query)

    @Slot()
    def settings(self):
        self.owner.open_settings()

    @Slot(str)
    def choose_color(self, scope):
        self.owner.choose_color(scope)

    @Slot()
    def reading_stats(self):
        self.owner.open_reading_stats()

    @Slot()
    def translation(self):
        self.owner.open_translation()

    @Slot(str, result=str)
    def translation_save(self, payload):
        try:return json.dumps(self.owner.translator.settings.save(json.loads(payload)))
        except (ValueError,TypeError,KeyError) as error:return json.dumps({'error':str(error)})

    @Slot(str,str)
    def translation_detect(self, identifier, text):
        self.owner.translator.submit('detect',identifier,detect_language,text[:6000])

    @Slot(str)
    def translation_models(self, identifier):
        provider,profile=self.owner.translator.settings.profile()
        self.owner.translator.submit('models',identifier,lambda:{'models':load_models(provider,profile)})

    @Slot(str,str,str)
    def translation_run(self, identifier, text, target):
        self.owner.translator.submit('translate',identifier,translate,self.owner.translator.settings,text,target,cancellable=True)

    @Slot()
    def translation_cancel(self):
        self.owner.translator.cancel()

    @Slot(str)
    def translation_codex_connect(self, identifier):
        self.owner.translator.submit('account',identifier,connect_codex,self.owner.translator.settings,cancellable=True)

    @Slot(result=str)
    def translation_codex_disconnect(self):
        self.owner.translator.settings.set_codex(False)
        return json.dumps(self.owner.translator.settings.public())

    @Slot(str)
    def translation_copy(self, text):
        QApplication.clipboard().setText(text)

    @Slot(str, result=str)
    def stats_add_entry(self, payload):
        try:
            entry = json.loads(payload)
            self.owner.stats_store.add_manual_entry(entry['characters'], entry['hours'], entry['minutes'],
                entry.get('description', ''), entry.get('day'), entry.get('identifier'))
            self.owner.stats_refresh_notice = ''
            self.owner.refresh_reading_stats()
            return json.dumps({'ok': True})
        except (ValueError, KeyError, TypeError) as error:
            return json.dumps({'error': str(error)})

    @Slot()
    def stats_refresh(self):
        self.owner.refresh_external_stats()

    @Slot(str,result=str)
    def stats_history_query(self,payload):
        try:
            request=json.loads(payload)
            if not isinstance(request,dict):raise ValueError('Invalid history request.')
            return json.dumps(query_history(self.owner.stats_store,request),ensure_ascii=False)
        except (ValueError,TypeError,OverflowError) as error:return json.dumps({'error':str(error)})

    @Slot(str,result=str)
    def stats_history_text(self,key):
        try:
            configured=self.owner.source_settings.values['gsm_history']['path']
            root=Path.home()/'.config/GameSentenceMiner'
            paths=[configured] if configured else []
            paths.extend(str(path) for pattern in ('*.db','*.sqlite3','data/*.db') for path in root.glob(pattern))
            return json.dumps(history_text(self.owner.stats_store,key,paths),ensure_ascii=False)
        except (ValueError,TypeError,OSError) as error:return json.dumps({'error':str(error)})

    @Slot(str,result=str)
    def stats_history_delete(self,payload):
        if self.owner.stats_import_future or self.owner.stats_refresh_future:return json.dumps({'error':'Wait for the current import to finish.'})
        try:
            selection=json.loads(payload)
            if not isinstance(selection,dict):raise ValueError('Invalid history selection.')
            result=delete_history(self.owner.stats_store,selection);self.owner.refresh_reading_stats()
            return json.dumps(dict(ok=True,**result))
        except (ValueError,TypeError,KeyError) as error:return json.dumps({'error':str(error)})

    @Slot(str)
    def stats_anki_insights(self, request_id):
        self.owner.load_anki_insights(request_id)

    @Slot(str, result=str)
    def stats_kanji_preferences(self, payload):
        try:
            values=clean_kanji_preferences(json.loads(payload),self.owner.kanji_grid_preferences())
            self.owner.stats_store.set_preference('kanji_grid_options',values)
            return json.dumps({'ok':True})
        except (ValueError,TypeError) as error:return json.dumps({'error':str(error)})

    @Slot()
    def stats_import(self):
        self.owner.import_reading_stats()

    @Slot(bool)
    def stats_capture(self, enabled):
        values = copy.deepcopy(self.owner.source_settings.values)
        values['gsm']['enabled'] = enabled
        self.owner.source_settings.save(values)
        self.owner.stats_feed.toggle(enabled)

    @Slot(str, result=str)
    def stats_save_sources(self, payload):
        try:
            values = json.loads(payload)
            self.owner.source_settings.save(values)
            self.owner.configure_stats_sources()
            return json.dumps({'ok': True, 'settings': self.owner.source_settings.public()})
        except (ValueError, TypeError, KeyError) as error:
            return json.dumps({'error': str(error)})

    @Slot(str)
    def stats_load_decks(self, payload):
        self.owner.load_stats_decks(payload)

    @Slot(str, result=str)
    def stats_pick_files(self, source):
        if source not in ('anki', 'gsm_history', 'mokuro', 'files','ttsu','jpdb','renshuu'):
            return '[]'
        filters = {'anki': 'Anki collections (*.anki2)', 'gsm_history': 'GSM database (*.db *.sqlite3)',
                   'mokuro': 'Mokuro history (*.json)', 'files': 'Reading history (*.csv *.json *.txt *.zip)',
                   'ttsu':'Ttsu statistics (*.json *.zip)','jpdb':'JPDB reviews (*.json)','renshuu':'Renshuu heatmap (*.json)'}
        paths, _ = QFileDialog.getOpenFileNames(self.owner, 'Choose source files', '', filters[source])
        return json.dumps(paths)

    @Slot(str,result=str)
    def stats_pick_import_folder(self,source):
        if source!='ttsu':return ''
        return QFileDialog.getExistingDirectory(self.owner,'Choose Ttsu export folder')

    @Slot(str)
    def stats_open_site(self,source):
        urls={'ttsu':'https://reader.ttsu.app/manage','jpdb':'https://jpdb.io/settings','renshuu':'https://www.renshuu.org/settings'}
        if source in urls:QDesktopServices.openUrl(QUrl(urls[source]))

    @Slot(str, result=str)
    def stats_remove_manual(self, identifier):
        if not identifier.startswith('manual:'):
            return json.dumps({'error':'Manual entry not found.'})
        with self.owner.stats_store.db:
            self.owner.stats_store.db.execute("DELETE FROM readings WHERE key=? AND kind='manual'",(identifier,))
        self.owner.refresh_reading_stats()
        return json.dumps({'ok':True})

    @Slot(str, result=str)
    def stats_remove_file(self, identifier):
        if self.owner.stats_import_future or self.owner.stats_refresh_future:
            return json.dumps({'error':'Wait for the current import to finish.'})
        try:
            asset=remove_import_asset(self.owner.stats_store,identifier)
            values=copy.deepcopy(self.owner.source_settings.values)
            kind,path=asset['kind'],asset['path']
            if kind in ('files','mokuro','ttsu','jpdb','renshuu'):
                for source in ('files','mokuro','ttsu','jpdb','renshuu'):
                    values[source]['paths']=[item for item in values[source]['paths'] if str(Path(item).expanduser().resolve())!=path]
            if kind=='gsm_history' and values[kind]['path']==path:values[kind]['enabled']=False
            if kind=='mokuro' and path:
                folder=values['mokuro']['local_folder']['path']
                if folder and Path(path) in (Path(folder).expanduser()/'volume-data.json',Path(folder).expanduser()/'mokuro-reader/volume-data.json'):
                    values['mokuro']['local_folder']['enabled']=False
            if identifier.startswith('cloud:'):
                provider=identifier.split(':',1)[1]
                if provider in values['mokuro']:values['mokuro'][provider]['enabled']=False
            self.owner.source_settings.save(values)
            self.owner.refresh_reading_stats()
            return json.dumps({'ok':True,'files':list_assets(self.owner.stats_store),'settings':self.owner.source_settings.public()})
        except (ValueError,OSError) as error:
            return json.dumps({'error':str(error)})

    @Slot(str)
    def stats_cloud_connect(self, provider):
        self.owner.start_cloud_connection(provider)

    @Slot(str, result=str)
    def stats_cloud_disconnect(self, provider):
        if provider not in ('google_drive','mega','onedrive','webdav'):
            return json.dumps({'error':'Unknown provider.'})
        if self.owner.stats_refresh_future:
            return json.dumps({'error':'Wait for Refresh to finish, then disconnect.'})
        active=self.owner.cloud_connections.pop(provider,None)
        if active:active.close()
        self.owner.refresh_auth_queue=[]
        self.owner.refresh_auth_succeeded=False
        values=copy.deepcopy(self.owner.source_settings.values)
        if provider=='webdav':
            values['mokuro']['webdav']={'enabled':False,'webdav_server_url':'','webdav_username':'','webdav_password':'','webdav_token':''}
        else:
            disconnect_account(CONFIG_DIR,provider)
            values['mokuro'][provider]['enabled']=False
        self.owner.source_settings.save(values)
        self.owner.refresh_reading_stats()
        return json.dumps({'connections':connection_summary(CONFIG_DIR),'settings':self.owner.source_settings.public()})

    @Slot(result=str)
    def stats_pick_folder(self):
        return QFileDialog.getExistingDirectory(self.owner,'Choose Mokuro folder')

    @Slot(str, str)
    def preference(self, key, value):
        self.owner.update_preference(key, json.loads(value))

    @Slot()
    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self.owner, 'Choose avatar image',
            source_and_edit(self.owner.settings['avatar'])[0], 'Images (*.png *.gif *.webp *.jpg *.jpeg)')
        if path:
            self.owner.edit_image(path,'avatar')

    @Slot(str)
    def edit_current_image(self,kind):
        if kind not in ('avatar','background'):return
        path=self.owner.settings['avatar' if kind=='avatar' else 'background_image']
        if path and Path(path).is_file():self.owner.edit_image(path,kind,keep_folder=True)

    @Slot()
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self.owner, 'Choose avatar folder',
            self.owner.settings['avatar_folder'])
        if folder:
            self.owner.update_preference('avatar_folder', folder)

    @Slot()
    def remove_background(self):
        self.owner.background_timer.stop()
        self.owner.background_files = []
        self.owner.background_index = -1
        self.owner.settings['background_folder'] = ''
        self.owner.set_background('')

    @Slot(bool)
    def choose_background(self, folder):
        if folder:
            path = QFileDialog.getExistingDirectory(self.owner, 'Choose pane background folder', self.owner.settings['background_folder'])
            if path:
                files = self.owner.media_catalog.files(path)
                if not files:
                    QMessageBox.information(self.owner, 'No images', 'This folder contains no supported images.')
                    return
                self.owner.settings['background_folder'] = path
                self.owner.background_files = files
                self.owner.order_background_files()
                self.owner.background_index = -1
                self.owner.next_background()
                self.owner.background_timer.start(self.owner.settings['background_seconds'] * 1000)
        else:
            initial=source_and_edit(self.owner.settings['background_image'])[0] if self.owner.settings['background_image'] else ''
            path, _ = QFileDialog.getOpenFileName(self.owner, 'Choose pane background', initial, 'Images (*.png *.gif *.webp *.jpg *.jpeg *.bmp)')
            if path and QImageReader(path).canRead():
                self.owner.edit_image(path,'background')

    @Slot()
    def popup_settings(self):
        self.owner.open_popup_settings()

    @Slot()
    def collapse_settings(self):
        self.owner.open_collapse_settings()

    @Slot(str,bool)
    def section_preference(self,key,opened):
        if len(key)>120:return
        states=dict(self.owner.popup_config.values['section_states']);states[key]=opened
        self.owner.popup_config.update('section_states',states)

    @Slot(str, str)
    def popup_preference(self, key, value):
        self.owner.popup_config.update(key, json.loads(value))
        self.owner.update_popup_appearance()
        self.owner.web.page().runJavaScript('setPopupPreferences(' + json.dumps(self.owner.popup_config.values) + ')')
        if key == 'main_collapsed_paths':
            self.owner.web.page().runJavaScript('applyDictionaryCollapseDefaults(' + json.dumps(self.owner.popup_config.values[key]) + ')')
        if key in ('main_frequency_paths','main_pitch_paths','main_frequency_order','main_pitch_order') and self.owner.query:
            self.owner.lookup_worker.submit(self.owner.query)
        if key in ('main_frequency_paths','main_pitch_paths','main_frequency_order','main_pitch_order') and self.owner.secondary_query and self.owner.settings['lookup_split']:
            self.owner.secondary_worker.submit(self.owner.secondary_query)
        if key in ('main_frequency_paths','main_pitch_paths','main_frequency_order','main_pitch_order'):
            self.owner.refresh_extra_lookups()

    @Slot(str, int, int)
    def hover_lookup(self, payload, x, y):
        if len(payload)>100000 or not self.owner.popup_config.values['enabled']:
            return
        self.owner.hover_position=self.owner.web.mapToGlobal(QPoint(x,y))
        self.owner.hover_close_timer.stop()
        self.owner.popup_requested=True
        self.owner.hover_worker.submit(payload)

    @Slot(str, int, int, bool)
    def kanji_lookup(self, character, x, y, from_popup):
        self.owner.open_character(character, x, y, from_popup)

    @Slot()
    def popup_back(self):
        self.owner.character_worker.cancel()
        if self.owner.popup_history:
            markup, title = self.owner.popup_history.pop()
            self.owner.show_popup_markup(markup, title)

    @Slot()
    def hide_hover(self):
        self.owner.hover_worker.cancel()
        self.owner.hover_close_timer.stop()

    @Slot(str)
    def release_scan_key(self, key):
        self.owner.web.page().runJavaScript('window.releasePopupScanKey?.('+json.dumps(key)+')')

    @Slot()
    def outside_popup_click(self):
        self.owner.hide_hover_popup(reset_scan=False)

    @Slot()
    def popup_pointer_press(self):
        self.owner.last_popup_press=monotonic()

    @Slot(int,int)
    def popup_drag_start(self,x,y):
        popup=self.owner.hover_popup
        if not popup:return
        self.owner.popup_user_position=True
        self.owner.popup_drag_origin=(QPoint(x,y),popup.pos())
        handle=popup.windowHandle()
        self.owner.popup_system_move=bool(handle and handle.startSystemMove())

    @Slot(int,int)
    def popup_drag_move(self,x,y):
        origin=getattr(self.owner,'popup_drag_origin',None)
        if origin and not getattr(self.owner,'popup_system_move',False):self.owner.hover_popup.move(origin[1]+QPoint(x,y)-origin[0])

    @Slot()
    def popup_drag_end(self):
        self.owner.popup_drag_origin=None

    @Slot()
    def dismiss_popup(self):
        self.owner.hide_hover_popup()

    @Slot()
    def dictionaries(self):
        self.owner.open_manager()

    @Slot(str,str)
    def dictionary_action(self,action,payload):
        self.owner.dictionary_action(action,json.loads(payload))

    @Slot()
    def swap(self):
        self.owner.flip_horizontal()

    @Slot(result=bool)
    def toggle_avatar_position(self):
        return self.owner.toggle_avatar_vertical_position()

    @Slot(result=bool)
    def rotate_panes(self):
        return self.owner.rotate_panes()

    @Slot()
    def close_window(self):
        self.owner.hide()

    @Slot(result=bool)
    def keep_above(self):
        return self.owner.toggle_keep_above()

    @Slot()
    def start_move(self):
        if self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove()

    @Slot(bool)
    def panel_visible(self, visible):
        changed = self.owner.panel_visible != visible
        self.owner.panel_visible = visible
        if changed:
            self.owner.fade_dictionary_overlay(visible)
        self.owner.update_panel_input_mask(visible)
        self.owner.set_splitter_handle_visible(visible)
        self.owner.update_avatar_fade()
        self.owner.apply_background_blur()


class CssPreviewBridge(QObject):
    def __init__(self, select, parent=None):
        super().__init__(parent)
        self.select = select

    @Slot(str)
    def selectCss(self, selector):
        self.select(selector)


class FloatingDictionary(QWidget):
    def __init__(self, query=''):
        super().__init__()
        self.db = connect()
        self.secondary_query = ''
        self.grid_lookup_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='lookup-grid')
        self.extra_queries = {}
        self.extra_workers = {}
        self.secondary_worker = AsyncLookup(self, executor=self.grid_lookup_pool)
        self.secondary_worker.ready.connect(lambda q,entries,error:self.display_search_results(q,entries,error,True))
        QApplication.instance().aboutToQuit.connect(self.secondary_worker.shutdown)
        QApplication.instance().aboutToQuit.connect(self.close_extra_lookups)
        self.lookup_worker = AsyncLookup(self)
        self.lookup_worker.ready.connect(self.display_search_results)
        QApplication.instance().aboutToQuit.connect(self.lookup_worker.shutdown)
        self.query = query
        self.settings = load_settings()
        self.image_edits=ImageEditLibrary(CONFIG_DIR)
        for kind,key in [('avatar','avatar'),('background','background_image')]:
            self.image_edits.adopt(self.settings[key],kind)
            self.settings[key]=self.image_edits.resolve(self.settings[key],kind)
        self.translator=Translator(CONFIG_DIR,self)
        self.translator.ready.connect(lambda kind,identifier,result:self.web.page().runJavaScript('translationResult('+json.dumps(kind)+','+json.dumps(identifier)+','+result+')'))
        QApplication.instance().aboutToQuit.connect(self.translator.close)
        self.color_dialog = None
        self.image_editor = None
        self.color_dialog_scope = None
        self.media_catalog = MediaCatalog()
        self.hover_worker = HoverLookup(self)
        self.hover_worker.ready.connect(self.show_hover_results)
        QApplication.instance().aboutToQuit.connect(self.hover_worker.shutdown)
        self.popup_config = PopupSettings(CONFIG_DIR / 'popup-settings.json', self.scanner_dictionaries(),
            CONFIG_DIR / 'yomitan-settings.json', Path.home()/'.local/share/floating-yomitan-browser/yomitan-options.json')
        self.popup_config.save()
        database_path=Path(self.db.execute('PRAGMA database_list').fetchone()[2])
        self.character_worker=CharacterLookup(self,database_path)
        self.character_worker.ready.connect(self.show_character_results)
        QApplication.instance().aboutToQuit.connect(self.character_worker.shutdown)
        self.popup_history=[]
        self.popup_title='Dictionary lookup'
        self.metadata_cache=MetadataCache(database_path)
        for worker in (self.lookup_worker,self.secondary_worker,self.hover_worker):
            worker.metadata_cache=self.metadata_cache
            worker.metadata_selection_provider=self.metadata_selection if worker is not self.hover_worker else self.popup_metadata_selection
        self.hover_worker.enabled_ids_provider = lambda: self.popup_config.enabled_ids(self.scanner_dictionaries())
        self.hover_entries = []
        self.hover_popup = None
        self.popup_generation=0
        self.last_popup_press=0.0
        self.popup_clicks=PopupClicks(self,enabled=os.environ.get('QT_QPA_PLATFORM')!='offscreen')
        self.popup_clicks.pressed.connect(self.global_popup_click)
        QApplication.instance().aboutToQuit.connect(self.popup_clicks.close)
        self.popup_requested = False
        self.hover_close_timer = QTimer(self)
        self.hover_close_timer.setInterval(500)
        self.hover_close_timer.timeout.connect(self.close_hover_if_outside)

        self.keep_above_enabled = read_keep_above_rule()
        self.panel_visible = True
        self.lookup_prompt = None
        self.lookup_prompt_requested = False
        self.manager = None
        self.quitting = False
        self.setWindowTitle('Ukijiten')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._panel_input_masked = False
        self.setMinimumSize(510, 360)
        self.resize(990, 670)

        self.avatar = AvatarPane(self)
        self.avatar.image_geometry_changed.connect(self.refresh_avatar_mask)
        if self.settings['avatar_hidden']:self.avatar.clear_image()
        else:self.avatar.set_image(self.settings['avatar'])
        self.avatar_timer = QTimer(self)
        self.avatar_timer.timeout.connect(self.next_avatar)
        self.avatar_files = []
        self.configure_avatar_rotation()
        self.web = QWebEngineView()
        self.web.installEventFilter(self)
        self.installEventFilter(self)
        self.avatar.installEventFilter(self)
        QApplication.instance().applicationStateChanged.connect(self.popup_application_state)
        web_policy = self.web.sizePolicy()
        web_policy.setRetainSizeWhenHidden(True)
        self.web.setSizePolicy(web_policy)
        self.web.setMinimumWidth(300)
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.web.setStyleSheet('background: transparent;')
        self.web.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.channel = QWebChannel(self.web.page())
        self.bridge = Bridge(self)
        self.channel.registerObject('app', self.bridge)
        self.web.page().setWebChannel(self.channel)
        self.background_files = []
        self.background_index = -1
        self.background_timer = QTimer(self)
        self.background_timer.timeout.connect(self.next_background)
        folder = Path(self.settings['background_folder']) if self.settings['background_folder'] else None
        if folder and folder.is_dir():
            self.background_files = self.media_catalog.files(folder)
            self.order_background_files()
            if self.background_files:
                self.background_timer.start(self.settings['background_seconds'] * 1000)
        self.page_loaded = False
        self.web.loadFinished.connect(self.page_ready)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.installEventFilter(self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setStyleSheet('QSplitter { background: transparent; }'
                                    'QSplitter::handle { background: rgba(255,255,255,35); border-radius: 3px; margin: 85px 2px; }'
                                    'QSplitter::handle:hover { background: rgba(149,176,255,130); }')
        self.splitter.addWidget(self.avatar)
        self.web.setMinimumWidth(300);self.splitter.addWidget(self.web)
        self.splitter.setSizes([350, 640])
        self.splitter.splitterMoved.connect(self.splitter_moved)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)
        self._input_mask_timer = QTimer(self)
        self._input_mask_timer.setSingleShot(True)
        self._input_mask_timer.timeout.connect(self.apply_panel_input_mask)
        grip = QSizeGrip(self)
        grip.setFixedSize(17, 17)
        grip.setStyleSheet('background: transparent;')
        self.grip = grip
        self.grip.hide()
        E = Qt.Edge
        C = Qt.CursorShape
        self.resize_edges = [ResizeEdge(self, edges, cursor) for edges, cursor in [
            (E.LeftEdge, C.SizeHorCursor), (E.RightEdge, C.SizeHorCursor),
            (E.TopEdge, C.SizeVerCursor), (E.BottomEdge, C.SizeVerCursor),
            (E.LeftEdge | E.TopEdge, C.SizeFDiagCursor),
            (E.RightEdge | E.TopEdge, C.SizeBDiagCursor),
            (E.LeftEdge | E.BottomEdge, C.SizeBDiagCursor),
            (E.RightEdge | E.BottomEdge, C.SizeFDiagCursor)]]
        self.update_resize_edges()
        self.apply_side()
        self.load_page()
        self.server = QLocalServer(self)
        QLocalServer.removeServer(SOCKET_NAME)
        if not self.server.listen(SOCKET_NAME):
            raise RuntimeError(f'Cannot register floating dictionary socket: {self.server.errorString()}')
        self.server.newConnection.connect(self.accept_connection)
        self.tray = QSystemTrayIcon(QIcon.fromTheme('accessories-dictionary'), self)
        menu = QMenu(self)
        menu.addAction('Show dictionary', self.show_and_raise)
        menu.addAction('Settings…', self.open_settings)
        menu.addSeparator()
        menu.addAction('Quit Ukijiten', self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('Ukijiten')
        self.tray.activated.connect(lambda reason: self.show_and_raise()
                            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self.source_settings = StatsSettings(CONFIG_DIR)
        reset_interrupted_connections(CONFIG_DIR)
        self.stats_store = ReadingStats(CONFIG_DIR / 'reading-stats.sqlite3')
        source_values = self.source_settings.values
        self.stats_store.set_preference('day_cutoff_hour',source_values['day']['cutoff_hour'])
        self.stats_store.set_preference('source_metrics',{name:{key:value for key,value in fields.items() if key.startswith('include_')} for name,fields in source_values.items()})
        self.stats_store.set_preference('anki_config_version', config_version(source_values['anki']))
        self.stats_store.set_preference('capture', source_values['gsm']['enabled'])
        self.stats_feed = StatsFeed(self.stats_store, self.refresh_reading_stats, self,
                                    url=source_values['gsm']['url'])
        self.mokuro_browser_feed = MokuroBrowserFeed(CONFIG_DIR/'reading-stats.sqlite3',
            source_values['mokuro_browser'],self.refresh_reading_stats,self)
        QApplication.instance().aboutToQuit.connect(self.mokuro_browser_feed.close)
        self.anki_stats_feed = AnkiStatsFeed(CONFIG_DIR / 'reading-stats.sqlite3',
            source_values['anki']['paths'], self.refresh_reading_stats, self)
        self.anki_stats_feed.config = copy.deepcopy(source_values['anki'])
        QApplication.instance().aboutToQuit.connect(self.anki_stats_feed.close)
        self.stats_import_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='stats-import')
        self.stats_import_future = None
        self.stats_refresh_future = None
        self.cloud_connections = {}
        self.refresh_auth_attempted = set()
        self.refresh_auth_queue = []
        self.refresh_auth_succeeded = False
        self.stats_decks_future = None
        self.anki_insights_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='anki-insights')
        self.anki_insights_jobs=[]
        self.anki_insights_poll=QTimer(self)
        self.anki_insights_poll.setInterval(100)
        self.anki_insights_poll.timeout.connect(self.finish_anki_insights)
        QApplication.instance().aboutToQuit.connect(lambda:self.anki_insights_pool.shutdown(wait=False,cancel_futures=True))
        self.stats_refresh_notice = ''
        self.stats_notice_timer = QTimer(self)
        self.stats_notice_timer.setSingleShot(True)
        self.stats_notice_timer.setInterval(5000)
        self.stats_notice_timer.timeout.connect(self.clear_stats_refresh_notice)
        self.stats_day_timer=QTimer(self)
        self.stats_day_timer.setInterval(60000)
        self.stats_day_timer.timeout.connect(self.refresh_reading_stats)
        self.stats_day_timer.start()
        self.stats_import_poll = QTimer(self)
        self.stats_import_poll.setInterval(100)
        self.stats_import_poll.timeout.connect(self.finish_stats_import)
        self.stats_import_poll.timeout.connect(self.finish_stats_refresh)
        self.stats_decks_poll = QTimer(self)
        self.stats_decks_poll.setInterval(100)
        self.stats_decks_poll.timeout.connect(self.finish_stats_decks)
        QApplication.instance().aboutToQuit.connect(self.close_cloud_connections)
        QApplication.instance().aboutToQuit.connect(self.stats_feed.close)
        QApplication.instance().aboutToQuit.connect(lambda: self.stats_import_pool.shutdown(wait=False))
        self.focus_timer = QTimer(self)
        self.focus_timer.setInterval(200)
        self.focus_timer.timeout.connect(self.sync_focus)
        self.focus_timer.start()
        self.last_active = None
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(500)
        self._geometry_save_timer.timeout.connect(self.save_window_state)

    def update_resize_edges(self):
        if not hasattr(self, 'resize_edges'):
            return
        w, h, b = self.width(), self.height(), 7
        rects = [(0,b,b,h-2*b), (w-b,b,b,h-2*b), (b,0,w-2*b,b), (b,h-b,w-2*b,b),
                 (0,0,b,b), (w-b,0,b,b), (0,h-b,b,b), (w-b,h-b,b,b)]
        for edge, rect in zip(self.resize_edges, rects):
            edge.setGeometry(*rect)
            edge.setVisible(self.isActiveWindow())
            edge.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.grip.move(self.width() - self.grip.width(), self.height() - self.grip.height())
        self.update_resize_edges()
        if getattr(self, 'dictionary_overlay', None):
            QTimer.singleShot(0, lambda: self.position_dictionary_overlay())
        if self._panel_input_masked:
            self.apply_panel_input_mask()
        self.schedule_window_state_save()
        QTimer.singleShot(0,self.restore_splitter_ratio)
        QTimer.singleShot(0, self.apply_background_blur)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.schedule_window_state_save()

    def splitter_moved(self, *_):
        if getattr(self,'_applying_splitter',False):return
        sizes=self.splitter.sizes();total=sum(sizes)
        if total and self.settings.get('avatar_enabled',True):self.settings['splitter_ratio']=sizes[self.splitter.indexOf(self.avatar)]/total
        self.settings['splitter_ratio_mode']='avatar'
        self.apply_background_blur()
        self.schedule_window_state_save()

    def schedule_window_state_save(self):
        timer = getattr(self, '_geometry_save_timer', None)
        if timer and not getattr(self, '_restoring_window_state', False):
            timer.start()

    def remember_window_state(self):
        self.settings['window_geometry'] = {
            'x': self.x(), 'y': self.y(),
            'width': self.width(), 'height': self.height()}

    def save_window_state(self):
        self.remember_window_state()
        self.save_preferences()

    def restore_window_state(self):
        geometry = self.settings['window_geometry']
        if not geometry:
            return False
        point = QPoint(geometry['x'], geometry['y'])
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if not screen:
            return False
        bounds = screen.availableGeometry()
        width = max(self.minimumWidth(), min(geometry['width'], bounds.width()))
        height = max(self.minimumHeight(), min(geometry['height'], bounds.height()))
        x = max(bounds.left(), min(geometry['x'], bounds.right() - width + 1))
        y = max(bounds.top(), min(geometry['y'], bounds.bottom() - height + 1))
        self._restoring_window_state = True
        self.setGeometry(x, y, width, height)
        ratio = self.settings['splitter_ratio']
        QTimer.singleShot(0, lambda: self.restore_splitter_ratio(ratio))
        self._restoring_window_state = False
        return True

    def restore_splitter_ratio(self, ratio=None):
        if not self.settings.get('avatar_enabled',True):return
        ratio = self.settings['splitter_ratio'] if ratio is None else ratio
        is_vertical = self.settings['split_orientation'] == 'vertical'
        available = (self.splitter.height() if is_vertical else self.splitter.width()) - self.splitter.handleWidth()
        avatar_size = round(max(1, available) * ratio)
        other_size = max(1, available - avatar_size)
        avatar_index = self.splitter.indexOf(self.avatar)
        self._applying_splitter=True
        try:self.splitter.setSizes([avatar_size, other_size] if avatar_index == 0 else [other_size, avatar_size])
        finally:self._applying_splitter=False

    def update_panel_input_mask(self, visible):
        self._input_mask_timer.stop()
        if visible or not self.settings.get('auto_fade',True):
            if self._panel_input_masked:
                if self.windowHandle():
                    self.windowHandle().setMask(QRegion())
                self._panel_input_masked = False
            return
        self._input_mask_timer.start(max(0, self.settings['fade_out_ms']))

    def refresh_avatar_mask(self):
        if self._panel_input_masked:
            self.apply_panel_input_mask()

    def apply_panel_input_mask(self):
        if self.panel_visible or not self.settings.get('auto_fade',True):
            if self._panel_input_masked and self.windowHandle():self.windowHandle().setMask(QRegion());self._panel_input_masked=False
            return
        if not self.settings.get('avatar_enabled',True):
            if self.windowHandle():
                self.windowHandle().setMask(QRegion(QRect(self.width()-3,0,3,self.height())))
                self._panel_input_masked=True
            return
        image_rect = self.avatar.image_rect()
        if image_rect.isEmpty():
            if self.settings.get('avatar_hidden',False) and self.windowHandle():
                self.windowHandle().setMask(QRegion(QRect(self.web.mapTo(self,QPoint(0,0)),self.web.size())))
                self._panel_input_masked=True
            return
        image_rect.moveTopLeft(self.avatar.mapTo(self, image_rect.topLeft()))
        handle = self.windowHandle()
        if handle is None:
            return
        # QWidget.setMask also clips backing-store damage: when the avatar
        # shrinks, pixels outside the new mask are never cleared on Wayland.
        # Restrict native input only, leaving the translucent widget unmasked
        # so Qt can erase the previous image across the entire avatar pane.
        handle.setMask(QRegion(image_rect))
        self._panel_input_masked = True

    def set_splitter_handle_visible(self, visible):
        is_vertical = self.settings['split_orientation'] == 'vertical'
        margin = '2px' if is_vertical else '85px 2px'
        self.splitter.setHandleWidth(3 if is_vertical else 8)
        handle = self.splitter.handle(1)
        if handle:
            handle.setEnabled(visible)
        if visible:
            self.splitter.setStyleSheet(
                'QSplitter { background: transparent; }'
                f'QSplitter::handle {{ background: rgba(255,255,255,35); border-radius: 3px; margin: {margin}; }}'
                'QSplitter::handle:hover { background: rgba(149,176,255,130); }')
        else:
            self.splitter.setStyleSheet(
                'QSplitter { background: transparent; }'
                f'QSplitter::handle {{ background: transparent; border: 0px; image: none; margin: {margin}; }}'
                'QSplitter::handle:hover { background: transparent; }')

    def apply_background_blur(self):
        if not KDE_BLUR or not self.windowHandle():
            return
        region = QRegion()
        panes = ((self.web, self.settings['blur_px'] > 0 and self.panel_visible),
                 (self.avatar, self.settings['avatar_blur'] and self.settings.get('avatar_enabled',True) and not self.settings.get('avatar_hidden',False)))
        for widget, enabled in panes:
            if enabled:
                region = region.united(QRegion(QRect(widget.mapTo(self, QPoint(0, 0)), widget.size())))
        KDE_BLUR(shiboken6.getCppPointer(self.windowHandle())[0], not region.isEmpty(),
                 shiboken6.getCppPointer(region)[0])

    def update_avatar_fade(self):
        hidden = self.settings['fade_avatar'] and not self.panel_visible
        duration = self.settings['fade_out_ms'] if hidden else self.settings['fade_in_ms']
        self.avatar.fade_to(0.0 if hidden else 1.0, duration)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate) and getattr(self, 'page_loaded', False):
            self.update_resize_edges()
            if self.isActiveWindow() and not (getattr(self, 'dictionary_overlay', None) and self.dictionary_overlay.isVisible()):
                self.web.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            self.sync_focus()

    def sync_focus(self):
        prompt_active = (self.lookup_prompt is not None and self.lookup_prompt.isActiveWindow()) or (self.image_editor is not None and self.image_editor.isVisible())
        active = (self.isVisible() and (((self.isActiveWindow() or prompt_active) and
                  QApplication.applicationState() == Qt.ApplicationState.ApplicationActive) or (self.hover_popup is not None and self.hover_popup.isVisible() and self.hover_popup.isActiveWindow())))
        if active != self.last_active:
            self.last_active = active
            self.update_resize_edges()
            if self.page_loaded:
                self.web.page().runJavaScript(f'setWindowActive({str(active).lower()})')

    def page_ready(self, loaded):
        if loaded:
            self.page_loaded = True
            self.last_active = None
            self.sync_focus()
            if self.lookup_prompt_requested:
                self.lookup_prompt_requested = False
                self.open_lookup_prompt()

    def accept_connection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda sock=socket: self.read_connection(sock))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self.read_connection(socket)

    def read_connection(self, socket):
        try:
            payload = json.loads(bytes(socket.readAll()).decode('utf-8'))
            query = str(payload.get('query', '')).strip()
        except (UnicodeDecodeError, ValueError, AttributeError):
            return
        if payload.get('prompt'):
            self.open_lookup_prompt()
            return
        if query:
            self.query = query
            self.web.page().runJavaScript('setQuery(' + json.dumps(query, ensure_ascii=False) + ')')
            self.search(query)
        self.show_and_raise()

    def open_lookup_prompt(self):
        self.show_and_raise()
        if not self.page_loaded:
            self.lookup_prompt_requested = True
            return
        if self.lookup_prompt is not None:
            self.lookup_prompt.raise_()
            self.lookup_prompt.activateWindow()
            return
        self.hover_worker.cancel()
        prompt = QInputDialog(self, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.lookup_prompt = prompt
        prompt.setWindowTitle('Japanese Lookup')
        prompt.setLabelText('Enter word:')
        prompt.setInputMode(QInputDialog.InputMode.TextInput)
        prompt.setModal(True)
        prompt.finished.connect(self.finish_lookup_prompt)
        prompt.show()
        prompt.raise_()
        prompt.activateWindow()

    def finish_lookup_prompt(self, result):
        prompt = self.lookup_prompt
        self.lookup_prompt = None
        query = prompt.textValue().strip()
        prompt.deleteLater()
        if result == QDialog.DialogCode.Accepted and query:
            self.web.page().runJavaScript('setQuery(' + json.dumps(query, ensure_ascii=False) + ')')
            self.search(query)
        # Let the dialog finish closing before restoring keyboard focus to its owner.
        QTimer.singleShot(0, self.show_and_raise)

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()
        if not (getattr(self, 'dictionary_overlay', None) and self.dictionary_overlay.isVisible()):
            self.web.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if self.page_loaded:
            self.web.page().runJavaScript('setWindowActive(true); showPanel()')
        self.apply_background_blur()
        self.last_active = None
        QTimer.singleShot(350, self.sync_focus)

    def toggle_keep_above(self):
        enabled = not self.keep_above_enabled
        previous = self.keep_above_enabled
        try:
            write_keep_above_rule(enabled)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            try:
                write_keep_above_rule(previous)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            QMessageBox.warning(self, 'Keep above windows', str(error))
            return previous
        self.keep_above_enabled = enabled
        if enabled:
            self.raise_()
            self.activateWindow()
        return enabled

    def toggle_avatar_vertical_position(self):
        self.mirror_for_layout('vertical')
        if self.settings['split_orientation'] == 'vertical':
            self.settings['avatar_top'] = not self.settings['avatar_top']
            self.apply_side()
            self.restore_splitter_ratio()
            self.save_preferences()
            return self.settings['avatar_top']
        is_top = self.settings['avatar_vertical_position'] != 'top'
        self.settings['avatar_vertical_position'] = 'top' if is_top else 'bottom'
        self.avatar.update()
        if self._panel_input_masked:
            self.apply_panel_input_mask()
        self.save_preferences()
        return is_top

    def quit_app(self):
        self.quitting = True
        self.save_window_state()
        self.tray.hide()
        self.server.close()
        self.db.close()
        QApplication.instance().quit()

    def apply_side(self):
        is_vertical = self.settings['split_orientation'] == 'vertical'
        self.splitter.setOrientation(Qt.Orientation.Vertical if is_vertical else Qt.Orientation.Horizontal)
        self.set_splitter_handle_visible(self.panel_visible)
        avatar_index = ((0 if self.settings['avatar_top'] else 1) if is_vertical
                        else (1 if self.settings['avatar_right'] else 0))
        self.splitter.insertWidget(avatar_index, self.avatar)
        self.avatar.setVisible(self.settings.get('avatar_enabled',True))
        if self._panel_input_masked:
            QTimer.singleShot(0, self.apply_panel_input_mask)
        QTimer.singleShot(0, self.apply_background_blur)

    def flip_horizontal(self):
        self.mirror_for_layout('sides')
        self.settings['avatar_right'] = not self.settings['avatar_right']
        if self.settings['split_orientation'] == 'horizontal':
            self.apply_side()
            self.restore_splitter_ratio()
        self.avatar.update()
        if self._panel_input_masked:
            self.apply_panel_input_mask()
        self.save_preferences()
        self.web.page().runJavaScript('paneOrderChanged(' + json.dumps(self.settings) + ')')

    def swap_panes(self):
        vertical = self.settings['split_orientation'] == 'vertical'
        current = ((3 if self.settings['avatar_top'] else 1) if vertical
                   else (0 if self.settings['avatar_right'] else 2))
        position = (current + 1) % 4
        self.settings['split_orientation'] = 'vertical' if position % 2 else 'horizontal'
        if position % 2:
            self.settings['avatar_top'] = position == 3
        else:
            self.settings['avatar_right'] = position == 0
        self.apply_side()
        self.restore_splitter_ratio()
        self.avatar.update()
        self.save_preferences()
        self.web.page().runJavaScript('paneOrderChanged(' + json.dumps(self.settings) + ')')

    def rotate_panes(self):
        self.swap_panes()
        return self.settings['split_orientation'] == 'vertical'

    def mirror_for_layout(self,action):
        for kind in ('avatar','background'):
            if self.settings.get(kind+'_auto_mirror_'+action,False):
                key=kind+'_mirror_x';self.settings[key]=not self.settings.get(key,False)
        self.avatar.scale_image()
        if getattr(self,'manager_background',None):self.update_manager_background_color()
        if self.page_loaded:self.web.page().runJavaScript('applyPreferences('+json.dumps(self.settings)+')')

    def save_preferences(self):
        self.remember_window_state()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')

    def load_page(self):
        self.page_loaded = False
        custom = load_css().replace('</style', '<\\/style')
        markup = (ROOT / 'floating_page.html').read_text(encoding='utf-8')
        markup = markup.replace('/* CONTRAST_JS */', (ROOT / 'appearance_contrast.js').read_text())
        markup = markup.replace('/* ENTRY_FONT_JS */', (ROOT / 'entry_fonts.js').read_text())
        markup = markup.replace('/* LOOKUP_GRID_JS */', (ROOT / 'lookup_grid.js').read_text())
        markup = markup.replace('/* BASE_CSS */', DEFAULT_CSS + (ROOT / 'reading_stats.css').read_text() + (ROOT / 'pitch_accent.css').read_text()+(ROOT/'entry_style.css').read_text()+(ROOT/'translation.css').read_text()).replace('/* CUSTOM_CSS */', custom)
        markup = markup.replace('INITIAL_QUERY', html.escape(self.query, quote=True))
        page_settings = {
            key: self.settings[key] for key in ('panel_opacity', 'panel_darkness', 'panel_color', 'text_color_mode', 'blur_px', 'auto_fade',
                'fade_only_when_inactive',
                'fade_delay_ms', 'fade_in_ms', 'fade_out_ms', 'search_as_you_type', 'navbar_auto_hide', 'lookup_split', 'lookup_ratio', 'avatar_enabled', 'avatar_hidden', 'font_headword', 'font_reading', 'font_definition', 'font_example', 'font_frequency', 'font_pitch', 'background_crossfade', 'background_fade_ms', 'background_seconds')}
        page_settings['background_url'] = self.background_url()
        page_settings.update({key:value for key,value in self.settings.items() if key.startswith(('avatar_auto_mirror_','background_auto_mirror_','background_mirror_')) or key=='avatar_fill_pane'})
        page_settings.update({key:self.settings[key] for key in ('dictionary_image_blur','dictionary_image_opacity','avatar_image_blur','avatar_background_color','avatar_corner_radius','avatar_corner_mode','dictionary_corner_radius','dictionary_corner_mode')})
        page_settings.update({key:value for key,value in self.settings.items() if key.startswith('background_show_')})
        page_settings.update({key:self.settings[key] for key in ('lookup_grid','lookup_column_weights','lookup_row_weights')})
        page_settings['font_family'] = self.settings['font_family']
        page_settings['font_choices'] = font_choices()
        page_settings['keep_above'] = self.keep_above_enabled
        page_settings['avatar_vertical_position'] = self.settings['avatar_vertical_position']
        page_settings['avatar_top'] = self.settings['avatar_top']
        page_settings['split_orientation'] = self.settings['split_orientation']
        markup = markup.replace('INITIAL_SETTINGS', json.dumps(page_settings))
        scripts = (ROOT / 'translation.js').read_text() + '\n' + (ROOT / 'stats_source_settings.js').read_text() + '\n' + (ROOT / 'reading_stats.js').read_text() + '\n' + (ROOT / 'reading_history.js').read_text() + '\n' + (ROOT / 'kanji_grid.js').read_text() + '\n' + (ROOT / 'anki_insights.js').read_text() + '\n' + (ROOT / 'popup_settings.js').read_text() + '\nsetPopupPreferences(' + json.dumps(self.popup_config.values) + ');\n' + (ROOT / 'popup_scanner.js').read_text() + '\n' + (ROOT / 'character_links.js').read_text() + '\nbindCharacterLinks(document.getElementById("lookup-area"));'
        markup = markup.replace('</body>', '<script>' + scripts + '</script></body>')
        self.web.setHtml(markup, QUrl.fromLocalFile(str(ROOT) + '/'))

    def reading_stats_payload(self):
        data = self.stats_store.summary()
        data['source_settings'] = self.source_settings.public()
        data['kanji_grid_options'] = self.kanji_grid_preferences()
        data['cloud_connections'] = connection_summary(CONFIG_DIR)
        data['imported_files'] = list_assets(self.stats_store)
        data['manual_entries'] = [dict(zip(('id','day','description','characters','seconds'),row)) for row in self.stats_store.db.execute("SELECT key,day,source,characters,seconds FROM readings WHERE kind='manual' ORDER BY day DESC,key DESC")]
        data['refreshing'] = bool(self.stats_refresh_future)
        data['refresh_notice'] = self.stats_refresh_notice
        data['anki_status'] = self.anki_stats_feed.status
        data['status'] = 'Importing…' if self.stats_import_future else self.stats_feed.status
        if self.mokuro_browser_feed.is_live and not self.stats_import_future:
            data['status'] = data['status']+' · Mokuro Browser' if data['status'].startswith('Live') else 'Live · Mokuro Browser'
        return json.dumps(data, ensure_ascii=False)

    def refresh_reading_stats(self):
        if self.page_loaded:
            self.web.page().runJavaScript("!!document.getElementById('reading-stats')", self.refresh_visible_reading_stats)

    def refresh_visible_reading_stats(self, visible):
        if visible and self.page_loaded:
            self.web.page().runJavaScript("if(document.getElementById('reading-stats'))updateReadingStats(" + self.reading_stats_payload() + ")")

    def open_reading_stats(self):
        self.web.page().runJavaScript('readingHistoryState=null')
        self.hover_worker.cancel()
        self.lookup_worker.cancel()
        self.cancel_additional_lookups()
        if getattr(self, 'dictionary_overlay', None):
            self.close_dictionary_manager()
        self.web.page().runJavaScript('showReadingStats(' + self.reading_stats_payload() + ')')

    def open_translation(self):
        self.hover_worker.cancel();self.lookup_worker.cancel();self.cancel_additional_lookups()
        self.hide_hover_popup()
        self.web.page().runJavaScript('openTranslation('+json.dumps(self.translator.settings.public())+')')

    def close_cloud_connections(self):
        for connection in self.cloud_connections.values():connection.close()

    def start_cloud_connection(self, provider, for_refresh=False):
        if provider not in ('google_drive','mega','onedrive'):return
        if self.stats_refresh_future and not for_refresh:return
        previous=self.cloud_connections.get(provider)
        if previous and not previous.future.done():return
        if previous:previous.close()
        connection=BrowserCloudConnection(CONFIG_DIR,provider,self)
        self.cloud_connections[provider]=connection
        connection.finished.connect(lambda name,success:self.finish_cloud_connection(name,success,for_refresh))
        connection.start()
        self.refresh_reading_stats()

    def finish_cloud_connection(self,provider,success,for_refresh):
        self.refresh_reading_stats()
        if for_refresh:
            self.refresh_auth_succeeded |= success
            self.continue_refresh_authentication()

    def continue_refresh_authentication(self):
        if self.refresh_auth_queue:
            provider=self.refresh_auth_queue.pop(0)
            self.start_cloud_connection(provider,for_refresh=True)
        elif self.refresh_auth_succeeded:
            self.refresh_auth_succeeded=False
            self.refresh_external_stats(auth_retry=True)

    def refresh_external_stats(self, auth_retry=False):
        if self.stats_refresh_future or self.stats_import_future:
            return
        if any(connection.future and not connection.future.done() for connection in self.cloud_connections.values()):
            self.stats_refresh_notice='Sign-in is in progress.'
            self.stats_notice_timer.start()
            self.refresh_reading_stats()
            return
        if not auth_retry:
            self.refresh_auth_attempted=set()
            self.refresh_auth_queue=[]
            self.refresh_auth_succeeded=False
        self.stats_refresh_notice = ''
        self.stats_notice_timer.stop()
        self.stats_refresh_future = self.stats_import_pool.submit(refresh_configured,
            CONFIG_DIR / 'reading-stats.sqlite3', copy.deepcopy(self.source_settings.values),
            CONFIG_DIR / 'import-sources')
        self.stats_import_poll.start()
        self.refresh_reading_stats()

    def finish_stats_refresh(self):
        if not self.stats_refresh_future or not self.stats_refresh_future.done():
            return
        self.stats_import_poll.stop()
        future, self.stats_refresh_future = self.stats_refresh_future, None
        try:
            self.stats_refresh_notice = future.result()
        except Exception:
            self.stats_refresh_notice = 'Refresh failed; existing stats were kept.'
        if self.page_loaded:self.web.page().runJavaScript('resetAnkiInsights()')
        self.stats_notice_timer.start()
        self.refresh_reading_stats()
        # This completion is only reached from an explicit Refresh action, never
        # from app startup, timers, or opening settings. Prompt at most once per
        # provider for this action, even if its new credentials still fail.
        connections=connection_summary(CONFIG_DIR)
        mokuro=self.source_settings.values['mokuro']
        if mokuro['enabled']:
            self.refresh_auth_queue=[provider for provider in ('google_drive','mega','onedrive')
                if mokuro[provider]['enabled'] and connections[provider]['state']=='needs_auth'
                and provider not in self.refresh_auth_attempted]
            self.refresh_auth_attempted.update(self.refresh_auth_queue)
            self.continue_refresh_authentication()

    def kanji_grid_preferences(self):
        if not hasattr(self,'_kanji_grid_defaults'):self._kanji_grid_defaults=kanji_options()
        saved=self.stats_store.preference('kanji_grid_options',{})
        try:return clean_kanji_preferences(saved,self._kanji_grid_defaults)
        except ValueError:return dict(self._kanji_grid_defaults)

    def load_anki_insights(self, request_id):
        config=copy.deepcopy(self.source_settings.values['anki'])
        for _,_,future in self.anki_insights_jobs:
            future.cancel()
        self.anki_insights_jobs.append((request_id,config_version(config),self.anki_insights_pool.submit(load_insights,config,options=self.kanji_grid_preferences(),cutoff_hour=self.stats_store.day_cutoff_hour())))
        self.anki_insights_poll.start()

    def finish_anki_insights(self):
        for job in list(self.anki_insights_jobs):
            request_id,version,future=job
            if not future.done():continue
            self.anki_insights_jobs.remove(job)
            if future.cancelled():continue
            if version!=config_version(self.source_settings.values['anki']):continue
            try:payload={'data':future.result()}
            except Exception as error:
                payload={'error':str(error) if isinstance(error,ValueError) else 'Cannot load Anki graphs. Check the connection and selected decks.'}
            if self.page_loaded:self.web.page().runJavaScript('ankiInsightsLoaded('+json.dumps(request_id)+','+json.dumps(payload,ensure_ascii=False)+')')
        if not self.anki_insights_jobs:self.anki_insights_poll.stop()

    def clear_stats_refresh_notice(self):
        self.stats_refresh_notice = ''
        self.refresh_reading_stats()

    def configure_stats_sources(self):
        self.stats_refresh_notice = ''
        if self.page_loaded:self.web.page().runJavaScript('resetAnkiInsights()')
        values = self.source_settings.values
        self.stats_store.set_preference('day_cutoff_hour',values['day']['cutoff_hour'])
        self.stats_store.set_preference('source_metrics',{name:{key:value for key,value in fields.items() if key.startswith('include_')} for name,fields in values.items()})
        self.stats_store.set_preference('anki_config_version', config_version(values['anki']))
        self.stats_feed.configure(values['gsm']['url'], values['gsm']['enabled'])
        self.mokuro_browser_feed.configure(values['mokuro_browser'])
        self.anki_stats_feed.config = copy.deepcopy(values['anki'])
        self.anki_stats_feed.paths = values['anki']['paths']
        self.anki_stats_feed.fingerprint = None
        self.anki_stats_feed.update()
        self.refresh_reading_stats()

    def load_stats_decks(self, payload):
        if self.stats_decks_future:
            return
        try:
            draft = json.loads(payload)
            config = dict(self.source_settings.values['anki'], **draft)
            self.stats_decks_future = self.stats_import_pool.submit(available_decks, config)
            self.stats_decks_poll.start()
        except (ValueError, TypeError):
            self.web.page().runJavaScript('statsDecksLoaded({error:"Invalid Anki settings."})')

    def finish_stats_decks(self):
        if not self.stats_decks_future or not self.stats_decks_future.done():
            return
        self.stats_decks_poll.stop()
        future, self.stats_decks_future = self.stats_decks_future, None
        try:
            payload = {'decks': future.result()}
        except Exception as error:
            payload = {'error': str(error) if isinstance(error, ValueError) else 'Cannot read Anki decks. Check the connection.'}
        self.web.page().runJavaScript('statsDecksLoaded(' + json.dumps(payload) + ')')

    def import_reading_stats(self):
        if not self.source_settings.values['files']['enabled']:
            QMessageBox.information(self, 'Reading history', 'Enable file imports in Stats settings.')
            return
        if self.stats_import_future or self.stats_refresh_future:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Import reading history', '',
            'Reading history (*.csv *.json *.txt *.zip);;All files (*)')
        if not paths:
            return
        self.stats_refresh_notice = ''
        database = CONFIG_DIR / 'reading-stats.sqlite3'
        def import_files():
            store = ReadingStats(database)
            try:
                return sum(import_path(store,path) for path in paths)
            finally:
                store.db.close()
        self.stats_import_future = self.stats_import_pool.submit(import_files)
        self.stats_import_poll.start()
        self.refresh_reading_stats()

    def finish_stats_import(self):
        if not self.stats_import_future or not self.stats_import_future.done():
            return
        self.stats_import_poll.stop()
        future, self.stats_import_future = self.stats_import_future, None
        try:
            imported = future.result()
            self.web.page().runJavaScript('window.statsImportNotice?.(' + json.dumps(f'Imported {imported} record' + ('' if imported == 1 else 's')) + ')')
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, 'Import reading history', str(error))
        self.refresh_reading_stats()

    def scanner_dictionaries(self):
        return self.db.execute('SELECT id,title,path,enabled FROM dictionaries ORDER BY sort_order,id').fetchall()

    def open_popup_settings(self):
        self.hover_worker.cancel()
        self.lookup_worker.cancel()
        self.cancel_additional_lookups()
        if getattr(self, 'dictionary_overlay', None):
            self.close_dictionary_manager()
        dictionaries=metadata_sources(self.db)
        self.web.page().runJavaScript('showPopupSettings(' + json.dumps(self.popup_config.values) + ',' + json.dumps(dictionaries) + ')')

    def open_collapse_settings(self):
        self.hover_worker.cancel();self.lookup_worker.cancel();self.cancel_additional_lookups()
        self.web.page().runJavaScript('showCollapseSettings(' + json.dumps(self.popup_config.values) + ',' + self.dictionary_payload() + ')')

    def popup_application_state(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            if getattr(self,'page_loaded',False):self.web.page().runJavaScript('window.clearPopupScanKeys?.()')
            self.hover_worker.cancel()

    def close_hover_if_outside(self):
        from PySide6.QtGui import QCursor
        if self.hover_popup and not self.hover_popup.geometry().contains(QCursor.pos()):
            self.hover_worker.cancel()
            self.hover_close_timer.stop()

    def hide_hover_popup(self, reset_scan=True):
        if reset_scan and getattr(self,'page_loaded',False):self.web.page().runJavaScript('window.resetPopupScan?.()')
        self.popup_requested=False
        self.popup_user_position=False
        self.hover_close_timer.stop()
        self.hover_worker.cancel()
        self.character_worker.cancel()
        if self.hover_popup:
            self.hover_popup.hide()

    def global_popup_click(self,when):
        if not self.hover_popup or not self.hover_popup.isVisible():return
        # WebEngine forwards inside presses asynchronously; allow that message
        # to arrive before deciding that a system-wide press was outside.
        generation=self.popup_generation
        def dismiss_if_outside():
            if generation==self.popup_generation and self.last_popup_press<when-.06 and self.hover_popup and self.hover_popup.isVisible():self.hide_hover_popup()
        QTimer.singleShot(200,dismiss_if_outside)

    def selected_entry_metadata(self, entries):
        return getattr(entries,'metadata',{})

    def metadata_selection(self):
        return self.popup_config.metadata_selection('main_')

    def popup_metadata_selection(self):
        return self.popup_config.metadata_selection()

    def open_character(self, character, x, y, from_popup=False):
        if not is_character(character):return
        self.hover_worker.cancel()
        self.character_worker.cancel()
        if from_popup and self.hover_popup and self.hover_popup.isVisible():
            self.popup_history.append((self.popup_markup,self.popup_title))
        else:
            self.popup_history=[]
            self.hover_position=self.web.mapToGlobal(QPoint(x,y))
        self.popup_requested=True
        ids=self.popup_config.enabled_ids(self.scanner_dictionaries()) if from_popup else None
        self.character_worker.submit(character,ids)

    def show_character_results(self, character, markup, error):
        if not self.popup_requested:return
        if error:markup='<p class="empty">'+html.escape(error)+'</p>'
        if markup:self.show_popup_markup(markup,'Character lookup')

    def show_hover_results(self, payload, entries, error):
        if error or not entries:
            self.hover_worker.cancel()
            return
        self.popup_history=[]
        pitches=self.selected_entry_metadata(entries)
        chunks=[]
        for term,reading,glossary,did,title in entries:
            try:definition=render(json.loads(glossary))
            except (ValueError,TypeError):continue
            chunks.append(f'<article><small>{html.escape(title)}</small><h2 data-headword="{html.escape(term,quote=True)}">{headword_markup(term)}</h2><div class="reading">{html.escape(reading)}</div>{pitches.get((term,reading), "")}<div class="definition">{definition}</div></article>')
        self.show_popup_markup(''.join(chunks),'Dictionary lookup')

    def show_popup_markup(self, markup, title):
        self.popup_requested=True
        self.popup_generation+=1
        self.popup_markup=markup
        self.popup_title=title
        if self.hover_popup is None:
            self.hover_popup=QWebEngineView(self)
            self.hover_popup.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.hover_popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.hover_popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.hover_popup.page().setBackgroundColor(QColor(Qt.GlobalColor.transparent))
            self.hover_popup.installEventFilter(self)
            self.popup_channel=QWebChannel(self.hover_popup.page());self.popup_channel.registerObject('app',self.bridge)
            self.hover_popup.page().setWebChannel(self.popup_channel)
            self.popup_ready=False
            self.hover_popup.loadFinished.connect(self.popup_page_ready)
            self.hover_popup.setHtml((ROOT/'popup_page.html').read_text().replace('/* ENTRY_FONT_JS */',(ROOT/'entry_fonts.js').read_text()).replace('/* CHARACTER_LINKS_JS */',(ROOT/'character_links.js').read_text()).replace('</style>',(ROOT/'pitch_accent.css').read_text()+(ROOT/'entry_style.css').read_text()+'</style>',1),QUrl.fromLocalFile(str(ROOT)+'/'))
        else:
            self.update_popup_content()

    def popup_page_ready(self, loaded):
        self.popup_ready=loaded
        if loaded:self.update_popup_content()

    def update_popup_appearance(self):
        if not self.hover_popup or not getattr(self,'popup_ready',False):return
        values={key:value for key,value in self.settings.items() if key.startswith('font_')}
        values['background_color']=self.popup_config.values['background_color']
        values['opacity']=self.popup_config.values['opacity']
        values.update(background_url=self.background_url(),background_show_popup=self.settings.get('background_show_popup',True),dictionary_image_blur=self.settings.get('dictionary_image_blur',0),dictionary_image_opacity=self.settings.get('dictionary_image_opacity',100),background_mirror_x=self.settings.get('background_mirror_x',False),background_mirror_y=self.settings.get('background_mirror_y',False))
        self.hover_popup.page().runJavaScript('applyPopupAppearance('+json.dumps(values)+')')

    def update_popup_content(self):
        if not self.popup_ready or not self.popup_requested:return
        self.update_popup_appearance()
        self.hover_popup.page().runJavaScript('renderPopup('+json.dumps(self.popup_markup)+','+json.dumps(self.popup_title)+','+json.dumps(bool(self.popup_history))+')')
        screen=QApplication.screenAt(self.hover_position) or QApplication.primaryScreen();bounds=screen.availableGeometry()
        width=min(self.popup_config.values['popup_width'],bounds.width());height=min(self.popup_config.values['popup_height'],bounds.height())
        self.hover_popup.resize(width,height)
        x=max(bounds.left(),min(self.hover_position.x()+18,bounds.right()-width+1))
        y=self.hover_position.y()+20
        if y+height>bounds.bottom():y=self.hover_position.y()-height-12
        if not getattr(self,'popup_user_position',False):self.hover_popup.move(x,max(bounds.top(),y))
        self.hover_popup.show();self.hover_popup.raise_()

    def search(self, query):
        self.hover_worker.cancel()
        self.web.page().runJavaScript('closeSettings()')
        if getattr(self, 'dictionary_overlay', None):
            self.dictionary_manager_open = False
            self.dictionary_overlay.hide()
            self.web.show()
            self.web.page().runJavaScript("document.querySelector('.panel').classList.remove('dictionary-manager-open')")
        self.query = query.strip()
        self.lookup_worker.submit(self.query)
        if not self.query:
            self.web.page().runJavaScript('renderResults("")')
            return

    def search_extra_pane(self, pane_id, query):
        if pane_id < 2 or pane_id not in {cell for row in self.settings['lookup_grid'] for cell in row}:
            return
        self.extra_queries[pane_id] = query.strip()
        if pane_id not in self.extra_workers:
            worker = AsyncLookup(self, executor=self.grid_lookup_pool)
            worker.metadata_cache = self.metadata_cache
            worker.metadata_selection_provider = self.metadata_selection
            worker.ready.connect(lambda q, entries, error, pid=pane_id:self.display_search_results(q, entries, error, pane_id=pid))
            self.extra_workers[pane_id] = worker
        self.extra_workers[pane_id].submit(self.extra_queries[pane_id])

    def cancel_additional_lookups(self):
        self.secondary_worker.cancel()
        for worker in self.extra_workers.values():worker.cancel()

    def refresh_extra_lookups(self):
        active = {cell for row in self.settings['lookup_grid'] for cell in row}
        for pid, worker in self.extra_workers.items():
            if pid in active and self.extra_queries.get(pid):worker.submit(self.extra_queries[pid])

    def close_extra_lookups(self):
        for worker in self.extra_workers.values():worker.shutdown()
        self.grid_lookup_pool.shutdown(wait=False, cancel_futures=True)

    def display_search_results(self, query, entries, error, secondary=False, pane_id=None):
        if pane_id is not None:
            if pane_id not in {cell for row in self.settings['lookup_grid'] for cell in row}:return
            expected = self.extra_queries.get(pane_id, '')
            renderer = '(markup, expected)=>renderPaneResults('+str(pane_id)+',markup,expected)'
            renderer = '('+renderer+')'
        else:
            expected=self.secondary_query if secondary else self.query
            renderer='renderSecondaryResults' if secondary else 'renderResults'
        if query != expected:
            return
        if error:
            self.web.page().runJavaScript(renderer+'(' + json.dumps('<div class="empty">' + html.escape(error) + '</div>') + ',' + json.dumps(query) + ')')
            return
        if not entries:
            output = '<div class="empty">No matches in the enabled dictionaries.</div>' if query else ''
        else:
            pitches = self.selected_entry_metadata(entries)
            paths = dict(self.db.execute('SELECT id,path FROM dictionaries'))
            collapsed = set(self.popup_config.values['main_collapsed_paths'])
            chunks = ['<div class="dictionary-nav-wrap"><nav class="dictionary-nav"><button class="dictionary-collapse-defaults" type="button">Collapse defaults…</button>']
            seen = set()
            for _, _, _, did, title in entries:
                if did not in seen:
                    chunks.append(f'<a href="#dict-{did}">{html.escape(title)}</a>')
                    seen.add(did)
            chunks.append('</nav><button class="dictionary-nav-toggle" type="button" aria-expanded="false" aria-label="Show all dictionaries" title="Show all dictionaries">↓</button></div>')
            current = None
            for term, reading, glossary, did, title in entries:
                if did != current:
                    if current is not None:
                        chunks.append('</details>')
                    current = did
                    path = paths.get(did, '')
                    expanded = '' if path in collapsed else ' open'
                    chunks.append(f'<details id="dict-{did}" class="dictionary" data-dictionary-path="{html.escape(path,quote=True)}"{expanded}><summary><h2>{html.escape(title)}</h2></summary>')
                chunks.append('<article class="entry">')
                chunks.append(f'<h3 data-headword="{html.escape(term,quote=True)}">{headword_markup(term)}</h3>')
                if reading:
                    chunks.append(f'<div class="reading">{html.escape(reading)}</div>')
                chunks.append(pitches.get((term, reading), ''))
                try:
                    chunks.append(f'<div class="definition">{render(json.loads(glossary))}</div>')
                except (ValueError, TypeError):
                    chunks.append('<div class="definition">Unable to display this entry.</div>')
                chunks.append('</article>')
            chunks.append('</details>')
            output = ''.join(chunks)
        self.web.page().runJavaScript(renderer+'(' + json.dumps(output, ensure_ascii=False) + ',' + json.dumps(query, ensure_ascii=False) + ')')

    def css_preview_markup(self):
        entries = search_entries(self.db, '読む')
        entry = next((row for row in entries if row[4].startswith('JMdict')),
                     entries[0] if entries else None)
        title = html.escape(entry[4]) if entry else 'JMdict'
        if entry:
            try:
                definition = render(json.loads(entry[2]))
            except (ValueError, TypeError):
                definition = 'to read'
        else:
            definition = '<ul><li>to read</li><li>to understand written words</li></ul>'
        markup = (ROOT / 'css_preview.html').read_text(encoding='utf-8')
        return (markup.replace('/* BASE_CSS */', DEFAULT_CSS)
                .replace('PREVIEW_PANEL_CLASS', 'no-glass' if self.settings['panel_opacity'] == 0 else '')
                .replace('PREVIEW_DICTIONARY', title)
                .replace('PREVIEW_DEFINITION', definition)
                .replace('<html lang="en">',
                         f'<html lang="en" style="--panel-opacity:{self.settings["panel_opacity"] / 100}">'))

    def order_background_files(self):
        self.background_files.sort(key=str.casefold)
        if self.settings['background_order'] == 'reverse':
            self.background_files.reverse()
        elif self.settings['background_order'] == 'random':
            random.shuffle(self.background_files)

    def next_background(self):
        if self.background_files:
            self.background_index = (self.background_index + 1) % len(self.background_files)
            if self.background_index == 0 and self.settings['background_order'] == 'random':
                previous = self.image_edits.source(self.settings['background_image'])
                random.shuffle(self.background_files)
                if len(self.background_files) > 1 and self.background_files[0] == previous:
                    self.background_files[0], self.background_files[1] = self.background_files[1], self.background_files[0]
            path = self.background_files[self.background_index]
            if self.media_catalog.readable(path):
                self.set_background(path)
            else:
                self.background_files.pop(self.background_index)
                self.background_index -= 1
                QTimer.singleShot(0, self.next_background)

    def background_url(self):
        path = Path(self.settings['background_image'])
        if not path.is_file():
            return ''
        return QUrl.fromLocalFile(str(path.resolve())).toString()

    def set_background(self, path):
        path=self.image_edits.resolve(path,'background')
        self.settings['background_image'] = path
        if path and Path(path).is_file():
            self.settings['blur_px']=0
            self.apply_background_blur()
        self.save_preferences()
        self.web.page().runJavaScript('applyPreferences(' + json.dumps(self.settings) + ')')
        self.update_popup_appearance()
        self.web.page().runJavaScript('setPaneBackground(' + json.dumps(self.background_url()) + ')')
        if getattr(self, 'dictionary_manager_open', False) and getattr(self, 'manager_background', None):
            self.manager_background.set_image(
                path, self.settings['background_crossfade'],
                min(self.settings['background_fade_ms'], self.settings['background_seconds'] * 1000))

    def open_settings(self):
        self.hover_worker.cancel()
        self.lookup_worker.cancel()
        self.cancel_additional_lookups()
        if getattr(self, 'dictionary_overlay', None):
            self.dictionary_manager_open = False
            self.dictionary_overlay.hide()
            self.web.show()
            self.web.page().runJavaScript("document.querySelector('.panel').classList.remove('dictionary-manager-open')")
        self.web.page().runJavaScript('showSettings(' + json.dumps(self.settings) + ')')

    def preview_color(self, scope, value):
        if scope=='avatar':
            self.settings['avatar_background_color']=value
            if value and not self.settings['avatar_background_opacity']:self.settings['avatar_background_opacity']=100
            self.avatar.update()
        elif not re.fullmatch(r'#[0-9a-fA-F]{6}', value):return
        elif scope == 'dictionary':
            self.settings['panel_color'] = value
            if getattr(self, 'manager_background', None):self.update_manager_background_color()
        else:
            self.popup_config.values['background_color'] = value
            self.update_popup_appearance()
        self.web.page().runJavaScript('applyColorPreview('+json.dumps(scope)+','+json.dumps(value)+')')

    def choose_color(self, scope):
        if scope not in ('dictionary', 'popup','avatar'):return
        if self.color_dialog:
            if self.color_dialog_scope == scope:
                self.color_dialog.raise_();self.color_dialog.activateWindow();return
            self.color_dialog.reject()
        original = self.settings['avatar_background_color'] if scope=='avatar' else self.settings['panel_color'] if scope == 'dictionary' else self.popup_config.values['background_color']
        original_opacity=self.settings['avatar_background_opacity']
        dialog = QColorDialog(QColor(original or '#000000'), self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setWindowTitle('Avatar background color' if scope=='avatar' else 'Dictionary background color' if scope == 'dictionary' else 'Popup background color')
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.color_dialog, self.color_dialog_scope = dialog, scope
        preview = QTimer(dialog);preview.setSingleShot(True);preview.setInterval(16)
        preview.timeout.connect(lambda:self.preview_color(scope, dialog.currentColor().name()))
        dialog.currentColorChanged.connect(lambda color:preview.start() if not preview.isActive() else None)
        def finished(result):
            preview.stop()
            value = dialog.currentColor().name() if result == QDialog.DialogCode.Accepted else original
            self.preview_color(scope, value)
            if scope == 'dictionary':self.update_preference('panel_color', value)
            elif scope=='avatar':
                if result!=QDialog.DialogCode.Accepted:self.settings['avatar_background_opacity']=original_opacity
                self.update_preference('avatar_background_color',value)
            else:
                self.popup_config.update('background_color', value)
                self.web.page().runJavaScript('setPopupPreferences('+json.dumps(self.popup_config.values)+')')
            self.color_dialog = None;self.color_dialog_scope = None
            self.web.page().runJavaScript('endColorPreview()')
            self.last_active = None;self.sync_focus()
        dialog.finished.connect(finished)
        self.web.page().runJavaScript('beginColorPreview()')
        dialog.show()

    def edit_image(self,path,kind,keep_folder=False):
        if self.image_editor:
            self.image_editor.raise_();self.image_editor.activateWindow();return
        path=self.image_edits.resolve(path,kind)
        current=self.settings['avatar' if kind=='avatar' else 'background_image']
        original,_=source_and_edit(current)
        if str(Path(path).resolve())==str(Path(original).resolve()) and Path(current).is_file():path=current
        try:editor=ImageEditDialog(path,self.settings,kind,self)
        except ValueError as error:
            QMessageBox.information(self,'Edit image',str(error));return
        self.image_editor=editor
        timer=self.avatar_timer if kind=='avatar' else self.background_timer
        was_cycling=timer.isActive();timer.stop()
        try:
            while editor.exec()==QDialog.DialogCode.Accepted:
                try:
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    edited=export_edit(editor.source,editor.specification(),CONFIG_DIR/'edited-images')
                    self.image_edits.remember(editor.source,kind,editor.specification(),edited)
                except (OSError,ValueError) as error:
                    editor.notice.setText(str(error));continue
                finally:QApplication.restoreOverrideCursor()
                ratio=self.settings['splitter_ratio']
                self.settings.update(editor.options())
                self.settings[kind+'_mirror_x']=False;self.settings[kind+'_mirror_y']=False
                if kind=='avatar':self.update_preference('avatar',edited,keep_folder=keep_folder)
                else:
                    if not keep_folder:self.settings['background_folder']=''
                    self.set_background(edited)
                self.avatar.scale_image();self.restore_splitter_ratio(ratio);self.save_preferences()
                self.web.page().runJavaScript('applyPreferences('+json.dumps(self.settings)+')')
                break
        finally:
            folder=self.settings['avatar_folder' if kind=='avatar' else 'background_folder']
            if folder and (was_cycling or keep_folder) and not (kind=='avatar' and self.settings['avatar_hidden']):
                timer.start(self.settings['avatar_seconds' if kind=='avatar' else 'background_seconds']*1000)
            self.image_editor=None;editor.deleteLater();self.last_active=None;QTimer.singleShot(0,self.sync_focus)

    def configure_avatar_rotation(self):
        self.avatar_timer.stop()
        folder = self.settings['avatar_folder']
        self.avatar_files = []
        if folder and Path(folder).is_dir():
            self.avatar_files = self.media_catalog.files(folder)
        if self.settings['avatar_order'] == 'reverse':
            self.avatar_files.reverse()
        elif self.settings['avatar_order'] == 'random':
            random.shuffle(self.avatar_files)
        self.avatar_index = -1
        if self.avatar_files and not self.settings['avatar_hidden']:
            current=self.image_edits.source(self.settings['avatar'])
            self.avatar_index=next((index for index,path in enumerate(self.avatar_files)
                                    if str(Path(path).resolve())==current),-1)
            if self.avatar_index<0:self.next_avatar()
            else:
                self.settings['avatar']=self.image_edits.resolve(self.avatar_files[self.avatar_index],'avatar')
                self.avatar.set_image(self.settings['avatar'])
            self.avatar_timer.start(self.settings['avatar_seconds'] * 1000)

    def next_avatar(self):
        if self.settings.get('avatar_hidden',False) or not self.avatar_files:
            return
        self.avatar_index = (self.avatar_index + 1) % len(self.avatar_files)
        if self.avatar_index == 0 and self.settings['avatar_order'] == 'random':
            previous = self.image_edits.source(self.settings['avatar'])
            random.shuffle(self.avatar_files)
            if len(self.avatar_files) > 1 and self.avatar_files[0] == previous:
                self.avatar_files[0], self.avatar_files[1] = self.avatar_files[1], self.avatar_files[0]
        path = self.avatar_files[self.avatar_index]
        if not self.media_catalog.readable(path):
            self.avatar_files.pop(self.avatar_index)
            self.avatar_index -= 1
            QTimer.singleShot(0, self.next_avatar)
            return
        self.settings['avatar'] = self.image_edits.resolve(path,'avatar')
        self.avatar.set_image(self.settings['avatar'])
        self.avatar.update()

    def update_preference(self, key, value,keep_folder=False):
        allowed = {'avatar_crossfade', 'avatar_fade_ms', 'background_crossfade', 'background_fade_ms', 'background_order', 'background_seconds', 'avatar_folder', 'avatar_seconds', 'avatar_order', 'avatar', 'avatar_vertical_position', 'avatar_right', 'search_as_you_type', 'navbar_auto_hide', 'lookup_split', 'lookup_ratio', 'avatar_enabled', 'avatar_hidden', 'font_headword', 'font_reading', 'font_definition', 'font_example', 'font_frequency', 'font_pitch',
            'blur_px', 'avatar_blur', 'panel_darkness', 'panel_color', 'text_color_mode', 'avatar_background_opacity',
            'auto_fade', 'fade_avatar', 'fade_delay_ms',
            'fade_in_ms', 'fade_out_ms'}
        allowed.update(('font_family','lookup_grid','lookup_column_weights','lookup_row_weights'))
        allowed.update(('avatar_fill_pane','avatar_auto_mirror_sides','avatar_auto_mirror_vertical','background_auto_mirror_sides','background_auto_mirror_vertical'))
        allowed.update(('dictionary_image_blur','dictionary_image_opacity','avatar_image_blur','avatar_background_color','avatar_corner_radius','dictionary_corner_radius','avatar_corner_mode','dictionary_corner_mode'))
        allowed.update('background_show_'+pane for pane in ('dictionary','popup','stats','translation','settings'))
        if key not in allowed:
            return
        if key in ('dictionary_image_blur','avatar_image_blur'):value=max(0,min(40,int(value)))
        if key=='dictionary_image_opacity':value=max(0,min(100,int(value)))
        if key in ('avatar_corner_radius','dictionary_corner_radius'):value=max(0,min(120,int(value)))
        if key in ('avatar_corner_mode','dictionary_corner_mode') and value not in ('all','top','bottom'):return
        if key=='avatar_background_color' and not re.fullmatch(r'(?:#[0-9a-fA-F]{6})?',str(value)):return
        if key == 'text_color_mode' and value not in ('automatic','black','white'):return
        if key == 'lookup_grid' and not valid_grid(value):return
        if key == 'font_family' and (not isinstance(value, str) or value not in {
                '', *(family for group in font_choices() for family in group['families'])}):
            return
        if key in ('avatar_fade_ms', 'background_fade_ms'):
            value = max(50, min(10000, int(value)))
        if key in {'avatar_seconds', 'background_seconds'}:
            value = max(1, min(86400, int(value)))
        if key in {'avatar_order', 'background_order'} and value not in ('default', 'reverse', 'random'):
            return
        if key == 'panel_color' and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):
            return
        if key == 'avatar_folder' and value:
            folder = Path(value)
            if not self.media_catalog.files(folder):
                QMessageBox.information(self, 'No images', 'Choose a folder containing supported images or GIFs.')
                return
        if key == 'avatar':
            value=self.image_edits.resolve(value,'avatar')
            if not Path(value).is_file() or QPixmap(value).isNull():
                return
            self.settings['avatar_hidden']=False
            self.avatar.set_image(value)
            if not keep_folder:
                self.settings['avatar_folder'] = ''
                self.avatar_timer.stop()
        if key=='avatar_folder' and value:self.settings['avatar_hidden']=False
        self.settings[key] = value
        if key in ('avatar_fill_pane','avatar_image_blur'):self.avatar.scale_image()
        if key in ('dictionary_image_blur','dictionary_image_opacity','dictionary_corner_radius','dictionary_corner_mode') and getattr(self,'manager_background',None):self.update_manager_background_color()
        if key == 'lookup_grid':
            self.settings.update(layout_settings(self.settings))
            active = {cell for row in value for cell in row}
            for pid in list(self.extra_workers):
                if pid not in active:
                    worker=self.extra_workers.pop(pid);worker.shutdown();worker.deleteLater();self.extra_queries.pop(pid,None)
            if 1 not in active:self.secondary_worker.cancel()
        if key == 'lookup_split':
            self.settings['lookup_grid'] = [[0,1]] if value else [[0]]
            self.settings.update(layout_settings(self.settings))
            if not value:self.cancel_additional_lookups()
        if key in ('lookup_column_weights','lookup_row_weights'):
            count=len(self.settings['lookup_grid'][0]) if key=='lookup_column_weights' else len(self.settings['lookup_grid'])
            self.settings[key]=weights(value,count)
        if key=='avatar_hidden' or (key=='avatar_folder' and not value):
            hidden=bool(value) if key=='avatar_hidden' else True
            self.settings['avatar_hidden']=hidden
            if hidden:self.avatar_timer.stop();self.avatar.clear_image()
            else:
                self.avatar.set_image(self.settings['avatar'])
                if self.settings['avatar_folder'] and self.avatar_files:
                    try:self.avatar_index=self.avatar_files.index(self.image_edits.source(self.settings['avatar']))
                    except ValueError:self.avatar_index=-1
                    self.avatar_timer.start(self.settings['avatar_seconds']*1000)

        if key=='auto_fade' and not value:self.update_panel_input_mask(True)
        if key=='avatar_enabled':
            self.avatar.setVisible(bool(value))
            if not value:self._panel_input_masked=False;self.windowHandle().setMask(QRegion()) if self.windowHandle() else None
            QTimer.singleShot(0,self.restore_splitter_ratio)
        if key.startswith('font_') and key != 'font_family':value=max(8,min(72,int(value)));self.settings[key]=value
        if key == 'lookup_ratio':value=max(.15,min(.85,float(value)));self.settings[key]=value
        if key == 'lookup_split' and not value:self.cancel_additional_lookups()
        if key == 'avatar_crossfade' and not value:
            self.avatar.finish_avatar_transition()
        if key == 'background_crossfade' and not value and getattr(self, 'manager_background', None):
            self.manager_background.finish_transition()
        if key in ('panel_darkness','panel_color') and getattr(self,'manager_background',None):
            self.update_manager_background_color()
        if key == 'background_order':
            self.order_background_files()
            self.background_index = -1
            self.next_background()
        if key == 'background_seconds' and self.settings['background_folder']:
            self.background_timer.start(value * 1000)
        if key in {'avatar_folder', 'avatar_order'}:
            self.configure_avatar_rotation()
        elif key == 'avatar_seconds' and self.avatar_files:
            self.avatar_timer.start(value * 1000)
        self.avatar.update()
        if key in {'avatar_right', 'avatar_vertical_position'}:
            self.apply_side()
        self.update_avatar_fade()
        self.apply_background_blur()
        self.save_preferences()
        self.web.page().runJavaScript('applyPreferences(' + json.dumps(self.settings) + ')')
        self.update_popup_appearance()

    def choose_avatar(self, field, parent):
        path, _ = QFileDialog.getOpenFileName(parent, 'Choose avatar image', field.text(),
                                              'Images (*.png *.gif *.webp *.jpg *.jpeg)')
        if path:
            field.setText(path)

    def fade_dictionary_overlay(self, visible):
        overlay = getattr(self, 'dictionary_overlay', None)
        if overlay and getattr(self, 'dictionary_manager_open', False):
            if visible:
                overlay.show()
            self.dictionary_fade.stop()
            self.dictionary_fade.setStartValue(self.dictionary_opacity.opacity())
            self.dictionary_fade.setEndValue(1.0 if visible else 0.0)
            self.dictionary_fade.setDuration(self.settings['fade_in_ms' if visible else 'fade_out_ms'])
            self.dictionary_fade.start()
            overlay.raise_()
            self.update_resize_edges()

    def finish_dictionary_fade(self):
        if not self.panel_visible and getattr(self, 'dictionary_overlay', None):
            self.dictionary_overlay.hide()

    def position_dictionary_overlay(self):
        overlay = getattr(self, 'dictionary_overlay', None)
        if overlay:
            origin = self.web.mapTo(self, QPoint(0, 0))
            overlay.setGeometry(QRect(origin, self.web.size()))
            if getattr(self, 'manager_background', None):
                self.manager_background.setGeometry(overlay.rect())
                self.manager_background.lower()
            overlay.raise_()
            self.update_resize_edges()

    def eventFilter(self, watched, event):
        popup=getattr(self,'hover_popup',None)
        if event.type()==QEvent.Type.MouseButtonPress and popup and popup.isVisible():
            if not popup.geometry().contains(event.globalPosition().toPoint()):
                self.hide_hover_popup(reset_scan=False)
        if watched is getattr(self,'hover_popup',None):
            if event.type()==QEvent.Type.Enter:self.hover_close_timer.stop()
            elif event.type()==QEvent.Type.Leave:self.hover_close_timer.stop()
        if watched is getattr(self, 'dictionary_overlay', None):
            if event.type() == QEvent.Type.Enter:
                self.web.page().runJavaScript('dictionaryHover(true)')
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self.web.page().runJavaScript('dictionaryHover(false)')
        if watched in (self,getattr(self,'web',None)) and event.type()==QEvent.Type.Enter and getattr(self,'page_loaded',False):
            if not self.settings.get('avatar_enabled',True) and self.settings.get('auto_fade',True):
                position=event.globalPosition().toPoint() if hasattr(event,'globalPosition') else None
                local=self.mapFromGlobal(position) if position is not None else QPoint(-1,-1)
                if local.x()>=self.width()-4:self.web.page().runJavaScript('showPanel()')
            elif self.settings.get('avatar_hidden',False):self.web.page().runJavaScript('showPanel()')
        if watched is getattr(self, 'web', None) and event.type() == QEvent.Type.Resize:
            overlay = getattr(self, 'dictionary_overlay', None)
            if overlay:
                self.position_dictionary_overlay()
        return super().eventFilter(watched, event)

    def close_dictionary_manager(self):
        if getattr(self, 'dictionary_overlay', None):
            self.dictionary_manager_open = False
            self.dictionary_overlay.hide()
            self.web.show()
            if self.query:self.lookup_worker.submit(self.query)
        self.web.page().runJavaScript("document.querySelector('.panel').classList.remove('dictionary-manager-open'); showPanel(); animatePaneContent()")

    def update_manager_background_color(self):
        if not getattr(self,'manager_background',None):return
        color=QColor(self.settings['panel_color'])
        self.manager_background.tint=color
        self.manager_background.darkness=self.settings['panel_darkness']
        self.manager_background.mirror_x=self.settings.get('background_mirror_x',False)
        self.manager_background.mirror_y=self.settings.get('background_mirror_y',False)
        self.manager_background.image_blur=self.settings.get('dictionary_image_blur',0)
        self.manager_background.image_opacity=self.settings.get('dictionary_image_opacity',100)
        self.manager_background.corner_radius=self.settings.get('dictionary_corner_radius',23)
        self.manager_background.corner_mode=self.settings.get('dictionary_corner_mode','all')
        self.manager_background.update()
        css=re.sub(r'QWidget#dictionaryOverlay\s*\{\s*background-color:[^}]*\}', '',self.dictionary_overlay.styleSheet())
        alpha=round(self.settings['panel_darkness']*2.55)
        self.dictionary_overlay.setStyleSheet(css+f'\nQWidget#dictionaryOverlay {{ background-color: rgba({color.red()},{color.green()},{color.blue()},{alpha}); border-radius: 23px; }}')

    def dictionary_payload(self):
        dictionaries=metadata_sources(self.db)
        states={did:(bool(enabled),count) for did,enabled,count in self.db.execute('SELECT id,enabled,count FROM dictionaries')}
        for row in dictionaries:row.update(enabled=states[row['id']][0],count=states[row['id']][1])
        return json.dumps(dictionaries,ensure_ascii=False)

    def refresh_dictionary_settings(self,*_):
        if self.page_loaded:
            self.web.page().runJavaScript('updateDictionarySettings('+json.dumps(self.popup_config.values)+','+self.dictionary_payload()+','+json.dumps(self.manager.statusBar().currentMessage())+')')

    def open_manager(self):
        self.hover_worker.cancel();self.lookup_worker.cancel()
        if self.manager is None:
            self.manager=DictionaryManager()
        if not getattr(self,'manager_web_connected',False):
            self.manager.statusBar().messageChanged.connect(self.refresh_dictionary_settings)
            self.manager_web_connected=True
        if getattr(self,'dictionary_overlay',None):self.close_dictionary_manager()
        self.web.page().runJavaScript('showDictionarySettings('+json.dumps(self.popup_config.values)+','+self.dictionary_payload()+')')

    def dictionary_action(self,action,data):
        if action=='add':
            paths,_=QFileDialog.getOpenFileNames(self,'Add dictionaries','','ZIP archives (*.zip)')
            self.manager.import_paths([Path(path) for path in paths]);return
        if self.manager.import_thread is not None and self.manager.import_thread.isRunning():return
        if action=='toggle':
            with self.db:self.db.execute('UPDATE dictionaries SET enabled=? WHERE id=?',(int(bool(data['enabled'])),int(data['id'])))
        elif action=='all':
            with self.db:self.db.execute('UPDATE dictionaries SET enabled=? WHERE has_frequency=0 AND has_pitch=0 AND has_kanji=0 AND has_kanji_frequency=0',(int(bool(data)),))
        elif action=='order':
            with self.db:self.db.executemany('UPDATE dictionaries SET sort_order=? WHERE id=?',[(i,int(did)) for i,did in enumerate(data)])
        elif action=='remove':
            row=self.db.execute('SELECT title FROM dictionaries WHERE id=?',(int(data),)).fetchone()
            if not row:return
            if QMessageBox.question(self,'Remove dictionary','Remove '+row[0]+'?\nThe ZIP file will be kept.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            with self.db:
                for table in ('entries','term_metadata','kanji_entries','kanji_metadata','dictionary_tags','dictionaries'):
                    self.db.execute('DELETE FROM '+table+' WHERE '+('id' if table=='dictionaries' else 'dictionary_id')+'=?',(int(data),))
        self.manager.refresh_dictionaries()
        self.refresh_dictionary_settings()
        if self.query:self.lookup_worker.submit(self.query)
        if self.secondary_query and self.settings['lookup_split']:self.secondary_worker.submit(self.secondary_query)
        self.refresh_extra_lookups()

    def open_native_manager(self):
        self.hover_worker.cancel()
        self.lookup_worker.cancel()
        self.cancel_additional_lookups()
        self.web.page().runJavaScript('clearTimeout(timer); closeSettings(); showPanel()')
        if self.manager is None:
            self.manager = DictionaryManager()
        if not getattr(self,'dictionary_overlay',None):
            # Keep the existing import worker and database owner alive without showing its window.
            self.dictionary_overlay = QWidget(self)
            self.dictionary_overlay.installEventFilter(self)
            self.dictionary_overlay.setObjectName('dictionaryOverlay')
            self.dictionary_opacity = QGraphicsOpacityEffect(self.dictionary_overlay)
            self.dictionary_opacity.setOpacity(1.0)
            self.dictionary_overlay.setGraphicsEffect(self.dictionary_opacity)
            self.dictionary_fade = QPropertyAnimation(self.dictionary_opacity, b'opacity', self)
            self.dictionary_fade.finished.connect(self.finish_dictionary_fade)

            self.dictionary_overlay.setAutoFillBackground(False)
            self.dictionary_overlay.setStyleSheet("""
                QWidget#dictionaryOverlay { background: transparent; color: #eee; }
                QWidget { background: transparent; color: #eee; font-size: 13px; }
                QListWidget { background: rgba(13,18,20,170); border: 1px solid rgba(255,255,255,28); border-radius: 14px; padding: 5px; outline: none; }
                QListWidget::item { border-radius: 8px; }
                QListWidget::item:selected { background: rgba(102,160,193,60); }
                QListWidget::item:hover { background: rgba(255,255,255,14); }
                QListWidget::indicator { width: 17px; height: 17px; border: 1px solid #627781; border-radius: 4px; background: #172126; }
                QListWidget::indicator:checked { background: #457d98; border-color: #70b5d4; image: url("CHECK_ICON"); }
                QLabel#dictionaryHint, QLabel#dictionaryStatus { color: #a4b3bd; font-size: 12px; }
                QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
                QScrollBar::handle:vertical { background: #60747e; min-height: 25px; border-radius: 3px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
                QMenu { background: #192127; padding: 5px; border: 1px solid #49535b; border-radius: 8px; }
                QMenu::item { padding: 7px 15px; }
                QMenu::item:selected { background: #34557b; }
                QPushButton { background: #242424; border: 1px solid #444; border-radius: 7px; padding: 8px; }
                QPushButton:hover { background: #333; }
            """.replace('CHECK_ICON',(ROOT/'assets/checkmark.svg').as_posix()))
            self.manager_background = PaneBackground(self.dictionary_overlay)
            self.manager_background.darkness = self.settings['panel_darkness']
            self.manager_background.tint = QColor(self.settings['panel_color'])
            self.manager_background.set_image(self.settings['background_image'])
            self.manager_background.lower()
            layout = QVBoxLayout(self.dictionary_overlay)
            layout.setContentsMargins(18, 18, 18, 18)
            back = QPushButton('← Back')
            back.setMaximumWidth(115)
            back.clicked.connect(self.close_dictionary_manager)
            header=QHBoxLayout();header.addWidget(back);header.addStretch();title=QLabel('Dictionaries');title.setStyleSheet('font-size: 20px; font-weight: 600;');header.addWidget(title);layout.addLayout(header)

            tab = self.manager.tabs.widget(1)
            self.manager.tabs.removeTab(1)
            tab.setParent(self.dictionary_overlay)
            layout.addWidget(tab, 1)
            tab.show()
            # refresh_dictionaries updates this tab label, even while embedded.
            self.manager.tabs.insertTab(1, QWidget(), 'Dictionaries')
        self.manager_background.set_image(self.settings['background_image'])
        self.update_manager_background_color()
        self.position_dictionary_overlay()
        self.web.page().runJavaScript("document.querySelector('.panel').classList.add('dictionary-manager-open')")
        self.dictionary_manager_open = True
        self.panel_visible = True
        self.dictionary_fade.stop()
        self.dictionary_opacity.setOpacity(1.0)
        self.web.page().runJavaScript("matchMedia('(prefers-reduced-motion: reduce)').matches", self.animate_dictionary_page)
        self.dictionary_overlay.show()
        self.dictionary_overlay.raise_()
        self.update_resize_edges()
        self.restore_splitter_ratio()
        QTimer.singleShot(0, self.position_dictionary_overlay)

    def animate_dictionary_page(self, reduced_motion):
        if reduced_motion or not self.dictionary_manager_open or not self.panel_visible:
            return
        self.dictionary_fade.stop()
        self.dictionary_fade.setDuration(90)
        self.dictionary_fade.setStartValue(0.55)
        self.dictionary_fade.setEndValue(1.0)
        self.dictionary_fade.start()

    def closeEvent(self, event):
        if self.quitting:
            super().closeEvent(event)
        else:
            self.save_window_state()
            self.hide()
            event.ignore()


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    app = QApplication(sys.argv)
    app.setApplicationName('Ukijiten')
    app.setDesktopFileName('ukijiten')
    app.setQuitOnLastWindowClosed(False)
    prompt = '--popup' in args
    if send_to_instance('', prompt=prompt):
        return 0
    window = FloatingDictionary('')
    window.lookup_prompt_requested = prompt
    window.show()
    if not window.restore_window_state():
        screen = app.primaryScreen().availableGeometry()
        window.move(screen.right() - window.width() - 55,
                    screen.center().y() - window.height() // 2)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
