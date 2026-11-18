"""Qt Library presentation; shares the existing catalog and read-only decoders."""
import os, sys, hashlib, tempfile, threading, json
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSize, QThreadPool, QRunnable, Signal, QObject, QTimer, QUrl, Slot, QEvent, QPoint, QRect
from PySide6.QtGui import QImage, QPixmap, QIcon, QDesktopServices, QShortcut, QKeySequence, QColor, QFont
from PySide6.QtWidgets import *
from catalog import Catalog, FAVORITE_KIND, FAVORITE_NAME, norm
from media_preview import preview_image, VIDEO
from browse_settings import load, save
HOME=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PHOTO_MANAGER_V21_R02'
COLS=[('file','檔案名稱'),('date','拍攝日期')]+[('tag:'+k,k if k!='自訂' else '自訂 TAG') for k in ('人物','事件','時間標籤','地點','物品','自訂')]
def is_favorite(tags):return any(t["kind"]==FAVORITE_KIND and t["norm"]==norm(FAVORITE_NAME) and not t["scope"] for t in tags)
def path(r):return Path(r['root'])/r['rel']
def btn(text,fn,style=None,owner=None):
    b=QPushButton(text);b.clicked.connect(fn)
    if style:b.setIcon(owner.style().standardIcon(getattr(QStyle.StandardPixmap,style)))
    return b
class Signals(QObject):
    done=Signal(object,object,object)
class Job(QRunnable):
    def __init__(self,key,fn):super().__init__();self.key=key;self.fn=fn;self.signals=Signals()
    def run(self):
        try:self.signals.done.emit(self.key,self.fn(),None)
        except Exception as e:self.signals.done.emit(self.key,None,str(e))
def image_for(r,size,cache=False):
    p=path(r); key=hashlib.sha256(f'qt1|{p}|{r["size"]}|{r["mtime"]}|{size}'.encode()).hexdigest(); target=HOME/'qt_thumbs'/f'{key}.jpg'
    if cache and target.is_file():
        q=QImage(str(target))
        if not q.isNull():return q
    im=preview_image(p,(size,size));raw=im.tobytes();q=QImage(raw,im.width,im.height,im.width*3,QImage.Format.Format_RGB888).copy()
    if cache:
        target.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=target.parent,suffix='.jpg');os.close(fd)
        try:im.save(tmp,quality=85);os.replace(tmp,target)
        finally:Path(tmp).unlink(missing_ok=True)
    return q
class Model(QAbstractTableModel):
    def __init__(self,parent):super().__init__(parent);self.owner=parent;self.rows=[];self.tags={};self.cols=COLS[:];self.cache=OrderedDict();self.pending=set();self.size=144;self.gen=0
    def reset(self,rows,tags):self.beginResetModel();self.rows=rows;self.tags=tags;self.gen+=1;self.endResetModel()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.cols)
    def headerData(self,s,o,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and o==Qt.Orientation.Horizontal:return self.cols[s][1]
    def data(self,i,role=Qt.ItemDataRole.DisplayRole):
        if not i.isValid():return None
        r=self.rows[i.row()];k=self.cols[i.column()][0]
        if role==Qt.ItemDataRole.DisplayRole:
            if k=='file':return ('★ ' if not self.owner.gallery.isVisible() and is_favorite(self.tags.get(r['id'],[])) else '')+path(r).name
            if k=='date':return r['capture_date'] or '未知'
            return '、'.join(t['name'] for t in self.tags.get(r['id'],[]) if t['kind']==k[4:])
        if role==Qt.ItemDataRole.ToolTipRole:return str(path(r))
        if role==Qt.ItemDataRole.DecorationRole and i.column()==0 and self.owner.gallery.isVisible():
            key=(r['id'],r['mtime'],self.size)
            if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
            if key not in self.pending and len(self.pending)<24:
                self.pending.add(key);self.owner.submit(self.owner.thumbs,key,lambda r=r,s=self.size:image_for(r,s,True),self.loaded)
        return None
    def loaded(self,key,img,error):
        self.pending.discard(key);self.cache[key]=QIcon(QPixmap.fromImage(img)) if img is not None else self.owner.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        while len(self.cache)>200:self.cache.popitem(last=False)
        for n,r in enumerate(self.rows):
            if (r['id'],r['mtime'],self.size)==key:self.dataChanged.emit(self.index(n,0),self.index(n,0),[Qt.ItemDataRole.DecorationRole]);break
        self.owner.gallery.viewport().update()
    def sort(self,col,order):self.owner.sort_key=self.cols[col][0];self.owner.desc=order==Qt.SortOrder.DescendingOrder;self.owner.refresh_rows()
class FavoriteDelegate(QStyledItemDelegate):
    def __init__(self,lib):super().__init__(lib.gallery);self.lib=lib
    @staticmethod
    def star_rect(rect):return QRect(rect.right()-27,rect.top()+3,24,24)
    def paint(self,painter,option,index):
        super().paint(painter,option,index)
        r=self.lib.model.rows[index.row()];fav=is_favorite(self.lib.model.tags.get(r['id'],[]));rect=self.star_rect(option.rect)
        painter.save();painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('#252d38'));painter.drawRoundedRect(rect,4,4);painter.setPen(QColor('#ffc857' if fav else '#e0e6ef'));font=QFont(painter.font());font.setPointSize(15);painter.setFont(font);painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'★' if fav else '☆');painter.restore()
class Viewer(QDialog):
    def __init__(self,lib,index):
        super().__init__(lib);self.lib=lib;self.rows=lib.model.rows[:];self.pos=index;self.gen=0;self.original=None;self.fit_mode=True;self.drag=None;self.closed=False;self.player=None;self.video_active=False;self.setWindowTitle('PHOTO_MANAGER | 大圖瀏覽');self.resize(1050,780)
        l=QVBoxLayout(self);self.title=QLabel();l.addWidget(self.title)
        self.media=QStackedWidget();l.addWidget(self.media,1)
        self.pic=QLabel(alignment=Qt.AlignmentFlag.AlignCenter);self.pic.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(False);self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter);self.scroll.setWidget(self.pic);self.media.addWidget(self.scroll)
        self.scroll.viewport().installEventFilter(self);self.pic.installEventFilter(self)
        self.fit_timer=QTimer(self);self.fit_timer.setSingleShot(True);self.fit_timer.timeout.connect(self.fit)
        self.init_video()
        self.strip=QListWidget();self.strip.setViewMode(QListView.ViewMode.IconMode);self.strip.setFlow(QListView.Flow.LeftToRight);self.strip.setWrapping(False);self.strip.setIconSize(QSize(88,70));self.strip.setGridSize(QSize(132,100));self.strip.setFixedHeight(116);self.strip.setWordWrap(False);l.addWidget(self.strip);self.strip.itemClicked.connect(lambda item:self.go(item.data(Qt.ItemDataRole.UserRole)))
        bar=QHBoxLayout();l.addLayout(bar);self.photo_buttons=[]
        for t,f in [('上一張',lambda:self.go(self.pos-1)),('下一張',lambda:self.go(self.pos+1)),('縮小',lambda:self.zoom(.8)),('放大',lambda:self.zoom(1.25)),('適合視窗',self.fit),('全螢幕',lambda:self.showNormal() if self.isFullScreen() else self.showFullScreen()),('關閉',self.reject)]:
            button=btn(t,f);bar.addWidget(button)
            if t in ('縮小','放大','適合視窗'):self.photo_buttons.append(button)
        self.favorite_button=btn('☆ 我的最愛',self.toggle_favorite);bar.addWidget(self.favorite_button)
        self.external_button=btn('外部播放器',self.external_video);bar.addWidget(self.external_button);self.external_button.hide()
        self.shortcuts=[]
        for k,f in [('Left',lambda:self.go(self.pos-1)),('Right',lambda:self.go(self.pos+1))]:
            shortcut=QShortcut(QKeySequence(k),self);shortcut.activated.connect(f);self.shortcuts.append(shortcut)
        self.go(index)
    def update_favorite(self):
        fav=is_favorite(self.lib.c.photo_tags(self.rows[self.pos]['id']));self.favorite_button.setText('★ 我的最愛' if fav else '☆ 我的最愛');self.favorite_button.setStyleSheet('color:#ffc857;' if fav else '')
    def toggle_favorite(self):
        pid=self.rows[self.pos]['id'];self.lib.change_favorite([pid],not is_favorite(self.lib.c.photo_tags(pid)));self.update_favorite()
    def init_video(self):
        try:
            from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.5);self.player.setAudioOutput(self.audio)
            self.video_page=QWidget();vl=QVBoxLayout(self.video_page);self.video=QVideoWidget();vl.addWidget(self.video,1);self.player.setVideoOutput(self.video)
            self.video_status=QLabel('');vl.addWidget(self.video_status);controls=QHBoxLayout();vl.addLayout(controls)
            controls.addWidget(btn('播放',self.player.play));controls.addWidget(btn('暫停',self.player.pause));controls.addWidget(btn('停止',self.player.stop));self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,0);controls.addWidget(self.seek,1);self.seek.sliderMoved.connect(self.player.setPosition);self.player.durationChanged.connect(lambda d:self.seek.setRange(0,min(d,2147483647)));self.player.positionChanged.connect(lambda p:self.seek.setValue(p) if not self.seek.isSliderDown() else None)
            controls.addWidget(QLabel('音量'));volume=QSlider(Qt.Orientation.Horizontal);volume.setRange(0,100);volume.setValue(50);volume.setMaximumWidth(110);volume.valueChanged.connect(lambda v:self.audio.setVolume(v/100));controls.addWidget(volume);controls.addWidget(btn('外部播放器',self.external_video));self.player.errorOccurred.connect(self.video_error);self.media.addWidget(self.video_page)
        except Exception:
            self.player=None
    def external_video(self):
        if self.player:self.player.pause()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path(self.rows[self.pos])))):QMessageBox.warning(self,'影片','無法開啟系統播放器。')
    def video_error(self,error,message):
        if self.video_active:self.video_status.setText('影片播放失敗：'+str(message)+'；可使用外部播放器。')
    def go(self,i):
        if not 0<=i<len(self.rows):return
        self.video_active=False
        if self.player:self.player.stop();self.player.setSource(QUrl())
        self.pos=i;self.update_favorite();self.gen+=1;g=self.gen;r=self.rows[i];self.title.setText(f'{i+1}/{len(self.rows)} · {path(r).name}');self.original=None;self.fit_mode=True;self.drag=None;self.pic.unsetCursor();self.pic.clear();self.pic.setText('載入中…');self.pic.resize(self.scroll.viewport().size());self.strip.clear()
        for n in range(max(0,i-4),min(len(self.rows),i+5)):
            item=QListWidgetItem(path(self.rows[n]).name);item.setToolTip(path(self.rows[n]).name);item.setData(Qt.ItemDataRole.UserRole,n);self.strip.addItem(item)
            if n==i:self.strip.setCurrentItem(item)
            self.lib.submit(self.lib.film,(g,n),lambda r=self.rows[n]:image_for(r,96,True),self.film_done)
        is_video=path(r).suffix.lower() in VIDEO;self.video_active=bool(self.player and is_video);self.external_button.setVisible(is_video and not self.video_active)
        for button in self.photo_buttons:button.setEnabled(not self.video_active)
        if self.video_active:
            self.media.setCurrentWidget(self.video_page);self.video_status.setText('按播放開始；若格式不支援，可使用外部播放器。');self.player.setSource(QUrl.fromLocalFile(str(path(r))))
        else:
            self.media.setCurrentWidget(self.scroll);self.lib.submit(self.lib.large,g,lambda:image_for(r,2400),self.loaded)
    def film_done(self,key,img,error):
        if self.closed or key[0]!=self.gen or img is None:return
        for n in range(self.strip.count()):
            it=self.strip.item(n)
            if it.data(Qt.ItemDataRole.UserRole)==key[1]:it.setIcon(QIcon(QPixmap.fromImage(img)));break
    def loaded(self,key,img,error):
        if self.closed or key!=self.gen:return
        if img is None:self.pic.setText(error or '無法預覽');return
        self.original=QPixmap.fromImage(img);self.fit()
    def fit(self):
        if self.original is None or self.video_active or self.closed:return
        self.fit_mode=True
        # maximumViewportSize excludes the scrollbars that disappear in fit mode.
        bounds=self.scroll.maximumViewportSize()-QSize(4,4)
        if bounds.width()<1 or bounds.height()<1:return
        p=self.original.scaled(bounds,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation);self.pic.setPixmap(p);self.pic.resize(p.size());self.scroll.horizontalScrollBar().setValue(0);self.scroll.verticalScrollBar().setValue(0)
    def zoom(self,f):
        if self.original is None or self.video_active:return
        old=self.pic.pixmap();w=max(100,min(6000,int(old.width()*f)))
        if w==old.width():return
        self.fit_mode=False
        # Preserve the image coordinate at the viewport center, including when centered with no scrollbars.
        center=self.scroll.viewport().rect().center();local=self.pic.mapFrom(self.scroll.viewport(),center);rx=max(0.,min(1.,local.x()/max(1,old.width())));ry=max(0.,min(1.,local.y()/max(1,old.height())))
        p=self.original.scaledToWidth(w,Qt.TransformationMode.SmoothTransformation);self.pic.setPixmap(p);self.pic.resize(p.size())
        h=self.scroll.horizontalScrollBar();v=self.scroll.verticalScrollBar();vp=self.scroll.viewport().size();h.setValue(round(rx*p.width()-vp.width()/2));v.setValue(round(ry*p.height()-vp.height()/2))
    def eventFilter(self,obj,event):
        if obj in (self.pic,self.scroll.viewport()):
            t=event.type()
            if t==QEvent.Type.Resize and obj==self.scroll.viewport() and self.fit_mode and self.original is not None:self.fit_timer.start(0)
            elif t==QEvent.Type.Wheel and self.original is not None:
                delta=event.angleDelta().y()
                if delta:self.zoom(1.25 if delta>0 else .8);return True
            elif t==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton and self.original is not None:
                self.drag=(event.globalPosition().toPoint(),self.scroll.horizontalScrollBar().value(),self.scroll.verticalScrollBar().value());self.pic.setCursor(Qt.CursorShape.ClosedHandCursor);return True
            elif t==QEvent.Type.MouseMove and self.drag is not None:
                start,h,v=self.drag;d=event.globalPosition().toPoint()-start;self.scroll.horizontalScrollBar().setValue(h-d.x());self.scroll.verticalScrollBar().setValue(v-d.y());return True
            elif t==QEvent.Type.MouseButtonRelease and self.drag is not None:self.drag=None;self.pic.unsetCursor();return True
        return super().eventFilter(obj,event)
    def done(self,result):
        self.closed=True;self.gen+=1;self.fit_timer.stop();self.video_active=False
        if self.player:self.player.stop();self.player.setSource(QUrl())
        super().done(result)
class LibraryPage(QWidget):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.c=Catalog(HOME/'catalog.sqlite');self.jobs={};self.thumbs=QThreadPool(self);self.thumbs.setMaxThreadCount(4);self.large=QThreadPool(self);self.large.setMaxThreadCount(1);self.film=QThreadPool(self);self.film.setMaxThreadCount(2);self.work=QThreadPool(self);self.work.setMaxThreadCount(1);self.running=False;self.cancel=threading.Event();self.gen=0;self.offset=0;self.sort_key=None;self.desc=False;self.total=0;self.scope=(None,None);self.year=None;self.favorites_only=False;self.star_press=None
        l=QVBoxLayout(self);l.setContentsMargins(12,10,12,8);bar=QHBoxLayout();l.addLayout(bar);bar.addWidget(QLabel('Library  照片瀏覽'));bar.addStretch();bar.addWidget(btn('新增來源',self.add_source,'SP_DirOpenIcon',self));bar.addWidget(btn('更新索引',self.scan,'SP_BrowserReload',self));bar.addWidget(btn('停止掃描',self.cancel.set,'SP_BrowserStop',self));self.search=QLineEdit();self.search.setPlaceholderText('搜尋檔名、人物、事件、TAG（分號分隔）');self.search.returnPressed.connect(self.search_now);bar.addWidget(self.search,2);bar.addWidget(btn('搜尋',self.search_now,'SP_FileDialogContentsView',self));bar.addWidget(btn('清除',self.clear_search));filters=QHBoxLayout();l.addLayout(filters);self.people=QLineEdit();self.people.setPlaceholderText('人物');self.event=QLineEdit();self.event.setPlaceholderText('事件');self.any=QCheckBox('任一關鍵字');self.rec=QCheckBox('含子資料夾');self.rec.setChecked(True);self.rec.toggled.connect(self.search_now);self.people.returnPressed.connect(self.search_now);self.event.returnPressed.connect(self.search_now)
        for w in (self.people,self.event,self.any,self.rec):filters.addWidget(w)
        self.any.toggled.connect(self.search_now);split=QSplitter();l.addWidget(split,1);self.tree=QTreeWidget();self.tree.setHeaderLabel('照片庫 / 資料夾 / 年份');split.addWidget(self.tree);self.tree.itemClicked.connect(self.choose);center=QWidget();cl=QVBoxLayout(center);cl.setContentsMargins(0,0,0,0);split.addWidget(center);tools=QHBoxLayout();cl.addLayout(tools);tools.addWidget(btn('縮圖',lambda:self.views.setCurrentIndex(0),'SP_FileDialogListView',self));tools.addWidget(btn('清單',lambda:self.views.setCurrentIndex(1),'SP_FileDialogDetailedView',self));self.sz=QComboBox();self.sz.addItems(['96','144','192','240']);self.sz.setCurrentText('144');self.sz.currentTextChanged.connect(self.resize_icons);tools.addWidget(self.sz);tools.addStretch();tools.addWidget(btn('★ 加入最愛',lambda:self.change_favorite([r['id'] for r in self.selected()],True)));tools.addWidget(btn('☆ 移除最愛',lambda:self.change_favorite([r['id'] for r in self.selected()],False)));tools.addWidget(btn('編輯 TAG',self.edit,'SP_FileDialogInfoView',self));tools.addWidget(btn('復原 TAG',self.undo));tools.addWidget(btn('新增分類',self.add_category));self.views=QStackedWidget();cl.addWidget(self.views,1);self.gallery=QListView();self.gallery.setViewMode(QListView.ViewMode.IconMode);self.gallery.setResizeMode(QListView.ResizeMode.Adjust);self.gallery.setUniformItemSizes(True);self.gallery.setLayoutMode(QListView.LayoutMode.Batched);self.gallery.setWordWrap(True);self.table=QTableView();self.model=Model(self);self.gallery.setModel(self.model);self.gallery.setItemDelegate(FavoriteDelegate(self));self.gallery.viewport().installEventFilter(self);self.table.setModel(self.model);self.table.setSelectionModel(self.gallery.selectionModel());self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.horizontalHeader().setSectionsMovable(True);self.table.horizontalHeader().sectionClicked.connect(self.sort_click)
        for v in (self.gallery,self.table):v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);v.doubleClicked.connect(self.open_view);self.views.addWidget(v)
        self.views.currentChanged.connect(lambda _:self.gallery.viewport().update());self.resize_icons('144');self.gallery.selectionModel().selectionChanged.connect(self.selection);pages=QHBoxLayout();cl.addLayout(pages);pages.addWidget(btn('上一頁',lambda:self.page(-1)));self.count=QLabel();pages.addWidget(self.count,1);pages.addWidget(btn('下一頁',lambda:self.page(1)));self.limit=QSpinBox();self.limit.setRange(1,10000);self.limit.setValue(load(HOME/'browse_r02g.json'));self.limit.valueChanged.connect(self.page_size);pages.addWidget(self.limit);right=QWidget();rl=QVBoxLayout(right);split.addWidget(right);rl.addWidget(QLabel('預覽 / 照片資訊'));self.preview=QLabel('請選取照片',alignment=Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumSize(200,200);rl.addWidget(self.preview);self.info=QPlainTextEdit();self.info.setReadOnly(True);rl.addWidget(self.info,1);self.editbtn=btn('編輯 TAG（0 張）',self.edit,'SP_FileDialogInfoView',self);self.editbtn.setObjectName('primary');rl.addWidget(self.editbtn);rl.addWidget(btn('大圖瀏覽',lambda:self.open_view(self.gallery.currentIndex()),'SP_FileDialogContentsView',self));rl.addWidget(btn('開啟所在資料夾',self.open_folder,'SP_DirOpenIcon',self));rl.addWidget(btn('日期健檢／修正',self.date_edit));split.setSizes([235,850,300]);self.msg=QLabel('準備就緒');l.addWidget(self.msg);self.rebuild();self.refresh_rows()
    def eventFilter(self,obj,event):
        if obj is self.gallery.viewport() and event.type() in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease,QEvent.Type.MouseButtonDblClick) and event.button()==Qt.MouseButton.LeftButton:
            idx=self.gallery.indexAt(event.position().toPoint());hit=idx.isValid() and FavoriteDelegate.star_rect(self.gallery.visualRect(idx)).contains(event.position().toPoint())
            if event.type()==QEvent.Type.MouseButtonPress:
                self.star_press=self.model.rows[idx.row()]['id'] if hit else None
                if hit:return True
            elif event.type()==QEvent.Type.MouseButtonDblClick and hit:return True
            elif event.type()==QEvent.Type.MouseButtonRelease and self.star_press is not None:
                pid=self.star_press;self.star_press=None
                if hit and self.model.rows[idx.row()]['id']==pid:self.change_favorite([pid],not is_favorite(self.c.photo_tags(pid)))
                return True
        return super().eventFilter(obj,event)
    def change_favorite(self,ids,enabled):
        if not ids or not self.guard():return
        try:
            n=self.c.set_favorite(ids,enabled);self.update_favorite_count()
            if self.favorites_only or self.search.text().strip():self.refresh_rows()
            else:
                self.model.tags.update(self.c.photo_tags_many(ids))
                for i,r in enumerate(self.model.rows):
                    if r['id'] in ids:self.model.dataChanged.emit(self.model.index(i,0),self.model.index(i,len(self.model.cols)-1))
                self.gallery.viewport().update();self.selection()
            self.msg.setText(f'{"加入" if enabled else "移除"}我的最愛：{n} 張')
        except Exception as e:self.error(e)
    def update_favorite_count(self):
        self.fav_item.setText(0,f'★ 我的最愛 ({self.c.search(favorites_only=True,count_only=True)})')
    def submit(self,pool,key,fn,callback):
        j=Job(None,fn);ident=id(j);j.key=(ident,key);self.jobs[ident]=(j,callback)
        j.signals.done.connect(self.job_done,Qt.ConnectionType.QueuedConnection);pool.start(j)
    @Slot(object,object,object)
    def job_done(self,k,v,e):
        ident,key=k;entry=self.jobs.pop(ident,None)
        if entry:entry[1](key,v,e)
    def guard(self):return not self.running and not self.window.busy
    def error(self,e):QMessageBox.warning(self,'PHOTO_MANAGER',str(e))
    def task(self,fn,after=None):
        if not self.guard():return
        self.running=True;self.cancel.clear();self.msg.setText('背景工作執行中…');self.window.status.setText('Library 背景工作執行中…')
        def done(k,v,e):
            self.running=False;self.window.status.setText('準備就緒');self.msg.setText(e or (f'已完成 {len(v)} 筆' if isinstance(v,list) else str(v)[:500]));
            if e:self.error(e)
            elif after:after(v)
        self.submit(self.work,0,fn,done)
    def rebuild(self):
        self.tree.clear();allitem=QTreeWidgetItem(['所有照片']);allitem.setData(0,Qt.ItemDataRole.UserRole,(None,None,None));self.tree.addTopLevelItem(allitem)
        self.fav_item=QTreeWidgetItem();self.fav_item.setData(0,Qt.ItemDataRole.UserRole,(None,None,None,True));self.tree.addTopLevelItem(self.fav_item);self.update_favorite_count()
        for s in self.c.sources():
            root=QTreeWidgetItem([f'{s["role"]} · {Path(s["root"]).name}']);root.setToolTip(0,s['root']);root.setData(0,Qt.ItemDataRole.UserRole,(s['id'],None,None));self.tree.addTopLevelItem(root);nodes={'':root}
            for f in self.c.folders(s['id']):
                parent,_,name=f.rpartition('/');it=QTreeWidgetItem([name]);it.setData(0,Qt.ItemDataRole.UserRole,(s['id'],f,None));nodes[parent].addChild(it);nodes[f]=it
        years=QTreeWidgetItem(['年份']);self.tree.addTopLevelItem(years)
        for r in self.c.timeline():
            it=QTreeWidgetItem([f'{r["year"] or "未知"} ({r["n"]})']);it.setData(0,Qt.ItemDataRole.UserRole,(None,None,r['year'] or 'unknown'));years.addChild(it)
        years.setExpanded(True)
    def choose(self,it,col):
        v=it.data(0,Qt.ItemDataRole.UserRole)
        if v is not None:self.scope=v[:2];self.year=v[2];self.favorites_only=len(v)>3 and bool(v[3]);self.search_now()
    def add_source(self):
        if not self.guard():return
        p=QFileDialog.getExistingDirectory(self,'選擇照片來源（不搬移原檔）');
        if not p:return
        role,ok=QInputDialog.getItem(self,'來源角色','角色',['primary','independent','backup','import'],0,False)
        if not ok:return
        try:sid=self.c.add_source(p,role);self.scope=(sid,None);self.year=None;self.favorites_only=False;self.rebuild();self.scan()
        except Exception as e:self.error(e)
    def scan(self):
        sid=self.scope[0]
        if sid is None:self.error('請先選取一個來源資料夾');return
        def work():
            c=Catalog(self.c.path)
            try:return f'掃描完成：{c.scan(sid,cancel=self.cancel.is_set)} 張'
            finally:c.close()
        self.task(work,lambda _: (self.rebuild(),self.refresh_rows()))
    def search_now(self,*_):self.offset=0;self.refresh_rows()
    def clear_search(self):self.search.clear();self.people.clear();self.event.clear();self.search_now()
    def filters(self):return dict(keyword=self.search.text(),people=self.people.text(),event=self.event.text(),any_keyword=self.any.isChecked(),source_id=self.scope[0],folder=self.scope[1],recursive=self.rec.isChecked(),years=[self.year] if self.year else None,sort=self.sort_key,descending=self.desc,favorites_only=self.favorites_only)
    def refresh_rows(self):
        try:
            self.update_favorite_count();f=self.filters();self.total=self.c.search(**f,count_only=True);self.offset=min(self.offset,max(0,((self.total-1)//self.limit.value())*self.limit.value()));rows=self.c.search(**f,offset=self.offset,limit=self.limit.value());self.model.reset(rows,self.c.photo_tags_many([r['id'] for r in rows]));self.count.setText(f'{self.offset+1 if rows else 0}–{self.offset+len(rows)} / {self.total:,} 張');self.selection()
        except Exception as e:self.error(e)
    def page(self,d):self.offset=max(0,self.offset+d*self.limit.value());self.refresh_rows()
    def page_size(self,n):save(HOME/'browse_r02g.json',n);self.search_now()
    def resize_icons(self,s):self.model.size=int(s);self.gallery.setIconSize(QSize(int(s),int(s)));self.gallery.setGridSize(QSize(int(s)+24,int(s)+48));self.gallery.viewport().update()
    def sort_click(self,col):self.desc=not self.desc if self.sort_key==self.model.cols[col][0] else False;self.sort_key=self.model.cols[col][0];self.refresh_rows()
    def selected(self):return [self.model.rows[n] for n in sorted({i.row() for i in self.gallery.selectionModel().selectedIndexes()}) if 0<=n<len(self.model.rows)]
    def selection(self,*_):
        rows=self.selected();self.editbtn.setText(f'編輯 TAG（{len(rows)} 張）');self.editbtn.setEnabled(bool(rows));self.gen+=1;g=self.gen;self.preview.clear();self.info.clear()
        if not rows:self.preview.setText('請選取照片');return
        r=rows[0];tags=self.model.tags.get(r['id'],[]);self.info.setPlainText(f'{path(r).name}\n{r["capture_date"] or "日期未知"}\n{r["size"]:,} bytes\n{path(r)}\n\n'+'\n'.join(f'{t["kind"]}：{t["name"]}' for t in tags));self.preview.setText('載入中…');self.submit(self.large,g,lambda:image_for(r,400),self.preview_done)
    def preview_done(self,g,img,error):
        if g!=self.gen:return
        if img is None:self.preview.setText(error or '無法預覽');return
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def open_view(self,i):
        if i.isValid():Viewer(self,i.row()).exec()
    def open_folder(self):
        r=self.selected()
        if r:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path(r[0]).parent)))
    def edit(self):
        if not self.guard():return
        rows=self.selected();ids=[r['id'] for r in rows]
        if not ids:return
        d=QDialog(self);d.setWindowTitle(f'編輯 TAG · {len(ids)} 張');d.resize(600,500);l=QVBoxLayout(d);l.addWidget(QLabel('所有欄位非必填；空白不變更。分號分隔多個 TAG。'));mode=QComboBox();mode.addItems(['新增／追加','移除','取代已填分類']);l.addWidget(mode);scroll=QScrollArea();scroll.setWidgetResizable(True);w=QWidget();form=QFormLayout(w);fields={}
        for k in self.c.kinds():
            e=QLineEdit();e.setPlaceholderText('輸入 TAG');fields[k]=e;form.addRow(k,e)
        scroll.setWidget(w);l.addWidget(scroll);existing=QComboBox();existing.addItem('選擇既有 TAG（含同名區別）',None)
        for t in self.c.tags():existing.addItem(f'{t["kind"]} · {t["name"]} {t["scope"]}',t['id'])
        l.addWidget(existing);bar=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);bar.accepted.connect(d.accept);bar.rejected.connect(d.reject);l.addWidget(bar)
        if d.exec()!=QDialog.DialogCode.Accepted:return
        try:
            vals={k:e.text() for k,e in fields.items() if e.text().strip()};m=['append','remove','replace'][mode.currentIndex()];tid=existing.currentData()
            if tid is not None and vals:raise ValueError('既有 TAG 與文字欄位請分開操作')
            if m=='replace' and QMessageBox.question(self,'確認取代','只取代已填分類的 TAG，確定？')!=QMessageBox.StandardButton.Yes:return
            if tid is not None:
                if m=='replace':raise ValueError('既有 TAG 選單僅支援追加或移除')
                self.c.assign(ids,tid,m=='remove')
            else:self.c.edit_categories(ids,vals,m)
            self.refresh_rows()
        except Exception as e:self.error(e)
    def add_category(self):
        if not self.guard():return
        name,ok=QInputDialog.getText(self,"新增 TAG 分類","分類名稱")
        if ok:
            try:self.c.add_kind(name)
            except Exception as e:self.error(e)
    def undo(self):
        if self.guard() and QMessageBox.question(self,'復原','復原上次 TAG 操作？')==QMessageBox.StandardButton.Yes:self.c.undo();self.refresh_rows()
    def date_edit(self):
        if not self.guard():return
        rows=self.selected()
        if not rows:return
        from date_inspector import evidence,apply,undo
        d=QDialog(self);d.setWindowTitle('日期健檢 · 原檔不修改');d.resize(800,500);l=QVBoxLayout(d);t=QPlainTextEdit();t.setReadOnly(True);t.setPlainText('\n'.join(str(evidence(r)) for r in rows));l.addWidget(t);e=QLineEdit();e.setPlaceholderText('YYYY-MM-DD');l.addWidget(e);bar=QHBoxLayout();l.addLayout(bar);bar.addWidget(btn('修正選取照片',d.accept));bar.addWidget(btn('復原上次修正',lambda:(undo(self.c),d.reject(),self.refresh_rows())));bar.addWidget(btn('取消',d.reject))
        if d.exec()==QDialog.DialogCode.Accepted:
            try:apply(self.c,[([r['id'] for r in rows],e.text())]);self.refresh_rows()
            except Exception as ex:self.error(ex)
    def shutdown(self):
        for p in (self.thumbs,self.large,self.film,self.work):p.clear();p.waitForDone()
        self.c.close()
