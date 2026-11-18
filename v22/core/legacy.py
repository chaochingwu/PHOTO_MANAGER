import os, re, json, sqlite3, hashlib, shutil, subprocess, datetime as dt, threading, queue, time, csv, uuid
from pathlib import Path
MEDIA=set('.jpg .jpeg .png .heic .heif .tif .tiff .webp .gif .bmp .dng .raw .cr2 .cr3 .nef .arw .orf .raf .rw2 .mov .mp4 .m4v .avi .mts .m2ts .mkv .3gp .wmv .mpg .mpeg'.split())
VIDEO=set('.mov .mp4 .m4v .avi .mts .m2ts .mkv .3gp .wmv .mpg .mpeg'.split())
SEARCH='ext:'+';'.join(sorted(x[1:] for x in MEDIA))
DATE=re.compile(r'(?<!\d)((?:19|20)\d{2})[-_:]?(\d{2})[-_:]?(\d{2})(?!\d)')
FINAL=re.compile(r'^(?:截圖_)?(\d{4}-\d{2}-\d{2})_(\d{3,})$')
SKIP={'99_log','95_duplicates','95_review','98_trash','.photo_manager'}
GENERIC=re.compile(r'^(?:dcim|camera|photos?|pictures?|images?|videos?|google photos|google takeout|takeout|google 相簿|新資料夾.*|\d{3}apple|\d{4}(?:-\d{2})?|pc[-_ ]?\d+|手機備份|相機備份|下載照片|00_inbox)$',re.I)
def dateparse(s):
    m=DATE.search(str(s or ''))
    if m:
        try:return dt.date(*map(int,m.groups())).isoformat()
        except ValueError:pass

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def linked(p):return p.is_symlink() or getattr(os.path,'isjunction',lambda x:False)(p)
def scan(root, inbox=False):
    base=root/'00_INBOX' if inbox else root
    for folder,dirs,names in os.walk(base,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d.lower() not in SKIP and not linked(Path(folder)/d))
        for n in sorted(names):
            p=Path(folder)/n
            if p.suffix.lower() in MEDIA and not linked(p):yield p

def sidecar(p):
    for q in (p.with_name(p.name+'.supplemental-metadata.json'),p.with_name(p.name+'.json'),p.with_name(p.name+'.takeout.json'),p.with_suffix('.json')):
        try:
            j=json.loads(q.read_text(encoding='utf-8-sig'))
            if not isinstance(j,dict):continue
            if j.get('title') and j['title']!=p.name and not q.name.endswith('.takeout.json'):continue
            if j.get('photoTakenTime'):return q,j
        except (OSError,ValueError,TypeError):pass
    return None,{}
def event(root,p):
    parts=p.relative_to(root).parts[:-1]
    return [x for x in parts if not GENERIC.fullmatch(x) and not re.fullmatch(r'Photos from \d{4}',x,re.I)]
def getdate(p,raw,ev):
    q,j=sidecar(p)
    d=dateparse(raw.get('DateTimeOriginal'))
    if d:return d,'EXIF',q
    try:return dt.datetime.fromtimestamp(int(j['photoTakenTime']['timestamp']),dt.timezone(dt.timedelta(hours=8))).date().isoformat(),'Takeout JSON',q
    except (KeyError,ValueError,TypeError,OverflowError,OSError):pass
    for k in ('CreationDate','CreateDate','MediaCreateDate','TrackCreateDate'):
        d=dateparse(raw.get(k))
        if d:return d,k,q
    d=dateparse(p.stem)
    if d:return d,'檔名',q
    for x in reversed(ev):
        d=dateparse(x)
        if d:return d,'事件日期',q
    return dt.datetime.fromtimestamp(p.stat().st_mtime).date().isoformat(),'FileModifyDate',q

def exif_path():
    return next((str(p) for p in [Path(getattr(__import__('sys'),'_MEIPASS',Path(__import__('sys').executable).parent))/'exiftool.exe' if getattr(__import__('sys'),'frozen',False) else Path(__file__).resolve().parent/'exiftool.exe',Path(__file__).resolve().parent/'exiftool'] if p.is_file()),None) or shutil.which('exiftool')
_exif_runtime=None

def portable_exif(exe):
    """Windows Perl launcher requires an ASCII runtime path; media paths remain UTF-8."""
    global _exif_runtime
    if not exe or os.name!='nt' or str(exe).isascii():return exe
    if _exif_runtime is not None:return str(Path(_exif_runtime.name)/'exiftool.exe')
    import tempfile, atexit
    source=Path(exe)
    for base in (tempfile.gettempdir(),os.environ.get('PUBLIC'),os.environ.get('ProgramData')):
        if not base or not str(base).isascii():continue
        runtime=None
        try:
            runtime=tempfile.TemporaryDirectory(prefix='PHOTO_MANAGER_exif_',dir=base)
            dest=Path(runtime.name)
            shutil.copy2(source,dest/'exiftool.exe')
            shutil.copytree(source.parent/'exiftool_files',dest/'exiftool_files')
            _exif_runtime=runtime
            atexit.register(runtime.cleanup)
            return str(dest/'exiftool.exe')
        except OSError:
            if runtime:runtime.cleanup()
    raise RuntimeError('無法建立英文 ExifTool 暫存路徑，請將程式放在英文資料夾')

def pillow_metadata(p):
    try:
        from PIL import Image
        with Image.open(p) as im:
            e=im.getexif(); sub=e.get_ifd(34665)
            return {k:str(v) for k,v in {'Make':e.get(271),'Model':e.get(272),'Software':e.get(305),'ImageDescription':e.get(270),'DateTimeOriginal':sub.get(36867) or e.get(36867),'CreateDate':sub.get(36868) or e.get(306)}.items() if v}
    except Exception:return {}

def batchmeta(paths,exe,log=lambda s:None):
    out={}
    for i in range(0,len(paths),40):
        chunk=paths[i:i+40]; rows=[]; r=None
        try:
            if not exe:raise RuntimeError('找不到 ExifTool')
            exe=portable_exif(exe)
            # UTF-8 argument file avoids Windows ANSI command-line filename conversion.
            args=['-charset','filename=UTF8','-j','-DateTimeOriginal','-CreateDate','-MediaCreateDate','-TrackCreateDate','-Keys:CreationDate','-ContentIdentifier','-Software','-ImageDescription','-Make','-Model',*[str(p.absolute()) for p in chunk]]
            r=subprocess.run([exe,'-charset','filename=UTF8','-@','-'],input=('\n'.join(args)+'\n').encode('utf-8'),capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            raw=r.stdout.decode('utf-8-sig',errors='replace'); rows=json.loads(raw)
            if not isinstance(rows,list):raise ValueError('ExifTool JSON 非陣列')
            if r.returncode:log(f'ExifTool 回傳 {r.returncode}：'+r.stderr.decode('utf-8',errors='replace')[:500])
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as e:
            log(f'ExifTool 批次失敗（{chunk[0]} 等 {len(chunk)} 筆）：{e}；改用 Pillow / 其他日期來源')
            if r is not None:log('ExifTool stderr: '+r.stderr.decode('utf-8',errors='replace')[:500])
            rows=[]
        for row in rows:
            if isinstance(row,dict) and isinstance(row.get('SourceFile'),str):out[os.path.normcase(os.path.abspath(row['SourceFile']))]=row
        for p in chunk:
            key=os.path.normcase(os.path.abspath(p)); row=out.get(key,{})
            if not row or row.get('Error'):
                log(f'中繼資料備援：{p}');out[key]=pillow_metadata(p)
    return out

def safe_copy(p,d,h):
    d.parent.mkdir(parents=True,exist_ok=True)
    if d.exists():
        if d.is_file() and digest(d)==h:return
        raise FileExistsError(f'不同內容，不覆蓋：{d}')
    tmp=d.with_name(d.name+'.pm-'+uuid.uuid4().hex+'.tmp')
    try:
        shutil.copy2(p,tmp)
        if digest(tmp)!=h:raise IOError('複製驗證失敗')
        # hard link publishes without overwrite, including on NTFS
        os.rename(tmp,d) if os.name=="nt" else os.link(tmp,d)
    finally:
        if tmp.exists():tmp.unlink()

def valid_paths(root,backup):
    root=Path(root).resolve(); backup=Path(backup).resolve() if backup else None
    if not root.is_dir() or root==Path(root.anchor):raise ValueError('請選擇存在的照片資料夾，不可選磁碟根目錄')
    if backup and (backup==Path(backup.anchor) or root==backup or root in backup.parents or backup in root.parents):raise ValueError('備份路徑不可為磁碟根目錄、相同或互相包含')
    return root,backup
# V1.3: preserve V1.3 metadata/date helpers; replace archive/backup engine.
from everything_search import PHOTO_EXT, VIDEO_EXT, search_command
PHOTO={'.'+x for x in PHOTO_EXT}
VIDEO={'.'+x for x in VIDEO_EXT}
MEDIA=PHOTO|VIDEO
SEARCH=search_command(PHOTO_EXT,VIDEO_EXT)
SKIP |= {'system'}
GENERIC=re.compile(GENERIC.pattern.replace('00_inbox','00_inbox|PHOTOS|VIDEOS|INBOX|截圖'),re.I)
try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError: pass
except ImportError:
    Image=None

def signature(p):
    if Image is None:return None
    try:
        with Image.open(p) as im:
            im=ImageOps.exif_transpose(im); w,h=im.size
            if min(w,h)<16 or getattr(im,"n_frames",1)>1 or p.suffix.lower() not in {".jpg",".jpeg",".png",".heic",".heif",".jfif"}:return None
            rgb=im.convert('RGB').resize((24,24),Image.Resampling.LANCZOS)
            data=tuple(v for pix in (rgb.get_flattened_data() if hasattr(rgb,"get_flattened_data") else rgb.getdata()) for v in pix)
            # Quality proxy: resolution first; same resolution retains existing version.
            return (w*h,w/h,data)
    except Exception:return None

def similar(a,b):
    if not a or not b or abs(a[1]/b[1]-1)>0.025:return False
    # Conservative threshold, not a guarantee of identity. No flat-color matches.
    x,y=a[2],b[2]
    if max(x)-min(x)<35 or max(y)-min(y)<35:return False
    return sum(abs(i-j) for i,j in zip(x,y))/len(x)<=0.35

def category(p):return 'VIDEOS' if p.suffix.lower() in VIDEO else 'PHOTOS'
