"""Read-only shared preview decoder. Optional codecs are loaded lazily."""
from pathlib import Path
from io import BytesIO
import shutil, subprocess
from PIL import Image, ImageOps
VIDEO=set('.mov .mp4 .m4v .avi .mkv .mts .m2ts .3gp .wmv'.split())
RAW=set('.dng .raw .cr2 .cr3 .nef .arw .raf .rw2'.split())
HEIF={'.heic','.heif'}
class PreviewError(Exception): pass

def ffmpeg_path():
    path=shutil.which('ffmpeg')
    if path:return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:raise PreviewError('影片需安裝 imageio-ffmpeg')

def video_frame(p, bounds):
    w,h=map(int,bounds)
    cmd=[ffmpeg_path(),'-nostdin','-v','error','-i',str(p),'-map','0:v:0','-frames:v','1','-vf',f'scale={w}:{h}:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','png','pipe:1']
    try:
        result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        with Image.open(BytesIO(result.stdout)) as im:return im.copy()
    except (subprocess.SubprocessError,OSError,ValueError) as e:raise PreviewError('影片畫面讀取失敗') from e

def raw_frame(p):
    try:import rawpy
    except ImportError:raise PreviewError('RAW 需安裝 rawpy')
    try:
        with rawpy.imread(str(p)) as raw:
            try:
                t=raw.extract_thumb()
                if t.format==rawpy.ThumbFormat.JPEG:
                    with Image.open(BytesIO(t.data)) as im:return ImageOps.exif_transpose(im).copy()
                return Image.fromarray(t.data)
            except (rawpy.LibRawNoThumbnailError,rawpy.LibRawUnsupportedThumbnailError):
                return Image.fromarray(raw.postprocess(half_size=True,use_camera_wb=True))
    except Exception as e:raise PreviewError('RAW 預覽讀取失敗') from e

def preview_image(path,bounds):
    p=Path(path);ext=p.suffix.lower()
    if not p.is_file():raise PreviewError('來源離線／檔案不存在')
    if ext in VIDEO:im=video_frame(p,bounds)
    elif ext in RAW:im=raw_frame(p)
    else:
        if ext in HEIF:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:raise PreviewError('HEIC 需安裝 pillow-heif')
        try:
            with Image.open(p) as src:
                im=ImageOps.exif_transpose(src);im.thumbnail(bounds);im=im.copy()
        except PermissionError as e:raise PreviewError('檔案無法存取') from e
        except Exception as e:raise PreviewError('圖片損壞或格式不支援') from e
    im.thumbnail(bounds)
    if 'A' in im.getbands() or 'transparency' in im.info:
        rgba=im.convert('RGBA');bg=Image.new('RGBA',rgba.size,(40,44,51,255));bg.alpha_composite(rgba);return bg.convert('RGB')
    return im.convert('RGB')
