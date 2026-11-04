#!/usr/bin/env python3
"""Exercise the actual native implementation with the fixed C2 triangle."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test(seed):
    seed = Path(seed).resolve()
    config = json.loads((seed / 'ss.json').read_text())
    triangle = next(t for t in config['cofseqs'] if t['name'] == 'S0__C2__S0')
    maps = {triangle[k] for k in ('i','q','d')}
    fixture = dict(config)
    fixture['rings'] = [x for x in config['rings'] if x['name'] == 'S0']
    fixture['modules'] = [x for x in config['modules'] if x['name'] == 'C2']
    fixture['maps'] = [x for x in config['maps'] if x['name'] in maps]
    fixture['maps_v2'] = [x for x in config['maps_v2'] if x['name'] in maps]
    fixture['cofseqs'] = [triangle]
    fixture['commutativity'] = []
    objects = ROOT / 'build/ss/CMakeFiles/ss.dir'
    backend = [p for p in sorted(objects.glob('*.cpp.o'))
               if p.name not in ('main.cpp.o','validated_syn.cpp.o')]
    executable = ROOT / 'build/bin/validated-syn-tests'
    subprocess.run(['c++','-std=c++20','-O2',
                    '-I'+str(ROOT/'include'),'-I'+str(ROOT/'ss'),
                    '-I'+str(ROOT/'thirdparty/fmt/include'),
                    '-I'+str(ROOT/'thirdparty/nlohmann_json'),
                    str(ROOT/'validation/tests/native_rules.cpp'),
                    *map(str,backend),str(ROOT/'build/src/libalgebras.a'),
                    str(ROOT/'build/thirdparty/sqlite3/libsqlite3.a'),
                    str(ROOT/'build/thirdparty/fmt/libfmt.a'),'-lpthread',
                    '-o',str(executable)],check=True)
    with tempfile.TemporaryDirectory(prefix='validated-syn-test-') as directory:
        directory = Path(directory)
        for section in ('rings','modules','maps','maps_v2'):
            for row in fixture[section]:
                if 'path' in row:
                    subprocess.run(['cp','--reflink=auto','--',str(seed/row['path']),
                                    str(directory/row['path'])],check=True)
        (directory/'ss.json').write_text(json.dumps(fixture))
        subprocess.run([str(executable),str(directory)],check=True,cwd=directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed',type=Path)
    test(parser.parse_args().seed)
