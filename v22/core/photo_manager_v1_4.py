import os, sys, json, sqlite3, shutil, uuid, time, threading, queue, traceback, datetime
from pathlib import Path
import legacy as core
from version import APP_VERSION as VERSION
NS=uuid.UUID('c384cb27-67ba-4c5d-b9f1-59835c32cb23')
def uid(h): return str(uuid.uuid5(NS,h))
def checkroot(p):
    p=Path(p).resolve()
    if not p.is_dir() or p==Path(p.anchor): raise ValueError('照片庫必須是已存在的非磁碟根資料夾')
    return p
def paths_ok(paths):
    for i,p in enumerate(paths):
        for q in paths[:i]:
            if p==q or p in q.parents or q in p.parents: raise ValueError('照片庫不可相同或互相包含')
def atomic_json(p,obj):
    t=p.with_suffix('.tmp');t.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8');os.replace(t,p)
def archive_files(root):
    for cat in ('PHOTOS','VIDEOS','截圖'):
        base=root/cat
        if not base.is_dir(): raise IOError(f'正式目錄不存在：{base}')
        def fail(e): raise e
        for folder,dirs,names in os.walk(base,onerror=fail,followlinks=False):
            if any(core.linked(Path(folder)/d) for d in dirs):raise IOError('正式庫包含連結目錄，禁止刪除同步')
            for n in names:
                p=Path(folder)/n
                if p.suffix.lower() in core.MEDIA and not core.linked(p): yield p
class Library:
    def __init__(self,root,create=True):
        self.root=checkroot(root);self.sys=self.root/'.PHOTO_MANAGER';
        if not create and not (self.sys/'identity.json').is_file():raise IOError('未登錄照片庫，請先建立或初始化')
        self.sys.mkdir(exist_ok=True)
        self.identity=self.sys/'identity.json'; dbpath=self.sys/'library.db'
        if self.identity.exists():
            self.info=json.loads(self.identity.read_text(encoding='utf-8'));self.id=self.info['uuid']
            if not dbpath.exists():raise IOError('索引遺失，禁止自動重建及刪除同步')
        else:
            if not create:raise IOError('未登錄照片庫')
            self.id=str(uuid.uuid4());self.info={'uuid':self.id}
            for n in ('PHOTOS','VIDEOS','截圖','00_INBOX','99_LOG'):(self.root/n).mkdir(exist_ok=True)
        (self.root/'截圖').mkdir(exist_ok=True)
        self.db=sqlite3.connect(dbpath)
        self.db.executescript('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,sha TEXT,size INTEGER,mtime INTEGER); CREATE INDEX IF NOT EXISTS hash_idx ON files(sha); CREATE TABLE IF NOT EXISTS tomb(sha TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS highwater(cat TEXT,day TEXT,n INTEGER,PRIMARY KEY(cat,day)); CREATE TABLE IF NOT EXISTS peers(id TEXT PRIMARY KEY);')
        self.db.commit()
        if not self.identity.exists():atomic_json(self.identity,self.info)
    def close(self):self.db.close()
    def verify(self):
        if json.loads(self.identity.read_text(encoding='utf-8'))['uuid']!=self.id:raise IOError('照片庫身分改變')
    def rows(self):return {r[0]:r[1:] for r in self.db.execute('SELECT path,sha,size,mtime FROM files')}
    def tombs(self):return {r[0] for r in self.db.execute('SELECT sha FROM tomb')}
    def resume(self,log=print,stop=lambda:None):
        if (self.sys/'organize_pending.json').exists():
            from organize import execute_moves
            self.verify();execute_moves(self.root,[],log,stop)
            log('已復原前次中斷交易')
            self.scan(log,stop,detect=False,force_hash=True)
    def scan(self,log=print,stop=lambda:None,detect=True,force_hash=False):
        self.verify();
        if (self.sys/'organize_pending.json').exists():raise IOError('整理交易未完成，請先續作')
        old=self.rows();new={}
        for i,p in enumerate(archive_files(self.root)):
            stop();rel=p.relative_to(self.root).as_posix();st=p.stat();o=old.get(rel)
            h=o[0] if not force_hash and o and o[1:]==(st.st_size,st.st_mtime_ns) else core.digest(p)
            new[rel]=(h,st.st_size,st.st_mtime_ns)
            if (i+1)%1000==0:log(f'掃描 {self.root}：已處理 {i+1} 筆')
        self.verify();missing={v[0] for k,v in old.items() if k not in new}-{v[0] for v in new.values()}
        if detect and missing and (len(missing)>500 or len(missing)>max(10,len(old)*.15)):
            raise IOError(f'異常大量刪除 {len(missing)} 筆，停止同步；請檢查主庫')
        with self.db:
            if detect:self.db.executemany('INSERT OR IGNORE INTO tomb VALUES(?)',[(h,) for h in missing])
            self.db.execute('DELETE FROM files');self.db.executemany('INSERT INTO files VALUES(?,?,?,?)',[(k,*v) for k,v in new.items()])
            for k in new:
                p=Path(k);m=core.FINAL.fullmatch(p.stem)
                if m:self.db.execute('INSERT INTO highwater VALUES(?,?,?) ON CONFLICT(cat,day) DO UPDATE SET n=max(n,excluded.n)',(p.parts[0],m[1],int(m[2])))
        log(f'掃描完成 {self.root}：{len(new)} 個媒體檔案')
        return new
    def allocate(self,rel):
        p=Path(rel);m=core.FINAL.fullmatch(p.stem)
        if not m:raise ValueError(f'非正式命名：{rel}，請先整理')
        cat,day=p.parts[0],m[1];r=self.db.execute('SELECT n FROM highwater WHERE cat=? AND day=?',(cat,day)).fetchone();n=max(int(m[2]),r[0] if r else 0)+1
        while True:
            q=p.with_name(('截圖_' if p.stem.startswith('截圖_') else '')+f'{day}_{n:03d}'+p.suffix)
            if not (self.root/q).exists():break
            n+=1
        with self.db:self.db.execute('INSERT OR REPLACE INTO highwater VALUES(?,?,?)',(cat,day,n))
        return q.as_posix()
    def copy(self,source,rel,dest,h):
        self.verify();source.verify();p=source.root/rel;d=self.root/dest
        if core.digest(p)!=h:raise IOError('來源內容已變更')
        core.safe_copy(p,d,h)
        q=p.with_name(p.name+'.takeout.json')
        if q.exists():core.safe_copy(q,d.with_name(d.name+'.takeout.json'),core.digest(q))
        st=d.stat()
        with self.db:self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?)',(dest,h,st.st_size,st.st_mtime_ns))
    def remove(self,rel,h,log):
        self.verify();p=self.root/rel
        if not p.exists():return
        if core.digest(p)!=h:raise IOError('刪除前驗證失敗')
        trash=self.sys/'recovery'/uuid.uuid4().hex/rel;trash.parent.mkdir(parents=True,exist_ok=True)
        os.rename(p,trash)
        q=p.with_name(p.name+'.takeout.json')
        if q.exists():os.rename(q,trash.with_name(trash.name+'.takeout.json'))
        with self.db:self.db.execute('DELETE FROM files WHERE path=?',(rel,))
        log(f'同步移除（可復原）：{self.root / rel} → {trash}')
def pair_units(rows):
    """Recognize unambiguous archive photo/video pairs by shared relative stem."""
    groups={}
    for rel in rows:
        p=Path(rel)
        if p.parts[0] not in ('PHOTOS','VIDEOS'):continue
        key=(tuple(p.parts[1:-1]),p.stem.casefold())
        groups.setdefault(key,[]).append(rel)
    pairs={};protected=set()
    for group in groups.values():
        photos=[r for r in group if Path(r).parts[0]=='PHOTOS']
        videos=[r for r in group if Path(r).parts[0]=='VIDEOS']
        if not photos or not videos:continue
        protected.update(group)
        if len(photos)!=1 or len(videos)!=1:raise IOError('Live Photo 配對不明確，請先整理：'+str(group))
        a,b=photos[0],videos[0];pairs.setdefault((rows[a][0],rows[b][0]),(a,b))
    return pairs,protected

def transfer_pairs(src,dst,rows,existing,log,stop,year=None):
    from organize import execute_moves
    pairs,_=pair_units(rows);known,_=pair_units(existing);count=0
    for sig,rels in pairs.items():
        stop()
        if year and not Path(rels[0]).name.startswith(year+'-'):continue
        if sig in known:continue
        # Reserve a shared sequence across both categories, including different extensions.
        paths=[Path(r) for r in rels];m=core.FINAL.fullmatch(paths[0].stem)
        if not m:raise IOError('Live Photo 尚未正式命名，請先整理')
        day=m[1];n=int(m[2]);occupied={ (tuple(Path(r).parts[1:-1]),Path(r).stem.casefold()) for r in existing if Path(r).parts[0] in ('PHOTOS','VIDEOS') }
        while True:
            stem=f'{day}_{n:03d}';dest=[p.with_name(stem+p.suffix).as_posix() for p in paths]
            if all((tuple(p.parts[1:-1]),stem.casefold()) not in occupied for p in paths) and not any((dst.root/r).exists() for r in dest):break
            n+=1
        if shutil.disk_usage(dst.root).free<sum(rows[r][1] for r in rels)+1024*1024:raise IOError('Live Photo 備份空間不足')
        token=uuid.uuid4().hex;stage=dst.sys/'pair_stage'/token;stage.mkdir(parents=True)
        entries=[]
        try:
            for i,(rel,d,h) in enumerate(zip(rels,dest,sig)):
                src.verify();dst.verify();p=src.root/rel;t=stage/str(i)
                core.safe_copy(p,t,h);entries.append((t,dst.root/d,h))
                q=p.with_name(p.name+'.takeout.json')
                if q.exists():
                    hq=core.digest(q);tq=stage/(str(i)+'.json');core.safe_copy(q,tq,hq);entries.append((tq,(dst.root/d).with_name(Path(d).name+'.takeout.json'),hq))
            execute_moves(dst.root,entries,log,stop)
        finally:
            if not (dst.sys/'organize_pending.json').exists():shutil.rmtree(stage,ignore_errors=True)
        for d,h in zip(dest,sig):
            st=(dst.root/d).stat();existing[d]=(h,st.st_size,st.st_mtime_ns)
            with dst.db:dst.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?)',(d,h,st.st_size,st.st_mtime_ns))
        known[sig]=tuple(dest);count+=2;log(f'Live Photo 完整配對複製：{dest}')
    return count

def backup(main,target,log=print,stop=lambda:None,year=None,mode="單向備份"):
    a,b=checkroot(main),checkroot(target);paths_ok([a,b]);src=Library(a,create=False)
    try:
        dst=Library(b,create=False)
        try:
            if src.id==dst.id:raise IOError('重複照片庫 UUID')
            def snapshot(lib):
                lib.verify();result={}
                if (lib.sys/'organize_pending.json').exists():raise IOError('整理交易未完成')
                for p in archive_files(lib.root):
                    stop();st=p.stat();result[p.relative_to(lib.root).as_posix()]=(core.digest(p),st.st_size,st.st_mtime_ns)
                lib.verify();log(f'備份掃描 {lib.root}：{len(result)} 個媒體檔案');return result
            src.resume(log,stop);dst.resume(log,stop)
            rows=snapshot(src);existing=snapshot(dst)
            pair_count=transfer_pairs(src,dst,rows,existing,log,stop,year)
            _,protected=pair_units(rows)
            hashes={v[0] for v in existing.values()};ops=[]
            def slot(rel):
                p=Path(rel);return (tuple(p.parts[1:-1]),p.stem.casefold())
            occupied={slot(r) for r in existing if Path(r).parts[0] in ('PHOTOS','VIDEOS')}

            for rel,(h,size,mt) in rows.items():
                if rel in protected:continue
                if year and not Path(rel).name.removeprefix("截圖_").startswith(year+"-"):continue
                if h in hashes:continue
                dest=rel if not (b/rel).exists() else dst.allocate(rel)
                if Path(dest).parts[0] in ('PHOTOS','VIDEOS'):
                    while slot(dest) in occupied:dest=dst.allocate(dest)
                    occupied.add(slot(dest))
                ops.append((rel,dest,h,size));hashes.add(h)
            if shutil.disk_usage(b).free<sum(x[3] for x in ops)+1024*1024:raise IOError('備份空間不足')
            for i,(rel,dest,h,size) in enumerate(ops,1):
                stop();dst.copy(src,rel,dest,h);log(f'單向備份 {i}/{len(ops)}：{a/rel} → {b/dest}')
            log(f'{mode}完成：{len(ops)+pair_count} 筆；不傳播刪除')
        finally:dst.close()
    finally:src.close()

def sync(main,targets,log=print,stop=lambda:None):
    targets=list(targets)
    paths_ok([checkroot(main)]+[checkroot(p) for p,m,y in targets])
    for p,m,y in targets:
        if m not in ('full','import','partial','backup'):raise ValueError('未知同步模式')
        if m=='partial' and (len(y)!=4 or not y.isdigit()):raise ValueError('年份須為四位數')
    # Isolate non-deleting modes from full-sync tombstones and name reconciliation.
    for p,m,y in targets:
        if m=='import':backup(p,main,log,stop,mode='僅匯入')
        elif m=='partial':
            log(f'指定年份 {y}：雙向合併，不傳播刪除')
            backup(main,p,log,stop,year=y,mode=f'指定年份 {y} 去程')
            backup(p,main,log,stop,year=y,mode=f'指定年份 {y} 回程')
    full=[(p,m,y) for p,m,y in targets if m=='full']
    if full:_sync(main,full,log,stop)
    for p,m,y in targets:
        if m=='backup':backup(main,p,log,stop)

def _sync(main,targets,log=print,stop=lambda:None):
    # targets: (path, full/import/partial, year); import always target -> main.
    libs=[]
    try:
        specs=[(checkroot(main),'full','')]+[(checkroot(p),m,y) for p,m,y in targets];paths_ok([x[0] for x in specs])
        for p,m,y in specs:libs.append((Library(p,create=False),m,y))
        if len({l.id for l,m,y in libs})!=len(libs):raise IOError('重複照片庫 UUID，禁止同步')
        groups={l.info.get('group') for l,m,y in libs if m=='full' and l.info.get('group')}
        if len(groups)>1 or (groups and any(not l.info.get('group') for l,m,y in libs if m=='full')):raise IOError('不同照片庫群組，請使用僅匯入，不可完整同步')
        for l,m,y in libs:l.resume(log,stop)
        rows={l.id:l.scan(log,stop,detect=m=='full' and any(tm=='full' for _,tm,_ in libs[1:])) for l,m,y in libs}
        full=[l for l,m,y in libs if m=='full']; primary=full[0]
        pair_count=0
        for src in full:
            for dst in full:
                if src!=dst:pair_count+=transfer_pairs(src,dst,rows[src.id],rows[dst.id],log,stop)
        # Canonical pair paths: primary names first, reserve both category slots.
        # Never overwrite unrelated files or split a pair during reconciliation.
        from organize import execute_moves
        canonical={}; reserved=set()
        def slot(rel):
            p=Path(rel);return (tuple(p.parts[1:-1]),p.stem.casefold())
        for l in full:
            pairs,protected_local=pair_units(rows[l.id])
            reserved.update(slot(r) for r in rows[l.id] if r not in protected_local and Path(r).parts[0] in ('PHOTOS','VIDEOS'))
        for l in full:
            pairs,_=pair_units(rows[l.id])
            for sig,rels in pairs.items():
                if sig in canonical:continue
                paths=[Path(r) for r in rels];m=core.FINAL.fullmatch(paths[0].stem)
                if not m:raise IOError('Live Photo 尚未正式命名')
                n=int(m[2]);day=m[1]
                while True:
                    dest=tuple(p.with_name(f'{day}_{n:03d}'+p.suffix).as_posix() for p in paths)
                    if not any(slot(r) in reserved for r in dest):break
                    n+=1
                canonical[sig]=dest;reserved.update(slot(r) for r in dest)
        for l in full:
            pairs,_=pair_units(rows[l.id]);moves=[]
            for sig,rels in pairs.items():
                for rel,d,h in zip(rels,canonical[sig],sig):
                    if rel==d:continue
                    p=l.root/rel;dest=l.root/d;moves.append((p,dest,h))
                    q=p.with_name(p.name+'.takeout.json')
                    if q.exists():moves.append((q,dest.with_name(dest.name+'.takeout.json'),core.digest(q)))
            execute_moves(l.root,moves,log,stop)
            rows[l.id]=l.scan(log,stop,detect=False,force_hash=True)
        protected={l.id:pair_units(rows[l.id])[1] for l in full}
        pair_hashes={rows[l.id][r][0] for l in full for r in protected[l.id]}
        tomb=(set().union(*(l.tombs() for l in full)) if len(full)>1 else set())-pair_hashes; sources={}
        if pair_hashes:log('Live Photo 配對成員禁止單檔刪除傳播；配對刪除需人工確認')
        for l,m,y in libs:
            for rel,(h,size,mt) in rows[l.id].items():
                if m=='partial' and not Path(rel).name.removeprefix('截圖_').startswith(y+'-'):continue
                if rel not in protected[l.id] and h not in tomb:sources.setdefault(h,(l,rel,size))
        # choose common canonical paths, deterministic; preserve existing primary names first
        chosen={};used=set();standalone_slots=set();pair_slots={slot(r) for dest in canonical.values() for r in dest}
        for h,(l,rel,size) in sources.items():
            dest=rel
            if dest.casefold() in used:dest=primary.allocate(rel)
            while dest.casefold() in used or (Path(dest).parts[0] in ('PHOTOS','VIDEOS') and slot(dest) in (pair_slots|standalone_slots)):dest=primary.allocate(dest)
            chosen[h]=dest;used.add(dest.casefold())
            if Path(dest).parts[0] in ('PHOTOS','VIDEOS'):standalone_slots.add(slot(dest))
        plans=[]
        for l,m,y in libs:
            if m=='import':continue
            existing=rows[l.id];byhash={v[0]:k for k,v in existing.items()};ops=[]
            for h,(src,rel,size) in sources.items():
                dest=chosen[h]
                if m=='partial' and not Path(dest).name.removeprefix('截圖_').startswith(y+'-'):continue
                if h in byhash:continue
                if dest in existing and existing[dest][0]!=h:dest=l.allocate(dest)
                ops.append((src,rel,dest,h,size))
            need=sum(x[4] for x in ops)
            if shutil.disk_usage(l.root).free<need+1024*1024:raise IOError(f'空間不足：{l.root}，需 {need:,} bytes')
            plans.append((l,m,y,ops))
        # copy first, then propagate tombstones; interrupted copy is idempotent
        total=sum(len(x[3]) for x in plans);done=0
        for l,m,y,ops in plans:
            for src,rel,dest,h,size in ops:
                stop();l.copy(src,rel,dest,h);done+=1;log(f'同步 {done}/{total}：{dest}')
        for l,m,y,ops in plans:
            if m!='full':continue
            with l.db:l.db.executemany('INSERT OR IGNORE INTO tomb VALUES(?)',[(h,) for h in tomb])
            for rel,(h,_,__) in list(l.rows().items()):
                stop()
                if h in tomb:l.remove(rel,h,log)
        # Reconcile names after copying and tombstone removal; stage swaps safely.
        from organize import execute_moves
        for l in full:
            current=l.rows();moves=[];seen=set()
            for rel,(h,_,__) in sorted(current.items()):
                if rel in protected[l.id] or h not in chosen or h in seen:continue
                seen.add(h);dest=chosen[h]
                if rel==dest:continue
                p,d=l.root/rel,l.root/dest
                moves.append((p,d,h))
                q=p.with_name(p.name+'.takeout.json')
                if q.exists():moves.append((q,d.with_name(d.name+'.takeout.json'),core.digest(q)))
            moving={p for p,d,h in moves}
            if any(d.exists() and d not in moving for p,d,h in moves):raise IOError('同步名稱衝突，保留檔案，請先整理重複檔案')
            execute_moves(l.root,moves,log,stop)
            l.scan(log,stop,detect=False,force_hash=True)
        log(f'同步完成：複製 {done+pair_count} 筆；完整庫 {len(full)} 個。')
    finally:
        for l,m,y in libs:l.close()
