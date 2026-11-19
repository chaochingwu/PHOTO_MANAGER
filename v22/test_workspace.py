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
                    window.show()
                    app.processEvents()
                    viewer = window.pages.currentWidget()
                    for width, height in [(1450, 850), (1200, 750)]:
                        window.resize(width, height)
                        app.processEvents()
                        before = window.switch.geometry()
                        window.switch.click()
                        app.processEvents()
                        self.assertIn("健康檢查", window.center.pages)
                        self.assertEqual(window.switch.text(), "返回照片工作室")
                        self.assertEqual(window.switch.geometry(), before)
                        window.switch.click()
                        self.assertIs(window.pages.currentWidget(), viewer)
                        self.assertEqual(window.switch.text(), "照片庫管理中心")
                    window.close()
