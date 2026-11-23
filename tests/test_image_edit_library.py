import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from image_edit_library import ImageEditLibrary
from image_editor import export_edit,source_and_edit


class ImageEditLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.png'
        Image.new('RGBA',(80,120),(20,90,180,80)).save(self.source)
        self.library=ImageEditLibrary(self.root/'config')
        self.edit={'operations':['horizontal'],'crop':[10,20,40,50],'size':[80,100]}

    def remember(self,kind='avatar'):
        rendered=export_edit(self.source,self.edit,self.library.directory/'edited-images')
        self.library.remember(self.source,kind,self.edit,rendered)
        return rendered

    def test_source_selection_and_restart_use_saved_crop_without_rendering_again(self):
        rendered=self.remember();original=self.source.read_bytes()
        restored=ImageEditLibrary(self.library.directory)
        with patch('image_edit_library.export_edit',side_effect=AssertionError('Cached image was rerendered')):
            self.assertEqual(restored.resolve(str(self.source),'avatar'),rendered)
            self.assertEqual(restored.resolve(rendered,'avatar'),rendered)
        self.assertEqual(source_and_edit(rendered)[1],self.edit)
        self.assertEqual(self.source.read_bytes(),original)
        with Image.open(rendered) as image:
            self.assertEqual(image.size,(80,100));self.assertEqual(image.getpixel((0,0))[3],80)

    def test_missing_cache_rebuilds_from_saved_details(self):
        rendered=self.remember();Path(rendered).unlink()
        result=ImageEditLibrary(self.library.directory).resolve(str(self.source),'avatar')
        self.assertTrue(Path(result).is_file())
        with Image.open(result) as image:self.assertEqual(image.size,(80,100))

    def test_avatar_and_background_edits_are_independent_and_reset_is_remembered(self):
        rendered=self.remember()
        self.assertEqual(self.library.resolve(str(self.source),'background'),str(self.source))
        reset={'operations':[],'crop':None,'size':[80,120]}
        self.library.remember(self.source,'avatar',reset,self.source)
        self.assertEqual(ImageEditLibrary(self.library.directory).resolve(rendered,'avatar'),str(self.source))

    def test_replaced_source_with_invalid_crop_keeps_cycling_and_retains_details(self):
        self.remember();Image.new('RGBA',(5,5),'red').save(self.source)
        self.assertEqual(self.library.resolve(str(self.source),'avatar'),str(self.source))
        saved=json.loads(self.library.path.read_text())
        self.assertEqual(saved['avatar'][str(self.source)]['edit'],self.edit)

    def test_adopts_existing_edited_image_sidecar(self):
        rendered=export_edit(self.source,self.edit,self.root/'legacy')
        self.library.adopt(rendered,'avatar')
        self.assertEqual(ImageEditLibrary(self.library.directory).resolve(str(self.source),'avatar'),rendered)


if __name__=='__main__':unittest.main()
