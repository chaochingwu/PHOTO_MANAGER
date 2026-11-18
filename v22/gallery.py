import tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image, ImageTk, ImageOps
from collections import OrderedDict
import hashlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from media_preview import preview_image, PreviewError
from theme import CANVAS, PANEL, FIELD, LINE, TEXT, MUTED, SELECT, ACCENT

class Gallery(ttk.Frame):
    def __init__(self,parent,app,cache):
        super().__init__(parent); self.app=app; self.cache=Path(cache); self.size=144; self.cards={}; self.images={}; self.memory=OrderedDict(); self.generation=0; self.anchor=None; self.pending=None; self.rows=[]; self.columns=0; self.workers=4; self.executor=ThreadPoolExecutor(max_workers=self.workers); self.inflight={}; self.closed=False; self.poll_pending=False; self.card_keys={}; self.jobs=set(); self.bind('<Destroy>',self.shutdown,add='+')
        self.canvas=tk.Canvas(self,background=CANVAS,highlightthickness=0,takefocus=True); self.scroll=ttk.Scrollbar(self,orient='vertical',command=self.scroll_to); self.canvas.configure(yscrollcommand=self.scroll.set); self.scroll.pack(side='right',fill='y'); self.canvas.pack(side='left',fill='both',expand=True)
        self.inner=tk.Frame(self.canvas,bg=CANVAS); self.window=self.canvas.create_window(0,0,window=self.inner,anchor='nw');  self.canvas.bind('<Configure>',self.resize); self.canvas.bind('<Control-a>',self.select_all); self.bind_wheel(self.canvas); self.bind_wheel(self.inner)
    def schedule(self,delay,fn):
        job=None
        def run():
            self.jobs.discard(job);fn()
        job=self.after(delay,run);self.jobs.add(job)
    def cancel_jobs(self):
        for job in self.jobs:self.after_cancel(job)
        self.jobs.clear()
    def bind_wheel(self,w):
        w.bind('<MouseWheel>',lambda e:self.wheel(-1 if e.delta>0 else 1)); w.bind('<Button-4>',lambda e:self.wheel(-1)); w.bind('<Button-5>',lambda e:self.wheel(1))
    def scroll_to(self,*args):
        self.canvas.yview(*args);self.layout()
    def wheel(self,d):self.canvas.yview_scroll(d*3,'units');self.layout();return 'break'
    def resize(self,e):
        self.canvas.itemconfigure(self.window,width=e.width);self.columns=max(1,e.width//(self.size+26));self.layout()
    def set_size(self,size):
        self.size=int(size);self.columns=max(1,self.canvas.winfo_width()//(self.size+26));self.render(self.rows,reset=False)
    def render(self,rows,reset=True):
        self.generation+=1;self.rows=list(rows);self.visible=[]
        # Retry previously failed files after an explicit refresh (e.g. drive reconnected).
        for key in list(self.memory):
            if isinstance(self.memory[key],str):del self.memory[key]
        if reset:self.anchor=None;self.canvas.yview_moveto(0)
        self.layout()
    def key_for(self,r):
        p=Path(r['root'])/r['rel']
        return hashlib.sha256(f'r02e|{p}|{r["size"]}|{r["mtime"]}|{self.size}'.encode()).hexdigest(),p
    def layout(self):
        if self.closed:return
        cols=max(1,self.columns);h=self.size+90;w=self.size+26
        total=max(h,((len(self.rows)+cols-1)//cols)*h)
        self.canvas.configure(scrollregion=(0,0,max(1,self.canvas.winfo_width()),total),yscrollincrement=20)
        self.canvas.itemconfigure(self.window,height=total)
        first=max(0,int(self.canvas.canvasy(0)//h));top=max(0,first-1);bottom=top+max(2,int(self.canvas.winfo_height()//h)+4)
        indices=list(range(top*cols,min(len(self.rows),bottom*cols)));self.visible=indices
        wanted={self.rows[i]['id'] for i in indices}
        for pid in list(self.cards):
            if pid not in wanted:
                self.cards.pop(pid)[0].destroy();self.images.pop(pid,None);self.card_keys.pop(pid,None)
        for i in indices:
            r=self.rows[i];pid=r['id'];key,_=self.key_for(r)
            if pid not in self.cards:
                card=tk.Frame(self.inner,bg=PANEL,highlightthickness=2,highlightbackground=LINE,padx=4,pady=4)
                img=tk.Label(card,text='載入中…',bg=FIELD,fg=MUTED,width=1,height=1);img.pack(fill='both',expand=True)
                title=tk.Label(card,bg=PANEL,fg=TEXT,justify='center',font=('Microsoft JhengHei',9));title.pack(fill='x')
                tag=tk.Label(card,bg=PANEL,fg=MUTED,justify='center',font=('Microsoft JhengHei',9));tag.pack(fill='x')
                self.cards[pid]=(card,img,title,tag);card.pack_propagate(False)
                for widget in (card,img,title,tag):
                    widget.bind('<Button-1>',lambda e,pid=pid:self.click(pid,e.state));widget.bind('<Double-Button-1>',lambda e,pid=pid:self.open(pid));self.bind_wheel(widget)
            card,img,title,tag=self.cards[pid]
            title.configure(text=Path(r['rel']).name,wraplength=self.size);tag.configure(text='、'.join(t['name'] for t in self.app.page_tags.get(pid,[])) or '未標記',wraplength=self.size)
            card.place(x=(i%cols)*w+4,y=(i//cols)*h+4,width=w-8,height=h-8)
            if self.card_keys.get(pid)!=key:
                self.card_keys[pid]=key;self.images.pop(pid,None);img.configure(image='',text='載入中…')
        self.sync();self.pump()
    def shutdown(self,event):
        if event.widget is self:
            self.closed=True;self.cancel_jobs();self.generation+=1;self.executor.shutdown(wait=False,cancel_futures=True)
    def decode(self,p,file,size):
        try:
            with Image.open(file) as im:return im.copy()
        except Exception:pass
        thumb=preview_image(p,(size,size))
        tmp=None
        try:
            self.cache.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.cache,suffix='.tmp',delete=False) as f:
                tmp=Path(f.name);thumb.save(f,'JPEG',quality=85)
            os.replace(tmp,file)
        except OSError:pass
        finally:
            if tmp is not None:tmp.unlink(missing_ok=True)
        return thumb
    def show_thumb(self,pid,key,pic):
        if self.card_keys.get(pid)!=key or pid not in self.cards:return
        self.images[pid]=pic;self.cards[pid][1].configure(image=pic,text='')
    def pump(self):
        if self.closed:return
        for key,future in list(self.inflight.items()):
            if not future.done():continue
            del self.inflight[key]
            try:
                pic=ImageTk.PhotoImage(future.result(),master=self.canvas);self.memory[key]=pic
                if len(self.memory)>200:self.memory.popitem(last=False)
            except Exception as e:
                pic=None;self.memory[key]=str(e) if isinstance(e,PreviewError) else '縮圖讀取失敗'
                if len(self.memory)>200:self.memory.popitem(last=False)
        cols=max(1,self.columns);first=max(0,int(self.canvas.canvasy(0)//(self.size+90)))*cols
        indices=sorted(self.visible,key=lambda i:(i<first,abs(i-first)))
        for i in indices:
            r=self.rows[i];pid=r['id'];key,p=self.key_for(r)
            if pid in self.images:continue
            if key in self.memory:
                pic=self.memory[key];self.memory.move_to_end(key)
                if isinstance(pic,str):self.cards[pid][1].configure(image='',text=pic,wraplength=self.size)
                else:self.show_thumb(pid,key,pic)
            elif key not in self.inflight and len(self.inflight)<self.workers:
                self.inflight[key]=self.executor.submit(self.decode,p,self.cache/(key+'.jpg'),self.size)
        if self.inflight and not self.poll_pending:
            self.poll_pending=True;self.schedule(15,self.poll)
    def poll(self):
        self.poll_pending=False;self.pump()
    def click(self,pid,state=0):
        self.canvas.focus_set();ids=[r['id'] for r in self.rows];sel=set(self.app.tree.selection())
        if state&1 and self.anchor in ids:
            a,b=sorted((ids.index(self.anchor),ids.index(pid)));span=set(ids[a:b+1]);sel=sel|span if state&4 else span
        elif state&4:
            sel.symmetric_difference_update({pid});self.anchor=pid
        else:sel={pid};self.anchor=pid
        self.app.tree.selection_set([x for x in ids if x in sel]);self.sync();return 'break'
    def open(self,pid):self.app.tree.selection_set(pid);self.sync();self.app.large_preview();return 'break'
    def select_all(self,e=None):self.app.tree.selection_set(self.app.tree.get_children());self.sync();return 'break'
    def sync(self):
        selected=set(self.app.tree.selection())
        for pid,(card,img,title,tag) in self.cards.items():
            on=pid in selected;bg=SELECT if on else PANEL;card.configure(bg=bg,highlightbackground=ACCENT if on else LINE);title.configure(bg=bg);tag.configure(bg=bg)
        self.app.selection_label.configure(text=f'已選取 {len(selected)} 張（本頁）')
