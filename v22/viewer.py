"""Read-only internal viewer. Stable filmstrip geometry and independent main preview."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from PIL import ImageTk
from media_preview import preview_image
from theme import BG, CANVAS, TEXT, MUTED, ACCENT, PANEL

class Viewer:
    def __init__(self, parent, total, index, fetch):
        self.total=total; self.index=index; self.fetch=fetch; self.zoom=1.; self.generation=0; self.strip_generation=0; self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=1); self.strip_pool=ThreadPoolExecutor(max_workers=2)
        self.main_future=None; self.strip_jobs=[]; self.q=Queue(); self.images=[]; self.photo=None; self.labels={}; self.row=None; self.last_bounds=None
        self.resize_job=None; self.timeout_job=None; self.initial_job=None; self.poll_job=None
        self.win=w=tk.Toplevel(parent); w.title('PHOTO_MANAGER | Photo Viewer'); w.geometry('1180x820'); w.minsize(700,500); w.configure(bg=BG); w.transient(parent); w.grab_set()
        top=ttk.Frame(w,padding=10);top.pack(fill='x');ttk.Label(top,text='PHOTO VIEWER',style='Brand.TLabel').pack(side='left');self.title=ttk.Label(top,style='Muted.TLabel');self.title.pack(side='left',padx=16)
        for label,fn in [('關閉 Esc',self.close),('全螢幕 F11',self.fullscreen),('＋',lambda:self.scale(1.25)),('－',lambda:self.scale(.8)),('適合視窗',self.fit),('下一張 →',lambda:self.move(1)),('← 上一張',lambda:self.move(-1))]:ttk.Button(top,text=label,command=fn).pack(side='right',padx=2)
        bottom=ttk.Frame(w,padding=(10,4));bottom.pack(fill='x',side='bottom');self.status=ttk.Label(bottom,style='Muted.TLabel');self.status.pack(side='left');self.pos=ttk.Label(bottom);self.pos.pack(side='right');self.strip=ttk.Frame(w,padding=8);self.strip.pack(fill='x',side='bottom');self.strip_visible=True
        ttk.Button(bottom,text='顯示／隱藏縮圖',command=self.toggle_strip).pack(side='right',padx=10)
        self.canvas=tk.Canvas(w,bg=CANVAS,highlightthickness=0);self.canvas.pack(fill='both',expand=True);self.canvas.bind('<ButtonPress-1>',lambda e:self.canvas.scan_mark(e.x,e.y));self.canvas.bind('<B1-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1));self.canvas.bind('<MouseWheel>',lambda e:self.scale(1.25 if e.delta>0 else .8));self.canvas.bind('<Configure>',self.resize)
        for key,fn in [('<Left>',lambda:self.move(-1)),('<Right>',lambda:self.move(1)),('<Escape>',self.close),('<F11>',self.fullscreen),('<Home>',lambda:self.go(0)),('<End>',lambda:self.go(self.total-1))]:w.bind(key,lambda e,fn=fn:fn())
        w.protocol('WM_DELETE_WINDOW',self.close);self.poll_job=w.after(60,self.poll);self.initial_job=w.after(100,self.initial_render)
    def cancel_timer(self,name):
        job=getattr(self,name,None)
        if job:
            try:self.win.after_cancel(job)
            except tk.TclError:pass
        setattr(self,name,None)
    def initial_render(self):
        self.initial_job=None
        if self.row is None:self.render()
    def fullscreen(self):self.win.attributes('-fullscreen',not bool(self.win.attributes('-fullscreen')))
    def toggle_strip(self):
        self.strip_visible=not self.strip_visible
        if self.strip_visible:self.strip.pack(fill='x',side='bottom',before=self.canvas)
        else:self.strip.pack_forget()
    def resize(self,e):
        if self.closed or self.row is None:return
        self.cancel_timer('resize_job');self.resize_job=self.win.after(180,self.resize_render)
    def resize_render(self):
        self.resize_job=None
        if not self.closed and self.row is not None:self.render_main()
    def scale(self,f):self.zoom=max(.5,min(4,self.zoom*f));self.render_main()
    def fit(self):self.zoom=1.;self.render_main()
    def move(self,d):self.go(self.index+d)
    def go(self,i):
        if 0<=i<self.total and (i!=self.index or self.row is None):self.index=i;self.zoom=1.;self.render()
    def submit(self,g,key,row,bounds):
        def work():
            try:self.q.put((g,key,preview_image(Path(row['root'])/row['rel'],bounds),None))
            except Exception as e:self.q.put((g,key,None,str(e) or type(e).__name__))
        return (self.pool if key=='main' else self.strip_pool).submit(work)
    def message(self,text):
        self.canvas.delete('all');self.canvas.create_text(max(100,self.canvas.winfo_width()/2),max(50,self.canvas.winfo_height()/2),text=text,fill=TEXT,justify='center',width=max(160,self.canvas.winfo_width()-40))
    def render(self):
        if self.closed:return
        self.cancel_timer('resize_job');self.cancel_timer('timeout_job');self.generation+=1;self.strip_generation+=1
        if self.main_future:self.main_future.cancel()
        for f in self.strip_jobs:f.cancel()
        self.strip_jobs=[];self.images=[];self.photo=None;self.row=None;self.last_bounds=None;self.labels={}
        for child in self.strip.winfo_children():child.destroy()
        start=max(0,min(self.index-4,self.total-9))
        try:
            rows=self.fetch(start,9)
            if not rows or not 0<=self.index-start<len(rows):raise ValueError('找不到選取的照片，請返回 Library 重新搜尋。')
            self.row=rows[self.index-start];self.title.configure(text=Path(self.row['rel']).name);self.pos.configure(text=f'{self.index+1:,} / {self.total:,}')
            for j,r in enumerate(rows,start):
                frame=tk.Frame(self.strip,bg=ACCENT if j==self.index else PANEL,padx=2,pady=2);frame.pack(side='left',fill='x',expand=True,padx=2)
                # Canvas has a fixed pixel size, unlike Label width/height which changes units when an image is set.
                lab=tk.Canvas(frame,bg=CANVAS,width=112,height=74,highlightthickness=0);lab.pack();lab.create_text(56,37,text='…',fill=TEXT)
                name=tk.Label(frame,bg=frame['bg'],fg=TEXT,text=Path(r['rel']).name[:18],font=('Segoe UI',9));name.pack();self.labels[j]=lab
                for widget in (frame,lab,name):widget.bind('<Button-1>',lambda e,j=j:self.go(j))
                self.strip_jobs.append(self.submit(self.strip_generation,j,r,(112,74)))
            self.render_main()
        except Exception as e:self.message('無法載入照片\n'+str(e))
    def render_main(self):
        if self.closed or self.row is None:return
        w=max(200,self.canvas.winfo_width());h=max(200,self.canvas.winfo_height());bounds=(min(5000,int(w*self.zoom)),min(5000,int(h*self.zoom)))
        if bounds==self.last_bounds:return
        self.last_bounds=bounds;self.generation+=1;g=self.generation
        if self.main_future:self.main_future.cancel()
        self.cancel_timer('timeout_job')
        self.status.configure(text=f"{self.row['capture_date'] or '日期未知'}  ·  {self.row['size']/1048576:.2f} MB  ·  {self.zoom:.0%}")
        # Keep the previous image visible while resizing instead of flashing a loading screen.
        if self.photo is None:self.message('載入中…')
        self.main_future=self.submit(g,'main',self.row,bounds);self.timeout_job=self.win.after(30000,lambda:self.timeout(g))
    def timeout(self,g):
        self.timeout_job=None
        if not self.closed and g==self.generation:
            self.message('預覽載入逾時\n可切換其他照片，或返回 Library 開啟原檔。')
    def poll(self):
        if self.closed:return
        try:
            while True:
                g,key,im,err=self.q.get_nowait()
                if key=='main':
                    if g!=self.generation:continue
                    self.cancel_timer('timeout_job')
                    try:
                        if err:raise ValueError(err)
                        self.photo=ImageTk.PhotoImage(im,master=self.win);w=max(im.width,self.canvas.winfo_width());h=max(im.height,self.canvas.winfo_height());self.canvas.delete('all');self.canvas.configure(scrollregion=(0,0,w,h));self.canvas.create_image(w/2,h/2,image=self.photo);self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)
                    except Exception as e:self.photo=None;self.message('無法預覽\n'+str(e))
                elif g==self.strip_generation and key in self.labels:
                    lab=self.labels[key];lab.delete('all')
                    try:
                        if err:raise ValueError(err)
                        pic=ImageTk.PhotoImage(im,master=self.win);self.images.append(pic);lab.create_image(56,37,image=pic)
                    except Exception:lab.create_text(56,37,text='無預覽',fill=TEXT)
        except Empty:pass
        finally:
            if not self.closed:self.poll_job=self.win.after(60,self.poll)
    def close(self):
        if self.closed:return
        self.closed=True
        for name in ('poll_job','initial_job','resize_job','timeout_job'):self.cancel_timer(name)
        self.pool.shutdown(wait=False,cancel_futures=True);self.strip_pool.shutdown(wait=False,cancel_futures=True);self.win.destroy()
