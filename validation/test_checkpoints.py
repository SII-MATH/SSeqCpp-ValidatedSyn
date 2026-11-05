#!/usr/bin/env python3
"""Crash a private native calculation and compare it with uninterrupted SS."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import signal
import shutil
import resource
import sqlite3
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def fixture(seed,directory):
    config=json.loads((seed/'ss.json').read_text())
    triangle=next(x for x in config['cofseqs'] if x['name']=='S0__C2__S0')
    maps={triangle[k] for k in ('i','q','d')}
    config['rings']=[x for x in config['rings'] if x['name']=='S0']
    config['modules']=[x for x in config['modules'] if x['name']=='C2']
    for section in ('maps','maps_v2'):config[section]=[x for x in config[section] if x['name'] in maps]
    config['cofseqs']=[triangle];config['commutativity']=[]
    directory.mkdir()
    for section in ('rings','modules','maps','maps_v2'):
        for row in config[section]:
            if 'path' in row:subprocess.run(['cp','--reflink=auto','--',str(seed/row['path']),str(directory/row['path'])],check=True)
    (directory/'ss.json').write_text(json.dumps(config))
    (directory/'initial-inputs.sha256').write_text('private native regression fixture\n')
    return config


def events(directory):
    with sqlite3.connect(directory/'log.db') as db:
        return db.execute('SELECT depth,reason,name,s,t,r,x,dx,info FROM log WHERE reason IS NOT NULL ORDER BY id').fetchall()


def states(directory,config):
    result={}
    for row in config['rings']+config['modules']+config['cofseqs']:
        with sqlite3.connect(directory/row['path']) as db:
            table='cofseq_'+row['name'] if row in config['cofseqs'] else row['name']+'_AdamsE2_ss'
            columns='iC,s,t,base,diff,level' if row in config['cofseqs'] else 's,t,base,diff,level'
            grouped=defaultdict(list)
            for value in db.execute(f'SELECT {columns} FROM "{table}"'):
                grouped[value[:-3]].append(value[-3:])
            result[row['name']]=dict(grouped)
    return result


def main(seed,reference,unit_only=False):
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    binary=ROOT/'build/bin/ss'
    backend=sorted((ROOT/'build/ss/CMakeFiles/ss.dir').glob('*.cpp.o'))
    backend=[x for x in backend if x.name!='main.cpp.o']
    executable=ROOT/'build/bin/recovery-tests'
    subprocess.run(['c++','-std=c++20','-O2','-I'+str(ROOT/'include'),'-I'+str(ROOT/'ss'),
                    '-I'+str(ROOT/'thirdparty/fmt/include'),'-I'+str(ROOT/'thirdparty/nlohmann_json'),
                    str(ROOT/'validation/tests/native_recovery.cpp'),*map(str,backend),
                    str(ROOT/'build/src/libalgebras.a'),str(ROOT/'build/thirdparty/fmt/libfmt.a'),
                    str(ROOT/'build/thirdparty/sqlite3/libsqlite3.a'),'-lpthread','-ldl','-o',str(executable)],check=True)
    with tempfile.TemporaryDirectory(prefix='ss-periodic-regression-') as tmp:
        tmp=Path(tmp);baseline=tmp/'baseline';resumed=tmp/'resumed';unit=tmp/'unit'
        fixture(seed,unit)
        if not unit_only:config=fixture(seed,baseline);fixture(seed,resumed)
        def run(exe,args,path):
            with (tmp/(path.name+'-output.txt')).open('a') as out:
                result=subprocess.run([str(exe),*args],cwd=tmp,stdout=out,stderr=subprocess.STDOUT,timeout=180)
            if result.returncode:
                print((tmp/(path.name+'-output.txt')).read_text(errors='replace')[-6000:],flush=True)
                result.check_returncode()
        for path in ((unit,) if unit_only else (baseline,resumed,unit)):run(reference,['reset',str(path),'confirm=1'],path)
        run(executable,[str(unit)],unit)
        if unit_only:
            print('PASS: unpublished first checkpoint, exact state/cache restore, failed-write rollback and trial refusal',flush=True)
            return
        options=['stem_min=0','stem_max=45','num=3']
        run(reference,['deduce','auto',str(baseline),*options],baseline)
        for case in ('degree','round','final'):
            if case=='degree':path=resumed
            else:
                path=tmp/case;fixture(seed,path);run(reference,['reset',str(path),'confirm=1'],path)
            interval='0.05' if case=='degree' else '3600'
            args=[str(binary),'deduce','auto',str(path),*options,'checkpoint_seconds='+interval]
            proc=subprocess.Popen(args,cwd=tmp,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
            killed=False;seen_rows=None;tail=[]
            try:
                for line in proc.stdout:
                    tail=(tail+[line])[-12:]
                    clean=re.sub(r'\x1b\[[0-9;]*m','',line).strip()
                    if clean.startswith('SS_PROGRESS '):
                        progress=json.loads(clean.removeprefix('SS_PROGRESS '))
                        selected=(case=='degree' and progress['checkpoint_sequence']>=2 or
                                  case=='round' and progress['round']>=2 and not progress['complete'] or
                                  case=='final' and progress['complete'])
                        if selected:
                            with sqlite3.connect(path/'log.db',timeout=2) as db:
                                seen_rows=db.execute('SELECT count(*) FROM log').fetchone()[0]
                                assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
                            assert seen_rows>=progress['log_rows']
                            proc.kill();killed=True;break
                code=proc.wait(timeout=10)
            finally:
                proc.stdout.close()
                if proc.poll() is None:proc.kill();proc.wait()
            if not killed:print(''.join(tail),flush=True)
            assert killed and code==-signal.SIGKILL,'test must kill an actively checkpointing command: '+case
            run(binary,['deduce','auto',str(path),*options,'checkpoint_seconds=3600','checkpoint_resume=1'],path)
            assert events(path)==events(baseline),'resumed event/proof stream differs: '+case
            assert states(path,config)==states(baseline,config),'resumed SS/cofiber state differs: '+case
            with sqlite3.connect(path/'recovery.sqlite3') as db:
                metadata=json.loads(db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
            assert metadata['complete']
            print('PASS: SIGKILL at '+case+'; live count readable; exact upstream proof order and final states',flush=True)
        syn=tmp/'synthetic'
        shutil.copytree(baseline,syn)
        run(reference,['deduce','synthetic',str(baseline)],baseline)
        proc=subprocess.Popen([str(binary),'deduce','synthetic',str(syn),'checkpoint_seconds=0.05'],cwd=tmp,
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
        killed=False
        try:
            for line in proc.stdout:
                clean=re.sub(r'\x1b\[[0-9;]*m','',line).strip()
                if clean.startswith('SS_PROGRESS ') and json.loads(clean.removeprefix('SS_PROGRESS '))['checkpoint_sequence']>=2:
                    proc.kill();killed=True;break
            code=proc.wait(timeout=10)
        finally:
            proc.stdout.close()
            if proc.poll() is None:proc.kill();proc.wait()
        assert killed and code==-signal.SIGKILL,'synthetic interruption was not exercised'
        run(binary,['deduce','synthetic',str(syn),'checkpoint_seconds=3600','checkpoint_resume=1'],syn)
        assert events(syn)==events(baseline),'synthetic proof stream differs after recovery'
        assert states(syn,config)==states(baseline,config),'synthetic state differs after recovery'
        print('PASS: synthetic scan SIGKILL/resume; exact upstream proof order and final states',flush=True)



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed',type=Path);parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--unit-only',action='store_true')
    args=parser.parse_args();main(args.seed.resolve(),args.reference.resolve(),args.unit_only)
