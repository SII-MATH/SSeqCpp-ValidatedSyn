#!/usr/bin/env python3
"""Read-only comparison; historical records are never fed to the SS engine."""
import argparse
import json
from pathlib import Path
import sqlite3

FIELDS = 'depth,reason,name,s,t,r,x,dx,info'
SYNTHETIC = ('Syn', 'SynValidated', 'SynCs', 'SynCsIn')


def compare(current, official):
    with sqlite3.connect(Path(current).resolve().as_uri() + '?mode=ro', uri=True) as got, \
         sqlite3.connect(Path(official).resolve().as_uri() + '?mode=ro', uri=True) as ref:
        start = ref.execute('SELECT min(id) FROM log').fetchone()[0]
        stop = ref.execute("SELECT min(id) FROM log WHERE reason IN ('Syn','SynCs','SynCsIn')").fetchone()[0]
        if start is None or stop is None:
            raise ValueError('Reference must contain an ordinary prefix followed by Syn')
        forbidden = got.execute("SELECT reason,count(*) FROM log WHERE reason IN (?,?,?,?) GROUP BY reason", SYNTHETIC).fetchall()
        result = {'passed': False, 'reference_first_id': start,
                  'reference_first_syn_id': stop, 'matched': 0,
                  'synthetic_outputs': forbidden,
                  'comparison': 'ordered depth/reason/object/degrees/page/source/target/proof; IDs and command metadata excluded'}
        if forbidden:
            result['error'] = 'Synthetic deductions occurred before prefix validation'
            return result
        # This published log omits its first 5431 rows. Align at its first
        # retained mathematical event, rather than treating absent rows as a
        # mismatch. Require that event to have exactly one match in reset.
        first = ref.execute(f'SELECT id,{FIELDS} FROM log WHERE reason IS NOT NULL ORDER BY id LIMIT 1').fetchone()
        candidates = got.execute('SELECT id FROM log WHERE depth IS ? AND reason IS ? AND name IS ? AND s IS ? AND t IS ? AND r IS ? AND x IS ? AND dx IS ? AND info IS ? LIMIT 2', first[1:]).fetchall()
        if len(candidates) != 1:
            result['error'] = f'Reference start has {len(candidates)} matches in initialization'
            return result
        result['current_first_id'] = candidates[0][0]
        expected = ref.execute(f'SELECT id,{FIELDS} FROM log WHERE id>=? AND id<? AND reason IS NOT NULL ORDER BY id', (start, stop))
        actual = got.execute(f'SELECT id,{FIELDS} FROM log WHERE id>=? AND depth>=0 AND reason IS NOT NULL ORDER BY id', (candidates[0][0],))
        while True:
            a, b = actual.fetchone(), expected.fetchone()
            if a is None and b is None:
                result['passed'] = True
                break
            if a is None or b is None or a[1:] != b[1:]:
                result['first_difference'] = {'current': a, 'official': b}
                result['error'] = 'Ordinary computation differs; new rules must remain disabled'
                break
            result['matched'] += 1
            result['last_current_id'], result['last_reference_id'] = a[0], b[0]
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('current', type=Path)
    parser.add_argument('official', type=Path)
    args = parser.parse_args()
    result = compare(args.current, args.official)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
