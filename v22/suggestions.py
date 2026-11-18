"""Pure TAG completion helpers. Never guess which same-name tag to assign."""
import re
from catalog import norm
KINDS=('人物','事件','地點','自訂','公司／組織')
def split_tail(text):
    m=list(re.finditer(r'[,，;；\n]',text)); i=m[-1].end() if m else 0
    return text[:i],text[i:].strip()
def suggest(catalog,text,limit=12):
    _,term=split_tail(text)
    kind=None
    if ':' in term or '：' in term:
        prefix,term2=re.split('[:：]',term,maxsplit=1)
        if prefix.strip() in catalog.kinds():kind=prefix.strip();term=term2.strip()
    q=norm(term)
    if not q:return []
    rows=catalog.db.execute('SELECT t.*, GROUP_CONCAT(a.norm, char(31)) AS alias_norm FROM tags t LEFT JOIN aliases a ON a.tag=t.id GROUP BY t.id').fetchall()
    ranked=[]
    for t in rows:
        if kind and t['kind']!=kind:continue
        n=t['norm']; aliases=(t['alias_norm'] or '').split(chr(31))
        if q==n:score=0
        elif n.startswith(q):score=1
        elif q in n:score=2
        elif any(q==a for a in aliases):score=3
        elif any(q in a for a in aliases):score=4
        else:continue
        ranked.append((score,t['kind'],n,t['scope'],t['id'],t))
    return [x[-1] for x in sorted(ranked,key=lambda x:x[:-1])[:limit]]
def completion(catalog,text,tag):
    # Typed token is safe only when kind+name identifies exactly one row.
    n=catalog.db.execute('SELECT COUNT(*) FROM tags WHERE kind=? AND norm=?',(tag['kind'],tag['norm'])).fetchone()[0]
    if n!=1:return None
    prefix,_=split_tail(text)
    return prefix+tag['kind']+':'+tag['name']+'; '
