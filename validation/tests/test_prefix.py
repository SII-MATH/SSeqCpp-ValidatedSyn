"""The comparison is a gate, not a source of inference facts."""
import json
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_prefix import compare
import run as runner

SCHEMA = 'CREATE TABLE log(id INTEGER PRIMARY KEY, depth,reason,name,s,t,r,x,dx,info)'
FIRST = (0, 'd2', 'S0', 5, 14, 2, '0', '', None)
MANUAL = (0, 'M', 'S0', 25, 88, 5, '1', '0', None)
ORDINARY = (0, 'D', 'S0', 6, 36, 3, '0', '0', None)
SYN = (0, 'Syn', 'C2', 6, 36, 4, '0', '0', 'witness')


def database(path, rows):
    with sqlite3.connect(path) as db:
        db.execute(SCHEMA)
        db.executemany('INSERT INTO log VALUES(?,?,?,?,?,?,?,?,?,?)', rows)


class PrefixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference = self.root/'official.db'
        database(self.reference, [(5432,*FIRST), (71642,*MANUAL),
                                  (152090,*ORDINARY), (2411455,*SYN)])
        self.current = self.root/'log.db'

    def test_accepts_same_events_with_different_ids_and_command_metadata(self):
        database(self.current, [(1,*FIRST), (2,*MANUAL),
                                (3,-1,None,None,None,None,None,None,None,'command'),
                                (4,*ORDINARY)])
        result = compare(self.current,self.reference)
        self.assertTrue(result['passed'])
        self.assertEqual(result['matched'],3)

    def test_missing_manual_record_fails(self):
        database(self.current, [(1,*FIRST), (2,*ORDINARY)])
        result = compare(self.current,self.reference)
        self.assertFalse(result['passed'])
        self.assertEqual(result['matched'],1)

    def test_early_new_syn_fails_even_if_ordinary_rows_match(self):
        syn = (SYN[0],'SynValidated',*SYN[2:])
        database(self.current, [(1,*FIRST),(2,*MANUAL),(3,*ORDINARY),(4,*syn)])
        self.assertIn('Synthetic',compare(self.current,self.reference)['error'])

    def test_changed_proof_fails(self):
        changed = (*ORDINARY[:-1],'different proof')
        database(self.current, [(1,*FIRST),(2,*MANUAL),(3,*changed)])
        self.assertFalse(compare(self.current,self.reference)['passed'])

    def test_extra_ordinary_record_fails(self):
        database(self.current, [(1,*FIRST),(2,*MANUAL),(3,*ORDINARY),(4,*ORDINARY)])
        self.assertFalse(compare(self.current,self.reference)['passed'])

    def test_resume_rechecks_only_the_previously_verified_prefix(self):
        syn=(SYN[0],'SynValidated',*SYN[2:])
        database(self.current,[(1,*FIRST),(2,*MANUAL),(3,*ORDINARY),(4,*syn)])
        self.assertTrue(compare(self.current,self.reference,current_stop=3)['passed'])
        self.assertFalse(compare(self.current,self.reference)['passed'])

    def controller(self, missing_manual, resume_after_ordinary=False, resume_mid_synthetic=False):
        project=self.root/'project';project.mkdir();(project/'validation').mkdir()
        (project/'validation/targets.json').write_text('{}')
        directory=self.root/'run';directory.mkdir()
        (directory/'initial-inputs.sha256').write_text('fixture')
        binary=project/'engine.py'
        binary.write_text('''#!/usr/bin/env python3
import sys,sqlite3,json
from pathlib import Path
a=sys.argv[1:];d=Path(a[1] if a[0]=='reset' else a[2] if a[0]=='deduce' else a[1])
with (d/'commands').open('a') as f:f.write(json.dumps(a)+'\\n')
if a[0]=='reset':
 with sqlite3.connect(d/'log.db') as c:
  c.execute(SCHEMA)
  c.execute('INSERT INTO log VALUES(?,?,?,?,?,?,?,?,?,?)',(1,*FIRST))
  if not MISSING:c.execute('INSERT INTO log VALUES(?,?,?,?,?,?,?,?,?,?)',(2,*MANUAL))
elif a[:2]==['deduce','auto'] and 'flags=validated_syn' not in a:
 with sqlite3.connect(d/'log.db') as c:c.execute('INSERT INTO log VALUES(?,?,?,?,?,?,?,?,?,?)',(3,*ORDINARY))
elif a[0]=='verify':
 (d/'acceptance.json').write_text(json.dumps({'total':201,'passed':201,'missing':[],'errors':[],'forbidden_outputs':0}))
if a[0]=='deduce' and (d/'recovery.sqlite3').exists():
 with sqlite3.connect(d/'recovery.sqlite3') as c:
  v=json.loads(c.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0]);v['complete']=True
  c.execute('UPDATE metadata SET value=? WHERE id=1',(json.dumps(v),))
'''.replace('if a[0]==\'reset\':',f'SCHEMA={SCHEMA!r}\nFIRST={FIRST!r}\nMANUAL={MANUAL!r}\nORDINARY={ORDINARY!r}\nMISSING={missing_manual!r}\nif a[0]==\'reset\':'))
        binary.chmod(0o755)
        if resume_after_ordinary:
            database(directory/'log.db',[(1,*FIRST),(2,*MANUAL),(3,*ORDINARY)])
            status={'phase':'ordinary-complete',
                'historical_log_imported':False,'last_completed_command':'ordinary','command':'ordinary',
                'targets_sha256':hashlib.sha256(b'{}').hexdigest(),'runner_pid':0}
            if resume_mid_synthetic:
                with sqlite3.connect(directory/'log.db') as db:
                    db.execute('INSERT INTO log VALUES(?,?,?,?,?,?,?,?,?,?)',(4,SYN[0],'SynValidated',*SYN[2:]))
                report=compare(directory/'log.db',self.reference,current_stop=3)
                (directory/'ordinary-comparison.json').write_text(json.dumps(report))
                status.update(command='validated-001',new_rules_enabled=True,ordinary_comparison={'passed':True})
                with sqlite3.connect(directory/'recovery.sqlite3') as db:
                    db.execute('CREATE TABLE metadata(id INTEGER PRIMARY KEY,value TEXT)')
                    db.execute('INSERT INTO metadata VALUES(1,?)',(json.dumps({'command':'validated-001','complete':False}),))
            (directory/'status.json').write_text(json.dumps(status))
        with patch.object(runner,'ROOT',project):
            if missing_manual:
                with self.assertRaisesRegex(RuntimeError,'new rules remain disabled'):
                    runner.run(binary,directory,1,261,official_log=self.reference)
            else:
                runner.run(binary,directory,1,261,official_log=self.reference,resume=resume_after_ordinary)
        commands=[json.loads(line) for line in (directory/'commands').read_text().splitlines()]
        return directory,commands

    def test_controller_stops_on_mismatch_before_any_syn_or_verify(self):
        directory,commands=self.controller(True)
        self.assertEqual([x[:2] for x in commands],[['reset',str(directory)],['deduce','auto']])
        status=json.loads((directory/'status.json').read_text())
        self.assertFalse(status['new_rules_enabled'])
        self.assertEqual(status['phase'],'prefix-mismatch')

    def test_controller_runs_syn_and_201_check_only_after_match(self):
        directory,commands=self.controller(False)
        self.assertEqual([x[0] for x in commands],['reset','deduce','deduce','deduce','verify'])
        self.assertNotIn('flags=validated_syn',commands[1])
        self.assertEqual(commands[2][:2],['deduce','synthetic'])
        self.assertEqual(json.loads((directory/'status.json').read_text())['phase'],'passed')

    def test_resume_after_normal_save_does_not_repeat_reset_or_ordinary(self):
        directory,commands=self.controller(False,True)
        self.assertEqual([x[:2] for x in commands[:2]],[['deduce','synthetic'],['deduce','auto']])
        self.assertEqual([x[0] for x in commands],['deduce','deduce','verify'])
        self.assertTrue(json.loads((directory/'ordinary-comparison.json').read_text())['passed'])

    def test_resume_first_synthetic_command_revalidates_the_saved_prefix(self):
        directory,commands=self.controller(False,True,True)
        self.assertIn('checkpoint_resume=1',commands[0])
        report=json.loads((directory/'ordinary-comparison.json').read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['last_current_id'],3)


if __name__ == '__main__':
    unittest.main()
