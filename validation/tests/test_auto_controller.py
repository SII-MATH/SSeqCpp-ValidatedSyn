"""Native command recovery, switch boundaries, and synthetic/auto scheduling."""
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
plan=json.loads((p/'engine-plan.json').read_text()) if (p/'engine-plan.json').exists() else {}
command=os.environ.get('SS_RUN_COMMAND','auto-001')
behavior=plan.get(command,{})
def event(**values):
 with (p/'events').open('a') as f:f.write(json.dumps(dict(command=command,**values))+'\\n')
with sqlite3.connect(p/'log.db') as d:
 if a[0]=='reset':
  d.execute('DROP TABLE IF EXISTS log');d.execute('CREATE TABLE log(id INTEGER PRIMARY KEY,reason TEXT)')
  d.execute('CREATE TABLE IF NOT EXISTS exclusions(id INTEGER PRIMARY KEY)');d.execute("INSERT INTO log VALUES(1,'d2')")
  d.execute('CREATE TABLE IF NOT EXISTS native_state(id INTEGER PRIMARY KEY,value TEXT)')
  d.execute("INSERT OR REPLACE INTO native_state VALUES(1,'reset')")
 elif a[0]=='deduce':
  d.execute('CREATE TABLE IF NOT EXISTS native_state(id INTEGER PRIMARY KEY,value TEXT)')
  old=None
  if 'checkpoint_resume=1' in a:
   with sqlite3.connect(p/'recovery.sqlite3') as c:
    old=json.loads(c.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
   if 'log_id' in old:d.execute('DELETE FROM log WHERE id>?',(old['log_id'],))
   if 'saved_state' in old:d.execute('INSERT OR REPLACE INTO native_state VALUES(1,?)',(old['saved_state'],))
   (p/'restored').write_text('yes')
  rows=d.execute('SELECT count(*) FROM log').fetchone()[0]
  (p/'start-rows').write_text(str(rows))
  current=d.execute('SELECT value FROM native_state WHERE id=1').fetchone()
  if old and old['complete']:
   event(action='restore',kind=a[1],start_rows=rows,start_state=current[0] if current else None)
  else:
   event(action='resume-scan' if old else 'scan',kind=a[1],start_rows=rows,
         start_state=current[0] if current else None)
   value=a[1]+'-result-'+command
   d.execute('INSERT OR REPLACE INTO native_state VALUES(1,?)',(value,))
   d.execute('INSERT INTO log(reason) VALUES(?)',('Syn' if behavior.get('forbidden') else 'D',))
   checkpoint=behavior.get('checkpoint','complete')
   if checkpoint!='none':
    options=dict(stem_min=0,stem_max=261,T=1,id_thread=0,num=100,
                 flag_names=[],mode=[],deduce_list=[])
    for arg in a[3:]:
     if '=' not in arg:continue
     key,val=arg.split('=',1)
     if key in ('stem_min','stem_max','T','id_thread','num'):options[key]=int(val)
     elif key=='flags':options['flag_names']=val.split(',') if val else []
     elif key in ('mode','deduce_list'):options[key]=val.split(',') if val else []
    metadata=dict(command=command,kind=a[1],complete=checkpoint=='complete',changed=False,
                  log_id=d.execute('SELECT max(id) FROM log').fetchone()[0],log_rows=rows+1,
                  saved_state=value,options=options)
    with sqlite3.connect(p/'recovery.sqlite3') as c:
     c.execute('CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY,value TEXT)')
     c.execute('INSERT OR REPLACE INTO metadata VALUES(1,?)',(json.dumps(metadata),))
  if (p/'tamper-binary').exists():Path(sys.argv[0]).write_text('# replaced executable')
 elif a[0]=='verify':
  (p/'acceptance.json').write_text(json.dumps({'passed':201,'total':201,'missing':[],'errors':[],'forbidden_outputs':0}))
sys.exit(behavior.get('exit_code',0) if a[0]=='deduce' else 0)
''');self.binary.chmod(0o755)
        self.state=dict(historical_log_imported=False,targets_sha256=auto_run.TARGET_SHA256,
            binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest(),source_commit='fixture',
            flags='syn,dxy',native_round_limit=100,command_index=1,runner_pid=None,child_pid=None)
        self.args=argparse.Namespace(directory=self.directory,seed=self.base,binary=self.binary,
            flags='syn,dxy',native_rounds=100,check_seconds=600,checkpoint_seconds=300,notify_user='',resume=True,
            adopt_binary=False,synthetic_before_auto=False)

    def save(self):
        (self.directory/'status.json').write_text(json.dumps(self.state))

    def log(self):
        with sqlite3.connect(self.directory/'log.db') as d:
            d.execute('CREATE TABLE log(id INTEGER PRIMARY KEY,reason TEXT)')
            d.execute('CREATE TABLE exclusions(id INTEGER PRIMARY KEY)')
            d.executemany('INSERT INTO log VALUES(?,?)',[(1,'d2'),(2,'D')])
            d.execute('CREATE TABLE native_state(id INTEGER PRIMARY KEY,value TEXT)')
            d.execute("INSERT INTO native_state VALUES(1,'unsaved-tail')")

    def metadata(self,complete,command='auto-001',kind='auto',saved_state=None):
        with sqlite3.connect(self.directory/'recovery.sqlite3') as d:
            d.execute('CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY,value TEXT)')
            d.execute('INSERT OR REPLACE INTO metadata VALUES(1,?)',(json.dumps(dict(command=command,complete=complete,
                changed=False,kind=kind,log_id=1,saved_state=saved_state or 'saved-'+command,
                options=dict(stem_min=0,stem_max=261,T=1,id_thread=0,
                num=100,flag_names=['syn','dxy'],mode=[],deduce_list=[]))),))

    def replacement_binary(self):
        replacement=self.base/'replacement.py'
        replacement.write_text(self.binary.read_text()+'\n# adopted executable\n');replacement.chmod(0o755)
        self.args.binary=replacement
        return hashlib.sha256(replacement.read_bytes()).hexdigest()

    def run_controller(self):
        original=time.sleep
        with patch.object(auto_run.time,'sleep',lambda _:original(.005)):
            auto_run.run(self.args)
        return self.commands()

    def commands(self):
        path=self.directory/'commands'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def events(self):
        path=self.directory/'events'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def status(self):
        return json.loads((self.directory/'status.json').read_text())

    def ready_synthetic(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001',last_completed_command='auto-001',exit_code=0)
        self.save();self.log();self.metadata(True)
        self.args.synthetic_before_auto=True

    def active_synthetic(self,stage='synthetic',command=None,completed='auto-001',exit_code=0):
        self.state.update(phase='deducing',command=command or 'synthetic-002',
            last_completed_command=completed,exit_code=exit_code,command_index=2,command_log_start=1,
            preceding_command='auto-001',controller_source_commit='controller-fixture',
            synthetic_before_auto=dict(index=2,stage=stage,preceding_command='auto-001'))
        self.save();self.log();self.args.synthetic_before_auto=True

    def assert_stage_done(self):
        result=self.status()
        self.assertEqual(result['phase'],'passed')
        self.assertEqual(result['command_index'],2)
        self.assertEqual(result['synthetic_before_auto'],dict(index=2,stage='done',preceding_command='auto-001'))
        self.assertEqual(result['source_commit'],'fixture')
        self.assertEqual(result['binary_sha256'],self.state['binary_sha256'])
        return result

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

    def test_adopt_binary_requires_resume_before_preparing_run(self):
        self.args.resume=False;self.args.adopt_binary=True
        with patch.object(auto_run,'prepare') as prepare:
            with self.assertRaisesRegex(RuntimeError,'requires --resume'):self.run_controller()
        prepare.assert_not_called()
        self.assertFalse((self.directory/'status.json').exists())

    def test_changed_binary_requires_explicit_adoption(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001');self.save();self.metadata(True)
        self.replacement_binary();before=(self.directory/'status.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'use --adopt-binary'):self.run_controller()
        self.assertEqual((self.directory/'status.json').read_bytes(),before)
        self.assertFalse((self.directory/'commands').exists())

    def test_binary_adoption_requires_existing_complete_checkpoint(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001');self.save()
        self.replacement_binary();self.args.adopt_binary=True
        before=(self.directory/'status.json').read_bytes()
        for complete in (None,False):
            with self.subTest(checkpoint_complete=complete):
                if complete is not None:self.metadata(complete)
                with self.assertRaisesRegex(RuntimeError,'completed native boundary'):self.run_controller()
                self.assertEqual((self.directory/'status.json').read_bytes(),before)
                self.assertFalse((self.directory/'commands').exists())

    def test_binary_adoption_refuses_live_controller_or_native_child(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001');self.metadata(True)
        self.replacement_binary();self.args.adopt_binary=True
        cmdline=Path('/proc/424242/cmdline');exists=Path.exists;read_bytes=Path.read_bytes
        with patch.object(Path,'exists',lambda path:path==cmdline or exists(path)), \
             patch.object(Path,'read_bytes',lambda path:b'engine\0'+str(self.directory.resolve()).encode()+b'\0' if path==cmdline else read_bytes(path)):
            for key in ('runner_pid','child_pid'):
                with self.subTest(pid_field=key):
                    self.state.update(runner_pid=None,child_pid=None);self.state[key]=424242;self.save()
                    before=(self.directory/'status.json').read_bytes()
                    with self.assertRaisesRegex(RuntimeError,'still live'):self.run_controller()
                    self.assertEqual((self.directory/'status.json').read_bytes(),before)
                    self.assertFalse((self.directory/'commands').exists())

    def test_completed_binary_and_switch_adoption_restores_old_boundary_once(self):
        self.state.update(phase='round-limit-incomplete',command='auto-001',last_completed_command='auto-001')
        self.save();self.log();self.metadata(True)
        previous={key:self.state[key] for key in ('binary_sha256','source_commit')}
        replacement_sha=self.replacement_binary();self.args.adopt_binary=True;self.args.flags='syn,dxy,zero'
        self.args.native_rounds=101
        with patch.object(auto_run.subprocess,'check_output',return_value='adopted-source\n'):
            commands=self.run_controller()
        self.assertEqual([x[0] for x in commands],['deduce','deduce','verify'])
        self.assertIn('checkpoint_resume=1',commands[0]);self.assertIn('flags=syn,dxy',commands[0])
        self.assertIn('num=100',commands[0]);self.assertIn('num=101',commands[1])
        self.assertIn('flags=syn,dxy,zero',commands[1]);self.assertNotIn('checkpoint_resume=1',commands[1])
        self.assertEqual((self.directory/'start-rows').read_text(),'1')
        result=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(result['command_index'],2);self.assertEqual(result['preceding_command'],'auto-001')
        self.assertEqual(result['previous_binary'],previous)
        self.assertEqual(result['binary_sha256'],replacement_sha);self.assertEqual(result['source_commit'],'adopted-source')

    def test_binary_only_adoption_restarts_a_previously_passed_command(self):
        self.state.update(phase='passed',command='auto-001',last_completed_command='auto-001')
        self.save();self.log();self.metadata(True)
        previous={key:self.state[key] for key in ('binary_sha256','source_commit')}
        replacement_sha=self.replacement_binary();self.args.adopt_binary=True
        with patch.object(auto_run.subprocess,'check_output',return_value='adopted-source\n'):
            commands=self.run_controller()
        self.assertEqual([x[0] for x in commands],['deduce','deduce','verify'])
        self.assertIn('checkpoint_resume=1',commands[0]);self.assertNotIn('checkpoint_resume=1',commands[1])
        result=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(result['command_index'],2);self.assertEqual(result['binary_sha256'],replacement_sha)
        self.assertEqual(result['previous_binary'],previous)

    def test_interrupted_binary_adoption_repeats_old_restore_without_new_adoption(self):
        previous={key:self.state[key] for key in ('binary_sha256','source_commit')}
        replacement_sha=self.replacement_binary();self.args.adopt_binary=True;self.args.flags='syn,dxy,zero'
        self.state.update(phase='fixed-point-incomplete',command='auto-001',last_completed_command='auto-001')
        self.save();self.log();self.metadata(True)
        popen=auto_run.subprocess.Popen
        def interrupt_new_command(arguments,**kwargs):
            if arguments[1]=='deduce' and 'checkpoint_resume=1' not in arguments:
                raise OSError('Interrupted before the new command')
            return popen(arguments,**kwargs)
        with patch.object(auto_run.subprocess,'check_output',return_value='adopted-source\n'), \
             patch.object(auto_run.subprocess,'Popen',side_effect=interrupt_new_command):
            with self.assertRaisesRegex(OSError,'Interrupted before'):self.run_controller()
        adopted=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(adopted['binary_sha256'],replacement_sha);self.assertEqual(adopted['command_index'],2)
        self.assertEqual(adopted['previous_binary'],previous);self.assertEqual(adopted['command'],'auto-001')
        with patch.object(auto_run.subprocess,'check_output') as git_head:
            commands=self.run_controller()
        git_head.assert_not_called()
        self.assertEqual([x[0] for x in commands],['deduce','deduce','deduce','verify'])
        self.assertIn('checkpoint_resume=1',commands[0]);self.assertIn('checkpoint_resume=1',commands[1])
        self.assertNotIn('checkpoint_resume=1',commands[2])
        self.assertEqual((self.directory/'start-rows').read_text(),'1')
        result=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(result['command_index'],2);self.assertEqual(result['previous_binary'],previous)
        self.assertEqual(result['source_commit'],'adopted-source')

    def test_already_adopted_binary_resumes_its_unfinished_checkpoint(self):
        previous={key:self.state[key] for key in ('binary_sha256','source_commit')}
        replacement_sha=self.replacement_binary();self.args.adopt_binary=True
        self.state.update(phase='deducing',command='auto-002',last_completed_command='auto-001',command_index=2,
            binary_sha256=replacement_sha,source_commit='adopted-source',previous_binary=previous)
        self.save();self.log();self.metadata(False,command='auto-002')
        with patch.object(auto_run.subprocess,'check_output') as git_head:
            commands=self.run_controller()
        git_head.assert_not_called()
        self.assertEqual([x[0] for x in commands],['deduce','verify'])
        self.assertIn('checkpoint_resume=1',commands[0])
        result=json.loads((self.directory/'status.json').read_text())
        self.assertEqual(result['command_index'],2);self.assertEqual(result['previous_binary'],previous)

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

    def test_synthetic_request_requires_resume_before_preparation(self):
        self.args.resume=False;self.args.synthetic_before_auto=True
        with patch.object(auto_run,'prepare') as prepare:
            with self.assertRaisesRegex(RuntimeError,'requires --resume'):self.run_controller()
        prepare.assert_not_called()
        self.assertFalse((self.directory/'status.json').exists())

    def test_synthetic_request_requires_a_successfully_recorded_complete_boundary(self):
        self.state.update(phase='fixed-point-incomplete',command='auto-001',last_completed_command='auto-001',exit_code=0)
        self.args.synthetic_before_auto=True
        cases=[('missing checkpoint',None,{},'completed native boundary'),
               ('partial checkpoint',False,{},'completed native boundary'),
               ('unrecorded exit',True,dict(exit_code=None),'successfully exited native command'),
               ('failed exit',True,dict(exit_code=7),'successfully exited native command'),
               ('unrecorded completion',True,dict(last_completed_command='initialize'),'successfully exited native command'),
               ('different command',True,dict(command='auto-002'),'successfully exited native command'),
               ('failed status',True,dict(phase='failed'),'successfully exited native command')]
        original=dict(self.state)
        for label,complete,changes,error in cases:
            with self.subTest(case=label):
                self.state=dict(original,**changes);self.save()
                if complete is not None:self.metadata(complete)
                before=(self.directory/'status.json').read_bytes()
                with self.assertRaisesRegex(RuntimeError,error):self.run_controller()
                self.assertEqual((self.directory/'status.json').read_bytes(),before)
                self.assertEqual(self.commands(),[])

    def test_synthetic_request_requires_positive_checkpoint_interval(self):
        self.ready_synthetic()
        for interval in (0,-1):
            with self.subTest(interval=interval):
                self.args.checkpoint_seconds=interval
                before=(self.directory/'status.json').read_bytes()
                with self.assertRaisesRegex(RuntimeError,'positive checkpoint'):self.run_controller()
                self.assertEqual((self.directory/'status.json').read_bytes(),before)
                self.assertEqual(self.commands(),[])

    def test_synthetic_request_refuses_live_controller_or_child(self):
        self.ready_synthetic()
        cmdline=Path('/proc/424242/cmdline');exists=Path.exists;read_bytes=Path.read_bytes
        with patch.object(Path,'exists',lambda path:path==cmdline or exists(path)), \
             patch.object(Path,'read_bytes',lambda path:b'engine\0'+str(self.directory.resolve()).encode()+b'\0' if path==cmdline else read_bytes(path)):
            for key in ('runner_pid','child_pid'):
                with self.subTest(pid_field=key):
                    self.state.update(runner_pid=None,child_pid=None);self.state[key]=424242;self.save()
                    before=(self.directory/'status.json').read_bytes()
                    with self.assertRaisesRegex(RuntimeError,'still live'):self.run_controller()
                    self.assertEqual((self.directory/'status.json').read_bytes(),before)
                    self.assertEqual(self.commands(),[])

    def test_synthetic_continuation_restores_then_scans_synthetic_and_auto(self):
        self.ready_synthetic()
        with patch.object(auto_run.subprocess,'check_output',return_value='controller-head\n'):
            commands=self.run_controller()
        events=self.events()
        self.assertEqual([(x['command'],x['action']) for x in events],
            [('auto-001','restore'),('synthetic-002','scan'),('synthetic-002','restore'),('auto-002','scan')])
        synthetic_scan=next(x for x in events if x['command']=='synthetic-002' and x['action']=='scan')
        self.assertEqual((synthetic_scan['start_rows'],synthetic_scan['start_state']),(1,'saved-auto-001'))
        auto_scan=events[-1]
        self.assertEqual((auto_scan['start_rows'],auto_scan['start_state']),(2,'synthetic-result-synthetic-002'))
        self.assertEqual(commands[1],['deduce','synthetic',str(self.directory),'checkpoint_seconds=300'])
        for command in commands:
            if command[:2]==['deduce','synthetic']:
                self.assertFalse(any(x.startswith(('flags=','num=')) for x in command))
        self.assertIn('flags=syn,dxy',commands[-2]);self.assertIn('num=100',commands[-2])
        self.assertEqual(commands[-1][0],'verify')
        result=self.assert_stage_done()
        self.assertEqual(result['controller_source_commit'],'controller-head')
        self.assertNotIn('previous_binary',result)

    def test_synthetic_request_and_boundary_option_changes_allocate_one_index(self):
        self.ready_synthetic();self.args.flags='syn,dxy,zero';self.args.native_rounds=101
        with patch.object(auto_run.subprocess,'check_output',return_value='controller-head\n'):
            commands=self.run_controller()
        result=self.assert_stage_done()
        self.assertEqual(result['flags'],'syn,dxy,zero');self.assertEqual(result['native_round_limit'],101)
        self.assertIn('flags=syn,dxy',commands[0]);self.assertIn('num=100',commands[0])
        self.assertIn('flags=syn,dxy,zero',commands[-2]);self.assertIn('num=101',commands[-2])
        self.assertEqual([x['command'] for x in self.events() if x['action']=='scan'],['synthetic-002','auto-002'])

    def test_synthetic_request_combined_binary_adoption_preserves_previous_binary(self):
        self.ready_synthetic();previous={key:self.state[key] for key in ('binary_sha256','source_commit')}
        replacement_sha=self.replacement_binary();self.args.adopt_binary=True;self.args.flags='syn,dxy,zero'
        with patch.object(auto_run.subprocess,'check_output',return_value='adopted-head\n'):
            self.run_controller()
        result=self.status()
        self.assertEqual(result['command_index'],2)
        self.assertEqual(result['synthetic_before_auto']['stage'],'done')
        self.assertEqual(result['previous_binary'],previous)
        self.assertEqual(result['binary_sha256'],replacement_sha)
        self.assertEqual(result['source_commit'],'adopted-head')
        self.assertEqual(result['controller_source_commit'],'adopted-head')

    def test_synthetic_before_first_checkpoint_trims_unpublished_log_tail(self):
        self.active_synthetic()
        with sqlite3.connect(self.directory/'log.db') as d:
            d.execute("UPDATE native_state SET value='last-saved-tables' WHERE id=1")
        sqlite3.connect(self.directory/'recovery.sqlite3').close()
        self.run_controller()
        events=self.events()
        self.assertEqual((events[0]['command'],events[0]['action'],events[0]['start_rows']),('synthetic-002','scan',1))
        self.assertEqual(events[0]['start_state'],'last-saved-tables')
        self.assertNotIn('checkpoint_resume=1',self.commands()[0])
        self.assert_stage_done()

    def test_interrupted_predecessor_restore_before_synthetic_start_repeats_safely(self):
        self.ready_synthetic();popen=auto_run.subprocess.Popen
        def interrupt_synthetic_start(arguments,**kwargs):
            if arguments[1:3]==['deduce','synthetic'] and 'checkpoint_resume=1' not in arguments:
                raise OSError('Interrupted before synthetic first checkpoint')
            return popen(arguments,**kwargs)
        with patch.object(auto_run.subprocess,'Popen',side_effect=interrupt_synthetic_start):
            with self.assertRaisesRegex(OSError,'before synthetic first checkpoint'):self.run_controller()
        saved=self.status()
        self.assertEqual(saved['command'],'auto-001')
        self.assertEqual(saved['synthetic_before_auto'],dict(index=2,stage='synthetic',preceding_command='auto-001'))
        self.args.synthetic_before_auto=False
        with patch.object(auto_run.subprocess,'check_output') as git_head:
            self.run_controller()
        git_head.assert_not_called()
        self.assertEqual([(x['command'],x['action']) for x in self.events()],
            [('auto-001','restore'),('auto-001','restore'),('synthetic-002','scan'),
             ('synthetic-002','restore'),('auto-002','scan')])
        self.assert_stage_done()

    def test_partial_synthetic_checkpoint_resumes_its_own_saved_state(self):
        self.active_synthetic();self.metadata(False,'synthetic-002','synthetic','partial-synthetic')
        self.args.synthetic_before_auto=False
        self.run_controller()
        events=self.events()
        self.assertEqual((events[0]['command'],events[0]['action'],events[0]['start_rows'],events[0]['start_state']),
                         ('synthetic-002','resume-scan',1,'partial-synthetic'))
        self.assertEqual(self.commands()[0],['deduce','synthetic',str(self.directory),
                                          'checkpoint_seconds=300','checkpoint_resume=1'])
        self.assert_stage_done()

    def test_synthetic_complete_checkpoint_before_save_nodes_only_restores(self):
        self.active_synthetic(exit_code=None)
        self.metadata(True,'synthetic-002','synthetic','complete-checkpoint-before-save')
        self.run_controller()
        events=self.events()
        self.assertEqual([(x['command'],x['action']) for x in events],
                         [('synthetic-002','restore'),('synthetic-002','restore'),('auto-002','scan')])
        self.assertEqual(events[-1]['start_state'],'complete-checkpoint-before-save')
        self.assertEqual(events[-1]['start_rows'],1)
        self.assert_stage_done()

    def test_completed_synthetic_exit_before_stage_advance_is_not_rescanned(self):
        self.ready_synthetic();atomic_json=auto_run.atomic_json
        def interrupt_stage_advance(path,value):
            atomic_json(path,value)
            if (value.get('synthetic_before_auto',{}).get('stage')=='synthetic' and
                    value.get('last_completed_command')=='synthetic-002'):
                raise OSError('Interrupted after synthetic exit was recorded')
        with patch.object(auto_run,'atomic_json',side_effect=interrupt_stage_advance):
            with self.assertRaisesRegex(OSError,'after synthetic exit'):self.run_controller()
        saved=self.status()
        self.assertEqual(saved['synthetic_before_auto']['stage'],'synthetic')
        self.assertEqual(saved['last_completed_command'],'synthetic-002');self.assertEqual(saved['exit_code'],0)
        self.run_controller()
        self.assertEqual([(x['command'],x['action']) for x in self.events()],
            [('auto-001','restore'),('synthetic-002','scan'),('synthetic-002','restore'),('auto-002','scan')])
        self.assert_stage_done()

    def test_auto_before_first_checkpoint_trims_tail_without_synthetic_resweep(self):
        self.active_synthetic(stage='auto',command='auto-002',completed='synthetic-002',exit_code=None)
        with sqlite3.connect(self.directory/'log.db') as d:
            d.execute("UPDATE native_state SET value='last-saved-tables' WHERE id=1")
        sqlite3.connect(self.directory/'recovery.sqlite3').close()
        self.run_controller()
        self.assertEqual([(x['command'],x['action'],x['start_rows']) for x in self.events()],
                         [('auto-002','scan',1)])
        self.assertEqual(self.events()[0]['start_state'],'last-saved-tables')
        self.assertNotIn('checkpoint_resume=1',self.commands()[0])
        self.assert_stage_done()

    def test_auto_predecessor_restore_repeats_after_two_interruptions(self):
        self.active_synthetic(stage='auto',command='auto-002',completed='synthetic-002')
        self.metadata(True,'synthetic-002','synthetic','synthetic-saved-state')
        popen=auto_run.subprocess.Popen
        def interrupt_auto_start(arguments,**kwargs):
            if arguments[1:3]==['deduce','auto'] and 'checkpoint_resume=1' not in arguments:
                raise OSError('Interrupted before auto first checkpoint')
            return popen(arguments,**kwargs)
        for attempt in range(2):
            with self.subTest(interruption=attempt), \
                 patch.object(auto_run.subprocess,'Popen',side_effect=interrupt_auto_start):
                with self.assertRaisesRegex(OSError,'before auto first checkpoint'):self.run_controller()
                result=self.status()
                self.assertEqual(result['synthetic_before_auto']['stage'],'auto')
                self.assertEqual(result['command'],'synthetic-002')
                self.assertEqual(result['command_index'],2)
        self.run_controller()
        events=self.events()
        self.assertEqual([(x['command'],x['action']) for x in events],
            [('synthetic-002','restore')]*3+[('auto-002','scan')])
        self.assertEqual(events[-1]['start_state'],'synthetic-saved-state')
        self.assertEqual(events[-1]['start_rows'],1)
        self.assert_stage_done()

    def test_partial_auto_checkpoint_resumes_without_synthetic_resweep(self):
        self.active_synthetic(stage='auto',command='auto-002',completed='synthetic-002',exit_code=None)
        self.metadata(False,'auto-002','auto','partial-auto')
        self.run_controller()
        self.assertEqual([(x['command'],x['action'],x['start_state']) for x in self.events()],
                         [('auto-002','resume-scan','partial-auto')])
        self.assertIn('checkpoint_resume=1',self.commands()[0])
        self.assert_stage_done()

    def test_completed_auto_checkpoint_before_stage_done_only_restores(self):
        self.active_synthetic(stage='auto',command='auto-002',completed='synthetic-002',exit_code=None)
        self.metadata(True,'auto-002','auto','complete-auto-before-save')
        self.run_controller()
        self.assertEqual([(x['command'],x['action'],x['start_state']) for x in self.events()],
                         [('auto-002','restore','complete-auto-before-save')])
        self.assertIn('checkpoint_resume=1',self.commands()[0])
        self.assert_stage_done()

    def test_unrelated_partial_checkpoint_cannot_enter_synthetic_stage(self):
        self.active_synthetic();self.metadata(False,'auto-001')
        with self.assertRaisesRegex(RuntimeError,'Unfinished checkpoint belongs to another'):self.run_controller()
        self.assertEqual(self.commands(),[])

    def test_active_stages_reject_option_or_binary_changes_even_at_complete_checkpoint(self):
        self.active_synthetic();self.metadata(True,'synthetic-002','synthetic')
        for stage in ('synthetic','auto'):
            for change in ('flags','rounds','binary'):
                with self.subTest(stage=stage,change=change):
                    self.state['synthetic_before_auto']['stage']=stage;self.save()
                    self.args.flags='syn,dxy';self.args.native_rounds=100;self.args.binary=self.binary
                    self.args.adopt_binary=False
                    if change=='flags':self.args.flags='syn,dxy,zero'
                    elif change=='rounds':self.args.native_rounds=101
                    else:self.replacement_binary();self.args.adopt_binary=True
                    before=(self.directory/'status.json').read_bytes()
                    with self.assertRaisesRegex(RuntimeError,'cannot change during explicit synthetic continuation'):
                        self.run_controller()
                    self.assertEqual((self.directory/'status.json').read_bytes(),before)
                    self.assertEqual(self.commands(),[])

    def test_done_stage_verification_retry_does_not_repeat_native_commands(self):
        self.ready_synthetic();run=auto_run.subprocess.run
        def interrupt_verifier(arguments,**kwargs):
            if arguments[1]=='verify':raise OSError('Verifier temporarily unavailable')
            return run(arguments,**kwargs)
        with patch.object(auto_run.subprocess,'run',side_effect=interrupt_verifier):
            with self.assertRaisesRegex(OSError,'temporarily unavailable'):self.run_controller()
        result=self.status()
        self.assertEqual(result['phase'],'verifying');self.assertEqual(result['synthetic_before_auto']['stage'],'done')
        commands_before=self.commands();events_before=self.events()
        self.run_controller()
        self.assertEqual(self.commands(),commands_before+[['verify',str(self.directory),str(auto_run.ROOT/'validation/targets.json')]])
        self.assertEqual(self.events(),events_before)
        self.assert_stage_done()

    def test_done_stage_notification_retry_consumes_repeated_request(self):
        self.ready_synthetic();self.args.notify_user='fixture-user'
        with patch.object(auto_run,'notify',side_effect=RuntimeError('Notification temporarily unavailable')):
            with self.assertRaisesRegex(RuntimeError,'Notification temporarily unavailable'):self.run_controller()
        self.assert_stage_done();commands_before=self.commands()
        with patch.object(auto_run,'notify') as notify:
            self.run_controller()
        notify.assert_called_once()
        self.assertEqual(self.commands(),commands_before)
        self.assert_stage_done()

    def test_stage_failure_or_forbidden_output_never_continues_or_notifies(self):
        self.active_synthetic()
        for stage in ('synthetic','auto'):
            for problem in ('nonzero','forbidden','missing-complete-checkpoint'):
                with self.subTest(stage=stage,problem=problem):
                    self.state['synthetic_before_auto']['stage']=stage
                    self.state['command']=stage+'-002';self.save()
                    for name in ('commands','events','recovery.sqlite3'):
                        (self.directory/name).unlink(missing_ok=True)
                    with sqlite3.connect(self.directory/'log.db') as d:
                        d.execute('DELETE FROM log WHERE id>1')
                    behavior=({'exit_code':7} if problem=='nonzero' else {'forbidden':True} if problem=='forbidden'
                              else {'checkpoint':'partial'})
                    (self.directory/'engine-plan.json').write_text(json.dumps({stage+'-002':behavior}))
                    error='exited 7' if problem=='nonzero' else 'forbidden output' if problem=='forbidden' else 'completed (auto )?checkpoint'
                    with patch.object(auto_run,'notify') as notify:
                        with self.assertRaisesRegex(RuntimeError,error):self.run_controller()
                    notify.assert_not_called()
                    self.assertEqual([x[:2] for x in self.commands()],[['deduce',stage]])
                    self.assertFalse((self.directory/'acceptance.json').exists())


if __name__=='__main__':unittest.main()
