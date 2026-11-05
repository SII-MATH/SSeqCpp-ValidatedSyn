#!/usr/bin/env python3
"""Adopt this run's output and switch binaries only after a native step exits.

The running C++ process is neither interrupted nor replaced. Its old Python
controller is suspended only after its output pipe has another reader. It is
retired after the C++ process exits and commits its own saved state.
"""
import argparse
from collections import deque
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import time

from run import ROOT, run


def process(pid):
    base=Path('/proc')/str(pid)
    fields=(base/'stat').read_text().rsplit(')',1)[1].split()
    return {'state':fields[0],'parent':int(fields[1]),'start':int(fields[19]),
            'exit':int(fields[49]) if len(fields)>49 else None,
            'arguments':(base/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')}


def adopt(parent,child,root,directory,update):
    root,directory=Path(root).resolve(),Path(directory).resolve()
    original=process(parent)
    actual=process(child)
    arguments=[v.decode() for v in actual['arguments']]
    if actual['parent']!=parent or str(directory) not in arguments:
        raise ValueError('Native process does not belong to this run')
    if (Path('/proc')/str(parent)/'cwd').resolve()!=root:
        raise ValueError('Unexpected controller working directory')
    if not any(v.endswith(b'validation/run.py') for v in original['arguments']):
        raise ValueError('Unexpected controller program')
    stdout=Path(f'/proc/{child}/fd/1').readlink()
    if not str(stdout).startswith('pipe:'):
        raise ValueError('Native stdout is not an adoptable pipe; leave the original controller running')
    readers=[]
    for fd in Path(f'/proc/{parent}/fd').iterdir():
        try:
            if fd.readlink()==stdout: readers.append(fd)
        except OSError: pass
    if len(readers)!=1: raise ValueError('Ambiguous native output pipe')
    adopted=os.open(str(readers[0]),os.O_RDONLY|os.O_NONBLOCK)
    stopped=False
    try:
        os.kill(parent,signal.SIGSTOP)
        stopped=True
        if process(parent)['start']!=original['start'] or process(child)['parent']!=parent:
            raise ValueError('Process identity changed during handoff')
        update(runner_pid=os.getpid(),original_runner_pid=parent,
               handoff='draining the unchanged native process; cache switch waits for normal exit')
        decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
        partial='';tail=deque(maxlen=80);lines=0;updated=time.monotonic()
        while True:
            ready,_,_=select.select([adopted],[],[],2)
            if not ready: continue
            chunk=os.read(adopted,65536)
            if not chunk: break
            partial+=decoder.decode(chunk)
            parts=re.split(r'[\r\n]',partial);partial=parts.pop()
            for line in parts:
                if line:tail.append(line+'\n');lines+=1
            if time.monotonic()-updated>10:
                update(handoff_progress_lines=lines,
                       last_progress=re.sub(r'\x1b\[[0-9;]*m','',tail[-1][-500:]).strip() if tail else '')
                updated=time.monotonic()
        deadline=time.monotonic()+10
        while process(child)['state']!='Z':
            if time.monotonic()>deadline: raise RuntimeError('Native stdout closed before normal completion')
            time.sleep(.05)
        exit_code=os.waitstatus_to_exitcode(process(child)['exit'])
        # A stopped parent cannot reap its child or start a second command.
        # Only now may it be retired: the native step has fully finished.
        os.kill(parent,signal.SIGKILL)
        stopped=False
        if exit_code:
            (directory/'handoff-step.error.log').write_text(''.join(tail))
        return arguments,exit_code
    finally:
        os.close(adopted)
        if stopped:
            try:os.kill(parent,signal.SIGCONT)
            except ProcessLookupError:pass


def main(directory,binary,rounds,stem_max):
    directory,binary=Path(directory).resolve(),Path(binary).resolve()
    status_file=directory/'status.json'
    status=json.loads(status_file.read_text())
    if status.get('historical_log_imported') is not False or status.get('phase')!='deducing':
        raise ValueError('Only this actively deducing fresh run can be handed off')
    old_binary=ROOT/'.runs/bin/ss-fc06963'
    if hashlib.sha256(old_binary.read_bytes()).hexdigest()!=status['binary_sha256']:
        raise ValueError('Old binary provenance mismatch')
    child_arguments=[v.decode() for v in process(status['child_pid'])['arguments']]
    if Path(child_arguments[0]).resolve()!=old_binary.resolve():
        raise ValueError('Unexpected native executable')
    if child_arguments[1:3] not in (['deduce','auto'],['deduce','synthetic']):
        raise ValueError('Current command is not a supported handoff boundary')
    if not binary.is_file() or not os.access(binary,os.X_OK):
        raise ValueError('Cache binary is not installed')
    def update(**values):
        status.update(values)
        temporary=status_file.with_suffix('.handoff.tmp')
        temporary.write_text(json.dumps(status,indent=2)+'\n')
        temporary.replace(status_file)
    print('Adopting the live native step; it continues unchanged.',flush=True)
    arguments,code=adopt(status['runner_pid'],status['child_pid'],ROOT,directory,update)
    if arguments[1:3]==['deduce','auto']: completed=(status['round'],'auto')
    elif arguments[1:3]==['deduce','synthetic']: completed=(status['round'],'synthetic')
    else: raise ValueError('Unsupported current command; no inference state is modified')
    if code:
        update(phase='failed',exit_code=code)
        raise RuntimeError('The original native step failed; cache continuation was not started')
    update(handoff='native step completed and saved; continuing with the cache binary')
    os.environ['SS_VALIDATED_CACHE_STATS']='1'
    print('Native step finished normally; continuing from its own saved state.',flush=True)
    run(binary,directory,rounds,stem_max,completed=completed,previous_status=status)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=10)
    parser.add_argument('--stem-max',type=int,default=261)
    args=parser.parse_args()
    main(args.directory,args.binary,args.rounds,args.stem_max)
