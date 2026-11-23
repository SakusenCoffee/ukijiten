"""Alpha-preserving, non-destructive image edits for avatars and backgrounds."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

OPERATIONS={
    'left':Image.Transpose.ROTATE_90,'right':Image.Transpose.ROTATE_270,
    'horizontal':Image.Transpose.FLIP_LEFT_RIGHT,'vertical':Image.Transpose.FLIP_TOP_BOTTOM,
}


def source_and_edit(path):
    path=Path(path)
    try:
        saved=json.loads(path.with_suffix(path.suffix+'.json').read_text())
        original=Path(saved['source'])
        if original.is_file():return str(original),saved['edit']
    except (OSError,ValueError,KeyError,TypeError):pass
    return str(path),{}


def export_edit(source,edit,directory):
    """Render copies, preserving alpha and animation. Never overwrite the source."""
    operations=edit.get('operations',[]);crop=edit.get('crop');size=edit.get('size')
    if any(operation not in OPERATIONS for operation in operations):raise ValueError('Invalid image operation.')
    with Image.open(source) as original:
        if not operations and not crop and (not size or tuple(size)==original.size) and original.getexif().get(274,1)==1:
            return str(Path(source).resolve())
        frames=[];durations=[];count=getattr(original,'n_frames',1)
        for frame in ImageSequence.Iterator(original):
            image=ImageOps.exif_transpose(frame).convert('RGBA')
            for operation in operations:image=image.transpose(OPERATIONS[operation])
            if crop:
                x,y,width,height=map(int,crop)
                if x<0 or y<0 or width<1 or height<1 or x+width>image.width or y+height>image.height:raise ValueError('The crop is outside the image.')
                image=image.crop((x,y,x+width,y+height))
            if size:
                width,height=map(int,size)
                if width<1 or height<1 or width*height>64000000:raise ValueError('Choose a smaller output size.')
                if image.size!=(width,height):image=image.resize((width,height),Image.Resampling.LANCZOS)
            if image.width*image.height*count>128000000:raise ValueError('Choose a smaller output size for this animation.')
            frames.append(image);durations.append(max(10,frame.info.get('duration',100)))
        if not frames:raise ValueError('Could not read the image.')
        if not operations and not crop and frames[0].size==original.size:return str(Path(source).resolve())
        source_path=Path(source).resolve();stamp=source_path.stat()
        digest=hashlib.sha256(json.dumps([str(source_path),stamp.st_mtime_ns,stamp.st_size,edit],sort_keys=True).encode()).hexdigest()[:20]
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        suffix='.webp' if len(frames)>1 else '.png';target=directory/('image-'+digest+suffix)
        temporary=target.with_suffix(suffix+'.tmp')
        if len(frames)>1:frames[0].save(temporary,format='WEBP',save_all=True,append_images=frames[1:],duration=durations,loop=original.info.get('loop',0),lossless=True)
        else:frames[0].save(temporary,format='PNG')
        temporary.replace(target)
        target.with_suffix(suffix+'.json').write_text(json.dumps({'source':str(source_path),'edit':edit},indent=2))
        return str(target)


def avatar_rect(image_size,pane_size,settings):
    if image_size.isEmpty() or pane_size.isEmpty():return QRect()
    fill=settings.get('avatar_fill_pane',False)
    size=image_size.scaled(pane_size,Qt.AspectRatioMode.KeepAspectRatioByExpanding if fill else Qt.AspectRatioMode.KeepAspectRatio)
    stacked=settings.get('split_orientation')=='vertical'
    x=(pane_size.width()-size.width() if settings.get('avatar_right',False) else 0) if fill or stacked else (pane_size.width()-size.width())//2
    at_top=settings.get('avatar_top',False) if stacked else settings.get('avatar_vertical_position')=='top'
    y=0 if at_top else pane_size.height()-size.height()
    return QRect(x,y,size.width(),size.height())


class CropCanvas(QWidget):
    changed=Signal()

    def __init__(self,image,parent=None):
        super().__init__(parent);self.image=image;self.crop=QRectF(image.rect());self.crop_enabled=False
        self.origin=None;self.mode=None;self.setMinimumSize(280,220);self.setMouseTracking(True)

    def image_rect(self):
        size=self.image.size().scaled(self.size()-QSize(24,24),Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def view_rect(self):
        bounds=self.image_rect();scale=bounds.width()/self.image.width()
        return QRectF(bounds.left()+self.crop.left()*scale,bounds.top()+self.crop.top()*scale,self.crop.width()*scale,self.crop.height()*scale)

    def image_point(self,point):
        bounds=self.image_rect();scale=bounds.width()/self.image.width()
        return QPointF(max(0,min(self.image.width(),(point.x()-bounds.left())/scale)),max(0,min(self.image.height(),(point.y()-bounds.top())/scale)))

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#202629'))
        bounds=self.image_rect();painter.save();painter.setClipRect(bounds)
        for y in range(int(bounds.top()),int(bounds.bottom())+16,16):
            for x in range(int(bounds.left()),int(bounds.right())+16,16):painter.fillRect(x,y,16,16,QColor('#646b70') if ((x-int(bounds.left()))//16+(y-int(bounds.top()))//16)%2 else QColor('#454c50'))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);painter.drawImage(bounds,self.image);painter.restore()
        if self.crop_enabled:
            selected=self.view_rect();outside=QPainterPath();outside.addRect(bounds);inside=QPainterPath();inside.addRect(selected)
            painter.fillPath(outside.subtracted(inside),QColor(0,0,0,145));painter.setPen(QPen(QColor('#b3d8eb'),1));painter.drawRect(selected)
            for point in (selected.topLeft(),selected.topRight(),selected.bottomLeft(),selected.bottomRight()):painter.fillRect(QRectF(point.x()-4,point.y()-4,8,8),QColor('#e5f4fc'))

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.image_rect().contains(event.position()):return
        self.origin=self.image_point(event.position());self.before=QRectF(self.crop);self.mode='new'
        if self.crop_enabled:
            rect=self.view_rect()
            for corner,point in [('tl',rect.topLeft()),('tr',rect.topRight()),('bl',rect.bottomLeft()),('br',rect.bottomRight())]:
                if (point-event.position()).manhattanLength()<16:self.mode=corner;break
            else:
                if rect.contains(event.position()):self.mode='move'
        self.crop_enabled=True
        if self.mode=='new':self.crop=QRectF(self.origin,self.origin)
        self.changed.emit();self.update()

    def mouseMoveEvent(self,event):
        if self.origin is None:return
        point=self.image_point(event.position());bounds=QRectF(self.image.rect())
        if self.mode=='move':
            rect=self.before.translated(point-self.origin)
            rect.moveLeft(max(0,min(bounds.width()-rect.width(),rect.left())));rect.moveTop(max(0,min(bounds.height()-rect.height(),rect.top())))
        elif self.mode=='new':rect=QRectF(self.origin,point).normalized()
        else:
            opposite={'tl':self.before.bottomRight(),'tr':self.before.bottomLeft(),'bl':self.before.topRight(),'br':self.before.topLeft()}[self.mode]
            rect=QRectF(opposite,point).normalized()
        self.crop=rect.intersected(bounds);self.changed.emit();self.update()

    def mouseReleaseEvent(self,event):
        if self.origin is not None:
            if self.crop.width()<1 or self.crop.height()<1:self.crop=self.before
            self.origin=None;self.mode=None;self.changed.emit();self.update()

    def transform_image(self,operation):
        width,height=self.image.width(),self.image.height();rect=self.crop
        if operation=='right':
            self.image=self.image.transformed(QTransform().rotate(90));self.crop=QRectF(height-rect.bottom(),rect.left(),rect.height(),rect.width())
        elif operation=='left':
            self.image=self.image.transformed(QTransform().rotate(-90));self.crop=QRectF(rect.top(),width-rect.right(),rect.height(),rect.width())
        elif operation=='horizontal':self.image=self.image.mirrored(True,False);self.crop=QRectF(width-rect.right(),rect.top(),rect.width(),rect.height())
        else:self.image=self.image.mirrored(False,True);self.crop=QRectF(rect.left(),height-rect.bottom(),rect.width(),rect.height())
        self.changed.emit();self.update()


class ImageEditDialog(QDialog):
    def __init__(self,path,settings,kind='avatar',parent=None):
        super().__init__(parent);self.kind=kind;self.source,edit=source_and_edit(path)
        reader=QImageReader(self.source);reader.setAutoTransform(True);self.original=reader.read()
        if self.original.isNull():raise ValueError('Could not read this image.')
        self.setWindowTitle('Edit avatar' if kind=='avatar' else 'Edit dictionary background');self.resize(760,650)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        color=QColor(settings.get('panel_color','#183b47'));light=color.lightnessF()>.65
        text='#152126' if light else '#eef3f5'
        def tint(amount):return QColor(*(round(channel*(1-amount)+(0 if light else 255)*amount) for channel in (color.red(),color.green(),color.blue())))
        button=tint(.14)
        self.setStyleSheet(f'QDialog {{ background:{color.name()};color:{text}; }} QLabel,QCheckBox {{ color:{text}; }} QPushButton,QSpinBox {{ background:{button.name()};color:{text};border:1px solid {tint(.3).name()};border-radius:6px;padding:6px 10px; }} QPushButton:hover {{ background:{tint(.22).name()}; }}')
        layout=QVBoxLayout(self);layout.setSpacing(12);layout.setContentsMargins(18,18,18,18)
        tools=QHBoxLayout();self.operations=[]
        self.canvas=CropCanvas(self.original,self)
        for title,operation in [('Rotate left','left'),('Rotate right','right'),('Mirror left/right','horizontal'),('Mirror top/bottom','vertical')]:
            button_widget=QPushButton(title);button_widget.setObjectName('image-'+operation);button_widget.clicked.connect(lambda checked=False,op=operation:self.transform_image(op));tools.addWidget(button_widget)
        reset=QPushButton('Reset');reset.clicked.connect(self.reset);tools.addWidget(reset);layout.addLayout(tools)
        self.crop_check=QCheckBox('Crop image');self.crop_check.setToolTip('Drag on the image to select a crop. Drag inside it to move it; drag a corner to resize it.')
        self.crop_check.toggled.connect(self.toggle_crop);layout.addWidget(self.crop_check)
        layout.addWidget(self.canvas,1);self.canvas.changed.connect(self.crop_changed)
        size_row=QHBoxLayout();size_row.addWidget(QLabel('Output size'))
        self.output_width=QSpinBox();self.output_height=QSpinBox()
        for control in (self.output_width,self.output_height):control.setRange(1,16384)
        size_row.addWidget(self.output_width);size_row.addWidget(QLabel('×'));size_row.addWidget(self.output_height)
        self.lock_ratio=QCheckBox('Keep proportions');self.lock_ratio.setChecked(True);size_row.addWidget(self.lock_ratio);size_row.addStretch();layout.addLayout(size_row)
        self.resizing=False;self.output_width.valueChanged.connect(lambda value:self.resize_output('width',value));self.output_height.valueChanged.connect(lambda value:self.resize_output('height',value))
        self.fill=QCheckBox('Fill avatar pane');self.fill.setToolTip('Keep proportions and clip overflow at the pane edge. The pane keeps its saved size.')
        self.fill.setChecked(settings.get('avatar_fill_pane',False));self.fill.setVisible(kind=='avatar');layout.addWidget(self.fill)
        self.auto_sides=QCheckBox('Auto-mirror when swapping sides (⇄)');self.auto_sides.setChecked(settings.get(kind+'_auto_mirror_sides',False));layout.addWidget(self.auto_sides)
        self.auto_vertical=QCheckBox('Auto-mirror when moving top/bottom (⇅)');self.auto_vertical.setChecked(settings.get(kind+'_auto_mirror_vertical',False));layout.addWidget(self.auto_vertical)
        self.notice=QLabel('Drag on the image to crop. Original files stay unchanged.');self.notice.setWordWrap(True);layout.addWidget(self.notice)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        for operation in edit.get('operations',[]):self.transform_image(operation)
        if edit.get('crop'):
            self.canvas.crop=QRectF(*edit['crop']);self.canvas.crop_enabled=True;self.crop_check.setChecked(True)
        self.crop_changed()
        if settings.get(kind+'_mirror_x',False):self.transform_image('horizontal')
        if settings.get(kind+'_mirror_y',False):self.transform_image('vertical')
        if edit.get('size'):
            self.resizing=True;self.output_width.setValue(edit['size'][0]);self.output_height.setValue(edit['size'][1]);self.resizing=False

    def crop_changed(self):
        if self.crop_check.isChecked()!=self.canvas.crop_enabled:
            self.crop_check.blockSignals(True);self.crop_check.setChecked(self.canvas.crop_enabled);self.crop_check.blockSignals(False)
        rect=self.crop_rect();self.resizing=True;self.output_width.setValue(rect.width());self.output_height.setValue(rect.height());self.resizing=False

    def crop_rect(self):
        rect=self.canvas.crop.toAlignedRect().intersected(self.canvas.image.rect()) if self.canvas.crop_enabled else self.canvas.image.rect()
        return rect if not rect.isEmpty() else self.canvas.image.rect()

    def toggle_crop(self,enabled):
        self.canvas.crop_enabled=enabled;self.canvas.update();self.crop_changed()

    def resize_output(self,axis,value):
        if self.resizing or not self.lock_ratio.isChecked():return
        rect=self.crop_rect();self.resizing=True
        if axis=='width':self.output_height.setValue(max(1,round(value*rect.height()/rect.width())))
        else:self.output_width.setValue(max(1,round(value*rect.width()/rect.height())))
        self.resizing=False

    def transform_image(self,operation):
        if len(self.operations)>=64:return
        self.operations.append(operation);self.canvas.transform_image(operation)

    def reset(self):
        self.operations=[];self.canvas.image=self.original;self.canvas.crop=QRectF(self.original.rect());self.canvas.crop_enabled=False;self.crop_check.setChecked(False);self.crop_changed();self.canvas.update()

    def specification(self):
        crop=self.crop_rect()
        return {'operations':list(self.operations),'crop':[crop.x(),crop.y(),crop.width(),crop.height()] if self.canvas.crop_enabled else None,'size':[self.output_width.value(),self.output_height.value()]}

    def options(self):
        values={self.kind+'_auto_mirror_sides':self.auto_sides.isChecked(),self.kind+'_auto_mirror_vertical':self.auto_vertical.isChecked()}
        if self.kind=='avatar':values['avatar_fill_pane']=self.fill.isChecked()
        return values
