#!/usr/bin/env python3
"""Fresh calculation; historical records are used only for prefix comparison."""
import argparse
from collections import deque
import json
import hashlib
import os
from pathlib import Path
import resource
import subprocess
import time
import re
import sqlite3
from compare_prefix import compare

ROOT = Path(__file__).resolve().parents[1]


def run(binary, directory, rounds, stem_max, *, official_log=None,
        completed=None, previous_status=None, resume=False, checkpoint_seconds=300, post_flags=None):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    binary, directory = Path(binary).resolve(), Path(directory).resolve()
    if official_log is None:
        raise ValueError('An official log is required for the read-only ordinary-prefix comparison')
    if stem_max != 261:
        raise ValueError('The fixed CW49 reference requires the full stem range 0..261')
    official_log = Path(official_log).resolve()
    if not official_log.is_file():
        raise FileNotFoundError(official_log)
    if completed is not None:
        raise ValueError('The staged rerun must start fresh; the earlier mixed-Syn run is ineligible')
    if not resume and (directory / 'log.db').exists():
        raise ValueError('This command requires a fresh prepared seed, with no log.db')
    if not (directory / 'initial-inputs.sha256').is_file():
        raise ValueError('Use validation/prepare.py first')
    status_file = directory / 'status.json'
    status = json.loads(status_file.read_text()) if resume else {
              'phase': 'initializing', 'started': time.time(), 'round': 0,
              'targets': 201, 'historical_log_imported': False,
              'forbidden_rules': ['SynCs', 'SynCsIn']}
    target_hash=hashlib.sha256((ROOT/'validation/targets.json').read_bytes()).hexdigest()
    boundary=status.get('last_completed_command') if resume else None
    recover_command=status.get('command') if resume else None
    prior_command_start=status.get('command_log_start') if resume else None
    had_verified_prefix=resume and status.get('ordinary_comparison',{}).get('passed') is True
    if resume:
        if status.get('historical_log_imported') is not False or status.get('targets_sha256')!=target_hash or not boundary:
            raise ValueError('Resume requires this fresh run, unchanged targets and a completed command boundary')
        old_pid=status.get('runner_pid')
        if old_pid and old_pid!=os.getpid() and Path(f'/proc/{old_pid}/cmdline').exists():
            args=Path(f'/proc/{old_pid}/cmdline').read_bytes().split(b'\0')
            if any(x.endswith(b'validation/run.py') for x in args):
                raise ValueError('The original controller is still running')
        status['previous_binary']={k:status.get(k) for k in ('source_commit','binary_sha256')}
    valid_boundaries=['initialize','ordinary']+[f'{kind}-{n:03d}' for n in range(1,rounds+1) for kind in ('validated','round','verify')]
    if resume and boundary not in valid_boundaries:raise ValueError('Unknown resume boundary')
    child=status.get('child_pid')
    if resume and child and Path(f'/proc/{child}/cmdline').exists():
        if str(directory).encode() in Path(f'/proc/{child}/cmdline').read_bytes().split(b'\0'):
            raise ValueError('The original native command is still running')
    if resume and status.get('phase')=='passed' and status.get('passed')==201:return
    if resume:
        # Let SQLite recover this run's own journal/WAL before read-only audits.
        with sqlite3.connect(directory/'log.db') as db:db.execute('SELECT max(id) FROM log').fetchone()
    skipping=bool(boundary)
    status['schedule'] = 'ordinary without Syn -> exact prefix comparison -> validated rules -> 201 targets'
    status.update({'runner_pid': os.getpid(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'targets_sha256': hashlib.sha256((ROOT/'validation/targets.json').read_bytes()).hexdigest(),
              'source_commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()})
    status['checkpoint_seconds']=checkpoint_seconds
    post_flags=status.get('post_flags','validated_syn') if post_flags is None else post_flags
    if not post_flags or any(x not in ('validated_syn','zero','pullback','dxy') for x in post_flags.split(',')):
        raise ValueError('Only validated_syn, zero, pullback and dxy are allowed after prefix validation')
    status['post_flags']=post_flags

    def skip(name):
        nonlocal skipping
        if skipping:
            if name==boundary:skipping=False
            return True
        return False

    def save(**values):
        status.update(values)
        temporary=status_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(status_file)

    def command(arguments, name):
        if skip(name):return
        metadata=None
        recovery=directory/'recovery.sqlite3'
        if recovery.exists():
            with sqlite3.connect(recovery) as db:
                if db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()[0]:
                    metadata=json.loads(db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
        if arguments[:2] in (['deduce','auto'],['deduce','synthetic']):
            arguments=[*arguments,f'checkpoint_seconds={checkpoint_seconds}']
            if metadata and metadata['command']==name:
                arguments.append('checkpoint_resume=1')
            elif metadata and not metadata['complete']:
                raise ValueError('An unfinished checkpoint belongs to another command')
            elif metadata and resume and name==recover_command:
                # A crash during the new command's initial save may leave the
                # previous complete checkpoint. Restore it before restarting.
                previous=metadata['options'];kind=metadata['kind']
                restore=['deduce',kind,str(directory),f'checkpoint_seconds={checkpoint_seconds}','checkpoint_resume=1']
                if kind=='auto':
                    restore += [f'stem_min={previous["stem_min"]}',f'stem_max={previous["stem_max"]}',f'T={previous["T"]}',f'id_thread={previous["id_thread"]}',f'num={previous["num"]}']
                    # Store original spellings as well as the parsed mask.
                    if previous.get('flag_names'):restore+=['flags='+','.join(previous['flag_names'])]
                    for field in ('mode','deduce_list'):
                        if previous.get(field):restore += [field+'='+','.join(previous[field])]
                env=os.environ|{'SS_RUN_COMMAND':metadata['command']}
                subprocess.run([str(binary),*restore],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,check=True)
            elif metadata is None and resume and name==recover_command and prior_command_start is not None:
                # No state checkpoint was published by this command yet.
                with sqlite3.connect(directory/'log.db') as db:
                    db.execute('DELETE FROM exclusions WHERE id>?',(prior_command_start,))
                    db.execute('DELETE FROM log WHERE id>?',(prior_command_start,))
        command_start=None
        if (directory/'log.db').exists():
            with sqlite3.connect(directory/'log.db') as db:
                command_start=db.execute('SELECT max(id) FROM log').fetchone()[0]
        tail = deque(maxlen=80)
        proc = subprocess.Popen([str(binary), *arguments], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace',env=os.environ|{'SS_RUN_COMMAND':name,
                                'SS_BINARY_SHA256':status['binary_sha256'],'SS_SOURCE_COMMIT':status['source_commit']})
        save(command=name, child_pid=proc.pid, terminal_lines=0,
             last_progress='', command_started=time.time(),command_log_start=command_start)
        updated, lines = time.monotonic(), 0
        for line in proc.stdout:
            tail.append(line)
            lines += 1
            if time.monotonic() - updated > 10:
                save(command=name, terminal_lines=lines,
                     last_progress=re.sub(r'\x1b\[[0-9;]*m','',line[-500:]).strip())
                updated = time.monotonic()
            if line.startswith('VALIDATED_CACHE '):
                save(cache_statistics=json.loads(line.removeprefix('VALIDATED_CACHE ')))
            clean=re.sub(r'\x1b\[[0-9;]*m','',line).strip()
            if clean.startswith('SS_PROGRESS '):
                progress=json.loads(clean.removeprefix('SS_PROGRESS '))
                save(saved_log_rows=progress['log_rows'],recovery=progress)
        code = proc.wait()
        proc.stdout.close()
        save(terminal_lines=lines, command_finished=time.time(), child_pid=None)
        if code:
            (directory / (name + '.error.log')).write_text(''.join(tail))
            save(phase='failed', command=name, exit_code=code)
            raise RuntimeError(f'{name} failed: see {directory / (name + ".error.log")}')
        # SQLite is authoritative only after the native command has committed.
        with sqlite3.connect((directory/'log.db').as_uri()+'?mode=ro',uri=True) as db:
            save(saved_log_rows=db.execute('SELECT count(*) FROM log').fetchone()[0],last_completed_command=name)

    save()
    command(['reset', str(directory), 'confirm=1'], 'initialize')
    # No synthetic, zero-expansion or pullback flag is used in the published
    # ordinary prefix (all retained trials there have depth one). The upstream
    # auto command stops when a complete SS/cofiber iteration adds no facts.
    save(phase='ordinary', new_rules_enabled=False)
    command(['deduce', 'auto', str(directory), 'stem_min=0', 'stem_max=261',
             'num=10'], 'ordinary')
    save(phase='comparing-prefix')
    report=directory/'ordinary-comparison.json'
    stop=None
    if skipping or had_verified_prefix:
        old=json.loads(report.read_text())
        if not old.get('passed'):raise ValueError('No successful ordinary-prefix comparison to resume')
        stop=old['last_current_id']
    comparison = compare(directory/'log.db', official_log, current_stop=stop)
    (directory/'ordinary-comparison.json').write_text(json.dumps(comparison, indent=2)+'\n')
    save(ordinary_comparison={'passed':comparison['passed'], 'matched':comparison['matched'],
                             'report':'ordinary-comparison.json'})
    if not comparison['passed']:
        save(phase='prefix-mismatch')
        raise RuntimeError('Ordinary prefix differs from official log; new rules remain disabled')
    save(phase='deducing', new_rules_enabled=True)
    for number in range(1, rounds + 1):
        save(round=number)
        # The first enabling point is strictly after a successful comparison.
        command(['deduce', 'synthetic', str(directory)], f'validated-{number:03d}')
        command(['deduce', 'auto', str(directory), 'stem_min=0', f'stem_max={stem_max}',
                 'num=1', 'flags='+post_flags], f'round-{number:03d}')
        verify_name=f'verify-{number:03d}'
        if skip(verify_name):continue
        acceptance_file = directory / 'acceptance.json'
        acceptance_file.unlink(missing_ok=True)
        save(command=verify_name)
        with (directory / f'check-{number:03d}.log').open('w') as log:
            result = subprocess.run([str(binary), 'verify', str(directory),
                                     str(ROOT / 'validation/targets.json')], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT)
        verify_code=result.returncode
        if not acceptance_file.is_file():
            save(phase='failed', command='verify', exit_code=verify_code)
            raise RuntimeError('Verification did not produce a result')
        acceptance = json.loads(acceptance_file.read_text())
        with sqlite3.connect((directory/'log.db').as_uri()+'?mode=ro',uri=True) as db:
            verified_log_rows=db.execute('SELECT count(*) FROM log').fetchone()[0]
        save(passed=acceptance['passed'], missing=acceptance['missing'],
             forbidden_outputs=acceptance['forbidden_outputs'],last_completed_command=verify_name,
             saved_log_rows=verified_log_rows)
        if acceptance['forbidden_outputs']:
            save(phase='failed')
            raise RuntimeError('Forbidden synthetic output detected')
        if verify_code == 0 and acceptance['passed'] == 201:
            save(phase='passed', completed=time.time())
            return
    save(phase='incomplete', completed=time.time())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/bin/ss')
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--stem-max', type=int, default=261)
    parser.add_argument('--official-log', type=Path, required=True,
                        help='Read only by the comparison; never passed to the native engine')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--checkpoint-seconds',type=float,default=300)
    parser.add_argument('--post-flags',default=None,
                        help='Post-prefix ordinary search flags: validated_syn, zero, pullback, dxy')
    args = parser.parse_args()
    run(args.binary, args.directory, args.rounds, args.stem_max, official_log=args.official_log,
        resume=args.resume,checkpoint_seconds=args.checkpoint_seconds,post_flags=args.post_flags)
