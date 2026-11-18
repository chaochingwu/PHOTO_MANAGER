# PHOTO_MANAGER RC3 UI Preview - safe, read-only folder browser
import os, sys, traceback, ctypes
from pathlib import Path
from PySide6.QtCore import Qt, QDir, QSize, QThreadPool, QRunnable, QObject, Signal, QFileInfo, QTimer, QEvent, QUrl, QMimeData
from PySide6.QtGui import QPixmap, QIcon, QImage, QAction, QKeySequence, QImageReader, QPainter, QColor, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QSplitter,QTreeView,QFileSystemModel,QListWidget,QListWidgetItem,QLabel,QPushButton,QLineEdit,QFileDialog,QTabWidget,QFormLayout,QScrollArea,QDialog,QMessageBox,QToolBar,QStatusBar,QCheckBox,QComboBox,QFrame, QToolButton, QAbstractItemView, QScrollBar, QMenu, QInputDialog, QSlider, QSpinBox, QTextEdit, QStackedWidget, QSizePolicy, QScrollArea)
from PIL import Image, ImageOps, ExifTags
import json, sqlite3, hashlib
try:
 from send2trash import send2trash
except ImportError:
 send2trash=None
from PIL.ImageQt import ImageQt
EXT={'.jpg','.jpeg','.png','.bmp','.gif','.webp','.tif','.tiff','.heic','.heif'}
try:
 import pillow_heif
 pillow_heif.register_heif_opener()
except Exception: pass
class Signals(QObject):
 ready=Signal(str,object,dict,int)
 large_ready=Signal(str,object,int,str)
class ThumbJob(QRunnable):
 def __init__(self,path,signals,edge,token,cache_dir):
  super().__init__();self.path=path;self.signals=signals;self.edge=edge;self.token=token;self.cache_dir=cache_dir
 def run(self):
  info={}
  try:
   st=os.stat(self.path)
   digest=hashlib.sha256(f'{self.path}|{st.st_size}|{st.st_mtime_ns}|{self.edge}'.encode('utf-8')).hexdigest()
   cached=Path(self.cache_dir)/(digest+'.jpg')
   if cached.is_file():
    image=QImage(str(cached))
    if not image.isNull():
     self.signals.ready.emit(self.path,image,info,self.token);return
   reader=QImageReader(self.path);reader.setAutoTransform(True)
   original=reader.size()
   if original.isValid():
    target=original.scaled(QSize(self.edge,self.edge),Qt.KeepAspectRatio)
    reader.setScaledSize(target)
   image=reader.read()
   if image.isNull():
    with Image.open(self.path) as im:
     im=ImageOps.exif_transpose(im);im.thumbnail((self.edge,self.edge));image=ImageQt(im.convert('RGB')).copy()
   if image.isNull():raise ValueError('縮圖解碼失敗')
   cached.parent.mkdir(parents=True,exist_ok=True)
   image.save(str(cached),'JPG',83)
   self.signals.ready.emit(self.path,image,info,self.token)
  except Exception as e:self.signals.ready.emit(self.path,None,{'error':str(e)},self.token)

class LargeJob(QRunnable):
 def __init__(self,path,signals,token,full=False):
  super().__init__();self.path=path;self.signals=signals;self.token=token;self.full=full
 def run(self):
  try:
   reader=QImageReader(self.path);reader.setAutoTransform(True)
   size=reader.size()
   if not self.full and size.isValid() and max(size.width(),size.height())>3600:
    reader.setScaledSize(size.scaled(QSize(3600,3600),Qt.KeepAspectRatio))
   image=reader.read()
   if image.isNull():
    with Image.open(self.path) as im:
     im=ImageOps.exif_transpose(im)
     if not self.full:im.thumbnail((3600,3600))
     image=ImageQt(im.convert('RGB')).copy()
   if image.isNull():raise ValueError('影像解碼失敗')
   self.signals.large_ready.emit(self.path,image,self.token,'')
  except Exception as e:self.signals.large_ready.emit(self.path,None,self.token,str(e))

class Viewer(QDialog):
 def __init__(self,paths,index,parent=None):
  super().__init__(parent);self.paths=paths;self.index=index;self.setWindowTitle('PHOTO_MANAGER · 照片檢視');self.resize(1080,780)
  v=QVBoxLayout(self);self.pic=QLabel(alignment=Qt.AlignCenter);self.pic.setMinimumHeight(350);self.pic.setStyleSheet('background:#15181d');v.addWidget(self.pic,1)
  nav=QHBoxLayout();prev=QPushButton('❮  上一張');prev.clicked.connect(lambda:self.move(-1));nxt=QPushButton('下一張  ❯');nxt.clicked.connect(lambda:self.move(1));nav.addWidget(prev);nav.addStretch(1);nav.addWidget(nxt);v.addLayout(nav)
  self.strip=QListWidget();self.strip.setViewMode(QListWidget.IconMode);self.strip.setIconSize(QSize(85,60));self.strip.setFixedHeight(104);self.strip.setResizeMode(QListWidget.Adjust);self.strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.strip.itemClicked.connect(lambda x:self.show_at(self.strip.row(x)));v.addWidget(self.strip)
  for p in paths:
   item=QListWidgetItem('');item.setData(Qt.UserRole,p);item.setToolTip(Path(p).name);self.strip.addItem(item)
  self.show_at(index)
 def show_at(self,index):
  if not self.paths:return
  self.index=index%len(self.paths);p=self.paths[self.index];self.strip.setCurrentRow(self.index);self.fill_strip()
  try:
   with Image.open(p) as im:
    im=ImageOps.exif_transpose(im);im.thumbnail((1500,1100));pix=QPixmap.fromImage(ImageQt(im.convert('RGB')).copy());self._pix=pix
   self.fit()
  except Exception as e:self.pic.setText('無法顯示：'+str(e))
 def fill_strip(self):
  for i in range(max(0,self.index-6),min(len(self.paths),self.index+7)):
   item=self.strip.item(i)
   if item and item.icon().isNull():
    try:
     with Image.open(self.paths[i]) as im:
      im=ImageOps.exif_transpose(im);im.thumbnail((90,65));item.setIcon(QIcon(QPixmap.fromImage(ImageQt(im.convert('RGB')).copy())))
    except Exception: pass
 def fit(self):
  if hasattr(self,'_pix'):self.pic.setPixmap(self._pix.scaled(self.pic.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
 def resizeEvent(self,e):super().resizeEvent(e);self.fit()
 def move(self,n):self.show_at(self.index+n)
 def keyPressEvent(self,e):
  if e.key() in (Qt.Key_Right,Qt.Key_Down):self.move(1)
  elif e.key() in (Qt.Key_Left,Qt.Key_Up):self.move(-1)
  else:super().keyPressEvent(e)
class FavoritesStore:
 def __init__(self):
  base=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.local'/'share'))/'PHOTO_MANAGER_RC3_REVIEW'
  base.mkdir(parents=True,exist_ok=True)
  self.path=base/'favorites.sqlite'
  with self.connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS favorites(path TEXT PRIMARY KEY, rating INTEGER NOT NULL DEFAULT 5, file_size INTEGER, sha256 TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
 def connect(self):return sqlite3.connect(self.path)
 def all(self):
  with self.connect() as db:return {os.path.normcase(os.path.abspath(r[0])) for r in db.execute('SELECT path FROM favorites WHERE rating=5')}
 def set(self,path,enabled):
  path=os.path.normcase(os.path.abspath(path))
  with self.connect() as db:
   if enabled:
    size=os.path.getsize(path) if os.path.isfile(path) else None
    db.execute('INSERT OR REPLACE INTO favorites(path,rating,file_size,sha256) VALUES(?,5,?,COALESCE((SELECT sha256 FROM favorites WHERE path=?),NULL))',(path,size,path))
   else:db.execute('DELETE FROM favorites WHERE path=?',(path,))
 def existing(self):return sorted(p for p in self.all() if os.path.isfile(p))
 def count(self):
  with self.connect() as db:return db.execute('SELECT COUNT(*) FROM favorites WHERE rating=5').fetchone()[0]

class Main(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('PHOTO_MANAGER · RC3 Photo Tidy Viewer Review');self.resize(1450,850)
  self.nav_history=[];self.nav_pos=-1;self.navigating_history=False;self.pool=QThreadPool.globalInstance();self.signals=Signals();self.signals.ready.connect(self.thumb_ready);self.signals.large_ready.connect(self.large_ready);self.generation=0;self.large_token=0;self.thumb_pending=set();self.thumb_cache_dir=Path.home()/"AppData"/"Local"/"PHOTO_MANAGER_RC3"/"thumb_cache";self.thumb_timer=QTimer(self);self.thumb_timer.setSingleShot(True);self.thumb_timer.timeout.connect(self.load_visible);self.pool.setMaxThreadCount(3);self.paths=[];self.items={};self.details={};self.favorite_store=FavoritesStore();self.favorites=self.favorite_store.all();self.favorites_mode=False;self.last_folder=None;self.current=None;self.show_names=False;self.thumb_size=160;self.focus_photo=False;self._filmstrip_wanted=True;self._viewer_open=False;self._info_stale=False
  self.setStyleSheet("""
   QMainWindow,QWidget{background:#1d2128;color:#e5e9f0;font-family:'Noto Sans TC','Microsoft JhengHei';font-size:13px}
   QTreeView,QListWidget{background:#1a1e25;color:#dce3ed;border:0;outline:0}
   QLineEdit{background:#292f39;color:#e8edf4;border:1px solid #353e4b;border-radius:7px;padding:7px 10px}
   QPushButton,QToolButton{background:#2b323d;color:#e8edf4;border:1px solid #3b4553;border-radius:7px;padding:6px 10px}
   QPushButton:hover,QToolButton:hover{background:#3c4857}
   QTabWidget::pane{border:0} QTabBar::tab{padding:9px 13px;background:transparent;color:#aeb8c6;border-bottom:2px solid transparent}
   QTabBar::tab:selected{color:#f0f4fa;border-bottom:2px solid #79a7da}
   QSplitter::handle{background:#303743;width:3px}
   QTreeView::item{height:25px} QTreeView::item:selected,QListWidget::item:selected{background:#344a65;border-radius:5px}
   QScrollBar:vertical{background:#1b2027;width:9px;margin:1px}
   QScrollBar::handle:vertical{background:#4a5360;min-height:32px;border-radius:4px}
   QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0}
   QScrollBar:horizontal{background:#1b2027;height:9px}
   QScrollBar::handle:horizontal{background:#4a5360;border-radius:4px}
   QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0}
   QLabel{background:transparent}
  """)
  top=QWidget();top.setObjectName('topbar');top.setStyleSheet('#topbar{background:#232933;border-bottom:1px solid #38414d}')
  topv=QHBoxLayout(top);topv.setContentsMargins(12,7,12,7);topv.setSpacing(9)
  brand=QLabel('▣  PHOTO_MANAGER');brand.setStyleSheet('font-weight:600;color:#f1f5fb;font-size:14px');topv.addWidget(brand)
  openbtn=QPushButton('▱  開啟資料夾');openbtn.clicked.connect(self.pick);topv.addWidget(openbtn)
  self.backbtn=QPushButton('←');self.backbtn.setToolTip('返回上一個資料夾');self.backbtn.setFixedWidth(36);self.backbtn.clicked.connect(lambda:self.go_history(-1));self.backbtn.setEnabled(False);topv.addWidget(self.backbtn)
  self.forwardbtn=QPushButton('→');self.forwardbtn.setToolTip('前進下一個資料夾');self.forwardbtn.setFixedWidth(36);self.forwardbtn.clicked.connect(lambda:self.go_history(1));self.forwardbtn.setEnabled(False);topv.addWidget(self.forwardbtn)
  self.upbtn=QPushButton('↑');self.upbtn.setToolTip('上一層資料夾');self.upbtn.setFixedWidth(36);self.upbtn.clicked.connect(self.go_up);topv.addWidget(self.upbtn)
  self.address=QLineEdit();self.address.setPlaceholderText('選擇資料夾，或輸入完整路徑');self.address.returnPressed.connect(lambda:self.open_folder(self.address.text()));topv.addWidget(self.address,1)
  refresh=QPushButton('↻');refresh.setFixedWidth(36);refresh.setToolTip('重新整理');refresh.clicked.connect(lambda:self.open_folder(self.address.text()));topv.addWidget(refresh)
  self.info_toggle=QPushButton('◧ 資訊');self.info_toggle.setCheckable(True);self.info_toggle.setChecked(True);topv.addWidget(self.info_toggle)
  container=QWidget();outer=QVBoxLayout(container);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0);outer.addWidget(top)
  splitter=QSplitter(Qt.Horizontal);outer.addWidget(splitter,1);self.setCentralWidget(container)
  left=QWidget();lv=QVBoxLayout(left);lv.setContentsMargins(8,8,8,8);lv.addWidget(QLabel('資料夾'))
  self.model=QFileSystemModel();self.model.setRootPath(QDir.rootPath());self.model.setFilter(QDir.AllDirs|QDir.NoDotAndDotDot|QDir.Drives)
  self.tree=QTreeView();self.tree.setModel(self.model);self.tree.setHeaderHidden(True)
  for c in range(1,4):self.tree.hideColumn(c)
  self.tree.clicked.connect(self.tree_clicked);self.tree.activated.connect(self.tree_clicked);lv.addWidget(self.tree,1)
  lv.addWidget(QLabel('我的照片庫（後續整合）'))
  self.favorites_button=QPushButton('♡  我的最愛 (0)')
  self.favorites_button.setToolTip('顯示已收藏的照片')
  self.favorites_button.setStyleSheet('QPushButton{background:#303945;border:1px solid #607086;text-align:left;padding:10px;border-radius:6px;color:#f3e0a3;font-weight:600} QPushButton:hover{background:#3e4b5c}')
  self.favorites_button.clicked.connect(self.open_favorites)
  lv.addWidget(self.favorites_button)
  self.update_favorites_count()
  splitter.addWidget(left)
  center=QWidget();cv=QVBoxLayout(center);cv.setContentsMargins(8,8,8,8)
  h=QHBoxLayout();self.folderlabel=QLabel('請選擇資料夾');h.addWidget(self.folderlabel,1);self.count=QLabel('0 張');h.addWidget(self.count);cv.addLayout(h)
  self.gallery=QListWidget();self.gallery.setViewMode(QListWidget.IconMode);self.gallery.setIconSize(QSize(160,118));self.gallery.setGridSize(QSize(168,124));self.gallery.setResizeMode(QListWidget.Adjust);self.gallery.setMovement(QListWidget.Static);self.gallery.setSpacing(0);self.gallery.setWordWrap(True);self.gallery.setSelectionMode(QAbstractItemView.ExtendedSelection);self.gallery.setContextMenuPolicy(Qt.CustomContextMenu);self.gallery.customContextMenuRequested.connect(self.context_menu);self.gallery.currentItemChanged.connect(self.selected);self.gallery.itemSelectionChanged.connect(self.refresh_single_fav);self.gallery.itemDoubleClicked.connect(self.open_viewer);self.gallery.viewport().installEventFilter(self);self.stack=QStackedWidget();self.stack.addWidget(self.gallery);cv.addWidget(self.stack,1)
  # Photo-first viewer: the browser's side panels remain available in gallery mode.
  # On opening a photo, only a slim title row, the image, tools and filmstrip are shown.
  self.viewer_page=QWidget();vp=QVBoxLayout(self.viewer_page)
  vp.setContentsMargins(2,2,2,2);vp.setSpacing(2)
  self.viewer_header=QWidget();self.viewer_header.setObjectName('photoViewerHeader')
  self.viewer_header.setStyleSheet('#photoViewerHeader{background:#20252d;border-bottom:1px solid #323a46}')
  vh=QHBoxLayout(self.viewer_header);vh.setContentsMargins(7,3,7,3);vh.setSpacing(5)
  self.close_view=QPushButton('← 縮圖');self.close_view.setToolTip('返回縮圖總覽（Esc）')
  self.close_view.clicked.connect(self.exit_viewer);vh.addWidget(self.close_view)
  self.view_prev=QPushButton('❮');self.view_prev.setToolTip('上一張（←）');self.view_prev.setFixedWidth(34)
  self.view_prev.clicked.connect(lambda:self.view_move(-1));vh.addWidget(self.view_prev)
  self.view_next=QPushButton('❯');self.view_next.setToolTip('下一張（→）');self.view_next.setFixedWidth(34)
  self.view_next.clicked.connect(lambda:self.view_move(1));vh.addWidget(self.view_next)
  self.view_title=QLabel('');self.view_title.setAlignment(Qt.AlignCenter)
  self.view_title.setStyleSheet('font-weight:600;color:#e5eaf1')
  vh.addWidget(self.view_title,1)
  self.view_counter=QLabel('');self.view_counter.setMinimumWidth(76);self.view_counter.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
  vh.addWidget(self.view_counter)
  self.strip_toggle=QPushButton('▤ 縮圖');self.strip_toggle.setToolTip('顯示／收起底部縮圖帶')
  self.strip_toggle.clicked.connect(self.toggle_filmstrip);vh.addWidget(self.strip_toggle)
  vp.addWidget(self.viewer_header)

  image_row=QHBoxLayout();image_row.setContentsMargins(0,0,0,0);image_row.setSpacing(0)
  self.big_scroll=QScrollArea();self.big_scroll.setWidgetResizable(False)
  self.big_scroll.setAlignment(Qt.AlignCenter)
  self.big_scroll.setStyleSheet('background:#11151a;border:0')
  self.big_scroll.viewport().installEventFilter(self)
  self.big_image=QLabel('');self.big_image.setAlignment(Qt.AlignCenter)
  self.big_image.setStyleSheet('background:#11151a')
  self.big_scroll.setWidget(self.big_image);image_row.addWidget(self.big_scroll,1)
  self.big_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
  self.big_scroll.customContextMenuRequested.connect(self.big_context_menu)
  self.big_image.setContextMenuPolicy(Qt.CustomContextMenu)
  self.big_image.customContextMenuRequested.connect(self.big_context_menu)
  self.zoom_percent=100;self.fit_mode=True;self.pan_start=None
  self.big_image.installEventFilter(self)
  self.big_scroll.horizontalScrollBar().setSingleStep(24)
  self.big_scroll.verticalScrollBar().setSingleStep(24)

  self.viewer_tools=QFrame();self.viewer_tools.setObjectName('photoViewerTools')
  self.viewer_tools.setFixedWidth(54)
  self.viewer_tools.setStyleSheet('#photoViewerTools{background:#20252d;border-left:1px solid #343d49}'
      'QPushButton{font-size:18px;min-height:30px;padding:3px 0px;border-radius:16px}'
      'QPushButton:hover{background:#45576b}')
  tv=QVBoxLayout(self.viewer_tools);tv.setContentsMargins(5,8,5,8);tv.setSpacing(7)
  self.zoom_in=QPushButton('+');self.zoom_in.setToolTip('放大（滑鼠滾輪）')
  self.zoom_in.clicked.connect(lambda:self.zoom_big(self.zoom_percent*1.25));tv.addWidget(self.zoom_in)
  self.zoom_out=QPushButton('−');self.zoom_out.setToolTip('縮小（滑鼠滾輪）')
  self.zoom_out.clicked.connect(lambda:self.zoom_big(self.zoom_percent/1.25));tv.addWidget(self.zoom_out)
  self.big_zoom=QSlider(Qt.Vertical);self.big_zoom.setRange(10,400)
  self.big_zoom.setFixedHeight(92);self.big_zoom.setValue(100)
  self.big_zoom.setToolTip('拖曳調整大圖縮放比例')
  self.big_zoom.valueChanged.connect(lambda v:self.zoom_big(v));tv.addWidget(self.big_zoom,0,Qt.AlignHCenter)
  self.zoom_label=QLabel('符合');self.zoom_label.setAlignment(Qt.AlignCenter)
  self.zoom_label.setStyleSheet('font-size:10px;color:#c8d3df');tv.addWidget(self.zoom_label)
  fitbtn=QPushButton('⊡');fitbtn.setToolTip('符合視窗')
  fitbtn.clicked.connect(self.fit_big_image);tv.addWidget(fitbtn)
  actualbtn=QPushButton('1:1');actualbtn.setToolTip('原始像素 100%（必要時重新載入原圖）')
  actualbtn.setStyleSheet('font-size:13px');actualbtn.clicked.connect(self.actual_pixels);tv.addWidget(actualbtn)
  self.big_fav=QPushButton('♡');self.big_fav.setToolTip('加入／取消我的最愛')
  self.big_fav.setObjectName('viewerHeart');self.big_fav.setMinimumSize(40,40)
  self.big_fav.clicked.connect(self.toggle_big_favorite);tv.addWidget(self.big_fav)
  self.viewer_info_button=QPushButton('ⓘ');self.viewer_info_button.setToolTip('顯示／隱藏 EXIF 與檔案資訊')
  self.viewer_info_button.clicked.connect(self.toggle_viewer_info);tv.addWidget(self.viewer_info_button)
  self.viewer_folder_button=QPushButton('☰');self.viewer_folder_button.setToolTip('顯示／隱藏資料夾樹')
  self.viewer_folder_button.clicked.connect(self.toggle_viewer_folders);tv.addWidget(self.viewer_folder_button)
  self.viewer_more=QPushButton('⋯');self.viewer_more.setToolTip('照片操作選單（與縮圖右鍵共用）')
  self.viewer_more.clicked.connect(self.viewer_more_menu);tv.addWidget(self.viewer_more)
  tv.addStretch(1)
  self.focus_button=QPushButton('⛶');self.focus_button.setToolTip('全圖模式（F11）；再次點擊還原')
  self.focus_button.clicked.connect(self.toggle_photo_focus);tv.addWidget(self.focus_button)
  image_row.addWidget(self.viewer_tools)
  self.viewer_image_area=QWidget();self.viewer_image_area.setLayout(image_row)
  vp.addWidget(self.viewer_image_area,1)

  self.filmstrip=QListWidget();self.filmstrip.setViewMode(QListWidget.IconMode)
  self.filmstrip.setFlow(QListWidget.LeftToRight);self.filmstrip.setWrapping(False)
  self.filmstrip.setIconSize(QSize(110,73));self.filmstrip.setGridSize(QSize(118,82))
  self.filmstrip.setFixedHeight(95);self.filmstrip.setSpacing(1)
  self.filmstrip.setStyleSheet('QListWidget{background:#1b2028;border-top:1px solid #343d49}'
     'QListWidget::item:selected{background:#405f81;border:2px solid #78a6db;border-radius:4px}')
  self.filmstrip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
  self.filmstrip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
  self.filmstrip.itemClicked.connect(lambda item:self.view_at(self.filmstrip.row(item)))
  vp.addWidget(self.filmstrip)
  self.viewer_toolbar=self.viewer_header  # Compatibility with earlier review versions.
  self.stack.addWidget(self.viewer_page);self.view_index=0;self.view_pix=None
  bottom=QHBoxLayout()
  self.name_toggle=QCheckBox('顯示檔名')
  self.name_toggle.setObjectName('filenameToggle')
  self.name_toggle.setCursor(Qt.PointingHandCursor)
  self.name_toggle.setToolTip('勾選顯示縮圖下方檔名；取消勾選可顯示更多照片')
  self.name_toggle.setStyleSheet("""
   QCheckBox#filenameToggle{background:#303945;color:#f4f7fc;border:1px solid #7b8798;
     border-radius:6px;padding:8px 13px;font-weight:600;spacing:9px}
   QCheckBox#filenameToggle:hover{background:#3c4858;border-color:#c4d5ea}
   QCheckBox#filenameToggle:checked{background:#30465e;border-color:#83b8ee}
   QCheckBox#filenameToggle::indicator{width:17px;height:17px;border:2px solid #dce5f0;
     border-radius:3px;background:#202833}
   QCheckBox#filenameToggle::indicator:checked{background:#79a7da;border-color:#a6cef6;
     image:none}
  """)
  self.name_toggle.setChecked(False)
  self.name_toggle.toggled.connect(self.change_names)
  bottom.addWidget(self.name_toggle)
  bottom.addStretch(1)
  bottom.addWidget(QLabel('縮圖大小'))
  self.zoom=QSlider(Qt.Horizontal);self.zoom.setRange(80,320);self.zoom.setSingleStep(10)
  self.zoom.setValue(160);self.zoom.setFixedWidth(180)
  self.zoom.valueChanged.connect(self.change_zoom);bottom.addWidget(self.zoom)
  self.zoom_value=QLabel('160 px');bottom.addWidget(self.zoom_value)
  self.single_fav=QPushButton('♡ 收藏選取照片')
  self.single_fav.setToolTip('單張收藏：點選一張縮圖後按此愛心；也可以直接點縮圖右上角的愛心')
  self.single_fav.clicked.connect(self.toggle_selected_favorite)
  bottom.insertWidget(1,self.single_fav)
  self.batch_fav=QPushButton('♡ 批次加入最愛');self.batch_fav.setToolTip('選取多張縮圖後，一次加入最愛');self.batch_fav.clicked.connect(lambda:self.batch_favorite(True));bottom.insertWidget(1,self.batch_fav)
  self.batch_unfav=QPushButton('♥ 批次取消');self.batch_unfav.clicked.connect(lambda:self.batch_favorite(False));bottom.insertWidget(2,self.batch_unfav)
  self.gallery_footer=QWidget();self.gallery_footer.setLayout(bottom);cv.addWidget(self.gallery_footer)
  splitter.addWidget(center)  # 主照片區
  right=QWidget();rv=QVBoxLayout(right);rv.setContentsMargins(9,8,9,8);rv.addWidget(QLabel('照片資訊'))
  self.tabs=QTabWidget();self.tabs.setUsesScrollButtons(False);self.tabs.tabBar().setExpanding(True);rv.addWidget(self.tabs,1)
  basics=QWidget();form=QFormLayout(basics);form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow);form.setLabelAlignment(Qt.AlignLeft|Qt.AlignTop);self.fields={}
  for key in ['檔名','檔案位置','檔案大小','修改時間','解析度','格式']:
   l=QLabel('—');l.setWordWrap(True);l.setMinimumWidth(1);l.setTextInteractionFlags(Qt.TextSelectableByMouse);l.setSizePolicy(__import__('PySide6.QtWidgets',fromlist=['QSizePolicy']).QSizePolicy.Ignored,__import__('PySide6.QtWidgets',fromlist=['QSizePolicy']).QSizePolicy.Preferred);form.addRow(key,l);self.fields[key]=l
  self.tabs.addTab(basics,'基本')
  ex=QWidget();ef=QFormLayout(ex);self.exif_fields={}
  for key in ['拍攝日期','相機品牌','相機型號','鏡頭','ISO','光圈','快門','焦距','曝光補償','閃光燈','白平衡','測光模式','色彩空間']:
   l=QLabel('—');l.setWordWrap(True);ef.addRow(key,l);self.exif_fields[key]=l
  self.tabs.addTab(ex,'拍攝')
  gps=QWidget();gf=QFormLayout(gps);self.gps_fields={}
  for key in ['GPS 緯度','GPS 經度','海拔','拍攝方向','軟體','影像方向']:
   l=QLabel('—');l.setWordWrap(True);gf.addRow(key,l);self.gps_fields[key]=l
  self.tabs.addTab(gps,'GPS')
  allmeta=QWidget();am=QVBoxLayout(allmeta);self.metadata_text=QTextEdit()
  self.metadata_text.setReadOnly(True);self.metadata_text.setPlaceholderText('選取照片後顯示可讀取的全部 Metadata')
  am.addWidget(self.metadata_text);self.tabs.addTab(allmeta,'Metadata')
  manage=QWidget();mv=QVBoxLayout(manage);self.fav=QCheckBox('♥ 我的最愛（儲存於本機資料庫）');self.fav.toggled.connect(self.toggle_fav);mv.addWidget(self.fav);mv.addWidget(QLabel('TAG（介面預覽，不寫入）'));self.tag=QLineEdit();self.tag.setPlaceholderText('例如：家庭、旅行');self.tag.setReadOnly(True);mv.addWidget(self.tag);mv.addWidget(QLabel('正式版將支援單張／批次編輯與寫入驗證。'));mv.addStretch();self.tabs.addTab(manage,'管理')
  self.more_info=QComboBox();self.more_info.addItems(['基本資訊','拍攝資訊','GPS','完整 Metadata','收藏管理']);self.more_info.currentIndexChanged.connect(self.tabs.setCurrentIndex);self.tabs.currentChanged.connect(self.more_info.setCurrentIndex);rv.insertWidget(1,self.more_info);self.tabs.tabBar().hide()
  rv.addWidget(QLabel('RC3 收藏驗收 · 只寫入本機收藏資料庫'))
  right.setMinimumWidth(205);right.setMaximumWidth(310);splitter.addWidget(right);self.main_splitter=splitter;self.left_panel=left;self.right_panel=right;self.top_panel=top;self.center_header=h;self.center_header_widget=None;splitter.setChildrenCollapsible(False);splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1);splitter.setStretchFactor(2,0);splitter.setSizes([245,1000,260]);self.info_toggle.toggled.connect(right.setVisible);self.setStatusBar(QStatusBar());self.statusBar().showMessage('RC3 收藏驗收版 · 收藏寫入本機 SQLite；原始照片不修改')
  self.set_dark_titlebar()
 def set_dark_titlebar(self):
  if sys.platform!='win32':return
  try:
   hwnd=int(self.winId());value=ctypes.c_int(1)
   for attr in (20,19):
    if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,attr,ctypes.byref(value),ctypes.sizeof(value))==0:break
  except Exception:pass
 def go_history(self,delta):
  pos=self.nav_pos+delta
  if pos<0 or pos>=len(self.nav_history):return
  self.nav_pos=pos;self.navigating_history=True
  try:self.open_folder(self.nav_history[pos])
  finally:self.navigating_history=False
 def open_workspace(self,mode):
  if mode=='browse':
   p=getattr(self,'last_folder',None)
   if p and os.path.isdir(p):self.open_folder(p)
   else:self.pick()
   return
  names={'inbox':'待整理照片','organize':'整理照片（V2）','rename':'批次重新命名','duplicates':'重複照片檢查','logs':'整理紀錄','trash':'垃圾桶'}
  name=names.get(mode,mode)
  QMessageBox.information(self,name,'此功能已納入 RC3 × V2 整合導覽。\n\n本階段包含完整 V2 原始碼，但尚未接通會改動檔案的操作。\n先驗收介面與瀏覽流程；待 TAG 索引衝突與資料安全測試通過後，再啟用正式執行。')
 def go_up(self):
  p=self.address.text().strip()
  if p and os.path.isdir(p):self.open_folder(str(Path(p).parent))
 def pick(self):
  p=QFileDialog.getExistingDirectory(self,'選擇要瀏覽的資料夾',self.address.text() or str(Path.home()))
  if p:self.open_folder(p)
 def tree_clicked(self,index):
  p=self.model.filePath(index)
  if os.path.isdir(p):self.open_folder(p,from_tree=True)
 def open_folder(self,p,from_tree=False):
  p=os.path.normpath(p.strip().strip('"'))
  if not os.path.isdir(p):QMessageBox.warning(self,'找不到資料夾',p);return
  if not getattr(self,'navigating_history',False):
   self.nav_history=self.nav_history[:self.nav_pos+1];self.nav_history.append(p);self.nav_pos=len(self.nav_history)-1
  self.backbtn.setEnabled(self.nav_pos>0);self.forwardbtn.setEnabled(self.nav_pos<len(self.nav_history)-1)
  self.favorites_mode=False;self.last_folder=p;self.generation+=1;self.address.setText(p);self.folderlabel.setText(Path(p).name or p)
  if not from_tree:
   idx=self.model.index(p)
   if idx.isValid():self.tree.setCurrentIndex(idx);self.tree.scrollTo(idx)
  self.exit_viewer()
  self.generation+=1;self.thumb_pending.clear();self.gallery.clear();self.items.clear();self.details.clear();self.paths=[];self.current=None;self.clear_info()
  try:self.paths=[str(x) for x in sorted(Path(p).iterdir(),key=lambda x:x.name.lower()) if x.is_file() and x.suffix.lower() in EXT]
  except Exception as e:QMessageBox.warning(self,'讀取失敗',str(e));return
  self.populate_gallery()
 def update_favorites_count(self):
  self.favorites=self.favorite_store.all()
  self.favorites_button.setText(f'♥  我的最愛 ({self.favorite_store.count()})')
 def open_favorites(self):
  self.exit_viewer()
  self.favorites_mode=True
  self.generation+=1
  self.folderlabel.setText('♡ 我的最愛')
  self.paths=self.favorite_store.existing()
  self.populate_gallery()
  missing=self.favorite_store.count()-len(self.paths)
  if missing:self.statusBar().showMessage(f'我的最愛：{len(self.paths)} 張可檢視，{missing} 張原始路徑已不存在（保留紀錄，待整理引擎同步）')
 def populate_gallery(self):
  self.thumb_pending.clear();self.gallery.clear();self.items.clear();self.details.clear();self.current=None;self.clear_info()
  self.count.setText(f'{len(self.paths)} 張')
  for path in self.paths:
   item=QListWidgetItem(('▧\n'+Path(path).name) if self.show_names else '')
   item.setData(Qt.UserRole,path);item.setToolTip(path)
   self.gallery.addItem(item);self.items[path]=item
  try:self.gallery.verticalScrollBar().valueChanged.disconnect(self.load_visible)
  except (RuntimeError,TypeError):pass
  self.gallery.verticalScrollBar().valueChanged.connect(lambda *_:self.thumb_timer.start(65))
  self.thumb_timer.start(20)
 def set_favorites(self,paths,enabled):
  errors=[]
  for p in paths:
   try:self.favorite_store.set(p,enabled)
   except Exception as e:errors.append(f'{Path(p).name}: {e}')
  self.update_favorites_count()
  for p in paths:self.update_thumb_heart(p)
  if self.current and self.right_panel.isVisible():self.update_info(self.current)
  self.refresh_big_fav()
  self.refresh_single_fav()
  if self.favorites_mode:self.open_favorites()
  if errors:QMessageBox.warning(self,'收藏更新失敗','\n'.join(errors[:10]))
  else:self.statusBar().showMessage(f'已{"加入" if enabled else "取消"} {len(paths)} 張我的最愛')
 def load_visible(self,*_):
  if not self.paths or self.stack.currentWidget()!=self.gallery:return
  view=self.gallery.viewport().rect().adjusted(-160,-160,160,160)
  candidates=[]
  for i in range(self.gallery.count()):
   item=self.gallery.item(i)
   if self.gallery.visualItemRect(item).intersects(view):
    p=item.data(Qt.UserRole)
    if p not in self.details and p not in self.thumb_pending:candidates.append(p)
  for p in candidates[:36]:
   self.thumb_pending.add(p)
   self.pool.start(ThumbJob(p,self.signals,max(240,self.thumb_size*2),self.generation,self.thumb_cache_dir))
 def thumb_ready(self,path,img,info,token):
  if token!=self.generation:return
  self.thumb_pending.discard(path)
  if path not in self.items:return
  if img is None:
   self.details[path]=info;self.items[path].setText('無預覽' if not self.show_names else Path(path).name)
  else:
   self.details[path]=info;item=self.items[path]
   item.setIcon(QIcon(QPixmap.fromImage(img)));self.update_thumb_heart(path);item.setText(Path(path).name if self.show_names else '')
  if hasattr(self,'filmstrip_items') and path in self.filmstrip_items:
   fi=self.filmstrip_items[path]
   if img is not None:fi.setIcon(QIcon(QPixmap.fromImage(img)))
  if self.current==path and self.right_panel.isVisible():self.update_info(path)
  if self.thumb_pending:return
  self.thumb_timer.start(15)

 def update_thumb_heart(self,path):
  """Paint a persistent heart badge on cached thumbnail icon, without altering the photo."""
  item=self.items.get(path)
  if item is None or item.icon().isNull():return
  # Keep the undecorated pixmap as the source to avoid drawing hearts repeatedly.
  raw=item.data(Qt.UserRole+3)
  if raw is None:
   raw=item.icon().pixmap(QSize(240,240))
   item.setData(Qt.UserRole+3,raw)
  if raw.isNull():return
  pix=QPixmap(raw);painter=QPainter(pix);painter.setRenderHint(QPainter.Antialiasing)
  d=max(22,min(39,int(pix.width()*.19)));x=pix.width()-d-3;y=3
  painter.setPen(Qt.NoPen);painter.setBrush(QColor(15,18,24,190));painter.drawRoundedRect(x,y,d,d,7,7)
  liked=os.path.normcase(os.path.abspath(path)) in self.favorites
  painter.setPen(QColor('#ff6e86') if liked else QColor('#ffffff'))
  font=QFont('Segoe UI Symbol',max(14,int(d*.63)));font.setBold(liked);painter.setFont(font)
  painter.drawText(x,y,d,d,Qt.AlignCenter,'♥' if liked else '♡');painter.end()
  item.setIcon(QIcon(pix))
 def toggle_selected_favorite(self):
  paths=self.selected_paths()
  if not paths and self.gallery.currentItem():paths=[self.gallery.currentItem().data(Qt.UserRole)]
  if not paths:
   self.statusBar().showMessage('請先點選一張縮圖，再按愛心');return
  if len(paths)>1:
   self.statusBar().showMessage('選取多張照片時，請使用批次加入／取消');return
  p=paths[0]
  self.set_favorites([p],os.path.normcase(os.path.abspath(p)) not in self.favorites)
 def refresh_single_fav(self):
  if not hasattr(self,'single_fav'):return
  paths=self.selected_paths()
  if not paths and self.gallery.currentItem():paths=[self.gallery.currentItem().data(Qt.UserRole)]
  if len(paths)!=1:
   self.single_fav.setText('♡ 收藏選取照片');return
  liked=os.path.normcase(os.path.abspath(paths[0])) in self.favorites
  self.single_fav.setText('♥ 取消收藏' if liked else '♡ 加入我的最愛')
  self.single_fav.setStyleSheet('QPushButton{color:'+('#ff6689' if liked else '#e8edf4')+';font-size:14px;font-weight:600}')
 def batch_favorite(self,enabled):
  paths=self.selected_paths()
  if not paths:
   self.statusBar().showMessage('請先在縮圖區選取一張或多張照片');return
  self.set_favorites(paths,enabled)
 def enter_photo_view(self):
  """Photo Tidy-style view: photo-first, without losing the gallery's management tools."""
  self._viewer_open=True;self.focus_photo=False;self._filmstrip_wanted=True
  self.top_panel.hide();self.left_panel.hide();self.right_panel.hide()
  self.gallery_footer.hide();self.folderlabel.hide();self.count.hide()
  self.statusBar().hide();self.viewer_header.show();self.filmstrip.show();self.viewer_tools.show()
  self.strip_toggle.setText('▤ 縮圖');self.focus_button.setText('⛶')
  QTimer.singleShot(0,self.fit_big_image)
 def toggle_filmstrip(self):
  if self.stack.currentWidget()!=self.viewer_page:return
  self._filmstrip_wanted=not self._filmstrip_wanted
  self.filmstrip.setVisible(self._filmstrip_wanted and not self.focus_photo)
  self.strip_toggle.setText('▤ 收起' if self._filmstrip_wanted else '▤ 顯示')
  if self.fit_mode:QTimer.singleShot(0,self.fit_big_image)
 def toggle_photo_focus(self):
  if self.stack.currentWidget()!=self.viewer_page:return
  self.focus_photo=not self.focus_photo
  self.viewer_header.setVisible(not self.focus_photo)
  self.filmstrip.setVisible(self._filmstrip_wanted and not self.focus_photo)
  self.left_panel.hide();self.right_panel.hide()
  self.focus_button.setText('↙' if self.focus_photo else '⛶')
  self.focus_button.setToolTip('退出全圖模式（F11）' if self.focus_photo else '全圖模式（F11）')
  if self.fit_mode:QTimer.singleShot(0,self.fit_big_image)
 def leave_photo_focus(self):
  if self.focus_photo:self.toggle_photo_focus()
 def toggle_viewer_info(self):
  if self.stack.currentWidget()!=self.viewer_page:return
  show=not self.right_panel.isVisible()
  if self.focus_photo and show:self.toggle_photo_focus()
  self.right_panel.setVisible(show)
  if show:
   self.update_info(self.current);self._info_stale=False
  if self.fit_mode:QTimer.singleShot(0,self.fit_big_image)
 def toggle_viewer_folders(self):
  if self.stack.currentWidget()!=self.viewer_page:return
  show=not self.left_panel.isVisible()
  if self.focus_photo and show:self.toggle_photo_focus()
  self.left_panel.setVisible(show)
  if self.fit_mode:QTimer.singleShot(0,self.fit_big_image)
 def viewer_more_menu(self):
  if self.current:
   self.show_photo_context(self.current,self.viewer_more.mapToGlobal(self.viewer_more.rect().bottomLeft()))
 def selected(self,item,previous):
  self.current=item.data(Qt.UserRole) if item else None
  self.update_info(self.current) if self.current else self.clear_info()
 def clear_info(self):
  for l in self.fields.values():l.setText('—')
  for l in self.exif_fields.values():l.setText('—')
  for l in self.gps_fields.values():l.setText('—')
  self.metadata_text.clear()
  self.fav.blockSignals(True);self.fav.setChecked(False);self.fav.blockSignals(False)
 def update_info(self,p):
  if not p:return
  try:
   st=os.stat(p);from datetime import datetime
   d={'檔名':Path(p).name,'檔案位置':str(Path(p).parent),'檔案大小':f'{st.st_size/1024/1024:.2f} MB','修改時間':datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'),'解析度':self.details.get(p,{}).get('dimensions','載入中'),'格式':self.details.get(p,{}).get('format',Path(p).suffix.upper())}
   for k,v in d.items():self.fields[k].setText(v)
   for l in self.exif_fields.values():l.setText('—')
   for l in self.gps_fields.values():l.setText('—')
   with Image.open(p) as im:
    ex=im.getexif()
    # EXIF photo tags are often in the nested ExifIFD (0x8769), not the top-level IFD0.
    merged=dict(ex)
    try:merged.update(ex.get_ifd(0x8769))
    except Exception:pass
    tagmap={271:'相機品牌',272:'相機型號',36867:'拍攝日期',36868:'拍攝日期',306:'拍攝日期',34855:'ISO',33437:'光圈',33434:'快門',37386:'焦距',42036:'鏡頭',37380:'曝光補償',37385:'閃光燈',37384:'白平衡',37383:'測光模式',40961:'色彩空間',305:'軟體',274:'影像方向'}
    vals={}
    for key,val in merged.items():
     name=ExifTags.TAGS.get(key,str(key))
     vals[str(name)]=str(val)[:1000]
     label=tagmap.get(key)
     if label in self.exif_fields:self.exif_fields[label].setText(str(val))
     if label in self.gps_fields:self.gps_fields[label].setText(str(val))
    try:
     gps=ex.get_ifd(0x8825)
     for k,v in gps.items():vals['GPS.'+str(ExifTags.GPSTAGS.get(k,k))]=str(v)
     if 2 in gps:self.gps_fields['GPS 緯度'].setText(f"{gps.get(1,'')} {gps[2]}")
     if 4 in gps:self.gps_fields['GPS 經度'].setText(f"{gps.get(3,'')} {gps[4]}")
     if 6 in gps:self.gps_fields['海拔'].setText(str(gps[6]))
     if 17 in gps:self.gps_fields['拍攝方向'].setText(str(gps[17]))
    except Exception:pass
    self.metadata_text.setPlainText(json.dumps(vals,ensure_ascii=False,indent=2) if vals else '此檔案沒有可讀取的 EXIF。\nIPTC／XMP／MakerNotes 尚未接入正式解析器。')
   self.fav.blockSignals(True);self.fav.setChecked(os.path.normcase(os.path.abspath(p)) in self.favorites);self.fav.blockSignals(False)
  except Exception as e:self.statusBar().showMessage('資訊讀取失敗：'+str(e))
 def toggle_fav(self,checked):
  if not self.current:return
  self.set_favorites([self.current],checked)
 def open_viewer(self,item):
  if item and item.data(Qt.UserRole) in self.paths:
   self.filmstrip.clear();self.filmstrip_items={}
   for p in self.paths:
    fi=QListWidgetItem('');fi.setData(Qt.UserRole,p);fi.setToolTip(Path(p).name)
    self.filmstrip.addItem(fi);self.filmstrip_items[p]=fi
   self.stack.setCurrentWidget(self.viewer_page)
   self.enter_photo_view()
   self.view_at(self.paths.index(item.data(Qt.UserRole)))
 def exit_viewer(self):
  if not hasattr(self,'stack'):return
  if self._viewer_open:
   self.focus_photo=False;self._viewer_open=False
   self.viewer_header.show();self.filmstrip.show()
   self.top_panel.show();self.left_panel.show()
   self.right_panel.setVisible(self.info_toggle.isChecked())
   self.gallery_footer.show();self.folderlabel.show();self.count.show()
   self.statusBar().show()
  self.stack.setCurrentWidget(self.gallery);self.thumb_timer.start(20)
 def view_at(self,index):
  if not self.paths:return
  self.view_index=index%len(self.paths);p=self.paths[self.view_index]
  self.view_counter.setText(f'{self.view_index+1} / {len(self.paths)}')
  self.view_title.setText(Path(p).name)
  self.filmstrip.setCurrentRow(self.view_index);self.filmstrip.scrollToItem(self.filmstrip.item(self.view_index))
  self.current=p
  self.favorites=self.favorite_store.all()
  if self.right_panel.isVisible():self.update_info(p)
  else:self._info_stale=True
  self.refresh_big_fav()
  self.large_token+=1;self._full_request=False;self.full_loaded=False;self.view_pix=None;self.big_image.clear();self.big_image.setText('載入照片中…');self.big_image.adjustSize()
  self.pool.start(LargeJob(p,self.signals,self.large_token),10)
  # Only queue nearby thumbnails; never decode all images synchronously.
  for i in range(max(0,self.view_index-6),min(len(self.paths),self.view_index+7)):
   path=self.paths[i];item=self.filmstrip.item(i)
   if item and item.icon().isNull():
    thumb=self.items.get(path)
    if thumb and not thumb.icon().isNull():item.setIcon(thumb.icon())
    elif path not in self.thumb_pending and path not in self.details:
     self.thumb_pending.add(path)
     self.pool.start(ThumbJob(path,self.signals,240,self.generation,self.thumb_cache_dir))
 def large_ready(self,path,img,token,error):
  if token!=self.large_token or path!=self.current or self.stack.currentWidget()!=self.viewer_page:return
  if img is None:
   self._full_request=False;self.big_image.setText('無法讀取照片：'+error);return
  self.view_pix=QPixmap.fromImage(img)
  if getattr(self,'_full_request',False):
   self._full_request=False;self.full_loaded=True;self.zoom_big(100)
  else:self.fit_big_image()
 def fit_big_image(self):
  if self.view_pix is None or self.view_pix.isNull():return
  size=self.big_scroll.viewport().size()
  self.zoom_percent=max(10,min(400,int(min(size.width()/self.view_pix.width(),size.height()/self.view_pix.height())*100)))
  self.fit_mode=True;self.apply_big_zoom()
 def actual_pixels(self):
  """On-demand original-pixel decode; the normal fast viewer stays downsampled."""
  if not self.current:return
  if self.full_loaded:
   self.zoom_big(100);return
  reader=QImageReader(self.current);sz=reader.size()
  if sz.isValid() and sz.width()*sz.height()>50000000:
   answer=QMessageBox.question(self,'原始解析度',
    f'這張照片約 {sz.width()*sz.height()/1000000:.1f} 百萬像素，載入原圖可能需要大量記憶體。\n仍要載入嗎？',
    QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
   if answer!=QMessageBox.Yes:return
  if sz.isValid() and max(sz.width(),sz.height())<=3600:
   self.full_loaded=True;self.zoom_big(100);return
  self.large_token+=1;self._full_request=True
  self.zoom_label.setText('載入')
  self.pool.start(LargeJob(self.current,self.signals,self.large_token,full=True),10)
 def zoom_big(self,percent):
  if self.view_pix is None or self.view_pix.isNull():return
  self.zoom_percent=max(10,min(400,int(percent)));self.fit_mode=False;self.apply_big_zoom()
 def apply_big_zoom(self):
  if self.view_pix is None or self.view_pix.isNull():return
  w=max(1,round(self.view_pix.width()*self.zoom_percent/100));h=max(1,round(self.view_pix.height()*self.zoom_percent/100))
  self.big_image.setPixmap(self.view_pix.scaled(w,h,Qt.KeepAspectRatio,Qt.SmoothTransformation));self.big_image.resize(w,h)
  self.big_zoom.blockSignals(True);self.big_zoom.setValue(self.zoom_percent);self.big_zoom.blockSignals(False)
  self.zoom_label.setText(f'{self.zoom_percent}%')
 def eventFilter(self,obj,event):
  if hasattr(self,'gallery') and obj is self.gallery.viewport() and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton and self.stack.currentWidget()==self.gallery:
   item=self.gallery.itemAt(event.position().toPoint())
   if item is not None:
    rect=self.gallery.visualItemRect(item);pos=event.position().toPoint()
    # Heart is in the upper-right of the thumbnail cell; single-click toggles it.
    if rect.right()-44<=pos.x()<=rect.right() and rect.top()<=pos.y()<=rect.top()+44:
     path=item.data(Qt.UserRole)
     self.set_favorites([path],os.path.normcase(os.path.abspath(path)) not in self.favorites)
     return True
  if hasattr(self,'big_image') and obj in (self.big_image,self.big_scroll.viewport()):
   if event.type()==QEvent.Wheel and self.stack.currentWidget()==self.viewer_page:
    factor=1.25 if event.angleDelta().y()>0 else .8
    self.zoom_big(self.zoom_percent*factor);return True
   if event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
    self.pan_start=event.globalPosition().toPoint();return False
   if event.type()==QEvent.MouseMove and self.pan_start is not None and (event.buttons()&Qt.LeftButton):
    delta=event.globalPosition().toPoint()-self.pan_start;self.pan_start=event.globalPosition().toPoint()
    for bar,d in [(self.big_scroll.horizontalScrollBar(),delta.x()),(self.big_scroll.verticalScrollBar(),delta.y())]:bar.setValue(bar.value()-d)
    return True
   if event.type()==QEvent.MouseButtonRelease:self.pan_start=None
  return super().eventFilter(obj,event)
 def toggle_big_favorite(self):
  # Use the displayed photo, not gallery selection. Read the database first so
  # thumbnail, filmstrip, and full-size views always share the same state.
  path=self.current
  if not path:return
  try:
   liked=os.path.normcase(os.path.abspath(path)) in self.favorite_store.all()
   self.favorite_store.set(path,not liked)
  except Exception as exc:
   QMessageBox.warning(self,'收藏失敗',f'{Path(path).name}\n{exc}')
   return
  self.update_favorites_count()
  self.update_thumb_heart(path)
  self.refresh_big_fav()
  self.refresh_single_fav()
  if self.right_panel.isVisible():
   self.fav.blockSignals(True)
   self.fav.setChecked(not liked)
   self.fav.blockSignals(False)
  self.statusBar().showMessage(('已加入' if not liked else '已取消')+'我的最愛：'+Path(path).name,3500)
 def refresh_big_fav(self):
  if not hasattr(self,'big_fav'):return
  liked=bool(self.current and os.path.normcase(os.path.abspath(self.current)) in self.favorites)
  self.big_fav.setText('♥' if liked else '♡')
  self.big_fav.setToolTip('♥ 已收藏，點擊取消' if liked else '♡ 點擊加入我的最愛')
  self.big_fav.setStyleSheet('QPushButton{font-size:25px;font-weight:700;color:'+('#ff5b7f' if liked else '#e6edf7')+';background:#303945;border:1px solid #607086;border-radius:18px}QPushButton:hover{background:#47566b}')

 def big_context_menu(self,pos):
  if self.current:
   sender=self.sender()
   widget=sender if isinstance(sender,QWidget) else self.big_image
   self.show_photo_context(self.current,widget.mapToGlobal(pos))
 def view_move(self,step):self.view_at(self.view_index+step)
 def resizeEvent(self,e):
  super().resizeEvent(e)
  if hasattr(self,'stack') and self.stack.currentWidget()==self.viewer_page and self.fit_mode:QTimer.singleShot(0,self.fit_big_image)
 def selected_paths(self):
  return [i.data(Qt.UserRole) for i in self.gallery.selectedItems()]
 def change_zoom(self,value):
  self.thumb_size=value
  self.zoom_value.setText(f'{value} px')
  self.gallery.setIconSize(QSize(value,round(value*.74)))
  self.gallery.setGridSize(QSize(value+8,round(value*.74)+(34 if self.show_names else 8)))
  self.gallery.doItemsLayout()
  self.thumb_timer.start(40)
 def change_names(self,checked):
  self.show_names=checked
  self.name_toggle.setText('✓ 顯示檔名' if checked else '顯示檔名')
  for p,item in self.items.items():
   item.setText(Path(p).name if checked else '')
  self.change_zoom(self.zoom.value())
 def preview_action(self,action,paths):
  QMessageBox.information(self,'RC3 操作流程預覽',
   f'功能：{action}\\n選取：{len(paths)} 張\\n\\n這是整合前的 UI 驗收版，不會修改、移動、刪除或覆寫照片。'.replace('\\n','\n'))
 def context_menu(self,pos):
  item=self.gallery.itemAt(pos)
  if item and not item.isSelected():
   self.gallery.clearSelection();item.setSelected(True);self.gallery.setCurrentItem(item)
  paths=self.selected_paths()
  self.show_photo_context(paths,self.gallery.viewport().mapToGlobal(pos))
 def show_photo_context(self,selection,global_pos):
  paths=[selection] if isinstance(selection,str) else list(selection)
  menu=QMenu(self);actions={}
  def add(name,enabled=True):
   a=menu.addAction(name);a.setEnabled(enabled);actions[a]=name
  add('開啟大圖',len(paths)==1)
  add('在檔案總管中顯示',len(paths)==1)
  menu.addSeparator()
  add('剪下    Ctrl+X',bool(paths));add('複製    Ctrl+C',bool(paths));add('貼上    Ctrl+V',True);add('另存新檔…',bool(paths))
  menu.addSeparator()
  add('重新命名    F2',len(paths)==1);add('批次重新命名…',len(paths)>1);add('刪除    Delete',bool(paths));add('全選    Ctrl+A',bool(self.paths))
  menu.addSeparator()
  all_fav=bool(paths) and all(os.path.normcase(os.path.abspath(p)) in self.favorites for p in paths)
  add('♥ 取消我的最愛' if all_fav else '♡ 加入我的最愛',bool(paths))
  add('編輯 TAG…',bool(paths));menu.addSeparator();add('內容／Metadata',len(paths)==1)
  act=menu.exec(global_pos)
  if act is None:return
  name=actions.get(act,'')
  if name=='開啟大圖':
   if self.stack.currentWidget()!=self.viewer_page:
    item=self.items.get(paths[0]);self.open_viewer(item) if item else None
  elif name=='在檔案總管中顯示':self.reveal_file(paths[0])
  elif name.startswith('全選'):
   self.exit_viewer();self.gallery.selectAll()
  elif name.startswith('複製'):
   mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(p) for p in paths]);QApplication.clipboard().setMimeData(mime)
   self.statusBar().showMessage(f'已複製 {len(paths)} 個檔案參照到剪貼簿')
  elif name.startswith('♡'):self.set_favorites(paths,True)
  elif name.startswith('♥'):self.set_favorites(paths,False)
  elif name=='內容／Metadata':
   if self.stack.currentWidget()==self.viewer_page and not self.right_panel.isVisible():self.toggle_viewer_info()
   self.tabs.setCurrentIndex(min(3,self.tabs.count()-1))
  else:self.preview_action(name,paths)
 def reveal_file(self,path):
  import subprocess
  if sys.platform=='win32':subprocess.Popen(['explorer.exe','/select,',os.path.normpath(path)])
  else:QMessageBox.information(self,'檔案位置',path)
 def rename_file(self,path):
  old=Path(path)
  name,ok=QInputDialog.getText(self,'重新命名','新檔名（含副檔名）：',text=old.name)
  if not ok or not name or name==old.name:return
  if name in ('.','..') or any(c in name for c in '<>:"/\\|?*') or name.endswith((' ','.')):
   QMessageBox.warning(self,'檔名無效','檔名含有 Windows 不允許的字元。');return
  dest=old.with_name(name)
  if dest.exists():QMessageBox.warning(self,'禁止覆蓋','目標檔案已存在，沒有執行重新命名。');return
  if QMessageBox.question(self,'確認重新命名',f'{old.name}\n→ {name}\n\n此操作會修改實體檔名。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
  try:
   old.rename(dest)
   self.open_folder(str(old.parent))
  except Exception as e:QMessageBox.critical(self,'重新命名失敗',str(e))
 def recycle_files(self,paths):
  if send2trash is None:
   QMessageBox.warning(self,'缺少安全刪除元件','未安裝 send2trash，已取消操作；不會永久刪除。');return
  if QMessageBox.question(self,'確認移至資源回收筒',f'確定將選取的 {len(paths)} 張照片移至 Windows 資源回收筒？\n\n此操作會移動原始檔案。請確認選取範圍。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
  ok=[];fail=[]
  for path in paths:
   try:
    if not Path(path).is_file():raise FileNotFoundError('原檔不存在')
    send2trash(path);ok.append(path)
   except Exception as e:fail.append(f'{Path(path).name}: {e}')
  self.open_folder(self.address.text())
  if fail:QMessageBox.warning(self,'部分照片未移動',f'成功 {len(ok)} 張，失敗 {len(fail)} 張。\n'+'\n'.join(fail[:12]))
  else:QMessageBox.information(self,'操作完成',f'{len(ok)} 張已送交系統資源回收筒。')
 def keyPressEvent(self,e):
  if hasattr(self,'stack') and self.stack.currentWidget()==self.viewer_page:
   if e.key()==Qt.Key_F11:self.toggle_photo_focus();return
   if e.key()==Qt.Key_Escape:
    if self.focus_photo:self.toggle_photo_focus()
    else:self.exit_viewer()
    return
   if e.key()==Qt.Key_Left:self.view_move(-1);return
   if e.key()==Qt.Key_Right:self.view_move(1);return
  if self.gallery.hasFocus():
   if e.key()==Qt.Key_Delete:
    self.preview_action('刪除',self.selected_paths());return
   if e.key()==Qt.Key_F2:
    self.preview_action('重新命名',self.selected_paths());return
   if e.matches(QKeySequence.Paste):
    self.preview_action('貼上',self.selected_paths());return
   if e.matches(QKeySequence.Cut):
    self.preview_action('剪下',self.selected_paths());return
   if e.key() in (Qt.Key_Return,Qt.Key_Enter):
    item=self.gallery.currentItem()
    if item:self.open_viewer(item)
    return
  super().keyPressEvent(e)

if __name__=='__main__':
 app=QApplication(sys.argv);app.setStyle('Fusion');w=Main();w.show();sys.exit(app.exec())
