"""Conservative copy-only workflow. Never deletes or overwrites media."""
from pathlib import Path
from dataclasses import dataclass
import os, tempfile, shutil, sqlite3, re, uuid
from contextlib import closing
from datetime import datetime, date
from library_catalog import MEDIA, EXCLUDED, linked, sha256
from date_year import capture_date, PAT

@dataclass(frozen=True)
class Entry:
    source: Path
    relative: str
    digest: str
    action: str
    size: int

def roots(a,b):
    a,b=Path(a).absolute(),Path(b).absolute()
    for p in (a,b):
        if not p.is_dir() or any(linked(q) for q in (p,*p.parents)):raise ValueError('來源及目的地須為可用普通資料夾，不可經過連結')
    a,b=a.resolve(),b.resolve()
    if a==b or a in b.parents or b in a.parents:raise ValueError('來源及目的地不可重疊')
    return a,b

def files(root,cancel):
    def fail(e):raise e
    for base,dirs,names in os.walk(root,followlinks=False,onerror=fail):
        base=Path(base);dirs[:]=sorted(d for d in dirs if d.casefold() not in EXCLUDED|{'photo_index','.pm_backup'} and not linked(base/d))
        for name in sorted(names):
            if cancel():raise InterruptedError('已取消')
            p=base/name
            if p.suffix.lower() in MEDIA and not linked(p) and p.is_file():yield p

def date_folder(p):
    value=capture_date(p)
    if value:return value[:4]+'/'+value[5:7]
    for m in PAT.finditer(p.stem):
        try:
            d=date(*map(int,m.groups()));return f'{d.year:04d}/{d.month:02d}'
        except ValueError:pass
    return '日期待確認'

def plan(source,dest,mode='preserve',backup=False,cancel=lambda:False,progress=lambda n:None):
    source,dest=roots(source,dest)
    if mode not in ('preserve','date'):raise ValueError('未知分類方式')
    existing={}; seen=set(); result=[]
    if not backup:
        for i,p in enumerate(files(dest,cancel),1):
            h=sha256(p);seen.add(h);existing[p.relative_to(dest).as_posix().casefold()]=h;progress(i)
    for i,p in enumerate(files(source,cancel),1):
        h=sha256(p);rel=p.relative_to(source).as_posix() if backup or mode=='preserve' else date_folder(p)+'/'+p.name
        target=dest/rel;key=rel.casefold()
        if not backup and h in seen:action='duplicate'
        elif key in existing or target.exists() or target.is_symlink():
            old=existing.get(key)
            if old is None and target.is_file() and not linked(target):old=sha256(target)
            action='duplicate' if old==h else 'conflict'
        else:action='copy';existing[key]=h;seen.add(h)
        result.append(Entry(p,rel,h,action,p.stat().st_size));progress(i)
    return result

def safe_parent(root,target):
    current=root
    for part in target.relative_to(root).parts[:-1]:
        current=current/part
        if current.exists() or current.is_symlink():
            if linked(current) or not current.is_dir():raise ValueError('目的路徑不是普通資料夾')
        else:current.mkdir()

def execute(source,dest,entries,cancel=lambda:False,progress=lambda n:None):
    source,dest=roots(source,dest);done=0
    needed=sum(e.size for e in entries if e.action=='copy')
    if shutil.disk_usage(dest).free<needed:raise OSError('目的地空間不足')
    for e in entries:
        if cancel():raise InterruptedError(f'已取消；已完成 {done} 個，重新健檢可續跑')
        if e.action!='copy':continue
        p=e.source;target=dest/e.relative
        if source not in p.parents or any(linked(q) for q in (p,*p.parents)) or dest not in target.parents or '..' in Path(e.relative).parts:raise ValueError('不安全的路徑')
        safe_parent(dest,target)
        fd,tmp=tempfile.mkstemp(prefix='.pm_copy_',dir=target.parent);os.close(fd);tmp=Path(tmp)
        try:
            shutil.copy2(p,tmp)
            if sha256(tmp)!=e.digest:raise OSError('來源變更或複製驗證失敗：'+str(p))
            if cancel():raise InterruptedError('已取消；已完成檔案保留')
            os.link(tmp,target) # exclusive publish; unsupported filesystem fails safely
            done+=1;progress(done)
        finally:tmp.unlink(missing_ok=True)
    return done

def snapshot(db,dest):
    dest=Path(dest);folder=dest/'.pm_backup';safe_parent(dest,folder/'placeholder')
    target=folder/('catalog_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.sqlite')
    fd,tmp=tempfile.mkstemp(dir=folder);os.close(fd);tmp=Path(tmp)
    try:
        with closing(sqlite3.connect(db)) as src,closing(sqlite3.connect(tmp)) as out:
            src.backup(out)
            if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise OSError('資料庫驗證失敗')
        os.link(tmp,target)
    finally:tmp.unlink(missing_ok=True)
    return target
