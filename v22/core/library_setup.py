import re,uuid,json
from pathlib import Path
from photo_manager_v1_4 import Library,atomic_json,checkroot,paths_ok
def valid_name(name):
    name=name.strip()
    if not name or name in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.', ' ')) or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:raise ValueError('照片庫名稱不合法')
    return name
def info(root):
    lib=Library(root,create=False)
    try:return dict(lib.info)
    finally:lib.close()
def initialize(parent,name,existing=False,source=None):
    name=valid_name(name);parent=Path(parent).resolve()
    if not parent.is_dir():raise ValueError('儲存位置不存在')
    root=parent if existing else parent/name
    if root==Path(root.anchor):raise ValueError('不可將磁碟根目錄直接設為照片庫')
    if source:paths_ok([Path(source).resolve(),root])
    for ancestor in root.parents:
        if (ancestor/'.PHOTO_MANAGER/identity.json').exists():raise ValueError('不可在其他照片庫內建立照片庫')
    if root.exists() and (root/'.PHOTO_MANAGER/identity.json').exists():
        data=info(root)
        if source and data.get('group')!=info(source).get('group'):raise ValueError('同名照片庫屬於其他群組')
        if not source:raise ValueError('照片庫已存在，請使用開啟現有照片庫')
        return root
    if root.exists() and not existing and any(root.iterdir()):raise ValueError('目的資料夾非空，請另選位置')
    if root.exists() and any(root.rglob('identity.json')):raise ValueError('資料夾可能包含其他照片庫，禁止初始化')
    root.mkdir(exist_ok=True);lib=Library(root)
    try:
        group=info(source).get('group') if source else None
        lib.info.update(name=name,group=group or str(uuid.uuid4()));atomic_json(lib.identity,lib.info)
    finally:lib.close()
    return root
def open_library(root):
    root=checkroot(root);lib=Library(root,create=False)
    try:
        if not lib.info.get('group'):
            lib.info.update(name=root.name,group=str(uuid.uuid4()));atomic_json(lib.identity,lib.info)
    finally:lib.close()
    return root
