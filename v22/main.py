"""RC3 viewer with the original Qt management center."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from rc3 import Main

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from qt_unified import Unified, STYLE


class ManagementCenter(Unified):
    def __init__(self):
        super().__init__()
        self.scope.setCurrentIndex(1)
        for key, box in self.taskboxes.items():
            box.setChecked(key == "classify")
        self.taskboxes["duplicates"].setEnabled(False)
        from capacity_page import CapacityPage
        self.add_page("容量預檢與備份",CapacityPage(self),1,"SP_DriveHDIcon")

    def start(self, action):
        if action == "organize":
            root = Path(self.paths[0].text())
            if not (root / ".PHOTO_MANAGER/identity.json").is_file():
                QMessageBox.warning(self, "選取測試主庫", "請先到照片庫管理選擇已初始化的測試主庫。")
                return
            if (root / ".PHOTO_MANAGER/organize_pending.json").exists():
                QMessageBox.warning(self, "整理尚未完成", "請先復原先前的整理交易。")
                return
        if action == "sync":
            QMessageBox.information(self, "開發版安全鎖", "完整同步尚待驗證。")
            return
        super().start(action)


class Workspace(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PHOTO_MANAGER V2.2")
        self.resize(1450, 850)
        self.viewer = Main()
        self.center = None
        self.pages = QStackedWidget()
        self.pages.addWidget(self.viewer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(14, 5, 14, 5)
        self.page_title = QLabel("照片工作室")
        self.switch = QPushButton("照片庫管理中心")
        self.switch.setFixedWidth(max(self.switch.sizeHint().width(), 132))
        self.switch.clicked.connect(self.toggle_workspace)
        header.addWidget(self.page_title)
        header.addStretch()
        header.addWidget(self.switch)
        layout.addLayout(header)
        layout.addWidget(self.pages)

    def toggle_workspace(self):
        if self.pages.currentWidget() is self.viewer:
            self.open_center()
        else:
            self.pages.setCurrentWidget(self.viewer)
            self.page_title.setText("照片工作室")
            self.switch.setText("照片庫管理中心")

    def open_center(self):
        if self.center is None:
            center = ManagementCenter()
            center.setStyleSheet(STYLE)
            center.showpage("總覽")
            self.pages.addWidget(center)
            self.center = center
        self.pages.setCurrentWidget(self.center)
        self.page_title.setText("照片庫管理中心")
        self.switch.setText("返回照片工作室")

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
        window.switch.click()
        assert window.pages.currentWidget() is window.viewer
        sys.exit(0 if window.close() else 1)
    window.show()
    sys.exit(app.exec())
