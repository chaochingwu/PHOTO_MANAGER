"""V1.5 historical archive: deterministic planning and resumable moves."""
import datetime as dt, json, os, re, uuid
from pathlib import Path
import legacy as core
from screenshot_detect import classify_image
CATS=('PHOTOS','VIDEOS','截圖')
SCREEN=re.compile(r'screen[ _-]?(?:shot|capture)|截圖|螢幕(?:快照|擷取)|屏幕截图|snipping tool|snip & sketch',re.I)

def screenshot(p,raw,root):
    if p.suffix.lower() not in core.PHOTO:return False
    return p.is_relative_to(root/'截圖') or bool(SCREEN.search(' '.join([p.name,*p.relative_to(root).parts[:-1],str(raw.get('Software','')),str(raw.get('ImageDescription',''))])))

def capture(p,raw,ev):
    day,why,q=core.getdate(p,raw,ev)
    value=raw.get('DateTimeOriginal') if why=='EXIF' else raw.get(why)
    if why=='Takeout JSON':
        _,j=core.sidecar(p)
        value=dt.datetime.fromtimestamp(int(j['photoTakenTime']['timestamp']),dt.timezone(dt.timedelta(hours=8))).strftime('%H:%M:%S')
    m=re.search(r'(\d{2}):(\d{2}):(\d{2})(?:[. +Z-]|$)',str(value or '').split(' ')[-1])
    if not m and why=='FileModifyDate': clock=dt.datetime.fromtimestamp(p.stat().st_mtime).strftime('%H:%M:%S')
    else:clock=':'.join(m.groups()) if m else '99:99:99'
    return day,clock,why,q

def write_journal(path,data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def move(p,d):
    d.parent.mkdir(parents=True,exist_ok=True)
    if d.exists():raise FileExistsError(str(d))
    os.rename(p,d)

def execute_moves(root, entries, log=print, stop=lambda:None):
    journal=root/'.PHOTO_MANAGER'/'organize_pending.json'
    if journal.exists():
        try:data=json.loads(journal.read_text(encoding='utf-8'))
        except (ValueError,OSError) as e:raise IOError(f'交易紀錄損壞，禁止自動搬移：{journal}') from e
    else:
        if not entries:return
        moving={p for p,d,h in entries if p!=d}
        destinations=[d for p,d,h in entries if p!=d]
        if len({str(d).casefold() for d in destinations})!=len(destinations) or any(d.exists() and d not in moving for d in destinations):raise IOError('目的地衝突，未搬移任何檔案')
        token=uuid.uuid4().hex
        data={'phase':'stage','moves':[[str(p.relative_to(root)),str(d.relative_to(root)),f'.PHOTO_MANAGER/staging/{token}/{i}',h] for i,(p,d,h) in enumerate(entries) if p!=d]}
        write_journal(journal,data)
    moves=data['moves']
    if data['phase']=='stage':
        for i,(s,d,t,h) in enumerate(moves):
            stop();p,tmp=root/s,root/t
            if tmp.exists():
                if core.digest(tmp)!=h:raise IOError('暫存雜湊不符')
            else:
                if core.digest(p)!=h:raise IOError('來源已變更：'+s)
                move(p,tmp)
            if i%1000==0:log(f'安全暫存 {i+1}/{len(moves)}')
        data['phase']='publish';write_journal(journal,data)
    for i,(s,d,t,h) in enumerate(moves):
        stop();tmp,dest=root/t,root/d
        if tmp.exists():
            if core.digest(tmp)!=h:raise IOError('暫存內容不符')
            move(tmp,dest)
        elif not dest.exists() or core.digest(dest)!=h:raise IOError('復原驗證失敗：'+d)
        log(f'搬移：{s} → {d}')
    journal.unlink()

def run(root,scope='all',tasks=('screenshots','classify','rename'),partial='',log=print,stop=lambda:None,metadata=None,include_children=True,confirm_plan=None):
    root=Path(root).resolve();journal=root/'.PHOTO_MANAGER'/'organize_pending.json'
    if journal.exists():
        if scope=='partial':raise ValueError('有未完成的整理交易，請先使用原範圍復原；局部整理不會自動執行舊交易')
        execute_moves(root,[],log,stop);log('已完成前次中斷交易；請再次執行新設定');return
    from scope_folders import local_base
    base=local_base(root,partial) if scope=='partial' else root/'00_INBOX' if scope=='inbox' else root
    allpaths=list(core.scan(root))
    if not base.is_dir() or not base.resolve().is_relative_to(root.resolve()):raise ValueError('局部範圍無效')
    selected=[p for p in allpaths if p.is_relative_to(base) and (scope!='partial' or include_children or p.parent==base)]
    if scope=='partial':
        selected_set=set(selected)
        outside={p.stem.casefold() for p in allpaths if p not in selected_set}
        if any(p.stem.casefold() in outside for p in selected):raise ValueError('局部範圍可能跨越 Live Photo 配對；請使用全庫整理')
    meta={}
    for i in range(0,len(selected),40):
        stop();chunk=selected[i:i+40];meta.update(metadata(chunk,core.exif_path()) if metadata else core.batchmeta(chunk,core.exif_path(),log));log(f'讀取日期 {min(i+40,len(selected))}/{len(selected)}')
    records=[];pairs={};ai=None
    if 'screenshots' in tasks:
        try:
            from clip_local import ClipLocal
            ai=ClipLocal();log('CLIP 本機辨識已啟用')
        except Exception as e:log(f'CLIP 無法啟用，使用原有辨識規則：{e}')
    for p in selected:
        stop();raw=meta.get(os.path.normcase(str(p)),{});ev=core.event(root,p);day,clock,why,q=capture(p,raw,ev)
        cat='截圖' if screenshot(p,raw,root) else core.category(p)
        if cat=='PHOTOS' and 'screenshots' in tasks:
            verdict,reason=classify_image(p,raw)
            if ai is not None and verdict!='screen' and '保護原圖' not in reason:
                try:
                    av,kind,scores=ai.classify(p)
                    log(f'CLIP：{p.name}：{kind}；{av}；分數 {scores[kind]:.3f}；照片 {scores["photo"]:.3f}')
                    if av=='screen':verdict,reason='screen','CLIP '+kind
                    elif av=='review':verdict,reason='review','CLIP 分類不確定'
                except Exception as e:log(f'CLIP 略過 {p.name}：{e}')
            if verdict=='screen':cat='截圖';log(f'影像辨識：{p.name}：{reason}')
            elif verdict=='review':log(f'疑似截圖／網路圖（保守歸入 PHOTOS）：{p}：{reason}')
        log(f'日期來源：{p.name} → {day} ({why})')
        # Existing split or original same-stem photo/video pairs retain shared numbering.
        rel=p.relative_to(root);key=(str(Path(*rel.parts[1:-1])) if rel.parts[0] in CATS else str(p.parent),p.stem.casefold())
        identifier=str(raw.get('ContentIdentifier') or '').strip().casefold()
        if identifier and p.suffix.lower() in core.PHOTO|core.VIDEO:
            key=('content-id',identifier)
        r=dict(p=p,cat=cat,day=day,clock=clock,why=why,q=q,key=key,ev=ev,raw=raw);records.append(r);pairs.setdefault(key,[]).append(r)
    protected=set();pairkeys={}
    for key,group in pairs.items():
        if len(group)==2 and {core.category(r['p']) for r in group}=={'PHOTOS','VIDEOS'}:
            a=next(r for r in group if core.category(r['p'])=='PHOTOS');protected.update(r['p'] for r in group)
            for r in group:r['cat']=core.category(r['p']);r['ev']=a['ev']
            for r in group:r['day']=a['day'];r['clock']=a['clock'];pairkeys[r['p']]=key
    # Global exact-match reference, even when only INBOX is selected.
    # Preserve paired media conservatively, including pairs outside the selection.
    global_pairs={}
    for p in allpaths:
        rel=p.relative_to(root)
        key=(str(Path(*rel.parts[1:-1])) if rel.parts[0] in CATS else str(p.parent),p.stem.casefold())
        global_pairs.setdefault(key,[]).append(p)
    for key,group in pairs.items():
        if key[0]=='content-id':global_pairs[key]=[r['p'] for r in group]
    for group in global_pairs.values():
        if any(p.suffix.lower() in core.VIDEO for p in group) and any(p.suffix.lower() in core.PHOTO for p in group):
            protected.update(group)
    duplicates=[]; duplicate_paths=set(); digests={}
    if 'duplicates' in tasks:
        selected_set=set(selected); groups={}
        # Size prefilter avoids hashing unique-sized files solely for deduplication.
        sizes={}
        for p in allpaths:
            stop();sizes.setdefault(p.stat().st_size,[]).append(p)
        for group in sizes.values():
            if len(group)<2 or not any(p in selected_set for p in group):continue
            for p in group:
                stop();h=core.digest(p);digests[p]=h;groups.setdefault(h,[]).append(p)
        # Only remove a complete duplicate pair when both members match another pair.
        pair_groups={}
        for group in global_pairs.values():
            if len(group)!=2 or not all(p in protected for p in group):continue
            photo=next((p for p in group if p.suffix.lower() in core.PHOTO),None)
            video=next((p for p in group if p.suffix.lower() in core.VIDEO),None)
            if not photo or not video:continue
            sig=tuple(digests.get(p) or core.digest(p) for p in (photo,video))
            pair_groups.setdefault(sig,[]).append((photo,video))
        for sig,group in pair_groups.items():
            if len(group)<2:continue
            winner=min(group,key=lambda pair:(any(p not in selected_set for p in pair)==False,any(p.relative_to(root).parts[0] not in CATS for p in pair),str(pair[0]).casefold()))
            for pair in group:
                if pair==winner or not all(p in selected_set for p in pair) or any(core.sidecar(p)[0] for p in pair):continue
                for p,h,w in zip(pair,sig,winner):
                    duplicates.append((p,h,w));duplicate_paths.add(p)
        def priority(p):
            return (p in selected_set, p.relative_to(root).parts[0] not in CATS, p not in protected, str(p).casefold(),str(p))
        for h,group in groups.items():
            if len(group)<2:continue
            winner=min((p for p in group if p not in duplicate_paths),key=priority)
            for p in group:
                if p==winner or p not in selected_set or p in protected or p in duplicate_paths:continue
                # Sidecar metadata may contain unique capture information; retain such copies.
                if core.sidecar(p)[0] is not None:
                    log(f'完全相同但含獨立拍攝資訊，保留：{p}');continue
                duplicates.append((p,h,winner));duplicate_paths.add(p)
        log(f'全庫去重參照：{len(allpaths)} 筆；處理範圍：{len(selected)} 筆')
    active=[r for r in records if r['p'] not in duplicate_paths and (('screenshots' in tasks and r['cat']=='截圖') or ('classify' in tasks or 'rename' in tasks) and r['cat']!='截圖')]
    activepaths={r['p'] for r in active};used={str(p).casefold() for p in allpaths if p not in activepaths};nums={};pairnums={};entries=[];sidecars=set()
    # Reserve shared date/sequence slots for both categories, even for standalone files.
    # Otherwise independent photos and videos can accidentally become a fake Live Photo.
    slots={}
    for p in allpaths:
        if p in activepaths:continue
        rel=p.relative_to(root)
        if rel.parts[0] in ('PHOTOS','VIDEOS'):slots[(tuple(rel.parts[1:-1]),p.stem.casefold())]=None
    for r in sorted(records,key=lambda r:(r['day'],r['clock'],str(r['p']).casefold())):
        stop();p=r['p'];cat=r['cat'];day=r['day']
        if p not in activepaths:continue
        h=digests.get(p) or core.digest(p)
        folder=root/'截圖' if cat=='截圖' else root/cat/day[:4]/day[:7]/Path(*r['ev']) if 'classify' in tasks else p.parent
        if cat=='截圖' or 'rename' in tasks or not core.FINAL.fullmatch(p.stem):
            k=(cat,day);pk=pairkeys.get(p);n=pairnums.get(pk,0) if pk else 0
            if not n:n=max(nums.get(k,0),nums.get(('PHOTOS',day),0) if pk else 0,nums.get(('VIDEOS',day),0) if pk else 0)+1
            while True:
                d=folder/(('截圖_' if cat=='截圖' else '')+f'{day}_{n:03d}'+p.suffix.upper())
                slot=(tuple(d.relative_to(root).parts[1:-1]),d.stem.casefold())
                if str(d).casefold() not in used and (not d.exists() or d in activepaths) and (cat=='截圖' or slot not in slots or (pk is not None and slots[slot]==pk)):break
                n+=1
            nums[k]=max(nums.get(k,0),n)
            if pk:pairnums[pk]=n
            if cat!='截圖':slots[slot]=pk
        else:d=folder/p.name
        if str(d).casefold() in used:raise IOError('目的地衝突：'+str(d))
        used.add(str(d).casefold());entries.append((p,d,h))
        q=r['q']
        if q and p!=d:
            target=d.with_name(d.name+'.takeout.json')
            if target!=q:
                # Preserve original JSON; copy after media moves using journal entries only for uniquely owned sidecars.
                if q.name.startswith(p.name+'.') and q not in sidecars:entries.append((q,target,core.digest(q)));sidecars.add(q)
    # Exact duplicates are recoverable, not permanently deleted. Keep them out of archive scans.
    for p,h,winner in duplicates:
        stop()
        if core.digest(winner)!=h:raise IOError('保留檔已變更，停止去重：'+str(winner))
        dest=root/'.PHOTO_MANAGER'/'recovery'/uuid.uuid4().hex/p.relative_to(root);entries.append((p,dest,h));log(f'完全相同，移至復原區：{p}；保留 {winner}')
    log(f'計畫：掃描 {len(selected)}，截圖 {sum(r["cat"]=="截圖" for r in records)}，重複 {len(duplicates)}')
    if confirm_plan is not None and not confirm_plan(entries,len(selected)):
        log('使用者取消預覽，未搬移任何照片');return False
    execute_moves(root,entries,log,stop)
    log(f'完成：實際搬移 {sum(p!=d for p,d,h in entries)} 筆；零筆亦為正常完成')
    return True
