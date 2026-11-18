"""Read-only evidence and reversible catalog-only capture date corrections."""
from datetime import date
from pathlib import Path
import json
from date_year import capture_date, detect_year, PAT

def evidence(row):
    p=Path(row['root'])/row['rel'];exif=capture_date(p);year,source=detect_year(row['root'],row['rel']);candidates=[]
    for part in Path(row['rel']).parts:
        for m in PAT.finditer(part):
            try:candidates.append(date(*map(int,m.groups())).isoformat())
            except ValueError:pass
    return dict(id=row['id'],path=str(p),embedded=exif,folder_filename_dates=list(dict.fromkeys(candidates)),year=year,source=source,index_date=row['capture_date'],anomaly=not exif or '衝突' in source or any(x!=exif for x in candidates))

def setup(c):
    with c.db:
        c.db.execute('CREATE TABLE IF NOT EXISTS date_overrides(photo TEXT PRIMARY KEY REFERENCES photos(id),value TEXT NOT NULL)')
        c.db.execute('CREATE TABLE IF NOT EXISTS date_audit(id INTEGER PRIMARY KEY,created TEXT DEFAULT CURRENT_TIMESTAMP,changes TEXT NOT NULL,undone INTEGER DEFAULT 0)')

def apply(c,groups):
    setup(c);changes=[];seen=set()
    with c.db:
        for ids,value in groups:
            value=date.fromisoformat(value).isoformat()
            for pid in ids:
                if pid in seen:raise ValueError('同一照片不可出現在多組')
                seen.add(pid);r=c.db.execute('SELECT capture_date,year,year_source FROM photos WHERE id=?',(pid,)).fetchone()
                if not r:raise ValueError('照片不存在')
                old=c.db.execute('SELECT value FROM date_overrides WHERE photo=?',(pid,)).fetchone();changes.append([pid,*r,old[0] if old else None])
                c.db.execute('INSERT OR REPLACE INTO date_overrides VALUES(?,?)',(pid,value));c.db.execute("UPDATE photos SET capture_date=?,year=?,year_source='人工修正（索引）' WHERE id=?",(value,int(value[:4]),pid))
        if changes:c.db.execute('INSERT INTO date_audit(changes) VALUES(?)',(json.dumps(changes,ensure_ascii=False),))
    return len(changes)

def undo(c):
    setup(c)
    with c.db:
        r=c.db.execute('SELECT id,changes FROM date_audit WHERE undone=0 ORDER BY id DESC LIMIT 1').fetchone()
        if not r:return 0
        changes=json.loads(r['changes'])
        for pid,dt,year,source,old in changes:
            if old:c.db.execute('INSERT OR REPLACE INTO date_overrides VALUES(?,?)',(pid,old))
            else:c.db.execute('DELETE FROM date_overrides WHERE photo=?',(pid,))
            c.db.execute('UPDATE photos SET capture_date=?,year=?,year_source=? WHERE id=?',(dt,year,source,pid))
        c.db.execute('UPDATE date_audit SET undone=1 WHERE id=?',(r['id'],))
    return len(changes)

def full_report(c,target,cancel=lambda:False,progress=lambda n:None):
    """Stream all primary/independent evidence to an atomic JSON report."""
    import tempfile,os
    target=Path(target).resolve();fd,tmp=tempfile.mkstemp(prefix='.date_audit_',dir=target.parent);n=0
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write('[')
            for r in c.db.execute("SELECT p.*,s.root FROM photos p JOIN sources s ON s.id=p.source WHERE s.role IN ('primary','independent') ORDER BY p.id"):
                if cancel():raise InterruptedError('已取消，未覆蓋報告')
                e=evidence(r);f.write((',' if n else '')+json.dumps(e,ensure_ascii=False));n+=1
                if n%100==0:progress(n)
            f.write(']');f.flush();os.fsync(f.fileno())
        os.replace(tmp,target);return n
    finally:Path(tmp).unlink(missing_ok=True)
