"""Regression: avatar rotation must update the faded window's crop immediately."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from floating_dictionary import AvatarPane, FloatingDictionary

APP = QApplication.instance() or QApplication([])


class Owner(QWidget):
    apply_panel_input_mask = FloatingDictionary.apply_panel_input_mask
    refresh_mask = FloatingDictionary.refresh_avatar_mask

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.settings = {'avatar_background_opacity': 0, 'split_orientation': 'horizontal',
                         'avatar_vertical_position': 'bottom', 'avatar_right': True}
        self.panel_visible = False
        self._panel_input_masked = False
        self.avatar = AvatarPane(self)
        self.avatar.setParent(self)
        self.avatar.setGeometry(30, 20, 300, 500)
        self.resize(400, 600)
        self.avatar.image_geometry_changed.connect(self.refresh_mask)
        self.show()
        QTest.qWait(80)


class AvatarMaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name, size in [('short.png', (600, 100)), ('tall.png', (100, 900)), ('wide.gif', (600, 100))]:
            Image.new('RGB', size, 'red').save(self.root / name)
        self.owner = Owner()
        self.owner.avatar.set_image(str(self.root / 'short.png'))
        self.owner.apply_panel_input_mask()
        self.old_mask = self.owner.windowHandle().mask()

    def tearDown(self):
        self.owner.close()
        self.owner.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def assert_mask_matches_image(self):
        avatar = self.owner.avatar
        rect = avatar.image_rect()
        rect.moveTopLeft(avatar.mapTo(self.owner, rect.topLeft()))
        self.assertEqual(self.owner.windowHandle().mask(), QRegion(rect))
        self.assertTrue(self.owner.mask().isEmpty(), 'Input region must not clip widget painting')

    def test_larger_image_updates_mask_before_next_event_loop(self):
        self.owner.avatar.set_image(str(self.root / 'tall.png'))
        self.assertNotEqual(self.owner.windowHandle().mask(), self.old_mask)
        self.assert_mask_matches_image()

    def test_colored_avatar_pane_rounds_selected_corners_and_clears_old_color(self):
        avatar=self.owner.avatar
        self.owner.panel_visible=True;self.owner.settings['auto_fade']=False
        self.owner.windowHandle().setMask(QRegion())
        self.owner.settings.update(avatar_background_color='#00ff00',avatar_background_opacity=100,
                                   avatar_corner_radius=0,avatar_corner_mode='all')
        def pixel(x,y):
            avatar.update();QTest.qWait(50)
            image=self.owner.backingStore().paintDevice().copy();scale=image.devicePixelRatio()
            return image.pixelColor(round((avatar.x()+x)*scale),round((avatar.y()+y)*scale))
        self.assertEqual(pixel(2,2).green(),255)
        self.owner.settings['avatar_corner_radius']=50
        self.assertEqual(pixel(2,2).alpha(),0)
        self.assertEqual(pixel(2,avatar.height()-3).alpha(),0)
        self.assertEqual(pixel(avatar.width()//2,2).green(),255)
        self.owner.settings['avatar_corner_mode']='top'
        self.assertEqual(pixel(2,2).alpha(),0)
        self.assertEqual(pixel(2,avatar.height()-3).alpha(),255)
        self.owner.settings['avatar_corner_mode']='bottom'
        self.assertEqual(pixel(2,2).alpha(),255)
        self.assertEqual(pixel(2,avatar.height()-3).alpha(),0)

    def test_smaller_image_shrinks_mask_immediately(self):
        self.owner.avatar.set_image(str(self.root / 'tall.png'))
        self.owner.apply_panel_input_mask()
        self.owner.avatar.set_image(str(self.root / 'short.png'))
        self.assertEqual(self.owner.windowHandle().mask(), self.old_mask)
        self.assert_mask_matches_image()

    def test_resize_of_avatar_refreshes_mask(self):
        self.owner.avatar.resize(250, 400)
        self.assert_mask_matches_image()

    def test_gif_replacement_refreshes_mask(self):
        self.owner.avatar.set_image(str(self.root / 'tall.png'))
        self.owner.apply_panel_input_mask()
        self.owner.avatar.set_image(str(self.root / 'wide.gif'))
        self.assertTrue(self.owner.avatar.rect().contains(self.owner.avatar.current_image_rect()))
        APP.processEvents()
        self.assert_mask_matches_image()

    def test_rotating_images_clears_old_pixels_in_backing_store(self):
        avatar = self.owner.avatar
        avatar.set_image(str(self.root / 'tall.png'))
        QTest.qWait(80)
        # This point is inside the tall image and outside the short replacement.
        pixel = avatar.mapTo(self.owner, avatar.image_rect().topLeft())
        pixel += avatar.image_rect().center() - avatar.image_rect().topLeft()
        image = self.owner.backingStore().paintDevice().copy()
        scale = image.devicePixelRatio()
        x, y = round(pixel.x() * scale), round(pixel.y() * scale)
        self.assertEqual(image.pixelColor(x, y).alpha(), 255)
        avatar.set_image(str(self.root / 'short.png'))
        QTest.qWait(80)
        image = self.owner.backingStore().paintDevice().copy()
        self.assertEqual(image.pixelColor(x, y).alpha(), 0,
                         'Old avatar pixels survived outside the replacement image')

    def test_crossfade_retains_both_bounds_then_releases_previous_image(self):
        avatar=self.owner.avatar
        self.owner.settings.update(avatar_crossfade=True, avatar_fade_ms=200, avatar_seconds=30)
        old=avatar.image_rect()
        avatar.set_image(str(self.root / 'tall.png'))
        self.assertFalse(avatar.previous_avatar.isNull())
        self.assertEqual(avatar.image_rect(), old.united(avatar.current_image_rect()))
        QTest.qWait(80)
        self.assertGreater(avatar.get_avatar_progress(),0)
        self.assertLess(avatar.get_avatar_progress(),1)
        # Replacing a mid-fade source keeps only its composited snapshot.
        avatar.set_image(str(self.root / 'short.png'))
        self.assertFalse(avatar.previous_avatar.isNull())
        QTest.qWait(260)
        self.assertTrue(avatar.previous_avatar.isNull())
        self.assertEqual(avatar.get_avatar_progress(),1)
        self.assert_mask_matches_image()
        image=self.owner.backingStore().paintDevice().copy()
        point=avatar.mapTo(self.owner,avatar.rect().center())
        scale=image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(point.x()*scale),round(point.y()*scale)).alpha(),0)

    def test_visible_dictionary_does_not_gain_mask(self):
        self.owner.panel_visible = True
        self.owner._panel_input_masked = False
        self.owner.windowHandle().setMask(QRegion())
        self.owner.avatar.set_image(str(self.root / 'tall.png'))
        self.assertTrue(self.owner.windowHandle().mask().isEmpty())

    def test_filled_avatar_clips_mask_to_pane_and_keeps_size(self):
        avatar=self.owner.avatar;geometry=avatar.geometry()
        self.owner.settings.update(avatar_fill_pane=True,split_orientation='vertical',avatar_top=True)
        avatar.set_image(str(self.root/'tall.png'))
        self.assertEqual(avatar.current_image_rect().top(),0)
        self.assertEqual(avatar.geometry(),geometry)
        self.assertEqual(avatar.image_rect(),avatar.rect())
        self.assert_mask_matches_image()
        self.owner.settings['avatar_top']=False
        avatar.scale_image()
        self.assertEqual(avatar.current_image_rect().bottom(),avatar.height()-1)
        self.assertEqual(avatar.image_rect(),avatar.rect())

    def test_clear_avatar_leaves_transparent_pane_without_changing_geometry(self):
        avatar=self.owner.avatar
        self.owner.panel_visible=True
        self.owner._panel_input_masked=False
        self.owner.windowHandle().setMask(QRegion())
        avatar.set_image(str(self.root/'tall.png'))
        QTest.qWait(80)
        geometry=avatar.geometry()
        point=avatar.mapTo(self.owner,avatar.image_rect().center())
        self.owner.settings.update(avatar_hidden=True,avatar_background_opacity=80)
        avatar.clear_image();QTest.qWait(80)
        self.assertEqual(avatar.geometry(),geometry)
        self.assertTrue(avatar.isVisible())
        self.assertTrue(avatar.pixmap().isNull())
        self.assertTrue(avatar.previous_avatar.isNull())
        image=self.owner.backingStore().paintDevice().copy();scale=image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(point.x()*scale),round(point.y()*scale)).alpha(),0)


if __name__ == '__main__':
    unittest.main()
