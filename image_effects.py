"""Image-only blur and shared, selectively rounded pane clipping."""
from PIL import Image,ImageFilter
from PySide6.QtCore import QRectF,Qt
from PySide6.QtGui import QImage,QPainterPath,QPixmap


def blur_pixmap(pixmap,radius):
    if not radius or pixmap.isNull():return pixmap
    source=pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    image=Image.frombytes('RGBA',(source.width(),source.height()),bytes(source.bits()))
    # Blur premultiplied color to avoid dark fringes around transparent artwork.
    image=image.convert('RGBa').filter(ImageFilter.GaussianBlur(radius)).convert('RGBA')
    result=QImage(image.tobytes(),image.width,image.height,QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(result)


def corner_path(rect,radius,mode='all'):
    bounds=QRectF(rect);path=QPainterPath();path.setFillRule(Qt.FillRule.WindingFill)
    radius=max(0,min(radius,bounds.width()/2,bounds.height()/2))
    if not radius:path.addRect(bounds);return path
    path.addRoundedRect(bounds,radius,radius)
    if mode=='top':path.addRect(QRectF(bounds.left(),bounds.center().y(),bounds.width(),bounds.height()/2))
    elif mode=='bottom':path.addRect(QRectF(bounds.left(),bounds.top(),bounds.width(),bounds.height()/2))
    return path
