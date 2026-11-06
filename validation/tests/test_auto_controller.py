"""Recovery and switch boundaries for the original native auto controller."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import auto_run


class AutoControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.directory=self.base/'run';self.directory.mkdir()
        self.binary=self.base/'engine.py'
        self.binary.write_text('''#!/usr/bin/env python3
import sys,json,sqlite3,os
from pathlib import Path
a=sys.argv[1:];p=Path(a[1] if a[0]=='reset' else a[2] if a[0]=='deduce' else a[1])
with (p/'commands').open('a') as f:f.write(json.dumps(a)+'\\n')
with sqlite3.connect(p/'log.db') as d:
 if a[0]=='reset':
  d.execute('DROP TABLE IF EXISTS log');d.execute('CREATE TABLE log(id INTEGER PRIMARY KEY,reason TEXT)')
  d.execute('CREATE TABLE IF NOT EXISTS exclusions(id INTEGER PRIMARY KEY)');d.execute("INSERT INTO log VALUES(1,'d2')")
 elif a[0]=='deduce':
  if 'checkpoint_resume=1' in a:
   with sqlite3.connect(p/'recovery.sqlite3') as c:
    old=json.loads(c.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
   if 'log_id' in old:d.execute('DELETE FROM log WHERE id>?',(old['log_id'],))
   (p/'restored').write_text('yes')
  (p/'start-rows').write_text(str(d.execute('SELECT count(*) FROM log').fetchone()[0]))
  with sqlite3.connect(p/'recovery.sqlite3') as c:
   c.execute('CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY,value TEXT)')
   c.execute('INSERT OR REPLACE INTO metadata VALUES(1,?)',(json.dumps({'command':os.environ.get('SS_RUN_COMMAND','auto-001'),'complete':True,'changed':False}),))
  if (p/'tamper-binary').exists():Path(sys.argv[0]).write_text('# replaced executable')
 elif a[0]=='verify':
  (p/'acceptance.json').write_text(json.dumps({'passed':201,'total':201,'missing':[],'errors':[],'forbidden_outputs':0}))
''');self.binary.chmod(0o755)
        self.state=dict(historical_log_imported=False,targets_sha256=auto_run.TARGET_SHA256,
            binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest(),source_commit='fixture',
            flags='syn,dxy',native_round_limit=100,command_index=1,runner_pid=None,child_pid=None)
        self.args=argparse.Namespace(directory=self.directory,seed=self.base,binary=self.binary,
            flags='syn,dxy',native_rounds=100,check_seconds=600,checkpoint_seconds=300,notify_user='',resume=True)

    def save(self):
        (self.directory/'status.json').write_text(json.dumps(self.state))

    def log(self):
        with sqlite3.connect(self.directory/'log.db') as d:
            d.execute('CREATE TABLE log(id INTEGER PRIMARY KEY,reason TEXT)')
            d.execute('CREATE TABLE exclusions(id INTEGER PRIMARY KEY)')
            d.executemany('INSERT INTO log VALUES(?,?)',[(1,'d2'),(2,'D')])

    def metadata(self,complete):
        with sqlite3.connect(self.directory/'recovery.sqlite3') as d:
            d.execute('CREATE TABLE metadata(id INTEGER PRIMARY KEY,value TEXT)')
            d.execute('INSERT INTO metadata VALUES(1,?)',(json.dumps(dict(command='auto-001',complete=complete,
                changed=False,kind='auto',log_id=1,options=dict(stem_min=0,stem_max=261,T=1,id_thread=0,
                num=100,flag_names=['syn','dxy'],mode=[],deduce_list=[]))),))

    def run_controller(self):
        original=time.sleep
        with patch.object(auto_run.time,'sleep',lambda _:original(.005)):
            auto_run.run(self.args)
        return [json.loads(x) for x in (self.directory/'commands').read_text().splitlines()]

    def test_interrupted_reset_repeats_reset_before_auto(self):
        self.state.update(phase='initializing',command='initialize');self.save();self.log()
        commands=self.run_controller()
        self.assertEqual([x[0] for x in commands],['reset','deduce','verify'])
        self.assertEqual((self.directory/'start-rows').read_text(),'1')

    def test_unpublished_first_checkpoint_discards_later_log_tail(self):
        self.state.update(phase='deducing',command='auto-001',last_completed_command='initialize',command_log_start=1)
        self.save();self.log()
        sqlite3.connect(self.directory/'recovery.sqlite3').close()
        commands=self.run_controller()
        self.assertNotIn('checkpoint_resume=1',commands[0])
        self.assertEqual((self.directory/'start-rows').read_text(),'1')

    def test_switch_change_requires_complete_native_boundary(self):
        self.state.update(phase='deducing',command='auto-001');self.save();self.metadata(False)
        self.args.flags='syn,dxy,zero'
        with self.assertRaisesRegex(RuntimeError,'completed native boundary'):self.run_controller()
        self.assertFalse((self.directory/'commands').exists())

    def test_completed_switch_change_starts_new_command(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001',last_completed_command='auto-001')
        self.save();self.log();self.metadata(True);self.args.flags='syn,dxy,zero'
        commands=self.run_controller()
        self.assertIn('checkpoint_resume=1',commands[0])
        self.assertIn('flags=syn,dxy,zero',commands[1]);self.assertNotIn('checkpoint_resume=1',commands[1])
        result=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(result['command_index'],2);self.assertEqual(result['preceding_command'],'auto-001')

    def test_previous_completed_checkpoint_restores_before_new_command_restart(self):
        self.state.update(phase='deducing',command='auto-002',last_completed_command='auto-001',command_index=2)
        self.save();self.log()
        metadata=dict(command='auto-001',complete=True,changed=False,kind='auto',log_id=1,
            options=dict(stem_min=0,stem_max=261,T=1,id_thread=0,num=100,flag_names=['syn','dxy'],mode=[],deduce_list=[]))
        with sqlite3.connect(self.directory/'recovery.sqlite3') as d:
            d.execute('CREATE TABLE metadata(id INTEGER PRIMARY KEY,value TEXT)')
            d.execute('INSERT INTO metadata VALUES(1,?)',(json.dumps(metadata),))
        commands=self.run_controller()
        self.assertIn('checkpoint_resume=1',commands[0]);self.assertNotIn('checkpoint_resume=1',commands[1])
        self.assertTrue((self.directory/'restored').exists());self.assertEqual((self.directory/'start-rows').read_text(),'1')

    def test_interrupted_previous_restoration_is_repeated(self):
        self.state.update(phase='deducing',command='auto-001',last_completed_command='auto-001',command_index=2)
        self.save();self.log();self.metadata(True)
        commands=self.run_controller()
        self.assertIn('checkpoint_resume=1',commands[0]);self.assertNotIn('checkpoint_resume=1',commands[1])
        self.assertEqual((self.directory/'start-rows').read_text(),'1')

    def test_inherited_lock_prevents_duplicate_after_parent_handle_closes(self):
        self.state.update(phase='initializing',command='initialize');self.save()
        lock=(self.directory/'.controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],pass_fds=(lock.fileno(),))
        lock.close()
        try:
            with self.assertRaisesRegex(RuntimeError,'locked by a controller or its native child'):self.run_controller()
            self.assertFalse((self.directory/'commands').exists())
        finally:
            child.terminate();child.wait()

    def test_replaced_binary_cannot_produce_final_acceptance(self):
        self.state.update(phase='initializing',command='initialize');self.save()
        (self.directory/'tamper-binary').touch()
        with self.assertRaisesRegex(RuntimeError,'pinned executable changed'):self.run_controller()
        commands=[json.loads(x) for x in (self.directory/'commands').read_text().splitlines()]
        self.assertEqual([x[0] for x in commands],['reset','deduce'])
        self.assertFalse((self.directory/'acceptance.json').exists())


if __name__=='__main__':unittest.main()
