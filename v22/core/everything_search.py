PHOTO_EXT=('jpg','jpeg','png','heic','heif','webp','avif','bmp','gif','tif','tiff','jfif')
VIDEO_EXT=('mp4','mov','m4v','avi','mkv','wmv','mpg','mpeg','mts','m2ts','webm','3gp')
def search_command(photos, videos, folder=''):
    selected=set(photos)|set(videos)
    ext=[x for x in PHOTO_EXT+VIDEO_EXT if x in selected]
    if not ext:return ''
    folder=folder.strip()
    if '"' in folder or '\n' in folder or '\r' in folder:raise ValueError('搜尋位置包含無效字元')
    return ('"'+folder.rstrip('\\/')+'\\" ' if folder else '')+'ext:'+';'.join(ext)
