"""Read statistics entries from ttsu backup/statistics ZIPs without extracting books."""
import json
from pathlib import PurePosixPath
import zipfile


def ttsu_zip_records(path):
    rows=[]
    with zipfile.ZipFile(path) as archive:
        entries=[item for item in archive.infolist() if PurePosixPath(item.filename).name.startswith('statistics_') and item.filename.endswith('.json')]
        if not entries:raise ValueError('This ZIP has no ttsu statistics. Export with Statistics selected.')
        if sum(item.file_size for item in entries)>64*1024*1024:raise ValueError('Statistics export exceeds the import limit.')
        for entry in entries:
            records=json.loads(archive.read(entry))
            if not isinstance(records,list):raise ValueError('Invalid ttsu statistics export.')
            rows.extend(records)
    if not all(isinstance(row,dict) and 'dateKey' in row and 'readingTime' in row for row in rows):
        raise ValueError('Invalid ttsu statistics records.')
    return rows
