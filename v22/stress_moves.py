"""Linux integration benchmark; writes only to a fresh temporary directory."""
import hashlib, json, resource, sys, tempfile, time
from pathlib import Path
from capacity import inspect, MODES
from library_catalog import sha256
sys.path.insert(0,str(Path(__file__).parent/'core'))
from organize import execute_moves

def bench(gib):
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        (root/".PHOTO_MANAGER").mkdir()
        entries=[]
        unit=16*1024**2
        for i in range(gib*64):
            p=root/f'{i:05}.mp4'
            block=hashlib.sha256(str(i).encode()).digest()*(1024**2//32)
            h=hashlib.sha256()
            with p.open('wb') as f:
                for _ in range(16):
                    f.write(block)
                    h.update(block)
            entries.append((p,root/'VIDEOS'/p.name,h.hexdigest()))
        started=time.monotonic()
        info=inspect(root,None,MODES[0])
        scan=time.monotonic()-started
        started=time.monotonic()
        n=0
        def stop():
            nonlocal n
            n+=1
            if n==len(entries)+1: raise InterruptedError()
        try: execute_moves(root,entries,lambda *_:None,stop)
        except InterruptedError: pass
        journal=root/'.PHOTO_MANAGER/organize_pending.json'
        assert journal.is_file()
        staged=sum(p.stat().st_size for p in (root/'.PHOTO_MANAGER/staging').rglob('*') if p.is_file())
        journal_size=journal.stat().st_size
        execute_moves(root,[],lambda *_:None)
        moved=time.monotonic()-started
        for src,dest,h in entries: assert not src.exists() and sha256(dest)==h
        assert not journal.exists() and len(list(root.rglob('*.mp4')))==len(entries)
        print(json.dumps(dict(gib=gib,files=len(entries),bytes=info['total'],scan_seconds=round(scan,2),move_recovery_seconds=round(moved,2),peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,staged_existing_bytes=staged,journal_bytes_at_stop=journal_size,missing_or_mismatched=0)),flush=True)
if __name__=='__main__': bench(int(sys.argv[1]))
