"""Verified, resumable Takeout import. Original ZIPs and existing media are never edited."""
import json, os, shutil, tempfile, zipfile, re
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from takeout_audit import audit, digest
from catalog import Catalog, norm
from library_catalog import linked

def hashfile(p):
    with p.open('rb') as f:return digest(f)

def taken(m):
    try:return datetime.fromtimestamp(int(m['photoTakenTime']['timestamp']),timezone(timedelta(hours=8))).date().isoformat()
    except (KeyError,TypeError,ValueError,OverflowError,OSError):return ''

def run(folder,destination,dbpath,checkpoint,progress=lambda s:None,cancel=lambda:False,approved=None):
    src=Path(folder).resolve(); dest=Path(destination).resolve(); dbpath=Path(dbpath).resolve()
    if src==dest or src in dest.parents or dest in src.parents:raise ValueError('匯入目的地不可與 ZIP 來源重疊')
    if not dest.is_dir() or linked(dest):raise ValueError('請先建立獨立的匯入資料夾')
    def tick(s):
        if cancel():raise InterruptedError('已停止；重新執行可續傳')
        progress(s)
    result=audit(src,checkpoint,dbpath,tick)
    if result['errors'] or result['incomplete']:raise ValueError('健檢有錯誤或下載未完成，停止匯入')
    def stable(rows):return [{k:v for k,v in m.items() if k!='duplicate'} for m in rows]
    if approved is not None and stable(approved)!=stable(result['media']):raise ValueError('來源與已確認報告不同，請重新健檢')
    c=Catalog(dbpath); counts={'new':0,'matched':0,'tags':0,'verified':False}; hashes=defaultdict(list)
    try:
        sid=c.add_source(dest,'independent');c.scan(sid,cancel=cancel)
        for r in c.db.execute("SELECT p.*,s.root FROM photos p JOIN sources s ON s.id=p.source WHERE s.role IN ('primary','independent')"):
            tick('確認主庫 '+r['rel']); p=Path(r['root'])/r['rel']; hashes[hashfile(p)].append(r['id'])
        with c.db:
            c.db.execute('CREATE TABLE IF NOT EXISTS takeout_import_log(sha TEXT,archive TEXT,member TEXT,photo TEXT,metadata TEXT,PRIMARY KEY(archive,member,sha,photo))')
        for i,m in enumerate(result['media']):
            tick(f'匯入 {i+1}/{len(result["media"])}：{m["member"]}')
            sha=m['sha256']; ids=hashes.get(sha,[]); dt=taken(m)
            if not ids:
                name=PurePosixPath(m['member']).name
                if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.rstrip(' .')!=name or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:raise ValueError('不安全檔名：'+name)
                sub=dest/(dt[:4] if dt else '未知日期')/(dt if dt else 'Takeout');sub.mkdir(parents=True,exist_ok=True)
                if any(linked(p) for p in (sub,sub.parent)):raise ValueError('目的地含連結')
                p=sub/name
                if p.exists():
                    # Preserve original filename in a separate collision folder.
                    sub=sub/sha;sub.mkdir(exist_ok=True)
                    if linked(sub):raise ValueError('目的地含連結')
                    p=sub/name
                if p.exists():raise FileExistsError(str(p))
                if shutil.disk_usage(sub).free<m['size']+16*1024*1024:raise OSError('磁碟空間不足')
                fd,tmp=tempfile.mkstemp(prefix='.pm_import_',dir=sub);os.close(fd);tmp=Path(tmp)
                try:
                    with zipfile.ZipFile(src/m['zip']) as z, z.open(m['member']) as f, tmp.open('wb') as out:
                        while True:
                            if cancel():raise InterruptedError('已停止')
                            block=f.read(1024*1024)
                            if not block:break
                            out.write(block)
                        out.flush();os.fsync(out.fileno())
                    if hashfile(tmp)!=sha:raise ValueError('SHA256 驗證失敗')
                    os.link(tmp,p) # atomic, never overwrites; NTFS or other hardlink-capable filesystem required
                finally:tmp.unlink(missing_ok=True)
                st=p.stat();rel=p.relative_to(dest).as_posix()
                import uuid
                pid=uuid.uuid4().hex
                with c.db:c.db.execute('INSERT INTO photos(id,source,rel,year,size,mtime,year_source,capture_date) VALUES(?,?,?,?,?,?,?,?)',(pid,sid,rel,int(dt[:4]) if dt else None,st.st_size,st.st_mtime_ns,'Google Takeout' if dt else '未知',dt))
                ids=[pid];hashes[sha]=ids;counts['new']+=1
            else:counts['matched']+=1
            with c.db:
                for pid in ids:
                    for name in m['people']:
                        matches=c.db.execute('SELECT id FROM tags WHERE kind=? AND norm=?',('人物',norm(name))).fetchall()
                        if len(matches)>1:raise ValueError('同名人物需人工確認：'+name)
                        tid=matches[0][0] if matches else c.db.execute('INSERT INTO tags(kind,name,norm,scope) VALUES(?,?,?,?)',('人物',name,norm(name),'')).lastrowid
                        counts['tags']+=c.db.execute('INSERT OR IGNORE INTO links VALUES(?,?,?)',(pid,tid,'Google Takeout')).rowcount
                    c.db.execute('INSERT OR REPLACE INTO takeout_import_log VALUES(?,?,?,?,?)',(sha,m['zip'],m['member'],pid,json.dumps(m,ensure_ascii=False)))
        counts['verified']=True;return counts
    finally:c.close()
