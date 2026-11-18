"""V2.1 R01 prototype: read-only inventory and source-year selection.
Not a replacement for the V2.0 sync database. No media writes.
"""
from pathlib import Path
import os, hashlib, re, sqlite3, argparse, stat
from dataclasses import dataclass
from datetime import date
MEDIA = set('.jpg .jpeg .png .heic .heif .webp .gif .bmp .tif .tiff .dng .raw .cr2 .cr3 .nef .arw .raf .rw2 .mov .mp4 .m4v .avi .mkv .mts .m2ts .3gp .wmv'.split())
EXCLUDED = {'.photo_manager','00_inbox','99_log','$recycle.bin','system volume information'}
@dataclass(frozen=True)
class Source:
    root: Path
    role: str = 'primary'

def linked(p):
    s=p.lstat()
    return p.is_symlink() or bool(getattr(s,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))

def source_year(rel):
    # Only a top-level year directory is a scope boundary, never EXIF or filename.
    parts=Path(rel).parts
    return int(parts[0]) if len(parts)>1 and re.fullmatch(r'(?:19|20)\d{2}',parts[0]) else None

def select_years(start=None,end=None,years=None):
    if years is not None:
        if start is not None or end is not None: raise ValueError('Choose range or explicit years, not both')
        out=frozenset(years)
        if not out: raise ValueError('Empty year selection')
    elif start is None and end is None: return None
    elif start is None or end is None or start>end: raise ValueError('Invalid range')
    else: out=frozenset(range(start,end+1))
    if any(type(y) is not int or not 1900<=y<=2099 for y in out): raise ValueError('Invalid year')
    return out

def selected(rel, years):
    return years is None or source_year(rel) in years

def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def scan(sources, db_path, progress=lambda n:None):
    roots=[]
    for s in sources:
        if s.role not in ('primary','backup','independent','import'): raise ValueError('Invalid role')
        p=Path(s.root).absolute()
        if not p.is_dir() or linked(p): raise ValueError(f'Invalid source: {p}')
        p=p.resolve()
        if any(p==q or p in q.parents or q in p.parents for q,_ in roots): raise ValueError('Overlapping roots')
        roots.append((p,s.role))
    if not roots: raise ValueError('No sources')
    db_path=Path(db_path).resolve()
    if any(db_path==p or p in db_path.parents for p,_ in roots): raise ValueError('Catalog must be outside media roots')
    if db_path.exists(): raise FileExistsError('Choose a new catalog path; existing catalog is not overwritten')
    # Exclusive create prevents accidental overwrite. Failed scans leave no catalog.
    with db_path.open('xb'): pass
    conn=None
    try:
        conn=sqlite3.connect(db_path)
        conn.executescript('CREATE TABLE sources(id INTEGER PRIMARY KEY, root TEXT UNIQUE, role TEXT); CREATE TABLE media(source_id INTEGER, rel TEXT, year INTEGER, sha TEXT, size INTEGER, mtime_ns INTEGER, PRIMARY KEY(source_id,rel)); CREATE INDEX hash_idx ON media(sha);')
        count=0
        def fail(e): raise e
        with conn:
            for root,role in roots:
                sid=conn.execute('INSERT INTO sources(root,role) VALUES(?,?)',(str(root),role)).lastrowid
                for folder,dirs,names in os.walk(root,onerror=fail,followlinks=False):
                    base=Path(folder)
                    dirs[:]=sorted(d for d in dirs if d.casefold() not in EXCLUDED and not linked(base/d))
                    for n in sorted(names):
                        p=base/n
                        if p.suffix.lower() not in MEDIA or linked(p) or not p.is_file(): continue
                        before=p.stat(); h=sha256(p); after=p.stat()
                        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise IOError(f'File changed: {p}')
                        rel=p.relative_to(root).as_posix()
                        conn.execute('INSERT INTO media VALUES(?,?,?,?,?,?)',(sid,rel,source_year(rel),h,after.st_size,after.st_mtime_ns));count+=1
                        if count%100==0: progress(count)
        progress(count); return count
    except BaseException:
        if conn: conn.close(); conn=None
        db_path.unlink(missing_ok=True); raise
    finally:
        if conn: conn.close()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',action='append',nargs=2,metavar=('ROLE','FOLDER'),required=True)
    ap.add_argument('--catalog',required=True)
    a=ap.parse_args(); print('Read-only scan:',scan([Source(Path(p),r) for r,p in a.source],a.catalog,lambda n:print(f'{n} files',flush=True)))
if __name__=='__main__': main()
