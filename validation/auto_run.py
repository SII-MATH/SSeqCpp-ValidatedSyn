#!/usr/bin/env python3
"""Original native auto/switch scheduling, with isolated checkpoint monitoring."""
import argparse
import fcntl
from collections import deque
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import re
from prepare import prepare

ROOT = Path(__file__).resolve().parents[1]
TARGET_SHA256 = '8c5af390415fc9250d0289bf6ca40a90d95177bf30c4e1d552c3914bbdef2299'


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    temporary.replace(path)


def log_counts(directory, floor=None):
    with sqlite3.connect((directory/'log.db').as_uri()+'?mode=ro', uri=True) as db:
        rows = db.execute('SELECT count(*) FROM log').fetchone()[0]
        where, args = ('', ()) if floor is None else (' AND id<=?', (floor,))
        forbidden = db.execute("SELECT count(*) FROM log WHERE reason IN ('Syn','SynCs','SynCsIn')"+where, args).fetchone()[0]
    return rows, forbidden


def recovery_metadata(directory):
    path = directory/'recovery.sqlite3'
    if not path.exists():
        return None
    with sqlite3.connect(path) as db:
        if not db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()[0]:
            return None
        return json.loads(db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])


def snapshot_check(directory, binary, targets, *, lock_fd=None):
    """Copy this run's atomic recovery state; never share its writable log."""
    with tempfile.TemporaryDirectory(prefix='ss-auto-verification-') as temporary:
        private = Path(temporary)
        config = json.loads((directory/'ss.json').read_text())
        for name in ('ss.json', 'initial-inputs.sha256'):
            shutil.copyfile(directory/name, private/name)
        for section in ('rings', 'modules', 'maps', 'maps_v2', 'cofseqs'):
            for entry in config.get(section, []):
                if 'path' in entry:
                    target = private/entry['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.is_symlink():
                        target.symlink_to(directory/entry['path'])
        with sqlite3.connect((directory/'recovery.sqlite3').as_uri()+'?mode=ro', uri=True) as origin, sqlite3.connect(private/'recovery.sqlite3') as copy:
            origin.backup(copy)
            metadata = json.loads(copy.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
        checked = subprocess.run([str(binary), 'verify', str(private), str(targets), 'checkpoint=1'],
                                 cwd=private, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 pass_fds=() if lock_fd is None else (lock_fd,))
        if not (private/'acceptance.json').is_file():
            raise RuntimeError('Checkpoint verification failed: '+checked.stdout[-3000:])
        result = json.loads((private/'acceptance.json').read_text())
        if checked.returncode not in (0, 1):
            raise RuntimeError('Checkpoint verifier exited '+str(checked.returncode))
        result['log_rows'], actual_forbidden = log_counts(directory, metadata['log_id'])
        result['forbidden_outputs'] += actual_forbidden
        result.update(checked_log_id=metadata['log_id'], checked_log_rows=metadata['log_rows'],
                      checkpoint_sequence=metadata['sequence'], checkpoint_command=metadata['command'],
                      checked_at=time.time())
        return result


def publish_progress(directory, result):
    atomic_json(directory/'progress.json', result)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    line = f'{now}\t{result["passed"]}/{result["total"]}\t{result["log_rows"]}\t{result.get("checked_log_id", "saved")}\n'
    with (directory/'progress.tsv').open('a') as out:
        out.write(line)
    print(f'{now}  {result["passed"]}/{result["total"]}  records={result["log_rows"]}', flush=True)


def notify(directory, user_id, state):
    if not user_id or (directory/'notification.json').exists():
        return
    result = json.loads((directory/'acceptance.json').read_text())
    assert result['passed'] == result['total'] == 201 and not result['errors'] and not result['forbidden_outputs']
    message = ('原版 auto＋开关机制重跑已通过：201/201。\n'
               f'实际日志 {state["saved_log_rows"]:,} 条；旧 Syn/SynCs/SynCsIn 输出为 0。\n'
               f'开关：{state["flags"]}。使用本次新生成的数据及检查点。\n'
               f'运行：{directory.name}\n'
               '项目：https://github.com/SII-MATH/SSeqCpp-ValidatedSyn')
    request = ['lark-cli', 'im', '+messages-send', '--as', 'bot', '--user-id', user_id,
               '--text', message, '--idempotency-key', 'ss-auto-'+hashlib.sha256(str(directory).encode()).hexdigest()[:28]]
    sent = subprocess.run(request, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if sent.returncode:
        raise RuntimeError('Feishu notification failed: '+sent.stderr[-1500:])
    receipt = json.loads(sent.stdout)
    if receipt.get('ok') is not True:
        raise RuntimeError('Feishu notification did not return success')
    atomic_json(directory/'notification.json', receipt)


def run(args):
    directory = args.directory.resolve()
    targets = ROOT/'validation/targets.json'
    assert hashlib.sha256(targets.read_bytes()).hexdigest() == TARGET_SHA256
    if not args.resume:
        prepare(args.seed, directory)
    with (directory/'.controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This run is locked by a controller or its native child') from None
        return run_locked(args, lock.fileno())


def run_locked(args, lock_fd):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    directory, binary = args.directory.resolve(), args.binary.resolve()
    targets = ROOT/'validation/targets.json'
    assert hashlib.sha256(targets.read_bytes()).hexdigest() == TARGET_SHA256
    if not args.resume:
        state = dict(phase='initializing', started=time.time(), historical_log_imported=False,
                     target_count=201, targets_sha256=TARGET_SHA256, schedule='native auto with original switches',
                     binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                     source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                     flags=args.flags, native_round_limit=args.native_rounds, command_index=1,
                     check_seconds=args.check_seconds, checkpoint_seconds=args.checkpoint_seconds)
    else:
        state = json.loads((directory/'status.json').read_text())
        assert state['historical_log_imported'] is False and state['targets_sha256'] == TARGET_SHA256
        assert state['binary_sha256'] == hashlib.sha256(binary.read_bytes()).hexdigest()
        for key in ('runner_pid', 'child_pid'):
            pid = state.get(key)
            if pid and Path(f'/proc/{pid}/cmdline').exists():
                if str(directory).encode() in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0'):
                    raise RuntimeError('Existing controller or native calculation is still live')
        changed_options = state['flags'] != args.flags or state['native_round_limit'] != args.native_rounds
        if changed_options or state['phase'] == 'round-limit-incomplete':
            metadata = recovery_metadata(directory)
            if not metadata or not metadata['complete']:
                raise RuntimeError('Search switches may change only at a completed native boundary')
            state.update(preceding_command=metadata['command'], command_index=state['command_index']+1,
                         flags=args.flags, native_round_limit=args.native_rounds, phase='deducing')
    state['runner_pid'] = os.getpid()
    status = directory/'status.json'
    def save(**values):
        state.update(values);atomic_json(status, state)
    def check_binary():
        if hashlib.sha256(binary.read_bytes()).hexdigest() != state['binary_sha256']:
            raise RuntimeError('The pinned executable changed during this run')
    save()

    def native(arguments, name, monitor):
        check_binary()
        tail = deque(maxlen=80); metrics = {}; lock = threading.Lock()
        log_start = None
        if (directory/'log.db').exists():
            with sqlite3.connect(directory/'log.db') as db:
                log_start = db.execute('SELECT max(id) FROM log').fetchone()[0]
        process = subprocess.Popen([str(binary), *arguments], cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   env=os.environ|{'SS_VALIDATED_CACHE_STATS':'1','SS_RUN_COMMAND':name,
                                       'SS_BINARY_SHA256':state['binary_sha256'],'SS_SOURCE_COMMIT':state['source_commit']},
                                   pass_fds=(lock_fd,))
        save(command=name, child_pid=process.pid, command_started=time.time(), command_log_start=log_start)
        def reader():
            for line in process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*m','',line).strip()
                with lock:
                    tail.append(clean)
                    metrics['last_progress'] = clean[-500:]
                    if clean.startswith('SS_PROGRESS '):
                        progress = json.loads(clean.removeprefix('SS_PROGRESS '))
                        metrics.update(saved_log_rows=progress['log_rows'], recovery=progress)
                    elif clean.startswith('VALIDATED_CACHE '):
                        metrics['cache_statistics'] = json.loads(clean.removeprefix('VALIDATED_CACHE '))
            process.stdout.close()
        thread = threading.Thread(target=reader);thread.start()
        next_check = time.monotonic()+min(args.check_seconds, 30)
        while process.poll() is None:
            with lock:
                values = dict(metrics)
            save(**values)
            if monitor and time.monotonic() >= next_check and (directory/'recovery.sqlite3').exists():
                try:
                    check_binary()
                    result = snapshot_check(directory, binary, targets, lock_fd=lock_fd)
                    publish_progress(directory, result)
                    save(passed=result['passed'], missing=result['missing'], last_checked=result['checked_at'], monitor_warning=None)
                    if result['forbidden_outputs']:
                        save(monitor_warning='Forbidden producer output detected')
                        process.terminate()
                except Exception as error:
                    # Monitoring must not kill a healthy native command or
                    # leave its stdout pipe unread after a transient error.
                    save(monitor_warning=str(error))
                next_check = time.monotonic()+args.check_seconds
            time.sleep(5)
        thread.join()
        with lock:
            values = dict(metrics)
        save(**values, child_pid=None, exit_code=process.returncode)
        if process.returncode:
            (directory/(name+'.error.log')).write_text('\n'.join(tail)+'\n')
            save(phase='failed')
            raise RuntimeError(f'Native command {name} exited {process.returncode}')
        save(last_completed_command=name, saved_log_rows=log_counts(directory)[0])

    if not args.resume or (state.get('command') == 'initialize' and state.get('last_completed_command') != 'initialize'):
        native(['reset',str(directory),'confirm=1'], 'initialize', False)
    elif state.get('phase') == 'passed':
        notify(directory,args.notify_user,state);return
    save(phase='deducing')
    index = state['command_index']
    name = f'auto-{index:03d}'
    options = ['deduce','auto',str(directory),'stem_min=0','stem_max=261',
               'num='+str(args.native_rounds),'flags='+args.flags,
               'checkpoint_seconds='+str(args.checkpoint_seconds)]
    recovery = directory/'recovery.sqlite3'
    m = recovery_metadata(directory)
    if m:
        if m['command'] == name:
            options.append('checkpoint_resume=1')
        elif not m['complete']:
            raise RuntimeError('Unfinished checkpoint belongs to another native command')
        elif args.resume:
            # A killed first publication can leave the preceding complete
            # checkpoint. Always restore it: even the preceding restoration
            # may have been interrupted after updating status.command.
            previous = m['options']
            restore = ['deduce',m['kind'],str(directory),
                       'checkpoint_seconds='+str(args.checkpoint_seconds),'checkpoint_resume=1']
            if m['kind'] == 'auto':
                restore += [f'{key}={previous[key]}' for key in ('stem_min','stem_max','T','id_thread','num')]
                if previous.get('flag_names'):
                    restore += ['flags='+','.join(previous['flag_names'])]
                for key in ('mode','deduce_list'):
                    if previous.get(key):
                        restore += [key+'='+','.join(previous[key])]
            native(restore, m['command'], False)
    elif args.resume and state.get('command') == name and state.get('command_log_start') is not None:
        # No first checkpoint was published; the last completed saved state
        # is authoritative. Never combine it with a later committed log tail.
        with sqlite3.connect(directory/'log.db') as db:
            db.execute('DELETE FROM exclusions WHERE id>?', (state['command_log_start'],))
            db.execute('DELETE FROM log WHERE id>?', (state['command_log_start'],))
    native(options, name, True)
    save(phase='verifying')
    check_binary()
    with (directory/'final-verification.log').open('w') as output:
        checked = subprocess.run([str(binary),'verify',str(directory),str(targets)],cwd=directory,
                                 stdout=output,stderr=subprocess.STDOUT,pass_fds=(lock_fd,))
    result = json.loads((directory/'acceptance.json').read_text())
    result.update(log_rows=log_counts(directory)[0], checked_at=time.time())
    publish_progress(directory,result)
    with sqlite3.connect(recovery) as db:
        m=json.loads(db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
    fixed = m['complete'] and not m['changed']
    passed = checked.returncode == 0 and result['passed'] == 201 and not result['errors'] and not result['forbidden_outputs']
    save(phase='passed' if passed else 'fixed-point-incomplete' if fixed else 'round-limit-incomplete',
         passed=result['passed'],missing=result['missing'],saved_log_rows=result['log_rows'],
         native_fixed_point=fixed,completed=time.time())
    if passed:
        notify(directory,args.notify_user,state)
        save(notification='sent' if args.notify_user else 'not-configured')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--seed',type=Path,required=True)
    parser.add_argument('--binary',type=Path,default=ROOT/'build/bin/ss')
    parser.add_argument('--flags',default='syn,dxy')
    parser.add_argument('--native-rounds',type=int,default=100)
    parser.add_argument('--check-seconds',type=int,default=600)
    parser.add_argument('--checkpoint-seconds',type=int,default=300)
    parser.add_argument('--notify-user',default='')
    parser.add_argument('--resume',action='store_true')
    run(parser.parse_args())
