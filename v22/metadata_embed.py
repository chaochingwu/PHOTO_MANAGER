"""Export a metadata-embedded copy using ExifTool. Never edits library originals."""
import json, shutil, subprocess, tempfile, os
from pathlib import Path
from library_catalog import linked

def export_copy(c,folder,ids,executable=None):
    exe=executable or shutil.which('exiftool')
    if not exe:raise RuntimeError('需安裝 ExifTool 並加入 PATH；原始照片未修改')
    folder=Path(folder).resolve()
    for s in c.sources():
        root=Path(s['root']).resolve()
        if folder==root or root in folder.parents:raise ValueError('輸出必須位於來源之外')
    folder.mkdir(parents=True,exist_ok=True);results=[]
    for pid in dict.fromkeys(ids):
        r=c.db.execute('SELECT p.*,s.root FROM photos p JOIN sources s ON s.id=p.source WHERE p.id=?',(pid,)).fetchone()
        if not r:raise ValueError('照片不存在')
        src=Path(r['root'])/r['rel']; ext=src.suffix.lower()
        if ext not in ('.jpg','.jpeg','.tif','.tiff','.png'):results.append((pid,'不支援，請使用 XMP'));continue
        if linked(src):raise ValueError('不處理連結')
        tags=list(dict.fromkeys(t['name'] for t in c.photo_tags(pid)))
        if not tags:results.append((pid,'無 TAG'));continue
        sub=folder/pid;sub.mkdir(exist_ok=True)
        if linked(sub):raise ValueError('輸出含連結')
        dst=sub/src.name
        if dst.exists():raise FileExistsError(str(dst))
        with tempfile.TemporaryDirectory(dir=sub) as tmp:
            p=Path(tmp)/src.name;shutil.copy2(src,p)
            def call(args):return subprocess.run([str(exe),*args,str(p)],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True,timeout=120).stdout
            before=json.loads(call(['-j','-XMP-dc:Subject']))[0].get('Subject',[])
            if isinstance(before,str):before=[before]
            missing=[t for t in tags if t not in before]
            if missing:call(['-overwrite_original',*[f'-XMP-dc:Subject+={t}' for t in missing]])
            after=json.loads(call(['-j','-XMP-dc:Subject']))[0].get('Subject',[])
            if isinstance(after,str):after=[after]
            if not set(before+tags)<=set(after):raise ValueError('Metadata 回讀驗證失敗')
            os.link(p,dst)
        results.append((pid,str(dst)))
    return results
