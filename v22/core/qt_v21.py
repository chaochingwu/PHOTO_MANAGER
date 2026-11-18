"""V2.1 presentation adapter; original V2.0 engine and UI source unchanged."""
import os,sys
from pathlib import Path
sys.path.insert(1,str(Path(__file__).resolve().parent.parent))
from release_guard import protected_roots
from qt_app import Window,QApplication,QFont,QFontDatabase,Qt,QMessageBox
from PySide6.QtWidgets import QStyle
STYLE='''QWidget{font-size:14px;color:#e6ebf1;background:#171b21} QFrame#card{background:#222831;border:1px solid #3a4552;border-radius:6px} QFrame#card QLabel{background:transparent} QFrame#nav,QFrame#header{background:#222831} QFrame#nav QLabel,QFrame#header QLabel{color:#e6ebf1;background:transparent} QPushButton{background:#2b333e;border:1px solid #3a4552;border-radius:5px;padding:8px 12px} QPushButton:hover{background:#344f70} QPushButton:disabled{color:#778493;background:#222831} QPushButton#primary{background:#3069a5;color:white} QPushButton#navbutton{text-align:left;border:0;padding:10px} QPushButton#navbutton:checked{background:#344f70;color:white} QLineEdit,QComboBox,QSpinBox,QPlainTextEdit{background:#2b333e;border:1px solid #3a4552;border-radius:4px;padding:6px;selection-background-color:#344f70} QProgressBar{background:#2b333e;border:0;text-align:center} QProgressBar::chunk{background:#5799e5} QScrollArea{border:0} QLabel#heading{font-size:21px;font-weight:700} QLabel#metric{font-size:24px;font-weight:700;color:#a9c9ef} QLabel#muted{color:#a7b3c2;font-size:12px}'''
class UpgradeWindow(Window):
    def __init__(self,page):
        super().__init__();self.setWindowTitle('PHOTO_MANAGER V2.1 | 核心工具')
        from PySide6.QtWidgets import QLabel
        for label in self.findChildren(QLabel):
            if label.text()=='PHOTO_MANAGER · V2.0':label.setText('PHOTO_MANAGER · V2.1')
        icons={'總覽':'SP_ComputerIcon','照片庫管理':'SP_DirIcon','整理照片與影片':'SP_FileDialogDetailedView','同步照片庫':'SP_DriveHDIcon','Everything 搜尋':'SP_FileDialogContentsView','健康檢查':'SP_DialogApplyButton','執行報告':'SP_FileIcon','系統設定':'SP_FileDialogInfoView','使用說明':'SP_DialogHelpButton','關於軟體':'SP_MessageBoxInformation'}
        for name,b in self.navbuttons.items():
            b.setIcon(self.style().standardIcon(getattr(QStyle.StandardPixmap,icons[name])))
        if page in self.pages:
            if not self.advanced:self.toggle()
            self.showpage(page)
    def start(self,a):
        if a=='sync':
            try:
                paths=[self.paths[0].text()] if a=='organize' else [p.text() for p in self.paths]
                blocked=protected_roots(os.environ['PM_V21_CATALOG'],paths)
                if blocked:raise ValueError('為保護既有 TAG／日期修正，暫停對已標記來源的整理或同步。請改用獨立測試庫。\n'+'\n'.join(blocked))
            except Exception as e:QMessageBox.warning(self,'TAG 安全保護',str(e));return
        super().start(a)
if __name__=='__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication([sys.argv[0]]);app.setStyle('Fusion');families=QFontDatabase.families();app.setFont(QFont('Noto Sans TC' if 'Noto Sans TC' in families else 'Microsoft JhengHei',10));app.setStyleSheet(STYLE);w=UpgradeWindow(sys.argv[1] if len(sys.argv)>1 else '總覽');w.show();sys.exit(app.exec())
