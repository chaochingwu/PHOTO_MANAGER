"""Independent import choices; no filesystem writes while selecting paths."""
from pathlib import Path
from workflow import roots
from library_catalog import linked


def unique_paths(values):
    out=[];seen=set()
    for value in values:
        if not value:continue
        p=Path(value).absolute()
        if not p.is_dir() or p==Path(p.anchor) or any(linked(q) for q in (p,*p.parents)):continue
        p=p.resolve();key=str(p).casefold()
        if key not in seen:seen.add(key);out.append(str(p))
    return out


def choices(rows,configured='',last_dest='',last_source=''):
    rows=list(rows)
    destinations=unique_paths([configured,last_dest,*[r['root'] for r in rows if r['role']=='primary']])
    sources=unique_paths([last_source,*[r['root'] for r in rows if r['role'] in ('independent','import')]])
    forbidden=[Path(r['root']).resolve() for r in rows if r['role'] in ('primary','backup')]
    sources=[p for p in sources if not any((q:=Path(p).resolve())==r or q in r.parents or r in q.parents for r in forbidden)]
    return destinations,sources


def validate(c,source,dest):
    if not source or not dest:raise ValueError('請分別選擇來源與目的主庫')
    raw_source=Path(source).resolve()
    for row in c.sources():
        p=Path(row['root']).resolve()
        if row['role'] in ('primary','backup') and (raw_source==p or raw_source in p.parents or p in raw_source.parents):
            raise ValueError('外部來源不得是主庫／備份庫或其上層、子資料夾；請改用主庫內部整理')
    s,d=roots(source,dest)
    if s==Path(s.anchor) or d==Path(d.anchor):raise ValueError('不可選擇磁碟根目錄')
    if d==c.path or d in c.path.parents:raise ValueError('索引必須位於主庫之外')
    for row in c.sources():
        p=Path(row['root']).resolve()
        if row['role'] in ('primary','backup') and (s==p or s in p.parents or p in s.parents):
            raise ValueError('外部來源不得是主庫／備份庫或其上層、子資料夾；請改用主庫內部整理')
        if p==d:
            if row['role']!='primary':raise ValueError('目的地已登錄為非主庫，請選擇其他資料夾')
        elif p in d.parents or d in p.parents:raise ValueError('目的地與已登錄照片庫重疊')
    return s,d
