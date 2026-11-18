"""Read-only display year; never used as a destructive scope boundary."""
from pathlib import Path
from datetime import date
import re
from PIL import Image
PAT=re.compile(r'(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)')
def dated(text):
    for m in PAT.finditer(text):
        try: return date(*map(int,m.groups())).year
        except ValueError: continue
    return None

def detect_year(root,rel):
    p=Path(root)/rel
    folders=[Path(root).name,*Path(rel).parts[:-1]]
    folder=next((int(x) for x in folders if re.fullmatch(r'(?:19|20)\d{2}',x)),None)
    if folder is None: folder=next((y for x in reversed(folders) if (y:=dated(x)) is not None),None)
    filename=dated(p.stem)
    exif=None
    try:
        with Image.open(p) as im:
            e=im.getexif(); raw=e.get_ifd(34665).get(36867) or e.get(36867)
            if isinstance(raw,str): exif=dated(raw[:10].replace(':','-'))
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError,SyntaxError): pass
    evidence=[(folder,'資料夾'),(filename,'檔名'),(exif,'EXIF')]
    year,source=next(((y,s) for y,s in evidence if y is not None),(None,'未知'))
    conflict=len({y for y,s in evidence if y is not None})>1
    return year,source+('（年份衝突）' if conflict else '')


def capture_date(p):
    """Only embedded original capture date; no invented day from folder or mtime."""
    try:
        with Image.open(p) as im:
            e=im.getexif();raw=e.get_ifd(34665).get(36867) or e.get(36867)
            if isinstance(raw,str):
                from datetime import datetime
                return datetime.strptime(raw[:10],'%Y:%m:%d').date().isoformat()
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError,SyntaxError):pass
    return ''
