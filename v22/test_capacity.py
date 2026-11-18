import tempfile, unittest, zipfile, json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from capacity import inspect, MODES
from takeout_audit import audit

class CapacityTest(unittest.TestCase):
    def test_modes_and_space(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'s'; dst=root/'d';src.mkdir();dst.mkdir()
            (src/'a.jpg').write_bytes(b'abc')
            results=[inspect(src,dst,m) for m in MODES]
            self.assertEqual(results[0]['count'],1)
            self.assertEqual(results[1]['required']-results[0]['required'],3)
            self.assertTrue(results[2]['issues'])
            with self.assertRaises(ValueError):inspect(src,src,MODES[3])
            with patch('capacity.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
                self.assertIn('不足', inspect(src,dst,MODES[3])['issues'][0])

    def test_selected_archives_and_guards(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'zip';src.mkdir()
            a,b,c=[src/(x+'.zip') for x in 'abc']
            for archive,name,data in [(a,'photo.jpg',b'abc'),(b,'photo.json',json.dumps({'title':'photo.jpg','photoTakenTime':{'timestamp':'1'}})),(c,'../bad.jpg',b'bad')]:
                with zipfile.ZipFile(archive,'w') as z:z.writestr(name,data)
            report=audit(src,root/'checkpoint',selected=[a,b])
            self.assertEqual(report['media'][0]['metadata_status'],'matched')
            self.assertEqual(len(report['archives']),2)
            self.assertTrue(audit(src,root/'checkpoint',selected=[c])['errors'])
            with zipfile.ZipFile(c,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('large.jpg',bytes(8*1024**2))
            self.assertTrue(audit(src,root/'checkpoint',selected=[c])['errors'])

    def test_interrupted_backup_and_disconnect(self):
        from workflow import plan,execute
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/'src';dest=root/'dest';src.mkdir();dest.mkdir()
            p=src/'photo.jpg';p.write_bytes(b'x'*(4*1024**2)); rows=plan(src,dest,backup=True)
            calls=iter([False,False,True])
            with self.assertRaises(InterruptedError): execute(src,dest,rows,lambda:next(calls,True))
            self.assertEqual(list(dest.iterdir()),[])
            self.assertTrue(p.exists())
            execute(src,dest,rows)
            self.assertEqual(plan(src,dest,backup=True)[0].action,'duplicate')
            (dest/p.name).write_bytes(b'other');self.assertEqual(plan(src,dest,backup=True)[0].action,'conflict')
            src.rename(root/'offline')
            with self.assertRaises(ValueError): execute(src,dest,rows)
            self.assertEqual((dest/p.name).read_bytes(),b'other')
