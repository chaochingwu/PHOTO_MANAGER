import json
from pathlib import Path

DEFAULT=100

def page_size(value):
    n=int(value)
    if not 1<=n<=10000: raise ValueError('請輸入 1–10000 張')
    return n

def load(path):
    try:
        d=json.loads(Path(path).read_text(encoding='utf-8'))
        return page_size(d['page_size'])
    except (OSError,ValueError,TypeError,KeyError): return DEFAULT

def save(path,n):
    n=page_size(n);p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'page_size':n}),encoding='utf-8');tmp.replace(p)
