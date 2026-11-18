"""RC2d: copy, verify, merge catalog metadata, then optional explicit deletion."""
from pathlib import Path
from dataclasses import dataclass
from datetime import date
import os, re, uuid, json
from catalog import Catalog
from library_catalog import MEDIA, linked, sha256
from workflow import roots, files, execute, Entry
from date_year import PAT, capture_date, detect_year

VIDEO=set('.mov .mp4 .m4v .avi .mkv .mts .m2ts .3gp .wmv'.split())
@dataclass(frozen=True)
class Item:
    source: Path
    relative: str
    digest: str
    action: str
    size: int
    source_id: str|None
    date: str
    tags: tuple
    override: str|None
    mtime: int

def check_file(p,root):
    if root not in p.parents or not p.is_file() or any(linked(q) for q in (p,*p.parents)):
        raise ValueError('檔案離線或不安全：'+str(p))

def source_row(c,p):
    for s in c.sources():
        root=Path(s['root'])
        if root in p.parents:
            return c.db.execute('SELECT * FROM photos WHERE source=? AND rel=?',(s['id'],p.relative_to(root).as_posix())).fetchone()
    return None

def metadata(c,p):
    r=source_row(c,p);st=p.stat()
    if r and (r['size'],r['mtime'])!=(st.st_size,st.st_mtime_ns):raise ValueError('來源索引已變更，請先確認並重新掃描：'+str(p))
    if not r:return None,(),None
    tags=tuple(x[0] for x in c.db.execute('SELECT tag FROM links WHERE photo=? ORDER BY tag',(r['id'],)))
    o=c.db.execute('SELECT value FROM date_overrides WHERE photo=?',(r['id'],)).fetchone()
    return r['id'],tags,o[0] if o else None

def day(p,override):
    if override:return override
    if d:=capture_date(p):return d
    for part in (p.stem,*[q.name for q in p.parents]):
        for m in PAT.finditer(part):
            try:return date(*map(int,m.groups())).isoformat()
            except ValueError:pass
    return ''

def plan(db,source,dest,mode='preserve',recursive=True,rename=False,cancel=lambda:False):
    source,dest=roots(source,dest);c=Catalog(db)
    try:
        if not any(Path(s['root'])==dest and s['role']=='primary' for s in c.sources()):raise ValueError('目的地須為已登錄的主庫')
        if mode not in ('preserve','date'):raise ValueError('未知分類方式')
        used={}; hashes={};out=[];managed=(dest/'.PHOTO_MANAGER/identity.json').is_file()
        for p in files(dest,cancel):
            if managed and p.relative_to(dest).parts[0] not in ('PHOTOS','VIDEOS','截圖'):continue
            h=sha256(p);rel=p.relative_to(dest).as_posix();used[rel.casefold()]=rel;hashes.setdefault(h,rel)
        for p in files(source,cancel):
            if not recursive and p.parent!=source:continue
            check_file(p,source);st=p.stat();h=sha256(p);pid,tags,override=metadata(c,p);d=day(p,override)
            if mode=='date':
                folder=Path(d[:4],d[:7] if managed else d[5:7]) if d else Path('日期待確認')
            else:folder=p.relative_to(source).parent
            if managed:folder=Path('VIDEOS' if p.suffix.lower() in VIDEO else 'PHOTOS')/folder
            name=p.name
            if rename and d:name=d+'_001'+p.suffix
            rel=(folder/name).as_posix()
            if h in hashes:rel=hashes[h];action='duplicate'
            else:
                original=rel;stem=Path(name).stem;match=re.fullmatch(r'(.*)_(\d+)',stem);prefix=match[1] if match else stem
                n=int(match[2])+1 if match else 1
                while rel.casefold() in used or os.path.lexists(dest/rel):
                    rel=(folder/(f'{prefix}_{n:03d}'+p.suffix)).as_posix();n+=1
                action='rename' if rel!=original or name!=p.name else 'copy';used[rel.casefold()]=rel;hashes[h]=rel
            out.append(Item(p,rel,h,action,st.st_size,pid,d,tags,override,st.st_mtime_ns))
        return out
    finally:c.close()

def verify(c,source,dest,items,check_metadata=True):
    sid=next(s['id'] for s in c.sources() if Path(s['root'])==dest and s['role']=='primary')
    for e in items:
        p=e.source;t=dest/e.relative;check_file(p,source);check_file(t,dest)
        if p.stat().st_mtime_ns!=e.mtime or sha256(p)!=e.digest or sha256(t)!=e.digest:raise ValueError('來源或主庫驗證失敗：'+str(p))
        if metadata(c,p)!=(e.source_id,e.tags,e.override):raise ValueError('來源 TAG／日期已變更，請重新匯入')
        if check_metadata:
            r=c.db.execute('SELECT id FROM photos WHERE source=? AND rel=?',(sid,e.relative)).fetchone()
            if not r:raise ValueError('主庫索引缺失')
            tags={x[0] for x in c.db.execute('SELECT tag FROM links WHERE photo=?',(r['id'],))}
            if not set(e.tags)<=tags:raise ValueError('主庫 TAG 驗證失敗')
            if e.override and not c.db.execute('SELECT 1 FROM date_overrides WHERE photo=? AND value=?',(r['id'],e.override)).fetchone():raise ValueError('主庫日期修正衝突')
    return sid

def audit(c,batch,event,details):
    with c.db:
        c.db.execute('CREATE TABLE IF NOT EXISTS master_import_audit(batch TEXT,event TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')
        c.db.execute('INSERT INTO master_import_audit(batch,event,details) VALUES(?,?,?)',(batch,event,json.dumps(details,ensure_ascii=False)))

def run(db,source,dest,items,cancel=lambda:False):
    source,dest=roots(source,dest);c=Catalog(db);batch=uuid.uuid4().hex
    try:
        if not items:raise ValueError('沒有可匯入的照片')
        audit(c,batch,'planned',[[str(e.source),e.relative,e.digest,e.action] for e in items])
        for e in items:
            if cancel():raise InterruptedError('取消；來源保留')
            check_file(e.source,source)
            if sha256(e.source)!=e.digest or metadata(c,e.source)!=(e.source_id,e.tags,e.override):raise ValueError('來源已變更')
        execute(source,dest,[Entry(e.source,e.relative,e.digest,'copy',e.size) for e in items if e.action!='duplicate'],cancel)
        sid=verify(c,source,dest,items,False)
        with c.db:
            for e in items:
                if cancel():raise InterruptedError('取消；來源保留')
                p=dest/e.relative;st=p.stat();r=c.db.execute('SELECT * FROM photos WHERE source=? AND rel=?',(sid,e.relative)).fetchone()
                if r and (r['size'],r['mtime'])!=(st.st_size,st.st_mtime_ns):raise ValueError('主庫既有索引已變更，請先確認')
                if r:pid=r['id']
                else:
                    pid=uuid.uuid4().hex;y,ys=detect_year(dest,e.relative)
                    c.db.execute('INSERT INTO photos(id,source,rel,year,size,mtime,year_source,capture_date) VALUES(?,?,?,?,?,?,?,?)',(pid,sid,e.relative,y,st.st_size,st.st_mtime_ns,ys,e.date))
                for tag in e.tags:c.db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?)',(pid,tag,'主庫匯入'))
                if e.override:
                    old=c.db.execute('SELECT value FROM date_overrides WHERE photo=?',(pid,)).fetchone()
                    if old and old[0]!=e.override:raise ValueError('人工日期衝突，來源保留')
                    c.db.execute('INSERT OR IGNORE INTO date_overrides VALUES(?,?)',(pid,e.override));c.db.execute("UPDATE photos SET capture_date=?,year=?,year_source='人工修正（索引）' WHERE id=?",(e.override,int(e.override[:4]),pid))
        verify(c,source,dest,items)
        if (dest/'.PHOTO_MANAGER/identity.json').is_file():
            from photo_manager_v1_4 import Library
            lib=Library(dest,create=False)
            try:
                def stop():
                    if cancel():raise InterruptedError('取消；來源保留')
                rows=lib.scan(stop=stop)
                if any(e.relative not in rows or rows[e.relative][0]!=e.digest for e in items):raise ValueError('V2.0 主庫索引驗證失敗')
            finally:lib.close()
        audit(c,batch,'verified',{'count':len(items)})
        return batch
    except Exception as ex:audit(c,batch,'failed',str(ex));raise
    finally:c.close()

def deletion_blockers(c,source,items):
    reasons=[]
    for s in c.sources():
        r=Path(s['root'])
        if (r==source or r in source.parents or source in r.parents) and s['role'] in ('primary','backup'):reasons.append('來源屬於主庫／備份庫，禁止刪除')
    for e in items:
        p=e.source
        if any((q/'.PHOTO_MANAGER/identity.json').is_file() for q in p.parents):reasons.append('來源屬於 V2.0 管理庫，禁止刪除')
        # Keep sidecar / possible Live Photo sources until pair-aware import is implemented.
        if any(q.is_file() and q!=p and (q.stem.casefold()==p.stem.casefold() or q.name.casefold().startswith(p.name.casefold()+'.')) for q in p.parent.iterdir()):reasons.append('存在同名配對或附屬檔，保留來源：'+p.name)
    return list(dict.fromkeys(reasons))

def delete_verified(db,source,dest,items,batch,confirmed=False):
    if not confirmed:raise ValueError('需要明確確認')
    source,dest=roots(source,dest);c=Catalog(db);done=[]
    try:
        if not c.db.execute("SELECT 1 FROM master_import_audit WHERE batch=? AND event='verified'",(batch,)).fetchone():raise ValueError('無完整驗證紀錄')
        saved=c.db.execute("SELECT details FROM master_import_audit WHERE batch=? AND event='planned'",(batch,)).fetchone()
        if not saved or json.loads(saved[0])!=[[str(e.source),e.relative,e.digest,e.action] for e in items]:raise ValueError('刪除清單與原始驗證批次不符')
        verify(c,source,dest,items);reasons=deletion_blockers(c,source,items)
        if reasons:raise ValueError('\n'.join(reasons))
        audit(c,batch,'delete_confirmed',[str(e.source) for e in items])
        for e in items:
            verify(c,source,dest,[e]);e.source.unlink();done.append(str(e.source));audit(c,batch,'deleted',str(e.source))
            if e.source_id:
                # Remove stale index, retain audit history; undo entries referring to deleted source are invalidated.
                with c.db:
                    for table in ('undo','date_audit'):
                        for r in c.db.execute(f'SELECT id,changes FROM {table}').fetchall():
                            changes=json.loads(r['changes']);keep=[x for x in changes if x[0]!=e.source_id]
                            if keep!=changes:
                                if keep:c.db.execute(f'UPDATE {table} SET changes=? WHERE id=?',(json.dumps(keep,ensure_ascii=False),r['id']))
                                else:c.db.execute(f'DELETE FROM {table} WHERE id=?',(r['id'],))
                    c.db.execute('DELETE FROM links WHERE photo=?',(e.source_id,));c.db.execute('DELETE FROM date_overrides WHERE photo=?',(e.source_id,));c.db.execute('DELETE FROM photos WHERE id=?',(e.source_id,))
        return len(done)
    except Exception as ex:audit(c,batch,'delete_stopped',{'deleted':done,'error':str(ex)});raise
    finally:c.close()
