import os
import tempfile
import unittest
from pathlib import Path

class WorkspaceTest(unittest.TestCase):
    def test_return_preserves_viewer(self):
        with tempfile.TemporaryDirectory() as temp:
            from unittest.mock import patch
            with patch.dict(os.environ, {"LOCALAPPDATA": temp, "QT_QPA_PLATFORM": "offscreen"}):
                from main import QApplication, Workspace
                import qt_app
                app = QApplication.instance() or QApplication([])
                with patch.object(qt_app, "HOME", Path(temp)):
                    window = Workspace()
                    viewer = window.currentWidget()
                    window.open_center()
                    self.assertIn("健康檢查", window.center.pages)
                    from PySide6.QtWidgets import QPushButton
                    back = next(b for b in window.center.findChildren(QPushButton) if b.text() == "返回照片工作室")
                    back.click()
                    self.assertIs(window.currentWidget(), viewer)
                    window.close()
