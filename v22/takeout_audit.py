"""Non-destructive Takeout audit. Cross-archive exact folder/title matching.
No extraction, deletion or writes to media. Durable per-member hash checkpoint.
"""
import argparse, hashlib, json, sqlite3, zipfile, re
from pathlib import Path, PurePosixPath
from collections import defaultdict, Counter
from library_catalog import MEDIA

def digest(stream):
    h=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def audit(folder,checkpoint,library=None,progress=lambda s:None):
    folder=Path(folder).resolve();checkpoint=Path(checkpoint).resolve()
    if library and checkpoint==Path(library).resolve():raise ValueError('checkpoint 不可使用主資料庫')
    if checkpoint==folder or folder in checkpoint.parents:raise ValueError('checkpoint 必須在來源之外')
    archives=sorted(folder.glob('*.zip')); incomplete=sorted(p.name for p in folder.glob('*.crdownload'))
    if not archives:raise ValueError('找不到 ZIP')
    checkpoint.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(checkpoint);db.execute('CREATE TABLE IF NOT EXISTS hashes(key TEXT PRIMARY KEY,sha TEXT)')
    media=[];meta=defaultdict(list);errors=[];people=Counter();json_count=0
    def cached(key,op):
        row=db.execute('SELECT sha FROM hashes WHERE key=?',(key,)).fetchone()
        if row:return row[0]
        sha=op()
        with db:db.execute('INSERT OR REPLACE INTO hashes VALUES(?,?)',(key,sha))
        return sha
    try:
        for i,p in enumerate(archives):
            progress(f'索引 {i+1}/{len(archives)} {p.name}')
            try:
                st=p.stat()
                with zipfile.ZipFile(p) as z:
                    names=Counter(x.filename for x in z.infolist())
                    for n,info in enumerate(z.infolist()):
                        progress(f"索引 {i+1}/{len(archives)} · {n+1}/{len(z.infolist())}")
                        if info.is_dir():continue
                        if names[info.filename]>1:errors.append([p.name,info.filename,"ZIP 內重複路徑"]);continue
                        path=PurePosixPath(info.filename)
                        if path.is_absolute() or '..' in path.parts or '\\' in info.filename:errors.append([p.name,info.filename,'不安全路徑']);continue
                        if path.suffix.lower()=='.json':
                            try:
                                if info.file_size>8*1024*1024:raise ValueError('JSON 過大')
                                data=json.loads(z.read(info));json_count+=1
                                title=data.get('title') if isinstance(data,dict) else None
                                if isinstance(title,str) and PurePosixPath(title).name==title:
                                    meta[(str(path.parent),title)].append(data)
                            except Exception as e:errors.append([p.name,info.filename,str(e)])
                        elif path.suffix.lower() in MEDIA:
                            try:
                                key=json.dumps([str(p),st.st_size,st.st_mtime_ns,n,info.CRC,info.file_size])
                                def read():
                                    with z.open(info) as f:return digest(f)
                                sha=cached(key,read);media.append(dict(zip=p.name,member=info.filename,sha256=sha,size=info.file_size))
                            except Exception as e:errors.append([p.name,info.filename,str(e)])
            except InterruptedError:raise
            except Exception as e:errors.append([p.name,'',str(e)])
        library_hashes=set();library_count=0
        if library:
            from catalog import Catalog
            c=Catalog(library)
            try:
                for r in c.db.execute("SELECT p.*,s.root FROM photos p JOIN sources s ON p.source=s.id WHERE s.role IN ('primary','independent')"):
                    p=Path(r['root'])/r['rel']
                    progress(f'主庫雜湊 {library_count+1}：{p.name}')
                    try:
                        st=p.stat();key=json.dumps(['file',str(p),st.st_size,st.st_mtime_ns]);
                        def read():
                            with p.open('rb') as f:return digest(f)
                        library_hashes.add(cached(key,read));library_count+=1
                    except Exception as e:errors.append(['library',str(p),str(e)])
            finally:c.close()
        seen=set();counts=Counter()
        for m in media:
            p=PurePosixPath(m['member']);matches=meta.get((str(p.parent),p.name),[])
            # Multiple distinct JSONs are ambiguous, not guessed.
            unique={json.dumps(x,sort_keys=True,ensure_ascii=False):x for x in matches}
            data=next(iter(unique.values())) if len(unique)==1 else {}
            m['metadata_status']='matched' if data else 'ambiguous' if matches else 'missing'
            m['photoTakenTime']=data.get('photoTakenTime');m['geoData']=data.get('geoData');m['description']=data.get('description')
            names=[]
            for person in data.get('people',[]) if isinstance(data.get('people'),list) else []:
                if isinstance(person,dict) and isinstance(person.get('name'),str) and person['name'].strip():names.append(person['name'].strip())
            m['people']=sorted(set(names));people.update(m['people']);sha=m['sha256'];m['duplicate']='library' if sha in library_hashes else 'batch' if sha in seen else 'new_candidate';seen.add(sha);counts[m['duplicate']]+=1;counts[m['metadata_status']]+=1
        return dict(archives=[p.name for p in archives],incomplete=incomplete,json_count=json_count,library_files_hashed=library_count,library_comparison=bool(library),counts=dict(counts),people=dict(people),errors=errors,media=media,verified=False)
    finally:db.close()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('folder');ap.add_argument('--checkpoint',required=True);ap.add_argument('--library');ap.add_argument('--report',required=True);a=ap.parse_args();out=Path(a.report).resolve();src=Path(a.folder).resolve()
    if out==src or src in out.parents:raise ValueError('報告必須在來源之外')
    result=audit(src,a.checkpoint,a.library,print);out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(out);print(result['counts'], 'errors:',len(result['errors']))
if __name__=='__main__':main()
