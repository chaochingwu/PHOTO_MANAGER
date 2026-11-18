"""Crash-recoverable V2.0 organizer -> V2.1 TAG catalog bridge.

The V2.0 organizer owns media moves; this module only changes the V2.1
catalog after the media plan has completed and every destination is verified.
Never bypass a pending transaction or change TAG IDs during a rename.
"""
import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from contextlib import closing
from datetime import datetime
from catalog import Catalog
from date_year import detect_year


def _hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def journal_path(db,root):
    root=Path(root).resolve();db=Path(db).resolve()
    return db.parent/('organize_bridge_'+hashlib.sha256(str(root).casefold().encode('utf-8')).hexdigest()[:20]+'.json')


def _write_atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def pending(db,root):
    return journal_path(db,root).exists()


def prepare(db,root,entries):
    """Validate mappings and persist manifest before V2.0 touches media."""
    db=Path(db).resolve();root=Path(root).resolve();journal=journal_path(db,root)
    if journal.exists():raise ValueError('前次整理交易尚未完成，禁止開始新整理；請先使用「恢復整理索引」')
    c=Catalog(db)
    try:
        s=c.db.execute('SELECT * FROM sources WHERE root=?',(str(root),)).fetchone()
        if not s or s['role']!='primary':raise ValueError('請先在 Library 登錄並索引目前主庫，再執行整理')
        sid=s['id'];changes=[];moves={str(Path(a).resolve()):str(Path(b).resolve()) for a,b,h in entries if a!=b}
        # Existing source rows may be stale if files changed outside the app.
        for src,dst,h in entries:
            src=Path(src).resolve();dst=Path(dst).resolve()
            if src==dst:continue
            if not src.is_relative_to(root) or not dst.is_relative_to(root):raise ValueError('整理計畫超出主庫')
            if not src.is_file() or src.is_symlink() or dst.is_symlink():raise ValueError('來源或目的地不可為連結')
            row=c.db.execute('SELECT * FROM photos WHERE source=? AND rel=?',(sid,src.relative_to(root).as_posix())).fetchone()
            if row and (row['size']!=src.stat().st_size or row['mtime']!=src.stat().st_mtime_ns):raise ValueError('照片與 TAG 索引不一致，請先更新 Library 索引：'+str(src))
            if row and _hash(src)!=h:raise ValueError('照片內容與整理計畫不一致')
            changes.append(dict(old=src.relative_to(root).as_posix(),new=dst.relative_to(root).as_posix(),hash=h,id=row['id'] if row else None,
                recovery='.PHOTO_MANAGER/recovery/' in dst.relative_to(root).as_posix()))
        if not changes:return None
        oldset={x['old'] for x in changes}
        if len(oldset)!=len(changes) or len({x['new'].casefold() for x in changes})!=len(changes):raise ValueError('整理計畫存在重複來源或目的地')
        for x in changes:
            existing=c.db.execute('SELECT id FROM photos WHERE source=? AND rel=?',(sid,x['new'])).fetchone()
            if existing and x['new'] not in oldset:raise ValueError('目的地 TAG 索引已存在，禁止覆蓋：'+x['new'])
        # Recovery-area duplicates are never discarded if tagged/overridden;
        # merging needs unambiguous content winner and date-override handling.
        for x in changes:
            if x['recovery'] and x['id']:
                pid=x['id'];has_tags=c.db.execute('SELECT 1 FROM links WHERE photo=? LIMIT 1',(pid,)).fetchone()
                has_date=c.db.execute('SELECT 1 FROM date_overrides WHERE photo=?',(pid,)).fetchone()
                if has_tags or has_date:raise ValueError('重複照片含 TAG／日期修正，為避免資料遺失，本次先取消去重；請取消「刪除重複檔案」後再整理：'+x['old'])
        data=dict(version=1,root=str(root),db=str(db),sid=sid,changes=changes,created=datetime.now().isoformat())
        # SQLite online backup preserves metadata in case of external corruption.
        backup=db.parent/(journal.stem+'.pre_'+uuid.uuid4().hex[:10]+'.sqlite')
        with closing(sqlite3.connect(backup)) as dst:c.db.backup(dst)
        data['catalog_backup']=str(backup)
        _write_atomic(journal,data)
        return journal
    finally:c.close()


def finalize(db,root):
    """Reconcile only a *completed* V2.0 move plan; never guess missing files."""
    db=Path(db).resolve();root=Path(root).resolve();journal=journal_path(db,root)
    if not journal.exists():return 0
    data=json.loads(journal.read_text(encoding='utf-8'))
    if data['root']!=str(root) or data['db']!=str(db):raise ValueError('整理交易記錄與照片庫不符')
    if (root/'.PHOTO_MANAGER/organize_pending.json').exists():raise ValueError('V2.0 搬移交易尚未完成；請先恢復搬移，再更新 TAG')
    for x in data['changes']:
        dst=root/x['new']
        if not dst.is_file() or _hash(dst)!=x['hash']:raise ValueError('整理目的地不存在或 SHA256 不符；TAG 保留在舊索引，禁止繼續：'+str(dst))
    c=Catalog(db)
    try:
        sid=data['sid'];changed=[x for x in data['changes'] if x['id']]
        with c.db:
            # All old rels vacated first, so chronological swaps are safe.
            for x in changed:
                row=c.db.execute('SELECT source,rel FROM photos WHERE id=?',(x['id'],)).fetchone()
                if not row:raise ValueError('TAG 照片識別碼消失：'+x['id'])
                if row['source']!=sid:raise ValueError('照片來源識別碼錯誤')
                if row['rel']==x['new']:continue
                if row['rel']!=x['old']:raise ValueError('照片已被其他工作變更：'+x['old'])
                c.db.execute('UPDATE photos SET rel=? WHERE id=?',('__PM_BRIDGE__/'+x['id'],x['id']))
            for x in changed:
                pid=x['id']
                if x['recovery']:
                    # Untagged records in recovery must not pollute Library results.
                    c.db.execute('DELETE FROM photos WHERE id=?',(pid,));continue
                st=(root/x['new']).stat();y,ys=detect_year(root,x['new'])
                override=c.db.execute('SELECT value FROM date_overrides WHERE photo=?',(pid,)).fetchone()
                if override:y=int(override[0][:4]);ys='人工修正（索引）'
                c.db.execute('UPDATE photos SET rel=?,size=?,mtime=?,year=?,year_source=? WHERE id=?',(x['new'],st.st_size,st.st_mtime_ns,y,ys,pid))
            c.db.execute('CREATE TABLE IF NOT EXISTS organize_bridge_audit(id INTEGER PRIMARY KEY,created TEXT DEFAULT CURRENT_TIMESTAMP,details TEXT)')
            c.db.execute('INSERT INTO organize_bridge_audit(details) VALUES(?)',(json.dumps(data,ensure_ascii=False),))
        journal.unlink()
        # Backup remains as an intentional recoverable safety snapshot.
        return len(changed)
    finally:c.close()


def recover(db,root,log=print):
    """Resume V2.0's staged transaction, then reconcile TAG identities."""
    root=Path(root).resolve()
    if not pending(db,root):return 0
    if (root/'.PHOTO_MANAGER/organize_pending.json').exists():
        from organize import execute_moves
        execute_moves(root,[],log)
    from photo_manager_v1_4 import Library
    lib=Library(root,create=False)
    try:lib.scan(log=log,detect=False)
    finally:lib.close()
    return finalize(db,root)
