"""RC3 viewer with the original Qt management center."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox, QStackedWidget
from rc3 import Main

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from qt_unified import Unified, STYLE


class ManagementCenter(Unified):
    def start(self, action):
        if action in {"sync", "organize"}:
            QMessageBox.information(self, "開發版安全鎖", "整理與同步等待完整預覽及衝突檢查驗證。")
            return
        super().start(action)


class Workspace(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PHOTO_MANAGER V2.2")
        self.resize(1450, 850)
        self.viewer = Main()
        self.center = None
        self.addWidget(self.viewer)
        button = QPushButton("照片庫管理中心")
        self.viewer.address.parentWidget().layout().addWidget(button)
        button.clicked.connect(self.open_center)

    def open_center(self):
        if self.center is None:
            center = ManagementCenter()
            center.setStyleSheet(STYLE)
            center.showpage("總覽")
            back = QPushButton("返回照片工作室")
            center.nav.layout().insertWidget(0, back)
            back.clicked.connect(lambda: self.setCurrentWidget(self.viewer))
            self.addWidget(center)
            self.center = center
        self.setCurrentWidget(self.center)

    def closeEvent(self, event):
        if self.center is not None and not self.center.close():
            event.ignore()
            return
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = Workspace()
    if "--smoke-test" in sys.argv:
        window.open_center()
        assert "照片庫管理" in window.center.pages
        window.setCurrentWidget(window.viewer)
        sys.exit(0 if window.close() else 1)
    window.show()
    sys.exit(app.exec())
