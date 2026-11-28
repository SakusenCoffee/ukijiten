"""Avatar and background painting, animation, and pointer handling."""
from PySide6.QtCore import Property, QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImageReader, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget
from image_editor import avatar_rect
from image_effects import blur_pixmap, corner_path


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


