"""Conservative protection of tagged sources until path migration is implemented."""
from pathlib import Path
import sqlite3

def protected_roots(db, paths):
    db=Path(db)
    if not db.exists(): return []
    roots=[Path(p).resolve() for p in paths if str(p).strip()]
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as con:
        rows=con.execute('''SELECT DISTINCT s.root FROM sources s JOIN photos p ON p.source=s.id
          WHERE EXISTS (SELECT 1 FROM links l WHERE l.photo=p.id)
          OR EXISTS (SELECT 1 FROM date_overrides d WHERE d.photo=p.id)''').fetchall()
    return [r for (r,) in rows if any((q:=Path(r).resolve())==p or q in p.parents or p in q.parents for p in roots)]
