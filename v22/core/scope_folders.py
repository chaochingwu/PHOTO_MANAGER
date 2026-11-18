"""Read-only folder choices and strict local scope validation."""
import os
from pathlib import Path
from legacy import SKIP, linked

def local_base(root, partial):
    root=Path(root).resolve(); rel=Path(partial)
    if not partial or rel.is_absolute() or rel.anchor or any(p in ('..','.') or p.lower() in SKIP for p in rel.parts) or not rel.parts:
        raise ValueError('請選擇有效的局部資料夾，不可選整庫或系統資料夾')
    p=root
    for part in rel.parts:
        p=p/part
        if linked(p):raise ValueError('不可整理連結或 junction 資料夾')
    if not p.is_dir() or not p.resolve().is_relative_to(root):raise ValueError('局部資料夾不存在或超出照片庫')
    return p

def folders(root):
    if not str(root).strip():return []
    root=Path(root).resolve()
    if not root.is_dir() or root==Path(root.anchor):return []
    result=[]
    for folder,dirs,_ in os.walk(root,followlinks=False):
        dirs[:]=sorted((d for d in dirs if d.lower() not in SKIP and not linked(Path(folder)/d)),key=str.casefold)
        for d in dirs:result.append((Path(folder)/d).relative_to(root).as_posix())
    return sorted(result,key=str.casefold)
