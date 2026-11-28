import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from image_editor import ImageEditDialog,avatar_rect,export_edit,source_and_edit
from image_effects import blur_pixmap,corner_path

APP=QApplication.instance() or QApplication([])


class ImageEditorTests(unittest.TestCase):
    def test_image_blur_keeps_alpha_and_unmodified_source(self):
        source=QPixmap(str(self.path));original=source.toImage()
        blurred=blur_pixmap(source,6).toImage()
        self.assertEqual(source.toImage(),original)
        self.assertEqual(blurred.size(),original.size())
        self.assertGreater(blurred.pixelColor(49,40).alpha(),80)
        self.assertLess(blurred.pixelColor(49,40).alpha(),160)

    def test_corner_radius_zero_and_selected_edges(self):
        rect=QRectF(0,0,100,100);top=QPointF(.1,.1);bottom=QPointF(.1,99.9)
        self.assertTrue(corner_path(rect,0).contains(top))
        self.assertTrue(corner_path(rect,0).contains(bottom))
        self.assertFalse(corner_path(rect,20,'top').contains(top))
        self.assertTrue(corner_path(rect,20,'top').contains(bottom))
        self.assertTrue(corner_path(rect,20,'bottom').contains(top))
        self.assertFalse(corner_path(rect,20,'bottom').contains(bottom))
        right=QPointF(99.9,.1)
        self.assertFalse(corner_path(rect,20,'left').contains(top))
        self.assertTrue(corner_path(rect,20,'left').contains(right))
        self.assertTrue(corner_path(rect,20,'right').contains(top))
        self.assertFalse(corner_path(rect,20,'right').contains(right))
        self.assertFalse(corner_path(rect,20,'sides').contains(top))
        self.assertFalse(corner_path(rect,20,'sides').contains(right))
        self.assertTrue(corner_path(rect,20,'none').contains(top))
        self.assertTrue(corner_path(rect,20,'none').contains(right))

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.path=self.root/'source.png'
        self.image=Image.new('RGBA',(100,80),(220,30,20,80));self.image.paste((20,30,220,160),(50,0,100,80));self.image.save(self.path)

    def test_crop_rotate_mirror_resize_preserves_alpha_and_original(self):
        before=self.path.read_bytes()
        edit={'operations':['right','horizontal'],'crop':[10,20,60,70],'size':[120,140]}
        output=export_edit(self.path,edit,self.root/'edits')
        expected=self.image.transpose(Image.Transpose.ROTATE_270).transpose(Image.Transpose.FLIP_LEFT_RIGHT).crop((10,20,70,90)).resize((120,140),Image.Resampling.LANCZOS)
        with Image.open(output) as actual:self.assertEqual(actual.tobytes(),expected.tobytes());self.assertEqual(actual.mode,'RGBA')
        self.assertEqual(self.path.read_bytes(),before)
        source,saved=source_and_edit(output);self.assertEqual(source,str(self.path.resolve()));self.assertEqual(saved,edit)

    def test_unchanged_image_is_not_reencoded(self):
        self.assertEqual(export_edit(self.path,{'operations':[],'crop':None,'size':[100,80]},self.root/'edits'),str(self.path.resolve()))

    def test_animation_and_transparency_survive_editing(self):
        path=self.root/'animated.gif';frames=[]
        for color in ('red','blue'):
            frame=Image.new('RGBA',(40,30),(0,0,0,0));frame.paste(color,(5,5,15,20));frames.append(frame)
        frames[0].save(path,save_all=True,append_images=frames[1:],duration=[90,150],loop=0,disposal=2)
        output=export_edit(path,{'operations':['horizontal'],'crop':None,'size':[40,30]},self.root/'edits')
        self.assertTrue(QImageReader(output).supportsAnimation())
        with Image.open(output) as result:
            self.assertEqual(result.n_frames,2)
            self.assertEqual(result.convert('RGBA').getpixel((0,0))[3],0)
            self.assertEqual(result.convert('RGBA').getpixel((30,10)),(255,0,0,255))
            result.seek(1);self.assertEqual(result.convert('RGBA').getpixel((30,10)),(0,0,255,255))

    def test_fill_anchors_top_bottom_and_reveals_with_more_room(self):
        image=QSize(400,1200)
        top={'avatar_fill_pane':True,'split_orientation':'vertical','avatar_top':True}
        bottom={**top,'avatar_top':False}
        first=avatar_rect(image,QSize(400,200),top);larger=avatar_rect(image,QSize(400,500),top)
        self.assertEqual(first.top(),0);self.assertEqual(larger.top(),0)
        self.assertEqual(first.size(),larger.size());self.assertEqual(first.height(),1200)
        self.assertEqual(avatar_rect(image,QSize(400,200),bottom).bottom(),199)
        self.assertEqual(avatar_rect(image,QSize(400,500),bottom).bottom(),499)
        left={'avatar_fill_pane':True,'split_orientation':'horizontal','avatar_right':False}
        right={**left,'avatar_right':True}
        self.assertEqual(avatar_rect(QSize(1200,400),QSize(200,400),left).left(),0)
        self.assertEqual(avatar_rect(QSize(1200,400),QSize(200,400),right).right(),199)

    def test_dialog_crop_resize_and_options(self):
        dialog=ImageEditDialog(str(self.path),{'panel_color':'#204653'},'avatar');dialog.show();QTest.qWait(40)
        try:
            bounds=dialog.canvas.image_rect()
            start=QPoint(round(bounds.left()+bounds.width()*.15),round(bounds.top()+bounds.height()*.15))
            end=QPoint(round(bounds.left()+bounds.width()*.8),round(bounds.top()+bounds.height()*.8))
            QTest.mousePress(dialog.canvas,Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(dialog.canvas,end);QTest.mouseRelease(dialog.canvas,Qt.MouseButton.LeftButton,pos=end)
            self.assertTrue(dialog.crop_check.isChecked());self.assertLess(dialog.crop_rect().width(),100)
            dialog.transform_image('right');self.assertEqual(dialog.canvas.image.size(),QSize(80,100))
            dialog.output_width.setValue(200)
            self.assertAlmostEqual(dialog.output_width.value()/dialog.output_height.value(),dialog.crop_rect().width()/dialog.crop_rect().height(),delta=.02)
            dialog.fill.setChecked(True);dialog.auto_sides.setChecked(True)
            self.assertTrue(dialog.options()['avatar_fill_pane']);self.assertTrue(dialog.options()['avatar_auto_mirror_sides'])
            dialog.grab().save('/tmp/ukijiten-avatar-editor.png')
            dialog.reject();self.assertEqual(self.path.read_bytes(),(self.root/'source.png').read_bytes())
        finally:dialog.close();dialog.deleteLater();APP.processEvents()
        background=ImageEditDialog(str(self.path),{'panel_color':'#204653'},'background')
        self.assertIn('background_auto_mirror_sides',background.options());self.assertNotIn('avatar_auto_mirror_sides',background.options());background.deleteLater()


if __name__=='__main__':unittest.main()
