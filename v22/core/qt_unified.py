"""Single-window V2.1 candidate; V2.0 engine unchanged."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from qt_v21 import UpgradeWindow,STYLE
from library_qt import LibraryPage,HOME,btn
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel,QMessageBox,QStyle,QFileDialog,QInputDialog,QPlainTextEdit,QDialog,QDialogButtonBox
from release_guard import protected_roots
class Unified(UpgradeWindow):
    def __init__(self):
        os.environ['PM_V21_CATALOG']=str(HOME/'catalog.sqlite')
        super().__init__('總覽');self.setWindowTitle('PHOTO_MANAGER V2.1 | Qt RC2f');self.resize(1500,900);self.setMinimumSize(1050,650)
        self.lib=LibraryPage(self);self.add_page('Library 瀏覽',self.lib,1,'SP_FileDialogListView');self.add_page('Import 匯入',self.import_page(),2,'SP_DialogOpenButton');self.showpage('Library 瀏覽')
        page_layout=self.pages['整理照片與影片'].widget().layout()
        notice=QLabel('主庫內部整理：使用下方「處理範圍」選擇 INBOX、全庫或局部資料夾。\n外部資料夾匯入：使用下方獨立入口；禁止選擇主庫內的來源。')
        notice.setWordWrap(True);page_layout.insertWidget(1,notice)
        page_layout.insertWidget(2,btn('整理外部資料夾並匯入主庫',self.quick_import,'SP_DialogOpenButton',self))
        page_layout.insertWidget(3,btn('恢復中斷的主庫整理／TAG 索引',self.recover_organize,'SP_BrowserReload',self))
    def add_page(self,name,page,pos,ico):
        self.pages[name]=page;self.stack.addWidget(page);b=btn(name,lambda:self.showpage(name),ico,self);b.setCheckable(True);b.setObjectName('navbutton');self.nav.layout().insertWidget(pos,b);self.navbuttons[name]=b
    def showpage(self,n):
        if n=='Library 瀏覽':
            self.stack.setCurrentWidget(self.pages[n]);[b.setChecked(k==n) for k,b in self.navbuttons.items()];return
        super().showpage(n)
    def start(self,a):
        if self.busy:return
        if getattr(self,'lib',None) and self.lib.running:
            QMessageBox.warning(self,'背景工作','請等待 Library 工作完成。');return
        if a=='organize':
            try:
                from catalog_bridge import pending
                from library_setup import initialize
                root=Path(self.paths[0].text()).resolve()
                if pending(self.lib.c.path,root):
                    QMessageBox.warning(self,'未完成的整理','有未完成的整理／TAG 交易。請先使用「恢復中斷的主庫整理／TAG 索引」。');return
                if not (root/'.PHOTO_MANAGER/identity.json').is_file():
                    if QMessageBox.question(self,'初始化 V2.0 主庫',
                        f'目前照片庫尚未初始化 V2.0 管理結構：\n{root}\n\n建立 .PHOTO_MANAGER 及 PHOTOS／VIDEOS／INBOX 等管理目錄（不搬移現有照片）？\n請只在測試副本上執行。',
                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                    initialize(root.parent,root.name,existing=True)
                row=self.lib.c.db.execute('SELECT id,role FROM sources WHERE root=?',(str(root),)).fetchone()
                if not row:
                    if QMessageBox.question(self,'Library 主庫索引',f'需要先將主庫登錄並索引，才能安全保留 TAG：\n{root}\n是否登錄並索引？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                    sid=self.lib.c.add_source(root,'primary');self.lib.c.scan(sid)
                elif row['role']!='primary':raise ValueError('此資料夾在 Library 不是主庫角色，請先確認來源設定')
            except Exception as e:QMessageBox.warning(self,'主庫整理準備失敗',str(e));return
        self._last_v20_action=a
        super().start(a)
    def recover_organize(self):
        from catalog_bridge import pending,recover
        root=Path(self.paths[0].text()).resolve()
        if not pending(self.lib.c.path,root):
            QMessageBox.information(self,'整理索引','目前沒有待恢復的整理交易。');return
        if QMessageBox.question(self,'恢復整理',f'偵測到未完成的整理交易：\n{root}\n\n將依已記錄的 SHA256 計畫續作搬移，再修復 TAG 索引。請確認測試庫已備份。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.lib.task(lambda:recover(self.lib.c.path,root),lambda n:(self.reload_library(),QMessageBox.information(self,'完成',f'已恢復 {n} 筆照片索引。')))
    def refresh(self):
        super().refresh()
        lib=getattr(self,'lib',None)
        if lib is None or not self.paths[0].text():return
        if self.metrics[0].text() not in ('0','—'):return
        root=str(Path(self.paths[0].text()).resolve())
        rows=lib.c.db.execute('SELECT p.rel,p.size FROM photos p JOIN sources s ON p.source=s.id WHERE s.root=? AND s.role=?',(root,'primary')).fetchall()
        if not rows:return
        from library_catalog import VIDEO
        photos=sum(Path(r['rel']).suffix.lower() not in VIDEO for r in rows)
        videos=len(rows)-photos
        self.metrics[0].setText(f'{photos:,}');self.metrics[1].setText(f'{videos:,}');self.metrics[3].setText(f'{sum(r["size"] for r in rows)/1024**3:,.2f} GB')
    def poll(self):
        was_busy=self.busy
        super().poll()
        if was_busy and not self.busy and self.status.text()=='完成':
            if getattr(self,'_last_v20_action',None)=='organize':
                root=Path(self.paths[0].text()).resolve()
                sid=self.lib.c.db.execute('SELECT id FROM sources WHERE root=?',(str(root),)).fetchone()
                if sid:
                    from catalog import Catalog
                    db=self.lib.c.path
                    def rescan():
                        c=Catalog(db)
                        try:return c.scan(sid[0],cancel=self.lib.cancel.is_set)
                        finally:c.close()
                    self.lib.task(rescan,lambda n:(self.reload_library(),self.refresh()))
            else:self.reload_library()

    def import_page(self):
        w=QWidget();l=QVBoxLayout(w);l.addWidget(QLabel('Import · 匯入照片（TAG 非必填）'));l.addWidget(QLabel('先安全保存，再選擇整理。原始檔案不刪除、不覆蓋。'))
        for t,f in [('快速匯入 · SHA256 去重',self.quick_import),('Google Takeout · ZIP 健檢',self.audit),('Google Takeout · 確認匯入',self.takeout),('匯出照片索引 HTML / CSV',self.export_index),('匯出選取照片 XMP',self.export_xmp),('全庫日期健檢報告',self.date_report),('備份 TAG 資料庫快照',self.backup_tags),('停止可取消的背景工作',lambda:self.lib.cancel.set())]:l.addWidget(btn(t,f))
        l.addStretch();return w
    def folder(self,t):return QFileDialog.getExistingDirectory(self,t)
    def report_path(self):
        p,_=QFileDialog.getSaveFileName(self,'報告位置（來源之外）','','JSON (*.json)')
        if not p:return None
        p=Path(p).resolve()
        if p==self.lib.c.path or any(p==Path(s['root']) or Path(s['root']) in p.parents for s in self.lib.c.sources()):raise ValueError('報告必須在來源及資料庫之外')
        return p
    def quick_import(self):
        if not self.lib.guard():return
        from master_import import plan,run,delete_verified,deletion_blockers
        from catalog import Catalog
        from PySide6.QtWidgets import QComboBox,QCheckBox,QPushButton,QHBoxLayout
        from scope_folders import folders
        from PySide6.QtCore import QSettings
        from import_choices import choices,validate
        settings=QSettings('PHOTO_MANAGER','V21Import')
        destinations,sources=choices(self.lib.c.sources(),self.paths[0].text(),settings.value('destination',''),settings.value('source',''))
        d=QDialog(self);d.setWindowTitle('整理並匯入主庫');d.resize(760,520);l=QVBoxLayout(d)
        def selector(title,values,button_text):
            l.addWidget(QLabel(title));row=QHBoxLayout();box=QComboBox();box.addItem('請選擇資料夾','')
            for p in values:box.addItem(p,p)
            row.addWidget(box,1);browse=QPushButton(button_text);row.addWidget(browse);l.addLayout(row)
            def choose():
                p=QFileDialog.getExistingDirectory(d,title,box.currentData() or str(Path.home()))
                if p:
                    p=str(Path(p).resolve());i=box.findData(p)
                    if i<0:box.addItem(p,p);i=box.count()-1
                    box.setCurrentIndex(i)
            browse.clicked.connect(choose);return box
        destbox=selector('目的主庫',destinations,'瀏覽／新增主庫…')
        srcbox=selector('來源照片庫／外部資料夾',sources,'瀏覽來源…')
        sub=QComboBox();l.addWidget(QLabel('整理範圍'));l.addWidget(sub)
        children=QCheckBox('包含子資料夾');children.setChecked(True);l.addWidget(children)
        mode=QComboBox();mode.addItems(['保留原結構','依日期分年／月']);l.addWidget(mode);rename=QCheckBox('依日期統一命名（無可靠日期則保留）');l.addWidget(rename)
        l.addWidget(QLabel('先複製並驗證；完成後才詢問是否刪除來源。原地整理請使用原有整理頁。'))
        status=QLabel();status.setWordWrap(True);l.addWidget(status)
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);ok=b.button(QDialogButtonBox.StandardButton.Ok);ok.setText('產生預覽');b.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');l.addWidget(b)
        def check():
            try:
                validate(self.lib.c,srcbox.currentData(),destbox.currentData());status.setText('來源與目的主庫已分開，可以產生預覽。');ok.setEnabled(True)
            except Exception as e:status.setText(str(e));ok.setEnabled(False)
        def refresh():
            sub.clear();sub.addItem('整個來源資料夾','')
            for f in folders(srcbox.currentData() or ''):sub.addItem(f,f)
            check()
        srcbox.currentIndexChanged.connect(refresh);destbox.currentIndexChanged.connect(check)
        if destinations:destbox.setCurrentIndex(1)
        last=settings.value('source','');i=srcbox.findData(last)
        if i>0:srcbox.setCurrentIndex(i)
        refresh()
        def accept():
            try:
                source,dest=validate(self.lib.c,srcbox.currentData(),destbox.currentData())
                if not any(Path(s['root'])==dest and s['role']=='primary' for s in self.lib.c.sources()):
                    if QMessageBox.question(d,'登錄主庫',f'將此資料夾登錄為 Library 主庫？\n{dest}\n不會建立 V2.0 管理庫或修改原始照片。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                    self.lib.c.add_source(dest,'primary')
                settings.setValue('destination',str(dest));settings.setValue('source',str(source));d.accept()
            except Exception as e:status.setText(str(e))
        b.accepted.connect(accept);b.rejected.connect(d.reject)
        if d.exec()!=QDialog.DialogCode.Accepted:return
        src=Path(srcbox.currentData())/(sub.currentData() or '');dest=Path(destbox.currentData());db=self.lib.c.path;cancel=self.lib.cancel.is_set
        def planned(items):
            if not items:self.lib.error('沒有可匯入照片');return
            counts={k:sum(e.action==k for e in items) for k in ('copy','rename','duplicate')}
            p=QDialog(self);p.setWindowTitle('匯入預覽');p.resize(850,520);v=QVBoxLayout(p);v.addWidget(QLabel(f'來源：{src}\n主庫：{dest}\n新增 {counts["copy"]}；改名 {counts["rename"]}；重複 {counts["duplicate"]}。不覆蓋、不刪除。'))
            t=QPlainTextEdit('\n'.join(f'{e.action}: {e.source} → {e.relative}' for e in items));t.setReadOnly(True);v.addWidget(t);b=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(p.accept);b.rejected.connect(p.reject);v.addWidget(b)
            if p.exec()!=QDialog.DialogCode.Accepted:return
            def complete(batch):
                self.reload_library();c=Catalog(db)
                try:reasons=deletion_blockers(c,src.resolve(),items)
                finally:c.close()
                if reasons:QMessageBox.information(self,'主庫已驗證，來源保留',f'{len(items)} 筆 SHA256／TAG 驗證通過。\n'+'\n'.join(reasons[:15]));return
                q=QMessageBox(self);q.setWindowTitle('主庫匯入完成');q.setText(f'{len(items)} 筆 SHA256／TAG 驗證通過。\n是否刪除已驗證來源檔案？\n來源：{src}');keep=q.addButton('保留來源（預設）',QMessageBox.ButtonRole.RejectRole);remove=q.addButton('刪除來源…',QMessageBox.ButtonRole.DestructiveRole);q.setDefaultButton(keep);q.exec()
                if q.clickedButton()!=remove:return
                if QMessageBox.question(self,'再次確認',f'永久刪除 {len(items)} 個已驗證來源檔案？\n不刪除其他檔案或資料夾。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                self.lib.task(lambda:delete_verified(db,src,dest,items,batch,True),lambda n:(self.reload_library(),QMessageBox.information(self,'完成',f'已刪除 {n} 個來源檔案')))
            self.lib.task(lambda:run(db,src,dest,items,cancel),complete)
        classification='date' if mode.currentIndex()==1 else 'preserve';recursive=children.isChecked();do_rename=rename.isChecked()
        self.lib.task(lambda:plan(db,src,dest,classification,recursive,do_rename,cancel),planned)
    def reload_library(self,_=None):self.lib.rebuild();self.lib.refresh_rows()
    def audit(self):
        if not self.lib.guard():return
        src=self.folder('Takeout ZIP 來源');
        if not src:return
        try:
            out=self.report_path()
            if not out:return
            if Path(src).resolve() in out.parents:raise ValueError('報告不可放在 ZIP 來源內')
        except Exception as e:self.lib.error(e);return
        from takeout_audit import audit
        import json,os,tempfile
        def run():
            data=audit(Path(src),HOME/'takeout_hashes.sqlite',self.lib.c.path);fd,tmp=tempfile.mkstemp(dir=out.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
                os.replace(tmp,out)
            finally:Path(tmp).unlink(missing_ok=True)
            return f'健檢完成：{out}'
        self.lib.task(run,lambda v:QMessageBox.information(self,'Takeout',v))
    def takeout(self):
        if not self.lib.guard():return
        import json
        from takeout_import import run
        src=self.folder('Takeout ZIP 來源');
        if not src:return
        p,_=QFileDialog.getOpenFileName(self,'已完成健檢報告','','JSON (*.json)')
        if not p:return
        try:
            d=json.loads(Path(p).read_text(encoding='utf-8'))
            if d['errors'] or d['incomplete'] or not d['library_comparison']:raise ValueError('需無錯誤且已比對主庫的報告')
            dest=self.folder('獨立匯入目的地');
            if not dest:return
            if QMessageBox.question(self,'確認匯入',f'{d["counts"]}\n保留 ZIP，驗證 SHA256。繼續？')!=QMessageBox.StandardButton.Yes:return
            self.lib.task(lambda:run(src,dest,self.lib.c.path,HOME/'takeout_hashes.sqlite',cancel=self.lib.cancel.is_set,approved=d['media']),self.reload_library)
        except Exception as e:self.lib.error(e)
    def export_index(self):
        if not self.lib.guard():return
        p=self.folder('匯出位置（來源之外）')
        if not p:return
        from catalog import Catalog
        def run():
            c=Catalog(self.lib.c.path)
            try:return f'匯出 {c.export(p)} 筆'
            finally:c.close()
        self.lib.task(run)
    def export_xmp(self):
        if not self.lib.guard():return
        ids=[r['id'] for r in self.lib.selected()];p=self.folder('XMP 匯出位置') if ids else None
        if not p:return
        from metadata_export import export
        try:QMessageBox.information(self,'XMP',f'匯出 {export(self.lib.c,p,ids)} 筆')
        except Exception as e:self.lib.error(e)
    def date_report(self):
        if not self.lib.guard():return
        try:p=self.report_path()
        except Exception as e:self.lib.error(e);return
        if not p:return
        from catalog import Catalog
        from date_inspector import full_report
        def run():
            c=Catalog(self.lib.c.path)
            try:return f'日期健檢 {full_report(c,p,self.lib.cancel.is_set)} 筆：{p}'
            finally:c.close()
        self.lib.task(run)
    def backup_tags(self):
        if not self.lib.guard():return
        p=self.folder("TAG 快照目的地（來源之外）")
        if not p:return
        q=Path(p).resolve()
        if any(q==Path(s["root"]) or Path(s["root"]) in q.parents for s in self.lib.c.sources()):self.lib.error("快照請放在來源之外");return
        from workflow import snapshot
        self.lib.task(lambda:str(snapshot(self.lib.c.path,q)),lambda v:QMessageBox.information(self,"TAG 快照",v))
    def closeEvent(self,e):
        if self.lib.running:QMessageBox.information(self,'背景工作','請等待背景工作完成；掃描可在 Library 停止。');e.ignore();return
        super().closeEvent(e)
        if e.isAccepted():self.lib.shutdown()
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion');families=QFontDatabase.families();app.setFont(QFont('Noto Sans TC' if 'Noto Sans TC' in families else 'Microsoft JhengHei',10));app.setStyleSheet(STYLE+' QTreeView,QListView,QTableView{background:#1d232b;alternate-background-color:#252d36;border:1px solid #3a4552;selection-background-color:#365f8b} QHeaderView::section{background:#303944;color:#e6ebf1;padding:6px;border:1px solid #3a4552} QSplitter::handle{background:#3a4552}');w=Unified();w.show();return app.exec()
if __name__=='__main__':sys.exit(main())
