from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLabel,QComboBox,
                               QPushButton,QFileDialog,QPlainTextEdit,QMessageBox)
from capacity import MODES, inspect
from workflow import plan, execute, roots
from library_catalog import sha256

class CapacityPage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.generation = 0
        self.preview = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.source = QPushButton("選擇來源資料夾")
        self.dest = QPushButton("選擇目的地資料夾")
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        form.addRow("來源", self.source)
        form.addRow("整理方式", self.mode)
        form.addRow("目的地", self.dest)
        self.source.clicked.connect(lambda: self.choose(self.source))
        self.dest.clicked.connect(lambda: self.choose(self.dest))
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.scan = QPushButton("容量預檢與差異預覽")
        self.scan.clicked.connect(self.check)
        layout.addWidget(self.scan)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.run = QPushButton("執行單向備份並驗證")
        self.run.clicked.connect(self.copy)
        layout.addWidget(self.run)
        stop = QPushButton("安全停止")
        stop.clicked.connect(owner.lib.cancel.set)
        layout.addWidget(stop)
        self.invalidate()

    def choose(self, button):
        path = QFileDialog.getExistingDirectory(self,"選擇資料夾")
        if path:
            button.setProperty("path",path)
            button.setText(path)
            self.invalidate()

    def invalidate(self):
        self.generation += 1
        self.preview = None
        self.run.setEnabled(False)
        self.dest.setEnabled(self.mode.currentIndex()!=0)
        self.output.setPlainText("請執行預檢。手機來源須有磁碟機或資料夾路徑。")

    def check(self):
        if not self.owner.lib.guard(): return
        self.invalidate()
        src, dst = (b.property("path") for b in (self.source,self.dest))
        mode = self.mode.currentText()
        generation = self.generation
        cancel = self.owner.lib.cancel.is_set
        def work():
            info = inspect(src,dst,mode,cancel)
            rows = None
            if mode == MODES[3] and not any(not issue.startswith('不足 ') for issue in info['issues']):
                rows = plan(src,dst,backup=True,cancel=cancel)
                info = inspect(src,dst,mode,cancel,sum(r.size for r in rows if r.action=='copy'))
            return info, rows
        def show(result):
            if generation != self.generation: return
            info,rows = result
            lines = [f"媒體 {info['count']:,} 檔，共 {info['total']:,} bytes",
                     f"預估需求 {info['required']:,} bytes，可用 {info['free']:,} bytes",
                     f"來源 {info['source_fs']} → 目的地 {info['dest_fs']}"]
            lines.extend(info['issues'])
            if rows is not None:
                conflicts = sum(r.action=='conflict' for r in rows)
                lines.append(f"新增 {sum(r.action=='copy' for r in rows)}，已相同 {sum(r.action=='duplicate' for r in rows)}，衝突 {conflicts}。以下最多顯示 500 筆。")
                lines.extend(f"{r.action}  {r.relative}" for r in rows[:500])
                if not conflicts and not info['issues']:
                    self.preview = (src,dst,rows)
                    self.run.setEnabled(True)
            elif not info['issues']:
                lines.append('本頁此模式開放容量估算，逐檔預覽與執行待驗收。')
            self.output.setPlainText('\n'.join(lines))
        self.owner.lib.task(work,show)

    def copy(self):
        if not self.preview or not self.owner.lib.guard(): return
        src,dst,rows = self.preview
        if QMessageBox.question(self,'確認備份','依本次預覽複製並核對 SHA-256？') != QMessageBox.StandardButton.Yes: return
        self.invalidate()
        from pathlib import Path
        cancel = self.owner.lib.cancel.is_set
        def work():
            info = inspect(src,dst,MODES[3],cancel,sum(r.size for r in rows if r.action=="copy"))
            if info['issues']: raise ValueError('；'.join(info['issues']))
            if plan(src,dst,backup=True,cancel=cancel)!=rows: raise ValueError('內容已變動，請重新預覽')
            execute(src,dst,rows,cancel)
            for row in rows:
                if cancel(): raise InterruptedError('已安全停止；重新預覽可跳過相同檔案')
                if sha256(row.source)!=row.digest or sha256(Path(dst)/row.relative)!=row.digest:
                    raise OSError('完整性驗證失敗：'+row.relative)
            roots(src,dst)
            return f'完成 SHA-256 驗證，共 {len(rows)} 個檔案'
        self.owner.lib.task(work,self.output.setPlainText)
