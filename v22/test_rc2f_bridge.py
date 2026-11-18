import sys, tempfile, unittest, sqlite3
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).parent/'core'))
from catalog import Catalog
from catalog_bridge import prepare,finalize,recover,pending,journal_path,_hash
from import_choices import validate,choices
from date_inspector import apply
from organize import execute_moves

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'main';self.root.mkdir()
        from photo_manager_v1_4 import Library
        lib=Library(self.root);lib.close()
        self.c=Catalog(self.base/'tag.sqlite');self.addCleanup(self.c.close)
        self.sid=self.c.add_source(self.root,'primary')
    def photo(self,rel,color):
        p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(32,32),color).save(p)
        return p
    def indexed(self):self.c.scan(self.sid)
    def row(self,rel):return self.c.db.execute('SELECT * FROM photos WHERE source=? AND rel=?',(self.sid,rel)).fetchone()
    def test_swap_preserves_ids_tags_dates_and_favorite(self):
        a=self.photo('PHOTOS/2026/2026-01/a.JPG','red');b=self.photo('PHOTOS/2026/2026-01/b.JPG','blue');self.indexed()
        ida,idb=self.row('PHOTOS/2026/2026-01/a.JPG')['id'],self.row('PHOTOS/2026/2026-01/b.JPG')['id']
        self.c.assign([ida],self.c.tag('人物','甲'));self.c.set_favorite([ida]);apply(self.c,[([ida],'2025-02-03')]);self.c.assign([idb],self.c.tag('事件','旅行'))
        entries=[(a,b,_hash(a)),(b,a,_hash(b))]
        prepare(self.c.path,self.root,entries);self.assertTrue(pending(self.c.path,self.root))
        execute_moves(self.root,entries,log=lambda *_:None)
        self.assertEqual(finalize(self.c.path,self.root),2)
        self.assertFalse(pending(self.c.path,self.root))
        self.assertEqual(self.row('PHOTOS/2026/2026-01/b.JPG')['id'],ida)
        self.assertEqual(self.row('PHOTOS/2026/2026-01/a.JPG')['id'],idb)
        self.assertEqual({x['name'] for x in self.c.photo_tags(ida)},{'甲','我的最愛'})
        self.assertEqual(self.c.db.execute('SELECT value FROM date_overrides WHERE photo=?',(ida,)).fetchone()[0],'2025-02-03')
        self.assertEqual(self.row('PHOTOS/2026/2026-01/b.JPG')['year'],2025)
    def test_recovery_after_crash_before_catalog_update(self):
        a=self.photo('PHOTOS/2026/a.JPG','red');b=self.root/'PHOTOS/2026/b.JPG';self.indexed();pid=self.row('PHOTOS/2026/a.JPG')['id'];self.c.set_favorite([pid]);entries=[(a,b,_hash(a))]
        prepare(self.c.path,self.root,entries);execute_moves(self.root,entries,log=lambda *_:None)
        self.assertEqual(self.row('PHOTOS/2026/a.JPG')['id'],pid)
        self.assertEqual(recover(self.c.path,self.root,lambda *_:None),1)
        self.assertEqual(self.row('PHOTOS/2026/b.JPG')['id'],pid)
        self.assertEqual(len(self.c.photo_tags(pid)),1)
    def test_v20_partial_organize_to_v21_tagged_catalog(self):
        from organize import run
        from photo_manager_v1_4 import Library
        import os
        a=self.photo('2026/event/a.JPG','red')
        old=self.photo('2025/event/b.JPG','blue')
        self.indexed();pid=self.row('2026/event/a.JPG')['id'];self.c.set_favorite([pid]);self.c.assign([pid],self.c.tag('人物','家人'))
        def meta(paths,exe):
            return {os.path.normcase(str(p)):{'DateTimeOriginal':'2026:11:15 09:00:00'} for p in paths}
        def confirm(entries,count):
            self.assertEqual(count,1)
            prepare(self.c.path,self.root,entries)
            return True
        result=run(self.root,'partial',('classify','rename'),'2026',log=lambda *_:None,metadata=meta,confirm_plan=confirm)
        self.assertTrue(result)
        lib=Library(self.root,create=False)
        try:lib.scan(log=lambda *_:None,detect=False)
        finally:lib.close()
        self.assertEqual(finalize(self.c.path,self.root),1)
        self.c.scan(self.sid)
        new=self.c.db.execute('SELECT rel FROM photos WHERE id=?',(pid,)).fetchone()[0]
        self.assertTrue(new.startswith('PHOTOS/2026/2026-11/'))
        self.assertEqual({t['name'] for t in self.c.photo_tags(pid)},{'我的最愛','家人'})
        self.assertTrue(old.exists())
    def test_duplicate_tagged_recovery_blocked(self):
        a=self.photo('PHOTOS/2026/a.JPG','red');self.indexed();pid=self.row('PHOTOS/2026/a.JPG')['id'];self.c.set_favorite([pid])
        target=self.root/'.PHOTO_MANAGER/recovery/t/a.JPG'
        with self.assertRaisesRegex(ValueError,'TAG'):
            prepare(self.c.path,self.root,[(a,target,_hash(a))])
        self.assertTrue(a.exists());self.assertFalse(pending(self.c.path,self.root))
    def test_existing_target_index_rejected(self):
        a=self.photo('PHOTOS/a.JPG','red');b=self.photo('PHOTOS/b.JPG','blue');self.indexed()
        with self.assertRaisesRegex(ValueError,'目的地 TAG'):
            prepare(self.c.path,self.root,[(a,b,_hash(a))])
    def test_import_rejects_primary_as_external_source(self):
        ext=self.base/'external';ext.mkdir()
        self.assertEqual(validate(self.c,ext,self.root),(ext.resolve(),self.root.resolve()))
        for p in (self.root,self.base,self.root/'2026'):
            if p.name=='2026':p.mkdir()
            with self.assertRaisesRegex(ValueError,'外部來源'):
                validate(self.c,p,ext)
        dests,sources=choices(self.c.sources(),str(self.root),'',str(ext))
        self.assertIn(str(self.root.resolve()),dests);self.assertNotIn(str(self.root.resolve()),sources)
    def test_multiple_organize_sessions_not_blocked_by_backups(self):
        a=self.photo('PHOTOS/a.JPG','red');self.indexed();pid=self.row('PHOTOS/a.JPG')['id'];self.c.set_favorite([pid])
        b=self.root/'PHOTOS/b.JPG';c=self.root/'PHOTOS/c.JPG'
        for old,new in [(a,b),(b,c)]:
            entries=[(old,new,_hash(old))]
            prepare(self.c.path,self.root,entries)
            execute_moves(self.root,entries,log=lambda *_:None)
            self.assertEqual(finalize(self.c.path,self.root),1)
        self.assertEqual(self.row('PHOTOS/c.JPG')['id'],pid)
    def test_pending_rejects_second_plan(self):
        a=self.photo('PHOTOS/a.JPG','red');b=self.root/'PHOTOS/b.JPG';self.indexed()
        prepare(self.c.path,self.root,[(a,b,_hash(a))])
        with self.assertRaisesRegex(ValueError,'前次整理'):
            prepare(self.c.path,self.root,[(a,b,_hash(a))])
    def test_untagged_recovery_removes_stale_catalog_row(self):
        a=self.photo('PHOTOS/a.JPG','red');self.indexed();target=self.root/'.PHOTO_MANAGER/recovery/t/a.JPG';entries=[(a,target,_hash(a))]
        prepare(self.c.path,self.root,entries);execute_moves(self.root,entries,log=lambda *_:None);finalize(self.c.path,self.root)
        self.assertIsNone(self.row('PHOTOS/a.JPG'))
        self.assertTrue(target.is_file())

if __name__=='__main__':unittest.main()
