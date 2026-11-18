"""Read-only media inventory and conservative space estimates."""
import ctypes
import os
import shutil
from pathlib import Path
from workflow import files, roots
from library_catalog import linked

MODES = ("原地整理", "重建照片庫", "匯入主庫", "單向備份")

def filesystem(path):
    if os.name != 'nt':
        return '未查詢（非 Windows）'
    volume = ctypes.create_unicode_buffer(1024)
    name = ctypes.create_unicode_buffer(256)
    kernel = ctypes.windll.kernel32
    if not kernel.GetVolumePathNameW(str(path), volume, len(volume)):
        raise ctypes.WinError()
    if not kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, name, len(name)):
        raise ctypes.WinError()
    return name.value

def inspect(source, destination, mode, cancel=lambda: False, copy_bytes=None):
    if mode not in MODES or not source or (mode != MODES[0] and not destination):
        raise ValueError('請選擇作業、來源及目的地')
    src = Path(source).absolute()
    if not src.is_dir() or any(linked(p) for p in (src, *src.parents)):
        raise ValueError('來源離線、含連結，或沒有檔案系統路徑')
    if mode == MODES[0]:
        src = dest = src.resolve()
    else:
        src, dest = roots(src, destination)
    initial = src.stat()
    count = total = largest = 0
    for path in files(src, cancel):
        size = path.stat().st_size
        total += size
        largest = max(largest, size)
        count += 1
    if not os.path.samestat(initial, src.stat()):
        raise OSError('來源裝置已變更')
    kind = filesystem(dest)
    # Same-volume moves use renames. Reserve space for indexes and journals.
    reserve = 16 * 1024**2 + count * 4096
    required = reserve if mode == MODES[0] else (total if copy_bytes is None else copy_bytes) + reserve
    free = shutil.disk_usage(dest).free
    issues = []
    if not count:
        issues.append('沒有可辨識的媒體檔案')
    if free < required:
        issues.append(f'不足 {required-free:,} bytes')
    if not os.access(dest, os.W_OK):
        issues.append('目的地無寫入權限')
    if mode == MODES[1] and any(dest.iterdir()):
        issues.append('重建目的地須為空資料夾')
    if mode == MODES[2] and not (dest/'.PHOTO_MANAGER/identity.json').is_file():
        issues.append('缺少主庫身分檔')
    if kind.upper() == 'FAT32' and largest >= 2**32:
        issues.append('單檔超過 FAT32 上限')
    if mode == MODES[3] and kind.upper() in {'EXFAT','FAT','FAT32'}:
        issues.append('目前備份核心需要支援硬連結的目的地')
    return dict(count=count,total=total,required=required,free=free,source_fs=filesystem(src),dest_fs=kind,issues=issues)
