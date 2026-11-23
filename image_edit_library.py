"""Saved edits belong to source files, independently of folder selection."""
import json
import os
from pathlib import Path

from image_editor import export_edit,source_and_edit


class ImageEditLibrary:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.path=self.directory/'image-edits.json'
        try:self.records=json.loads(self.path.read_text())
        except (OSError,ValueError):self.records={}
        if not isinstance(self.records,dict):self.records={}
        for kind in ('avatar','background'):
            values=self.records.get(kind,{})
            self.records[kind]={key:value for key,value in values.items() if isinstance(value,dict)} if isinstance(values,dict) else {}

    @staticmethod
    def source(path):
        return str(Path(source_and_edit(path)[0]).expanduser().resolve())

    @staticmethod
    def stamp(path):
        stat=Path(path).stat()
        return [stat.st_mtime_ns,stat.st_size]

    def remember(self,source,kind,edit,rendered):
        source=str(Path(source).expanduser().resolve())
        record={'edit':edit,'rendered':str(Path(rendered).resolve()),'stamp':self.stamp(source)}
        records=dict(self.records)
        records[kind]=dict(records.get(kind,{}),**{source:record})
        self.directory.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        with open(temporary,'w',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
            json.dump(records,stream,ensure_ascii=False,indent=2)
        temporary.replace(self.path)
        self.records=records

    def adopt(self,path,kind):
        """Retain edits made before the source-file library was introduced."""
        if not path:return
        source,edit=source_and_edit(path)
        if edit and self.source(source) not in self.records.get(kind,{}):
            self.remember(source,kind,edit,path)

    def resolve(self,path,kind):
        if not path:return path
        source=self.source(path)
        record=self.records.get(kind,{}).get(source)
        if not record:return path
        try:
            if record.get('stamp')==self.stamp(source) and Path(record['rendered']).is_file():
                return record['rendered']
            rendered=export_edit(source,record['edit'],self.directory/'edited-images')
            self.remember(source,kind,record['edit'],rendered)
            return rendered
        except (OSError,ValueError,KeyError,TypeError):
            # A replaced source may no longer fit its saved crop. Keep cycling
            # and retain the edit so a restored original can use it again.
            return source
