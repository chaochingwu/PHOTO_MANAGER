import os,sys,json,time,threading,queue,datetime,re,sqlite3,subprocess,traceback
from version import APP_VERSION, APP_AUTHOR
from organize import run as organize_run
from everything_search import PHOTO_EXT,VIDEO_EXT,search_command
from PySide6.QtCore import QSettings
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl
from PySide6.QtGui import QIcon,QFont,QFontDatabase,QDesktopServices
from PySide6.QtWidgets import *
from library_setup import initialize,open_library,info
from photo_manager_v1_4 import Library,sync,checkroot,paths_ok,atomic_json,core
BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).parent)); HOME=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
STYLE='''QWidget{font-size:14px;color:#20354b;background:#f2f5fa} QFrame#card{background:white;border:1px solid #dce4ef;border-radius:12px} QFrame#card QLabel{background:transparent} QFrame#nav,QFrame#header{background:#173957} QFrame#nav QLabel,QFrame#header QLabel{color:white;background:transparent} QPushButton{background:white;border:1px solid #cbd7e5;border-radius:8px;padding:10px 16px;font-weight:600} QPushButton:hover{background:#e6f0fc} QPushButton:disabled{color:#8995a5;background:#e9edf2} QPushButton#primary{background:#1769b4;color:white;border:0} QPushButton#primary:hover{background:#217dce} QPushButton#navbutton{background:transparent;color:#e7f1ff;text-align:left;border:0;padding:12px} QPushButton#navbutton:checked{background:#2c76b9;color:white} QLineEdit,QComboBox,QSpinBox{background:white;border:1px solid #cbd7e5;border-radius:7px;padding:8px;min-height:22px} QLineEdit:focus{border:2px solid #2476bf} QProgressBar{background:#e1e8f1;border:0;border-radius:5px;height:10px;text-align:center} QProgressBar::chunk{background:#2581d9;border-radius:5px} QPlainTextEdit{background:white;border:1px solid #dce4ef;border-radius:8px;padding:8px} QScrollArea{border:0} QLabel#heading{font-size:25px;font-weight:700} QLabel#metric{font-size:25px;font-weight:700;color:#173957} QLabel#muted{color:#65788c;font-size:12px}'''
def label(t,name=''):
    w=QLabel(t);w.setObjectName(name);w.setWordWrap(True);return w
def button(t,fn,primary=False):
    b=QPushButton(t);b.clicked.connect(fn);b.setObjectName('primary' if primary else '');b.setMinimumHeight(38);return b
def card(title=''):
    w=QFrame();w.setObjectName('card');l=QVBoxLayout(w);l.setContentsMargins(18,16,18,16);l.setSpacing(12)
    if title:l.addWidget(label(title,'heading'))
    return w,l
class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('PHOTO_MANAGER V2.0');self.setWindowIcon(QIcon(str(BASE/'PHOTO_MANAGER.ico')));self.resize(1180,780);self.setMinimumSize(850,650)
        self.cfg=HOME/'CONFIG'/'settings.json';self.cfg.parent.mkdir(exist_ok=True)
        try:c=json.loads(self.cfg.read_text(encoding='utf-8'))
        except Exception:c={}
        self.local=QSettings('PHOTO_MANAGER','Everything');self.search_cfg=c.get('everything_formats',{});self.advanced=c.get('advanced',False);self.busy=False;self.q=queue.Queue();self.stop=threading.Event();self.pause=threading.Event();self.report=None;self.started=0;self.buttons=[]
        self.paths=[QLineEdit(x) for x in c.get('paths',['','',''])];self.modes=[];self.years=[]
        for i in range(2):
            m=QComboBox();m.addItems(['完整同步','僅匯入','指定年份','單向備份']);m.setCurrentText(c.get('modes',['完整同步','僅匯入'])[i]);self.modes.append(m);y=QLineEdit(c.get('years',['2026','2026'])[i]);y.setMaximumWidth(85);self.years.append(y);m.currentTextChanged.connect(lambda t,y=y:y.setVisible(t=='指定年份'))
        self.inbox=QCheckBox('只整理 INBOX');self.inbox.setChecked(c.get('inbox',True))
        self.scope=QComboBox();self.scope.addItems(['僅 INBOX','全部照片庫','局部資料夾']);self.partial=QComboBox();self.partial.setMinimumContentsLength(25);self.partial.addItem('請選擇資料夾','');self.partial_refresh=button('重新讀取資料夾',self.refresh_partial);self.partial_children=QCheckBox('包含所有子資料夾');self.partial_children.setChecked(True);self.scope.currentIndexChanged.connect(self.scope_changed);self.taskboxes={k:QCheckBox(t) for k,t in [('screenshots','辨識及分離截圖／網路圖片'),('classify','依日期分類'),('rename','依拍攝時間重新排序及命名'),('duplicates','刪除重複檔案（可復原）')]};[b.setChecked(True) for b in self.taskboxes.values()]
        self.root=QWidget();self.setCentralWidget(self.root);outer=QVBoxLayout(self.root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        head=QFrame();head.setObjectName('header');hl=QHBoxLayout(head);hl.setContentsMargins(20,10,20,10);ico=QLabel();ico.setPixmap(QIcon(str(BASE/'PHOTO_MANAGER.ico')).pixmap(48,48));hl.addWidget(ico);title=label('PHOTO_MANAGER · V2.0','heading');title.setWordWrap(False);hl.addWidget(title);hl.addStretch();copyright=label('Copyright © 2026 Chaoching Wu');copyright.setWordWrap(False);copyright.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter);hl.addWidget(copyright);outer.addWidget(head)
        body=QHBoxLayout();body.setContentsMargins(0,0,0,0);body.setSpacing(0);outer.addLayout(body,1)
        self.nav=QFrame();self.nav.setObjectName('nav');self.nav.setFixedWidth(205);nl=QVBoxLayout(self.nav);nl.setContentsMargins(12,16,12,16);body.addWidget(self.nav)
        self.stack=QStackedWidget();body.addWidget(self.stack,1);self.pages={};self.navbuttons={}
        for name in ['總覽','照片庫管理','整理照片與影片','同步照片庫','Everything 搜尋','健康檢查','執行報告','系統設定','使用說明','關於軟體']:
            b=button(name,lambda checked=False,n=name:self.showpage(n));b.setObjectName('navbutton');b.setCheckable(True);nl.addWidget(b);self.navbuttons[name]=b
        nl.addStretch();nl.addWidget(button('切換簡易模式',self.toggle));self.simple=self.make_simple();self.stack.addWidget(self.simple)
        for name in self.navbuttons:self.pages[name]=self.make_page(name);self.stack.addWidget(self.pages[name])
        self.footer=QFrame();fl=QHBoxLayout(self.footer);fl.setContentsMargins(18,8,18,8);self.status=label('準備就緒');fl.addWidget(self.status,1);self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);fl.addWidget(self.progress,2);self.pausebtn=button('暫停',self.toggle_pause);self.stopbtn=button('安全停止',self.stop.set);fl.addWidget(self.pausebtn);fl.addWidget(self.stopbtn);outer.addWidget(self.footer);self.pausebtn.setEnabled(False);self.stopbtn.setEnabled(False)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(100);self.toggle(initial=True)
    def save(self):atomic_json(self.cfg,{'paths':[x.text() for x in self.paths],'modes':[x.currentText() for x in self.modes],'years':[x.text() for x in self.years],'advanced':self.advanced,'inbox':self.inbox.isChecked(),'everything_formats':{k:[x for x,b in boxes.items() if b.isChecked()] for k,boxes in self.extboxes.items()} if hasattr(self,'extboxes') else self.search_cfg})
    def browse(self,i):
        if self.busy:return
        try:
            if i==0:
                p=QFileDialog.getExistingDirectory(self,'開啟現有照片庫',self.paths[0].text() or str(Path.home()))
                if not p:return
                p=open_library(p)
                self.paths[0].setText(str(p));self.paths[1].clear();self.paths[2].clear()
            else:
                p=QFileDialog.getExistingDirectory(self,'選擇既有同步照片庫',self.paths[i].text() or str(Path.home()))
                if not p:return
                p=open_library(p);paths_ok([Path(self.paths[0].text()).resolve(),p]);self.paths[i].setText(str(p))
            self.save();self.refresh()
        except Exception as e:QMessageBox.warning(self,'照片庫設定',str(e))
    def create_library(self,existing=False):
        if self.busy:return
        parent=QFileDialog.getExistingDirectory(self,'選擇現有資料夾' if existing else '選擇照片庫儲存位置',str(Path.home()))
        if not parent:return
        name,ok=QInputDialog.getText(self,'照片庫名稱','輸入照片庫名稱',text=Path(parent).name if existing else '家庭照片庫')
        if not ok:return
        try:
            p=initialize(parent,name,existing);self.paths[0].setText(str(p));self.paths[1].clear();self.paths[2].clear();self.save();self.refresh()
        except Exception as e:QMessageBox.warning(self,'建立失敗',str(e))
    def backup_library(self,i):
        if self.busy:return
        try:
            if not self.paths[0].text():raise ValueError('請先建立或開啟目前照片庫')
            source=open_library(self.paths[0].text());name=info(source)['name']
            parent=QFileDialog.getExistingDirectory(self,'選擇備份庫的上層資料夾',str(Path.home()))
            if not parent:return
            p=initialize(parent,name,source=source);paths_ok([source,p]);self.paths[i].setText(str(p));self.modes[i-1].setCurrentText('單向備份');self.save();self.refresh()
        except Exception as e:QMessageBox.warning(self,'備份設定',str(e))
    def pathcard(self):
        w,l=card('照片庫設定');r=QHBoxLayout()
        for t,f in [('建立新照片庫',lambda:self.create_library()),('開啟現有照片庫',lambda:self.browse(0)),('使用現有資料夾',lambda:self.create_library(True))]:r.addWidget(button(t,f))
        l.addLayout(r)
        for i in range(3):
            l.addWidget(label(['目前照片庫','同步照片庫 1','同步照片庫 2'][i]));r=QHBoxLayout();self.paths[i].setReadOnly(True);r.addWidget(self.paths[i],1)
            if i:
                r.addWidget(button('建立同名備份',lambda checked=False,i=i:self.backup_library(i)));r.addWidget(button('開啟既有庫',lambda checked=False,i=i:self.browse(i)));r.addWidget(button('清除',lambda checked=False,i=i:self.clear_target(i)))
            l.addLayout(r)
            if i:
                r=QHBoxLayout();r.addWidget(self.modes[i-1],1);r.addWidget(self.years[i-1]);self.years[i-1].setVisible(self.modes[i-1].currentText()=='指定年份');l.addLayout(r)
        l.addWidget(label('單向備份：目前庫 → 目標庫；僅匯入：目標庫 → 目前庫。指定年份：雙向合併。以上三種均不傳播刪除。','muted'));return w
    def clear_target(self,i):
        if not self.busy:self.paths[i].clear();self.save();self.refresh()
    def actions(self,l):
        r=QHBoxLayout()
        for t,a in [('整理照片與影片','organize'),('同步照片庫','sync')]:
            b=button(t,lambda checked=False,a=a:self.showpage('整理照片與影片') if a=='organize' else self.start(a),a=='organize');b.setMinimumHeight(58);r.addWidget(b);self.buttons.append(b)
        l.addLayout(r)
    def scroll(self,w):
        s=QScrollArea();s.setWidgetResizable(True);s.setWidget(w);return s
    def make_simple(self):
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(30,24,30,24);r=QHBoxLayout();r.addWidget(label('簡易模式','heading'));r.addStretch();r.addWidget(button('進階模式',self.toggle));l.addLayout(r);self.pathbox=self.pathcard();self.actions(l);l.addWidget(self.pathbox);r=QHBoxLayout();r.addWidget(button('開啟 INBOX',self.open_inbox));r.addWidget(button('執行報告',self.open_report));l.addLayout(r);l.addStretch();return self.scroll(w)
    def make_page(self,n):
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(26,22,26,22);l.setSpacing(16);l.addWidget(label(n,'heading'))
        if n=='總覽':
            r=QHBoxLayout();self.metrics=[]
            for t in ['照片','影片','已設定照片庫','索引容量']:
                c,cl=card();cl.addWidget(label(t,'muted'));v=label('—','metric');cl.addWidget(v);self.metrics.append(v);r.addWidget(c)
            l.addLayout(r);c,cl=card('快速操作');self.actions(cl);l.addWidget(c);c,cl=card('照片庫狀態');self.states=[label('未設定') for _ in range(3)];[cl.addWidget(x) for x in self.states];cl.addWidget(button('設定照片庫',lambda:self.showpage('照片庫管理')));l.addWidget(c);c,cl=card('執行進度');self.detail=label('尚未執行','muted');cl.addWidget(self.detail);cl.addWidget(button('查看執行日誌',lambda:self.showpage('執行報告')));l.addWidget(c)
        elif n=='同步照片庫':
            c,cl=card('同步照片庫');cl.addWidget(label('先在照片庫管理設定方向。完整同步會傳播刪除；單向備份、僅匯入及指定年份不傳播刪除。'));cl.addWidget(button('設定照片庫',lambda:self.showpage('照片庫管理')));b=button('同步照片庫',lambda:self.start('sync'),True);cl.addWidget(b);self.buttons.append(b);l.addWidget(c)
        elif n=='整理照片與影片':
            c,cl=card('整理照片與影片');cl.addWidget(label('依拍攝日期分類、統一命名、照片與影片分開存放、刪除重複照片與影片。保護 Live Photo。'));cl.addWidget(label('處理範圍'));cl.addWidget(self.scope);cl.addWidget(self.partial);cl.addWidget(self.partial_refresh);cl.addWidget(self.partial_children);cl.addWidget(label('局部整理只選取指定來源；分類目的地可能在其他年份或類別，請核對預覽。'));cl.addWidget(label('處理項目'));[cl.addWidget(b) for b in self.taskboxes.values()];b=button('開始整理照片與影片',lambda:self.start('organize'),True);cl.addWidget(b);self.buttons.append(b);cl.addWidget(button('開啟 INBOX',self.open_inbox));cl.addWidget(button('返回簡易模式',lambda:self.toggle(initial=True) if not self.advanced else self.toggle()));l.addWidget(c)
        elif n=='照片庫管理':
            self.pathholder=QVBoxLayout();l.addLayout(self.pathholder);l.addWidget(button('開啟目前照片庫',lambda:self.open_path(self.paths[0].text())))
        elif n=='使用說明':
            c,cl=card('第一次使用');cl.addWidget(label('1. 建立新照片庫或開啟既有庫。\n2. 將照片及影片放入 00_INBOX。\n3. 整理照片與影片。\n4. 設定同名備份庫，再同步。\n完整同步會傳播刪除；請保留獨立備份。'));cl.addWidget(button('開啟完整使用說明',lambda:self.open_path(str(HOME/'README.txt'))));l.addWidget(c)
        elif n=='關於軟體':
            c,cl=card('PHOTO_MANAGER V2.0');cl.addWidget(label('作者：Chaoching Wu（吳照慶）\nCopyright © 2026 Chaoching Wu\n開發協作：ChatGPT\n正式版 · Windows 免安裝\nV2.0 正式版。\n照片與影片管理、索引及多庫同步。'));l.addWidget(c)
        elif n=='Everything 搜尋':
            self.extboxes={}
            for key,title,exts in [('photo','照片格式',PHOTO_EXT),('video','影片格式',VIDEO_EXT)]:
                c,cl=card(title);g=QGridLayout();boxes={};self.extboxes[key]=boxes
                for i,x in enumerate(exts):
                    cb=QCheckBox(x.upper());cb.setChecked(x in self.search_cfg.get(key,exts));boxes[x]=cb;g.addWidget(cb,i//4,i%4);cb.toggled.connect(self.update_search)
                cl.addLayout(g);r=QHBoxLayout();r.addStretch();r.addWidget(button('全選',lambda checked=False,k=key:self.select_ext(k,True)));r.addWidget(button('取消全選',lambda checked=False,k=key:self.select_ext(k,False)));cl.addLayout(r);l.addWidget(c)
            c,cl=card('搜尋指令');r=QHBoxLayout();self.searchfolder=QLineEdit();self.searchfolder.setPlaceholderText('搜尋位置（選填）');self.searchfolder.textChanged.connect(self.update_search);r.addWidget(self.searchfolder,1);r.addWidget(button('瀏覽',self.choose_search_folder));cl.addLayout(r)
            self.searchtext=QPlainTextEdit();self.searchtext.setReadOnly(True);self.searchtext.setMaximumHeight(90);cl.addWidget(self.searchtext);self.copysearch=button('複製搜尋指令',self.copy_search,True);cl.addWidget(self.copysearch);self.searchstatus=label('','muted');cl.addWidget(self.searchstatus);l.addWidget(c)
            c,cl=card('Everything 程式整合（選用）');self.ev_enabled=QCheckBox('啟用 Everything 程式整合');self.ev_enabled.setChecked(self.local.value('enabled',False,type=bool));cl.addWidget(self.ev_enabled);self.ev_panel=QWidget();el=QVBoxLayout(self.ev_panel);el.setContentsMargins(0,0,0,0);r=QHBoxLayout();self.ev_path=QLineEdit(self.local.value('path','',type=str));self.ev_path.setPlaceholderText('請指定 Everything.exe');r.addWidget(self.ev_path,1);r.addWidget(button('瀏覽',self.choose_everything));el.addLayout(r);self.ev_launch=button('開啟 Everything 並搜尋',self.launch_everything);el.addWidget(self.ev_launch);cl.addWidget(self.ev_panel);self.ev_enabled.toggled.connect(self.update_search);self.ev_path.textChanged.connect(self.update_search);l.addWidget(c);self.update_search()
        elif n=='健康檢查':
            c,cl=card('完整雜湊檢查');cl.addWidget(label('讀取所有已歸檔檔案，核對索引；大量照片可能耗時。'));b=button('開始檢查',lambda:self.start('check'),True);cl.addWidget(b);self.buttons.append(b);l.addWidget(c)
        elif n=='執行報告':
            self.out=QPlainTextEdit();self.out.setReadOnly(True);l.addWidget(self.out,1);l.addWidget(button('開啟 TXT 報告',self.open_report))
        else:
            c,cl=card('系統設定');cl.addWidget(label('設定隨程式資料夾保存。字體優先使用 Noto Sans TC，其次使用 Windows 微軟正黑體。'));cl.addWidget(button('儲存設定',self.save));l.addWidget(c)
        l.addStretch();return self.scroll(w)
    def select_ext(self,key,value):
        for b in self.extboxes[key].values():b.setChecked(value)
    def choose_search_folder(self):
        p=QFileDialog.getExistingDirectory(self,'選擇搜尋位置',self.searchfolder.text() or str(Path.home()))
        if p:self.searchfolder.setText(p)
    def choose_everything(self):
        p,_=QFileDialog.getOpenFileName(self,'選擇 Everything.exe',self.ev_path.text() or str(Path.home()),'Everything (Everything.exe);;執行檔 (*.exe)')
        if p:self.ev_path.setText(p)
    def update_search(self,*args):
        if not hasattr(self,'ev_launch'):return
        try:
            cmd=search_command(*[[x for x,b in self.extboxes[k].items() if b.isChecked()] for k in ('photo','video')],self.searchfolder.text());self.searchstatus.setText('' if cmd else '請至少選擇一種格式')
        except ValueError as e:cmd='';self.searchstatus.setText(str(e))
        self.searchtext.setPlainText(cmd);self.copysearch.setEnabled(bool(cmd));enabled=self.ev_enabled.isChecked();self.ev_panel.setVisible(enabled);self.ev_launch.setEnabled(bool(cmd and self.ev_path.text().strip()));self.local.setValue('enabled',enabled);self.local.setValue('path',self.ev_path.text());self.save()
    def copy_search(self):
        cmd=self.searchtext.toPlainText();QApplication.clipboard().setText(cmd)
        self.searchstatus.setText('已複製，請貼到 Everything 搜尋欄。' if QApplication.clipboard().text()==cmd else '複製未確認，請手動選取指令複製。')
    def launch_everything(self):
        try:
            p=Path(self.ev_path.text().strip()).resolve()
            if not self.ev_enabled.isChecked() or not p.is_file() or p.name.lower()!='everything.exe':raise ValueError('請重新指定有效的 Everything.exe')
            subprocess.Popen([str(p),'-search',self.searchtext.toPlainText()],cwd=str(p.parent));self.searchstatus.setText('已送出搜尋指令。')
        except Exception as e:QMessageBox.warning(self,'Everything',str(e))
    def toggle(self,initial=False):
        if self.busy:return
        if not initial:self.advanced=not self.advanced
        self.nav.setVisible(self.advanced)
        if self.advanced:self.showpage('總覽' if self.paths[0].text() else '照片庫管理')
        else:
            self.simple.widget().layout().insertWidget(1,self.pathbox);self.stack.setCurrentWidget(self.simple)
        self.save();self.refresh()
    def refresh_partial(self):
        from scope_folders import folders
        old=self.partial.currentData();self.partial.clear();self.partial.addItem('請選擇資料夾','')
        for rel in folders(self.paths[0].text()):self.partial.addItem(rel,rel)
        i=self.partial.findData(old);self.partial.setCurrentIndex(max(0,i))
    def scope_changed(self,*_):
        local=self.scope.currentIndex()==2
        for w in (self.partial,self.partial_refresh,self.partial_children):w.setEnabled(local)
        if local:self.refresh_partial()
    def showpage(self,n):
        if n=='整理照片與影片':self.scope_changed()
        if n=='照片庫管理':self.pathholder.addWidget(self.pathbox)
        self.stack.setCurrentWidget(self.pages[n]);[b.setChecked(k==n) for k,b in self.navbuttons.items()];self.refresh()
    def refresh(self):
        p=self.paths[0].text();counts=[0,0,0];db=Path(p)/'.PHOTO_MANAGER/library.db' if p else None
        if db and db.is_file():
            try:
                with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as con:
                    for path,size in con.execute('SELECT path,size FROM files'):counts[1 if path.startswith('VIDEOS/') else 0]+=1;counts[2]+=size
            except Exception:pass
        for v,t in zip(self.metrics,[f'{counts[0]:,}',f'{counts[1]:,}',str(sum(bool(x.text()) for x in self.paths)),f'{counts[2]/1024**3:,.2f} GB']):v.setText(t if p else '—')
        for i,v in enumerate(self.states):
            p=self.paths[i].text();v.setText(f'{["目前庫","同步庫 1","同步庫 2"][i]}  •  '+(p+'  |  '+('可存取' if Path(p).is_dir() else '離線') if p else '未設定'))
    def open_path(self,p):
        if p and Path(p).exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).resolve())))
        else:QMessageBox.information(self,'提示','尚未設定或檔案不存在。')
    def open_inbox(self):
        try:
            if not self.paths[0].text().strip():raise ValueError('請選擇目前照片庫')
            p=checkroot(self.paths[0].text())/'00_INBOX';p.mkdir(exist_ok=True);self.open_path(str(p))
        except Exception as e:QMessageBox.warning(self,'錯誤',str(e))
    def open_report(self):self.open_path(str(self.report) if self.report else '')
    def toggle_pause(self):
        if self.pause.is_set():self.pause.clear();self.pausebtn.setText('暫停')
        else:self.pause.set();self.pausebtn.setText('繼續')
    def checkpoint(self):
        while self.pause.is_set() and not self.stop.is_set():time.sleep(.1)
        if self.stop.is_set():raise InterruptedError('使用者停止')
    def start(self,a):
        if self.busy:return
        try:
            if not self.paths[0].text().strip():raise ValueError('請選擇目前照片庫')
            root=open_library(self.paths[0].text());targets=[]
            if a=='organize' and self.scope.currentIndex()==2:
                from scope_folders import local_base
                local_base(root,self.partial.currentData() or '')
            for i in range(2):
                p=self.paths[i+1].text();m=['full','import','partial','backup'][self.modes[i].currentIndex()];y=self.years[i].text()
                if p:
                    if m=='partial' and not re.fullmatch(r'\d{4}',y):raise ValueError('年份須為四位數')
                    targets.append((p,m,y))
            if a=='sync':
                paths_ok([root]+[Path(p).resolve() for p,m,y in targets])
            if a=='sync' and not targets:raise ValueError('請設定同步庫')
        except Exception as e:QMessageBox.warning(self,'設定錯誤',str(e));return
        if QMessageBox.question(self,'確認操作','此版本仍為候選版，請使用測試複本。重複檔案移至復原區。請先保留獨立備份。是否開始？')!=QMessageBox.StandardButton.Yes:return
        self.save();self.busy=True;self.stop.clear();self.pause.clear();self.started=time.monotonic();self.out.clear();self.progress.setRange(0,0);self.status.setText('執行中');self.pausebtn.setEnabled(True);self.stopbtn.setEnabled(True);[b.setEnabled(False) for b in self.buttons];scope=['inbox','all','partial'][self.scope.currentIndex()];partial=self.partial.currentData() or '';include_children=self.partial_children.isChecked();tasks=tuple(k for k,b in self.taskboxes.items() if b.isChecked())
        def worker():
            lines=[];status='完成'
            def log(s):lines.append(str(s));self.q.put(('log',str(s)))
            try:
                if a=='organize':
                    if not tasks:raise ValueError('請選擇處理項目')
                    def confirm(entries,count):
                        event=threading.Event();answer=[]
                        self.q.put(('plan',(entries,count,event,answer)))
                        while not event.wait(.1):self.checkpoint()
                        return bool(answer and answer[0])
                    from catalog_bridge import prepare,finalize,pending
                    catalog_db=os.environ.get('PM_V21_CATALOG')
                    if catalog_db and pending(catalog_db,root):raise ValueError('前次 TAG 整理交易尚未完成；請先恢復整理索引')
                    def confirmed(entries,count):
                        if not confirm(entries,count):return False
                        if catalog_db:prepare(catalog_db,root,entries)
                        return True
                    result=organize_run(root,scope,tasks,partial,log,self.checkpoint,include_children=include_children,confirm_plan=confirmed)
                    if result is False:raise InterruptedError('已取消整理預覽，未搬移照片')
                    lib=Library(root)
                    try:lib.scan(log,self.checkpoint,detect=False)
                    finally:lib.close()
                    if catalog_db:
                        updated=finalize(catalog_db,root)
                        log(f'已同步更新 {updated} 筆照片身分／TAG 路徑')
                elif a=='sync':
                    online=[]
                    for p,m,y in targets:
                        if Path(p).is_dir():
                            info(p);online.append((p,m,y))
                        else:log('離線，跳過：'+p)
                    if not online:status='同步暫停';log('沒有可用同步庫；本次未變更任何照片。請重新連接硬碟。')
                    else:sync(root,online,log,self.checkpoint)
                else:
                    lib=Library(root)
                    try:
                        old=lib.rows(); from photo_manager_v1_4 import archive_files
                        actual={}; errors=0
                        for p in archive_files(root):
                            self.checkpoint();rel=p.relative_to(root).as_posix()
                            try:actual[rel]=core.digest(p)
                            except OSError as e:errors+=1;log(f'讀取失敗：{rel}：{e}')
                        missing=set(old)-set(actual);new=set(actual)-set(old);changed={k for k in set(old)&set(actual) if old[k][0]!=actual[k]}
                        for kind,items in [('索引缺失',missing),('未索引',new),('內容變更',changed)]:
                            for rel in sorted(items):log(f'{kind}：{rel}')
                        log(f'健康檢查：索引 {len(old)}；可讀 {len(actual)}；缺失 {len(missing)}；未索引 {len(new)}；變更 {len(changed)}；讀取錯誤 {errors}；相同雜湊額外副本 {len(actual)-len(set(actual.values()))}。未修改索引。')
                    finally:lib.close()
            except InterruptedError as e:status='已停止';log(str(e))
            except Exception as e:status='執行失敗';log(f'{type(e).__name__}：{e}')
            report=None
            try:
                report=root/'99_LOG'/('PHOTO_MANAGER_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.txt');report.parent.mkdir(exist_ok=True);report.write_text(f'PHOTO_MANAGER V2.0\n結果：{status}\n耗時：{time.monotonic()-self.started:.1f} 秒\n'+'\n'.join(lines),encoding='utf-8-sig')
            except Exception as e:status='報告寫入失敗';log(str(e));report=None
            self.q.put(('done',(status,report)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        while True:
            try:k,v=self.q.get_nowait()
            except queue.Empty:break
            if k=='log':
                self.out.appendPlainText(v);self.detail.setText(v);m=re.search(r'(?:同步|單向備份) (\d+)/(\d+)',v)
                if m and int(m[2]):self.progress.setRange(0,int(m[2]));self.progress.setValue(int(m[1]));self.status.setText(f'複製階段 {m[1]}/{m[2]}')
            elif k=='plan':
                entries,count,event,answer=v
                try:
                    changed=[(p,d) for p,d,h in entries if p!=d];dialog=QDialog(self);dialog.setWindowTitle('局部整理預覽');dialog.resize(900,550);layout=QVBoxLayout(dialog);layout.addWidget(label(f'選定來源 {count} 個媒體；預計搬移／改名／復原區 {len(changed)} 筆。請核對目的地，可能跨年份或類別。'));view=QPlainTextEdit('\n'.join(f'{p} → {d}' for p,d in changed[:2000]));view.setReadOnly(True);layout.addWidget(view);layout.addWidget(label('最多顯示前 2000 筆；超過此數量請縮小整理範圍後再執行。'));buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(len(changed)<=2000);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);answer.append(dialog.exec()==QDialog.DialogCode.Accepted and not self.stop.is_set())
                finally:event.set()
            else:
                self.busy=False;self.status.setText(v[0]);self.report=v[1];self.progress.setRange(0,100);self.progress.setValue(100 if v[0]=='完成' else 0);self.pausebtn.setEnabled(False);self.stopbtn.setEnabled(False);self.pausebtn.setText('暫停');[b.setEnabled(True) for b in self.buttons];self.refresh()
    def closeEvent(self,e):
        if self.busy:QMessageBox.information(self,'執行中','請先安全停止並等待完成。');e.ignore()
        else:self.save();e.accept()
if __name__=='__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(sys.argv);app.setStyle('Fusion');families=QFontDatabase.families();app.setFont(QFont('Noto Sans TC' if 'Noto Sans TC' in families else 'Microsoft JhengHei',11));app.setStyleSheet(STYLE);w=Window();w.show();sys.exit(app.exec())
