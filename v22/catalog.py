from pathlib import Path
import sqlite3, os, uuid, re, csv, json, html, unicodedata
from urllib.parse import quote
from library_catalog import MEDIA, EXCLUDED, linked, source_year
from date_year import detect_year, capture_date
FAVORITE_KIND="收藏"
FAVORITE_NAME="我的最愛"
DEFAULT_KINDS=("人物","事件","時間標籤","地點","物品","自訂","公司／組織",FAVORITE_KIND)

def norm(s): return unicodedata.normalize('NFKC',s).strip().casefold()
def tokens(s): return [x.strip() for x in re.split('[,，;；\n]',s) if x.strip()]
class Catalog:
    def __init__(self,path):
        self.path=Path(path).resolve(); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30); self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,root TEXT UNIQUE,role TEXT);
        CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY,source INTEGER REFERENCES sources(id),rel TEXT,year INTEGER,size INTEGER,mtime INTEGER,UNIQUE(source,rel));
        CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY,kind TEXT,name TEXT,norm TEXT,scope TEXT DEFAULT '',UNIQUE(kind,norm,scope));
        CREATE TABLE IF NOT EXISTS aliases(tag INTEGER REFERENCES tags(id),name TEXT,norm TEXT,PRIMARY KEY(tag,norm));
        CREATE TABLE IF NOT EXISTS links(photo TEXT REFERENCES photos(id),tag INTEGER REFERENCES tags(id),origin TEXT,PRIMARY KEY(photo,tag));
        CREATE INDEX IF NOT EXISTS links_tag ON links(tag,photo); CREATE INDEX IF NOT EXISTS photos_year ON photos(year); CREATE TABLE IF NOT EXISTS undo(id INTEGER PRIMARY KEY,changes TEXT);''')
        with self.db:
            if 'year_source' not in [r[1] for r in self.db.execute('PRAGMA table_info(photos)')]:
                self.db.execute("ALTER TABLE photos ADD COLUMN year_source TEXT NOT NULL DEFAULT ''")
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY)')
            self.db.execute('CREATE TABLE IF NOT EXISTS batch_audit(id INTEGER PRIMARY KEY,created TEXT DEFAULT CURRENT_TIMESTAMP,mode TEXT,photo_count INTEGER,changes TEXT)')
            self.db.executemany('INSERT OR IGNORE INTO categories VALUES(?)',[(k,) for k in DEFAULT_KINDS])
            self.db.execute('INSERT OR IGNORE INTO categories SELECT DISTINCT kind FROM tags')
            if 'capture_date' not in [r[1] for r in self.db.execute('PRAGMA table_info(photos)')]:
                self.db.execute("ALTER TABLE photos ADD COLUMN capture_date TEXT NOT NULL DEFAULT ''")
        from date_inspector import setup
        setup(self)
    def kinds(self):
        return list(DEFAULT_KINDS)+[r[0] for r in self.db.execute('SELECT name FROM categories ORDER BY name') if r[0] not in DEFAULT_KINDS]
    def add_kind(self,name):
        name=name.strip()
        if not name or len(name)>40 or any(c in name for c in ':：;；,，\n\r') or name=='自訂 TAG':raise ValueError('分類名稱不合法')
        if any(norm(k)==norm(name) for k in self.kinds()):raise ValueError('分類已存在')
        with self.db:self.db.execute('INSERT INTO categories VALUES(?)',(name,))
        return name
    def folders(self,source):
        # Derive the full hierarchy from existing indexed media, including old catalogs.
        folders=set()
        for (rel,) in self.db.execute('SELECT rel FROM photos WHERE source=?',(source,)):
            parts=rel.split('/')[:-1]
            for i in range(1,len(parts)+1):folders.add('/'.join(parts[:i]))
        return sorted(folders,key=lambda x:(x.count('/'),x.casefold(),x))
    def folder_ids(self,source,rel):
        prefix=Path(rel).parent.as_posix()
        return [r[0] for r in self.db.execute("SELECT id FROM photos WHERE source=? AND (?='.' OR substr(rel,1,length(?)+1)=?||'/')",(source,prefix,prefix,prefix))]
    def edit_categories(self,ids,fields,mode='append'):
        ids=list(dict.fromkeys(ids)); fields={k:list(dict.fromkeys(tokens(v))) for k,v in fields.items() if tokens(v)}
        if not ids or not fields or mode not in ('append','remove','replace'):raise ValueError('請選取照片及輸入 TAG')
        if any(k not in self.kinds() for k in fields):raise ValueError('未知分類')
        changes=[]
        with self.db:
            targets={}
            for k,names in fields.items():
                tids=set()
                for name in names:
                    found=self.db.execute('SELECT id FROM tags WHERE kind=? AND norm=?',(k,norm(name))).fetchall()
                    if len(found)>1:raise ValueError(f'{k}：{name} 有同名 TAG，請使用既有 TAG 選單指定')
                    if found:tid=found[0][0]
                    elif mode=='remove':raise ValueError(f'找不到 TAG：{k}／{name}')
                    else:tid=self.db.execute('INSERT INTO tags(kind,name,norm,scope) VALUES(?,?,?,?)',(k,name,norm(name),'')).lastrowid
                    tids.add(tid)
                targets[k]=tids
            for pid in ids:
                if not self.db.execute('SELECT 1 FROM photos WHERE id=?',(pid,)).fetchone():raise ValueError('照片索引不存在')
                for k,tids in targets.items():
                    old={r[0]:r[1] for r in self.db.execute('SELECT l.tag,l.origin FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo=? AND t.kind=?',(pid,k))}
                    remove=(set(old)&tids if mode=='remove' else set(old)-tids if mode=='replace' else set())
                    add=tids-set(old) if mode!='remove' else set()
                    for tid in remove:self.db.execute('DELETE FROM links WHERE photo=? AND tag=?',(pid,tid));changes.append([pid,tid,old[tid]])
                    for tid in add:self.db.execute('INSERT INTO links VALUES(?,?,?)',(pid,tid,'人工'));changes.append([pid,tid,None])
            if changes:
                payload=json.dumps(changes,ensure_ascii=False);self.db.execute('INSERT INTO undo(changes) VALUES(?)',(payload,));self.db.execute('INSERT INTO batch_audit(mode,photo_count,changes) VALUES(?,?,?)',(mode,len(ids),payload))
        return len(changes)
    def close(self): self.db.close()
    def timeline(self):
        return self.db.execute("SELECT p.year, COUNT(*) AS n FROM photos p JOIN sources s ON p.source=s.id WHERE s.role NOT IN ('backup','import') GROUP BY p.year ORDER BY p.year DESC").fetchall()
    def sources(self): return self.db.execute('SELECT * FROM sources ORDER BY id').fetchall()
    def add_source(self,root,role='primary'):
        p=Path(root).absolute();
        if not p.is_dir() or linked(p): raise ValueError('來源不是可用的普通資料夾')
        p=p.resolve()
        if p==self.path or p in self.path.parents: raise ValueError('索引必須位於來源之外')
        if role not in ('primary','backup','independent','import'): raise ValueError('角色錯誤')
        for s in self.sources():
            q=Path(s['root'])
            if p==q:
                if role!=s['role']: raise ValueError('已存在，角色不同')
                return s['id']
            if p in q.parents or q in p.parents: raise ValueError('來源不可重疊')
        with self.db: return self.db.execute('INSERT INTO sources(root,role) VALUES(?,?)',(str(p),role)).lastrowid
    def scan(self,sid,progress=lambda n:None,cancel=lambda:False):
        s=self.db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone(); root=Path(s['root'])
        if not root.is_dir() or linked(root): raise ValueError('來源離線；保留既有索引')
        n=0
        def fail(e): raise e
        with self.db:
            for folder,dirs,files in os.walk(root,followlinks=False,onerror=fail):
                base=Path(folder); dirs[:]=sorted(d for d in dirs if d.casefold() not in EXCLUDED|{'photo_index'} and not linked(base/d))
                for name in sorted(files):
                    if cancel(): raise InterruptedError('掃描取消，這次更新已回復')
                    p=base/name
                    if p.suffix.lower() not in MEDIA or linked(p) or not p.is_file(): continue
                    st=p.stat(); rel=p.relative_to(root).as_posix()
                    old=self.db.execute('SELECT id,size,mtime,year,year_source,capture_date FROM photos WHERE source=? AND rel=?',(sid,rel)).fetchone()
                    if old and (old['size'],old['mtime'])!=(st.st_size,st.st_mtime_ns) and (self.db.execute('SELECT 1 FROM links WHERE photo=? LIMIT 1',(old['id'],)).fetchone() or self.db.execute('SELECT 1 FROM date_overrides WHERE photo=?',(old['id'],)).fetchone()):
                        raise ValueError(f'已標記檔案在外部變更，需先人工確認：{p}')
                    year,ys=(old['year'],old['year_source']) if old and old['year_source'] and (old['size'],old['mtime'])==(st.st_size,st.st_mtime_ns) else detect_year(root,rel)
                    cd=old['capture_date'] if old and old['capture_date'] and (old['size'],old['mtime'])==(st.st_size,st.st_mtime_ns) else capture_date(p)
                    self.db.execute('INSERT INTO photos(id,source,rel,year,size,mtime,year_source,capture_date) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,rel) DO UPDATE SET year=excluded.year,size=excluded.size,mtime=excluded.mtime,year_source=excluded.year_source,capture_date=excluded.capture_date',(uuid.uuid4().hex,sid,rel,year,st.st_size,st.st_mtime_ns,ys,cd)); n+=1
                    if n%100==0: progress(n)
        progress(n); return n
    def tag(self,kind,name,scope='',aliases=()):
        name=name.strip(); scope=scope.strip()
        if kind not in self.kinds() or not name: raise ValueError('標籤類型或名稱錯誤')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO tags(kind,name,norm,scope) VALUES(?,?,?,?)',(kind,name,norm(name),scope))
            tid=self.db.execute('SELECT id FROM tags WHERE kind=? AND norm=? AND scope=?',(kind,norm(name),scope)).fetchone()[0]
            self.db.executemany('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',[(tid,a.strip(),norm(a)) for a in aliases if a.strip()]); return tid
    def set_favorite(self,ids,enabled=True):
        ids=list(dict.fromkeys(ids))
        if not ids:return 0
        tid=self.tag(FAVORITE_KIND,FAVORITE_NAME)
        return self.assign(ids,tid,remove=not enabled)
    def tags(self): return self.db.execute('SELECT * FROM tags ORDER BY kind,name,scope').fetchall()
    def assign(self,ids,tid,remove=False):
        changes=[]
        with self.db:
            for pid in dict.fromkeys(ids):
                old=self.db.execute('SELECT origin FROM links WHERE photo=? AND tag=?',(pid,tid)).fetchone()
                if remove and old: self.db.execute('DELETE FROM links WHERE photo=? AND tag=?',(pid,tid)); changes.append([pid,tid,old[0]])
                elif not remove and not old: self.db.execute('INSERT INTO links VALUES(?,?,?)',(pid,tid,'人工')); changes.append([pid,tid,None])
            if changes:self.db.execute('INSERT INTO undo(changes) VALUES(?)',(json.dumps(changes,ensure_ascii=False),))
        return len(changes)
    def batch_tags(self,ids,text,remove=False):
        """One atomic operation; untyped new names are custom, existing exact names reused."""
        ids=list(dict.fromkeys(ids)); terms=tokens(text)
        if not ids or not terms: raise ValueError('請選取照片並輸入 TAG')
        kinds=self.kinds(); changes=[]; tids=[]
        with self.db:
            for term in terms:
                prefix,sep,name=term.partition(':')
                if not sep: prefix,sep,name=term.partition('：')
                kind=prefix.strip() if sep and prefix.strip() in kinds else None
                name=name.strip() if kind else term.strip()
                if not name: raise ValueError('TAG 名稱不可空白')
                q='SELECT id FROM tags WHERE norm=?'; args=[norm(name)]
                if kind:q+=' AND kind=?';args.append(kind)
                found=self.db.execute(q,args).fetchall()
                if len(found)>1: raise ValueError(f'「{name}」有多個同名 TAG，請用下方既有 TAG 選單指定區分／年份')
                if found:tid=found[0][0]
                elif remove:raise ValueError(f'找不到 TAG：{name}')
                else:
                    tid=self.db.execute('INSERT INTO tags(kind,name,norm,scope) VALUES(?,?,?,?)',(kind or '自訂',name,norm(name),'')).lastrowid
                if tid not in tids:tids.append(tid)
            for pid in ids:
                for tid in tids:
                    old=self.db.execute('SELECT origin FROM links WHERE photo=? AND tag=?',(pid,tid)).fetchone()
                    if remove and old:
                        self.db.execute('DELETE FROM links WHERE photo=? AND tag=?',(pid,tid));changes.append([pid,tid,old[0]])
                    elif not remove and not old:
                        self.db.execute('INSERT INTO links VALUES(?,?,?)',(pid,tid,'人工'));changes.append([pid,tid,None])
            if changes:self.db.execute('INSERT INTO undo(changes) VALUES(?)',(json.dumps(changes,ensure_ascii=False),))
        return len(changes)
    def selection_tags(self,ids):
        ids=list(dict.fromkeys(ids))
        if not ids:return []
        return self.db.execute('SELECT t.*,COUNT(*) AS n FROM tags t JOIN links l ON l.tag=t.id WHERE l.photo IN ('+','.join('?' for _ in ids)+') GROUP BY t.id ORDER BY t.kind,t.name',ids).fetchall()
    def undo(self):
        with self.db:
            row=self.db.execute('SELECT * FROM undo ORDER BY id DESC LIMIT 1').fetchone()
            if not row:return 0
            changes=json.loads(row['changes'])
            for pid,tid,old in changes:
                if old is None:self.db.execute('DELETE FROM links WHERE photo=? AND tag=?',(pid,tid))
                else:self.db.execute('INSERT OR REPLACE INTO links VALUES(?,?,?)',(pid,tid,old))
            self.db.execute('DELETE FROM undo WHERE id=?',(row['id'],));self.db.execute('INSERT INTO batch_audit(mode,photo_count,changes) VALUES(?,?,?)',('undo',len({x[0] for x in changes}),row['changes'])); return len(changes)
    def photo_tags_many(self, ids):
        ids=list(dict.fromkeys(ids)); result={pid:[] for pid in ids}
        for start in range(0,len(ids),500):
            chunk=ids[start:start+500]
            sql='SELECT l.photo AS photo_id,t.* FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo IN ('+','.join('?' for _ in chunk)+') ORDER BY l.photo,t.kind,t.name'
            for row in self.db.execute(sql,chunk):result[row['photo_id']].append(row)
        return result
    def photo_tags(self,pid): return self.db.execute('SELECT t.* FROM tags t JOIN links l ON l.tag=t.id WHERE l.photo=? ORDER BY kind,name',(pid,)).fetchall()
    def search(self,keyword='',people='',event='',years=None,any_people=False,untagged=False,offset=0,limit=100,include_backup=False,any_keyword=False,sort=None,descending=False,count_only=False,source_id=None,folder=None,recursive=True,favorites_only=False):
        where=[]; args=[]
        if source_id is not None:
            where.append('p.source=?');args.append(source_id)
        elif not include_backup:where.append("s.role NOT IN ('backup','import')")
        if folder is not None:
            if source_id is None:raise ValueError('資料夾需指定來源')
            prefix=folder.strip('/')
            if prefix:
                prefix+='/';where.append('substr(p.rel,1,length(?))=?');args.extend([prefix,prefix])
            if not recursive:
                where.append("instr(substr(p.rel,length(?)+1),'/')=0");args.append(prefix)
        if years == ['unknown']:where.append('p.year IS NULL')
        elif years:where.append('p.year IN ('+','.join('?' for _ in years)+')');args.extend(years)
        if favorites_only:
            where.append("EXISTS(SELECT 1 FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo=p.id AND t.kind=? AND t.norm=? AND t.scope='')")
            args.extend([FAVORITE_KIND,norm(FAVORITE_NAME)])
        if untagged:where.append("NOT EXISTS(SELECT 1 FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo=p.id AND t.kind='人物')")
        def match(kind,value):
            # instr treats %, _ literally; aliases are normalized too.
            args.extend([kind,norm(value),norm(value)])
            return 'EXISTS(SELECT 1 FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo=p.id AND t.kind=? AND (instr(t.norm,?)>0 OR EXISTS(SELECT 1 FROM aliases a WHERE a.tag=t.id AND instr(a.norm,?)>0)))'
        ps=[match('人物',x) for x in tokens(people)]
        if ps:where.append('('+(' OR ' if any_people else ' AND ').join(ps)+')')
        if event:where.append(match('事件',event))
        ks=[]
        for term in tokens(keyword):
            k=norm(term);args.extend([k,k,k]);ks.append('(instr(pmnorm(p.rel),?)>0 OR EXISTS(SELECT 1 FROM links l JOIN tags t ON t.id=l.tag WHERE l.photo=p.id AND (instr(t.norm,?)>0 OR EXISTS(SELECT 1 FROM aliases a WHERE a.tag=t.id AND instr(a.norm,?)>0))))')
        if ks:where.append('('+(' OR ' if any_keyword else ' AND ').join(ks)+')')
        self.db.create_function('pmnorm',1,norm,deterministic=True)
        self.db.create_function('pmfilename',1,lambda x:Path(x).name.casefold(),deterministic=True)
        self.db.create_function('pmformat',1,lambda x:Path(x).suffix.casefold(),deterministic=True)
        if count_only:
            sql='SELECT count(*) FROM photos p JOIN sources s ON p.source=s.id'+(' WHERE '+' AND '.join(where) if where else '')
            return self.db.execute(sql,args).fetchone()[0]
        order='p.year DESC,p.rel,p.id'
        if sort:
            expr={'file':'pmfilename(p.rel)','date':'p.capture_date','year':'p.year','path':'p.rel','size':'p.size','format':"pmformat(p.rel)"}.get(sort)
            if sort.startswith('tag:') and sort[4:] in self.kinds():
                expr="(SELECT group_concat(name,'、') FROM (SELECT t.name FROM tags t JOIN links l ON l.tag=t.id WHERE l.photo=p.id AND t.kind=? ORDER BY t.norm,t.id))";args.append(sort[4:])
            if expr:order=expr+(' DESC' if descending else ' ASC')+',p.rel,p.id'
        sql='SELECT p.*,s.root,s.role FROM photos p JOIN sources s ON p.source=s.id'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY '+order+' LIMIT ? OFFSET ?' 
        return self.db.execute(sql,(*args,limit,offset)).fetchall()
    def export(self,folder):
        folder=Path(folder).resolve()
        for s in self.sources():
            p=Path(s['root']);
            if folder==p or p in folder.parents: raise ValueError('匯出請選來源之外的資料夾')
        folder.mkdir(parents=True,exist_ok=True)
        rows=[]; offset=0; kinds=self.kinds()
        while True:
            batch=self.search(offset=offset,limit=1000)
            if not batch:break
            for r in batch:
                p=Path(r['root'])/r['rel']; ts=self.photo_tags(r['id']); groups={k:'、'.join(t['name'] for t in ts if t['kind']==k) for k in kinds}
                aliases='、'.join(a[0] for t in ts for a in self.db.execute('SELECT name FROM aliases WHERE tag=?',(t['id'],)))
                try: link=quote(os.path.relpath(p,folder).replace(os.sep,'/'),safe='/'); relative=os.path.relpath(p,folder)
                except ValueError:link=p.as_uri();relative=str(p)
                rows.append([r['id'],relative,r['year'] or '',*[groups[k] for k in kinds],aliases,link])
            offset+=len(batch)
        for name in ('photo_catalog.csv','index.html'):
            if (folder/name).exists():raise FileExistsError('匯出檔已存在，請選新資料夾')
        def safe(v):
            s=str(v);return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
        with (folder/'photo_catalog.csv').open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['ID','路徑','年份',*kinds,'別名']);w.writerows([safe(x) for x in r[:-1]] for r in rows)
        with (folder/'index.html').open('x',encoding='utf-8') as f:
            f.write('''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>家庭照片索引</title><style>body{font:16px system-ui;margin:32px;color:#20354b}input{padding:10px;width:70%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{width:100%;border-collapse:collapse}</style><h1>家庭照片索引</h1><p>離線快照；輸入人物、事件、年份或檔名。跨磁碟連結可能需要重新匯出。</p><input id="q" placeholder="搜尋（分號分隔）"><select id="mode"><option value="and">全部符合 AND</option><option value="or">任一符合 OR</option></select><p id="count"></p><table><thead><tr><th>照片</th><th>年份</th><th>人物</th><th>事件</th><th>其他／別名</th></tr></thead><tbody>''')
            for r in rows:
                esc=lambda x:html.escape(str(x),quote=True)
                f.write(f'<tr><td><a href="{esc(r[-1])}">{esc(r[1])}</a></td><td>{esc(r[2])}</td><td>{esc(r[3])}</td><td>{esc(r[4])}</td><td>{esc(" ".join(r[5:-1]))}</td></tr>')
            f.write('''</tbody></table><script>const q=document.getElementById('q'), rows=[...document.querySelectorAll('tbody tr')];function run(){let n=0;const terms=q.value.normalize('NFKC').toLowerCase().split(/[;；,，]/).map(x=>x.trim()).filter(Boolean);for(const r of rows){const t=r.textContent.normalize('NFKC').toLowerCase();r.hidden=terms.length>0 && !(document.getElementById('mode').value==='or'?terms.some(x=>t.includes(x)):terms.every(x=>t.includes(x)));if(!r.hidden)n++}document.getElementById('count').textContent=n+' 筆'}q.addEventListener('input',run);document.getElementById('mode').addEventListener('change',run);run()</script></html>''')
        return len(rows)
