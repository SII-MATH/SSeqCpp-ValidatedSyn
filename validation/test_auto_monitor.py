#!/usr/bin/env python3
"""Verify an atomic checkpoint while the ordinary saved SS tables are stale."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from auto_run import snapshot_check
from test_checkpoints import fixture

ROOT=Path(__file__).resolve().parents[1]


def main(seed):
    binary=ROOT/'build/bin/ss'
    with tempfile.TemporaryDirectory(prefix='ss-auto-monitor-test-') as tmp:
        run=Path(tmp)/'run';fixture(seed,run)
        for args in (['reset',str(run),'confirm=1'],
                     ['deduce','auto',str(run),'stem_min=0','stem_max=45','num=1','checkpoint_seconds=300']):
            p=subprocess.run([str(binary),*args],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
            if p.returncode:raise RuntimeError(p.stdout[-3000:])
        config=json.loads((run/'ss.json').read_text());s0=next(x for x in config['rings'] if x['name']=='S0')
        with sqlite3.connect(run/s0['path']) as db:
            rows=db.execute('SELECT s,t,base,diff,level FROM S0_AdamsE2_ss WHERE level>9000 AND level<=9998 AND diff IS NOT NULL ORDER BY id LIMIT 201').fetchall()
            assert len(rows)==201
            targets={'count':201,'targets':[dict(id=f'fixture-{i}',object='S0',kind='equation',s=s,t=t,r=10000-lv,
                x=[int(k) for k in x.split(',') if k],y=[int(k) for k in y.split(',') if k])
                for i,(s,t,x,y,lv) in enumerate(rows)]}
            # The running native engine can have much newer in-memory state
            # than these saved tables. Require the checker to use its checkpoint.
            db.execute('DELETE FROM S0_AdamsE2_ss');db.commit()
        target_file=Path(tmp)/'fixture-targets.json';target_file.write_text(json.dumps(targets))
        with sqlite3.connect(run/'log.db') as db:
            before=db.execute('SELECT count(*),max(id) FROM log').fetchone()
        result=snapshot_check(run,binary,target_file)
        assert result['passed']==201 and not result['errors'] and not result['forbidden_outputs'],result
        # A failed target evaluation must not continue into subsequent targets:
        # upstream trial exceptions are not guaranteed to pop their trial node.
        invalid=json.loads(json.dumps(targets));invalid['targets'][0]['kind']='invalid-test-kind'
        target_file.write_text(json.dumps(invalid))
        aborted=snapshot_check(run,binary,target_file)
        assert aborted['passed']==0 and len(aborted['errors'])==1 and len(aborted['missing'])==201,aborted
        with sqlite3.connect(run/'log.db') as db:
            assert before==db.execute('SELECT count(*),max(id) FROM log').fetchone(),'monitor wrote production log'
        with sqlite3.connect(run/s0['path']) as db:
            assert db.execute('SELECT count(*) FROM S0_AdamsE2_ss').fetchone()[0]==0,'monitor wrote saved SS state'
        print('PASS: checkpoint state used instead of stale saved tables; 201 distinct fixture equations; abort after target exception; producer log and state unchanged')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('seed',type=Path);main(parser.parse_args().seed.resolve())
