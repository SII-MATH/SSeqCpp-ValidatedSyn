"""Process-control regression: adopt a mock job, never the live SS job."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from handoff import adopt


class HandoffTests(unittest.TestCase):
    def fixture(self,root):
        (root/'validation').mkdir()
        child=root/'native.py'
        child.write_text('''import sys,time
from pathlib import Path
for i in range(250):
 print(i,flush=True);time.sleep(.003)
Path(sys.argv[-1],'checkpoint.marker').write_text('saved')
''')
        parent=root/'validation/run.py'
        parent.write_text('''import sys,subprocess
from pathlib import Path
root=Path(sys.argv[1])
p=subprocess.Popen([sys.executable,str(root/'native.py'),'deduce','auto',str(root)],stdout=subprocess.PIPE,text=True)
(root/'ready').write_text(str(p.pid))
for line in p.stdout:pass
assert p.wait()==0
(root/'parent-would-continue.marker').write_text('continued')
''')
        proc=subprocess.Popen([sys.executable,str(parent),str(root)],cwd=root,
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def cleanup():
            if proc.poll() is None:proc.terminate()
            proc.wait(timeout=5)
        self.addCleanup(cleanup)
        deadline=time.monotonic()+5
        while not (root/'ready').exists():
            if proc.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('mock controller did not start')
            time.sleep(.005)
        return proc,int((root/'ready').read_text())

    def test_normal_completion_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent,child=self.fixture(root);updates=[]
            arguments,code=adopt(parent.pid,child,root,root,lambda **v:updates.append(v))
            self.assertEqual(code,0)
            self.assertEqual((root/'checkpoint.marker').read_text(),'saved')
            self.assertFalse((root/'parent-would-continue.marker').exists())
            self.assertEqual(parent.wait(timeout=5),-9)
            self.assertTrue(updates)

    def test_failed_handoff_resumes_original_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent,child=self.fixture(root)
            def fail(**values):raise RuntimeError('test abort')
            with self.assertRaisesRegex(RuntimeError,'test abort'):
                adopt(parent.pid,child,root,root,fail)
            self.assertEqual(parent.wait(timeout=5),0)
            self.assertTrue((root/'checkpoint.marker').exists())
            self.assertTrue((root/'parent-would-continue.marker').exists())

    def test_wrong_job_is_left_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent,child=self.fixture(root)
            with self.assertRaises(ValueError):
                adopt(parent.pid,child,root,root/'wrong-job',lambda **v:None)
            self.assertEqual(parent.wait(timeout=5),0)


if __name__=='__main__':unittest.main()
