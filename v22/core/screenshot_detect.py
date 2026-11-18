"""Conservative offline image heuristics. No trained AI model; uncertain images stay put."""
from PIL import Image
import cv2
import numpy as np

def classify_image(p,raw):
    try:
        with Image.open(p) as im:
            ex=im.getexif(); sub=ex.get_ifd(34665)
            if raw.get('Make') or raw.get('Model') or ex.get(271) or ex.get(272) or raw.get('DateTimeOriginal') or sub.get(36867):return 'photo','相機拍攝資訊，保護原圖'
            im=im.convert('RGB');im.thumbnail((900,900));a=np.asarray(im)
        g=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY);h,w=g.shape
        if min(h,w)<80:return 'review','影像太小'
        white=float(np.mean(g>245)); flat=float(np.mean(np.max(a,axis=2)-np.min(a,axis=2)<5))
        k=cv2.getStructuringElement(cv2.MORPH_RECT,(9,9));m=np.maximum(cv2.morphologyEx(g,cv2.MORPH_TOPHAT,k),cv2.morphologyEx(g,cv2.MORPH_BLACKHAT,k));b=(m>45).astype('uint8')
        _,_,stats,_=cv2.connectedComponentsWithStats(b)
        boxes=[(x,y,ww,hh) for x,y,ww,hh,area in stats[1:] if 3<=ww<=65 and 5<=hh<=65 and .12<area/(ww*hh)<.95]
        peak=max((sum(y0<=y+hh/2<y0+20 for x,y,ww,hh in boxes) for y0 in range(0,h,10)),default=0)
        if white>.35 and flat>.45 and len(boxes)>=15:return 'screen','大面積介面背景及文字元件'
        # Text overlays and edited photos are ambiguous: report, never auto-move.
        if peak>=8 or (len(boxes)>=25 and str(raw.get('Software') or ex.get(305,'')).lower().find('picasa')>=0):return 'review','疑似字幕、祝福文字或轉傳圖'
        return 'photo','未發現足夠介面特徵'
    except Exception as e:return 'review',f'影像無法分析：{e}'
