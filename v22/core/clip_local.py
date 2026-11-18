"""Offline CLIP candidate; no network or file mutations at inference time."""
import json, sys, hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

LABELS = {
 'photo': ['a real camera photograph of people or family life','a natural camera photograph of scenery, objects or food','a personal photograph with added text or a date stamp'],
 'greeting': ['a designed good morning greeting card with decorative text and flowers','a digital greeting poster with Chinese lettering'],
 'meme': ['an internet meme image with caption text','a digitally designed humorous social media graphic'],
 'movie': ['a screenshot of a movie or television scene with subtitles','a frame from a film with subtitle text'],
 'screen': ['a screenshot of a computer desktop or file explorer','a screenshot of a smartphone app interface or webpage'],
}

def normalize(a):
    a=np.asarray(a,dtype=np.float32)
    return a/np.maximum(np.linalg.norm(a,axis=-1,keepdims=True),1e-12)

def scores_for(image_embedding, text_embeddings):
    v=normalize(image_embedding).reshape(-1)
    t=normalize(text_embeddings)
    if t.shape != (sum(map(len,LABELS.values())),len(v)): raise ValueError('CLIP embedding shape mismatch')
    s=t@v; out={}; i=0
    for k,p in LABELS.items():
        out[k]=float(max(s[i:i+len(p)])); i+=len(p)
    return out

def decide(scores, threshold=.24, margin=.06):
    # Provisional thresholds, NOT calibrated probabilities. Default is conservative.
    best=max((k for k in scores if k!='photo'),key=scores.get)
    if scores[best]>=threshold and scores[best]-scores['photo']>=margin:
        return 'screen',best
    # Near ties are uncertain, not evidence for automatic screenshot classification.
    return 'review' if scores[best]>=threshold and scores[best]>=scores['photo']-.015 else 'photo',best

def preprocess(path):
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB')
        w,h=im.size; scale=224/min(w,h)
        im=im.resize((max(224,int(w*scale)),max(224,int(h*scale))),Image.Resampling.BICUBIC)
        w,h=im.size; x=(w-224)//2; y=(h-224)//2
        a=np.asarray(im.crop((x,y,x+224,y+224)),dtype=np.float32)/255
    a=(a-np.array([.48145466,.4578275,.40821073],np.float32))/np.array([.26862954,.26130258,.27577711],np.float32)
    return np.ascontiguousarray(a.transpose(2,0,1)[None])

class ClipLocal:
    def __init__(self, directory=None):
        import onnxruntime as ort
        base=Path(directory) if directory else (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent)/'AI_MODELS'
        manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
        if manifest['labels']!=LABELS: raise ValueError('CLIP prompt mismatch')
        for name in ('image_encoder.onnx','text_embeddings.npy'):
            with (base/name).open('rb') as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=manifest['sha256'][name]: raise ValueError('CLIP model checksum mismatch: '+name)
        self.text=np.load(base/'text_embeddings.npy',allow_pickle=False)
        opts=ort.SessionOptions(); opts.intra_op_num_threads=4; opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(base/'image_encoder.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    def classify(self,path):
        emb=self.session.run(None,{'pixel_values':preprocess(path)})[0]
        scores=scores_for(emb,self.text); verdict,label=decide(scores)
        return verdict,label,scores
