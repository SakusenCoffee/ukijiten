import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from popup_settings import PopupSettings

class MigrationTests(unittest.TestCase):
 def test_collapsed_dictionaries_use_saved_paths(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'popup.json';settings=PopupSettings(path,[])
   self.assertEqual(settings.values['main_collapsed_paths'],[])
   settings.update('main_collapsed_paths',['one.zip','two.zip','one.zip',None])
   restored=PopupSettings(path,[(42,'Same title','one.zip',1)])
   self.assertEqual(restored.values['main_collapsed_paths'],['one.zip','two.zip'])
   restored.update('main_collapsed_paths',[])
   self.assertEqual(PopupSettings(path,[]).values['main_collapsed_paths'],[])
 def test_expansion_states_persist_independently(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'popup.json';settings=PopupSettings(path,[])
   settings.update('section_states',{'main-entry-text-size':True,'metadata-main_frequency':False,'popup-scanning':True})
   restored=PopupSettings(path,[])
   self.assertEqual(restored.values['section_states'],{'main-entry-text-size':True,'metadata-main_frequency':False,'popup-scanning':True})
 def test_popup_color_validation_and_persistence(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'popup.json';settings=PopupSettings(path,[])
   self.assertEqual(settings.values['background_color'],'#141414')
   settings.update('background_color','#d9efd8')
   settings.update('background_color','invalid')
   self.assertEqual(PopupSettings(path,[]).values['background_color'],'#d9efd8')
 def test_main_metadata_migrates_then_saves_independently(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'popup.json';path.write_text(json.dumps({'frequency_paths':['freq.zip'],'pitch_paths':['pitch.zip']}))
   settings=PopupSettings(path,[])
   self.assertEqual(settings.values['main_frequency_paths'],['freq.zip'])
   self.assertEqual(settings.values['main_pitch_paths'],['pitch.zip'])
   settings.update('main_frequency_paths',[]);settings.update('pitch_paths',[])
   restored=PopupSettings(path,[])
   self.assertEqual(restored.values['frequency_paths'],['freq.zip'])
   self.assertEqual(restored.values['main_frequency_paths'],[])
   self.assertEqual(restored.values['pitch_paths'],[])
   self.assertEqual(restored.values['main_pitch_paths'],['pitch.zip'])
 def test_browser_choices_and_mouse_input_migrate_without_browser_runtime(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);old=root/'browser.json'
   old.write_text(json.dumps({'profileCurrent':0,'profiles':[{'options':{
    'general':{'enable':True,'popupWidth':420,'popupHeight':300},
    'scanning':{'delay':120,'length':16,'inputs':[{'include':'ctrl mouse2','types':{'mouse':True}}]},
    'dictionaries':[{'name':'Second','enabled':True},{'name':'First','enabled':False}]}}]}))
   dictionaries=[(1,'First','a.zip',1),(2,'Second','b.zip',0)]
   settings=PopupSettings(root/'popup.json',dictionaries,browser_options=old)
   self.assertEqual(settings.values['scan_hotkey'],['Control','Mouse2'])
   self.assertEqual(settings.values['dictionary_order'],['b.zip','a.zip'])
   self.assertEqual(settings.enabled_ids(dictionaries),[2])
   settings.save();old.unlink()
   self.assertEqual(PopupSettings(root/'popup.json',dictionaries).values,settings.values)
 def test_new_dictionary_is_appended_without_changing_saved_order(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'popup.json';path.write_text(json.dumps({'dictionary_order':['b.zip','a.zip'],'disabled_paths':[]}))
   settings=PopupSettings(path,[(1,'A','a.zip',1),(2,'B','b.zip',1),(3,'C','c.zip',0)])
   self.assertEqual(settings.values['dictionary_order'],['b.zip','a.zip','c.zip'])
   self.assertEqual(settings.enabled_ids([(1,'A','a.zip',1),(2,'B','b.zip',1),(3,'C','c.zip',0)]),[2,1,3])
if __name__=='__main__':unittest.main()
