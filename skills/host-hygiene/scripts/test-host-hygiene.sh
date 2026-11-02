#!/usr/bin/env bash
# Exercise the real SSH launcher/remote script against disposable CLI fixtures.
# Imported from dotfiles scripts/test-host-hygiene.sh at
# c94f7fc746c325c8e987df084127ea63d45ca365; adapted only layout and synthetic names.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
python3 - "$repo_dir" <<'PY'
import copy
import datetime as datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(sys.argv[1])
class FixtureInfrastructureError(RuntimeError):
    pass

SOURCE = (ROOT / 'skills/host-hygiene/scripts/hygiene.py').read_text()
C, C2 = 'a' * 64, 'b' * 64
I = 'sha256:' + 'c' * 64
N, N2 = '/nix/store/' + 'd' * 32 + '-old', '/nix/store/' + 'e' * 32 + '-new'
K = 'k' * 25
OLD = '2020-01-01T00:00:00Z'
FIXTURE = r'''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys
from pathlib import Path
name = Path(sys.argv[0]).name
state_path = Path(os.environ['FIXTURE_STATE'])
s = json.loads(state_path.read_text())
a = sys.argv[1:]
def log():
    with open(os.environ['FIXTURE_LOG'], 'a') as f:
        f.write(json.dumps([name] + a) + '\n')
if name == 'ssh':
    command = shlex.split(a[-1])
    source = command[2]
    prelude = r"""import socket, os, json, sys, time, datetime, re
if os.environ.get('FIXTURE_LEGACY_TIME'):
    real_datetime=datetime.datetime
    class LegacyDatetime(real_datetime):
        @classmethod
        def fromisoformat(cls,value):
            if re.search(r'\.\d{7,}',value): raise ValueError('Python3.10 rejects nanosecond fraction')
            return real_datetime.fromisoformat(value)
    datetime.datetime=LegacyDatetime
real_clock=time.monotonic
clock_calls=0
def fixture_clock():
    global clock_calls
    if os.environ.get('FIXTURE_SCAN_TIMEOUT') and sys._getframe(1).f_code.co_name=='worktrees':
        clock_calls+=1
        return real_clock()+clock_calls*61
    return real_clock()
time.monotonic=fixture_clock
from pathlib import Path
from types import SimpleNamespace
socket.gethostname=lambda: 'buildhost0'
real_stat=os.stat
real_iter=Path.iterdir
real_lstat=Path.lstat
def fixture_lstat(self,*a,**kw):
    if os.environ.get('FIXTURE_NONREGULAR') and self.name=='compose.yml':
        return SimpleNamespace(st_mode=0o140777)
    return real_lstat(self,*a,**kw)
Path.lstat=fixture_lstat
def fixture_stat(path, *a, **kw):
    if str(path).startswith('/nix/store/'):
        state=json.loads(Path(os.environ['FIXTURE_STATE']).read_text())
        if str(path) not in state['nix']: raise FileNotFoundError(str(path))
        item=state['nix'][str(path)]
        return SimpleNamespace(st_dev=1, st_ino=item['inode'], st_mtime_ns=item['mtime']*1000000000, st_mtime=item['mtime'])
    return real_stat(path, *a, **kw)
os.stat=fixture_stat
Path.iterdir=lambda self: real_iter(Path(os.environ['FIXTURE_TMP'])) if str(self)=='/tmp' else real_iter(self)
"""
    p = subprocess.run([sys.executable, '-c', prelude + source, '--remote'], input=sys.stdin.read(), text=True)
    sys.exit(p.returncode)
if name == 'du':
    if '--files0-from=-' in a:
        p=subprocess.run([os.environ['FIXTURE_REAL_DU']]+a,input=sys.stdin.buffer.read(),capture_output=True)
        sys.stdout.buffer.write(p.stdout)
        if os.environ.get('FIXTURE_DU_PARTIAL'):
            print('partial du fixture',file=sys.stderr);sys.exit(1)
        sys.stderr.buffer.write(p.stderr);sys.exit(p.returncode)
    print('4096\t' + a[-1]); sys.exit()
if name == 'nix-store':
    if '--print-roots' in a: print('/owned-root -> /nix/store/'+'f'*32+'-live')
    elif '--print-dead' in a: print('\n'.join(k for k,v in s['nix'].items() if not v.get('live')))
    elif '--size' in a: print(s['nix'][a[-1]]['size'])
    elif '--delete' in a:
        log()
        if not s.get('nix_noop'):
            for path in a[1:]: s['nix'].pop(path,None)
            state_path.write_text(json.dumps(s))
    else: sys.exit(6)
    sys.exit()
if name == 'docker':
    if a[:2] == ['container','ls']: print('\n'.join(s['containers']))
    elif a[:2] == ['image','ls']: print('\n'.join(s['images']))
    elif a[:2] == ['volume','ls']: print('\n'.join(s['volumes']))
    elif a[0]!='buildx' and a[1:2] == ['inspect']:
        if s.get('inventory_error') and a[0]=='image':
            print('[{}]'); sys.exit()
        print(json.dumps([s[a[0]+'s'][a[-1]]]))
    elif a[1:2] == ['rm']:
        log()
        if s.get('delete_error') == a[-1]:
            print('fixture mutation failed', file=sys.stderr); sys.exit(8)
        if not s.get('delete_noop'): s[a[0]+'s'].pop(a[-1])
        state_path.write_text(json.dumps(s))
    elif a[:2]==['buildx','inspect']: print(s.get('backend','fixed-builder-endpoint'))
    elif a[:2]==['buildx','du']:
        print('\n'.join(json.dumps(v) for v in s.get('cache',{}).values() if not any(x.startswith('id=') and x[3:]!=v['ID'] for x in a)))
        if s.pop('cache_error',False):
           state_path.write_text(json.dumps(s)); print('{}')
    elif a[:2]==['buildx','prune']:
        log()
        target=next((x[3:] for x in a if x.startswith('id=')),None)
        if target is None: s['cache']={}
        else: s['cache'].pop(target,None)
        state_path.write_text(json.dumps(s))
    elif 'prune' in a: log()
    else: print('unsupported docker fixture '+repr(a),file=sys.stderr); sys.exit(7)
'''

def scenario(case, source):
    with tempfile.TemporaryDirectory(prefix='hygiene-test-') as directory:
        d = Path(directory)
        bin_dir = d / 'bin'; bin_dir.mkdir()
        fixture = bin_dir / 'fixture'; fixture.write_text(FIXTURE); fixture.chmod(0o755)
        for name in ('ssh','docker','nix-store','du'): (bin_dir / name).symlink_to(fixture)
        scripts = d / 'scripts'; scripts.mkdir()
        shutil.copy(ROOT / 'skills/host-hygiene/scripts/hygiene.sh', scripts)
        (scripts / 'hygiene.py').write_text(source)
        projects = d / 'Projects'; projects.mkdir()
        wt = projects / 'live'; wt.mkdir(); (wt / '.git').write_text('gitdir: unused')
        record = d / 'lanes.md'; record.write_text('paused peer keeps peer-image and peer-service')
        tmp = d / 'tmp'; tmp.mkdir(); oldtmp = tmp / 'peer-artifact'; oldtmp.write_text('keep me')
        os.utime(oldtmp, (0, 0))
        tmpdirs=[]
        if case in ('tmp-directory-estimate','tmp-directory-partial'):
            for name in ('space name','line\nbreak','-leading'):
                path=tmp/name;path.mkdir();(path/'data').write_bytes(b'x'*8192)
                os.utime(path,(0,0));tmpdirs.append(path)
        volume = d / 'volume'; volume.mkdir()
        def container(ident, name):
            return dict(Id=ident, Name='/'+name, Image='sha256:'+'9'*64,
                        Config=dict(Image='private:base',Labels={}), SizeRw=100,
                        State=dict(Status='exited',FinishedAt=OLD),Mounts=[])
        state = dict(containers={C:container(C,'owned-old')},images={},volumes={},
                     nix={N:dict(inode=1,mtime=int(time.time()),size=123)})
        policy = dict(projects_root=str(projects), records=[str(record)],
                      protected=['peer-service'], tmp_owner='peer-lane', builder='fixed',
                      claims=[dict(kind='container',id=ident,owner='lane',idle=True) for ident in (C,C2)])
        if case in ('cache','cache-shared','cache-protected','cache-unknown','cache-backend','cache-error'):
            state['cache']={K:dict(ID=K,Description='private-build',Size='4.096kB',LastUsedAt='4 days ago',CreatedAt='2026-09-01 12:00:00 +0000 UTC',Mutable=False,Shared=case=='cache-shared',Reclaimable=True)}
            if case!='cache-unknown': policy['claims'].append(dict(kind='cache',id=K,owner='lane',idle=True))
            if case=='cache-protected': policy['protected'].append(K)
        if case=='timestamp-nanos': state['containers'][C]['State']['FinishedAt']='2020-01-01T00:00:00.123456789-04:00'
        if case=='timestamp-offset': state['containers'][C]['State']['FinishedAt']=datetime.datetime.fromtimestamp(time.time()-23*3600,datetime.timezone(datetime.timedelta(hours=-4))).isoformat(timespec='microseconds')
        if case=='age': state['containers'][C]['State']['FinishedAt']='2999-01-01T00:00:00Z'
        if case=='running': state['containers'][C]['State']['Status']='running'
        if case in ('tag-release','shared-tag','cross-owner-release'):
            state['images'][I] = dict(Id=I,RepoTags=['private:old'],Created=OLD,Size=555,Config=dict(Labels={}))
            policy['claims'].append(dict(kind='image',id=I,owner='lane',idle=True,released_tags=['private:old'] if case=='tag-release' else []))
        if case=='cross-owner-release': policy['claims'].append(dict(kind='image',id=I,owner='peer',idle=False,released_tags=['private:old']))
        if case in ('used-volume','private-volume'):
            state['volumes']['private_chain'] = dict(Name='private_chain',Labels={'com.docker.compose.project':'private-stack'},Mountpoint=str(volume))
            policy['claims'].append(dict(kind='volume',id='private_chain',owner='lane',idle=True))
            if case=='used-volume': state['containers'][C]['Mounts']=[dict(Type='volume',Name='private_chain')]
        if case=='symlink-directory':
            external=d/'external'; external.mkdir(); (external/'compose.yml').write_text('container_name: owned-old')
            (projects/'paused').symlink_to(external,target_is_directory=True)
        if case=='complete-root':
            normal=projects/'paused'; normal.mkdir(); (normal/'compose.yml').write_text('container_name: different-peer')
        if case=='nonregular': (wt/'compose.yml').write_text('not a regular compose file')
        if case in ('missing-size','negative-size','boolean-size'):
            state['containers'][C]['SizeRw']={'missing-size':None,'negative-size':-1,'boolean-size':True}[case]
        if case=='docker-noop': state['delete_noop']=True
        if case=='nix-noop': state['nix_noop']=True
        if case=='partial-failure':
            state['containers'][C2]=container(C2,'second-owned'); state['delete_error']=C2
        statepath=d/'state.json'; policypath=d/'policy.json'; logfile=d/'calls.jsonl'; planpath=d/'plan.json'
        def save():
            statepath.write_text(json.dumps(state)); policypath.write_text(json.dumps(policy))
        save()
        env=dict(os.environ, PATH=str(bin_dir)+':'+os.environ['PATH'], FIXTURE_STATE=str(statepath),FIXTURE_LOG=str(logfile),FIXTURE_TMP=str(tmp),FIXTURE_REAL_DU=shutil.which('du'))
        if case=='tmp-directory-partial': env['FIXTURE_DU_PARTIAL']='1'
        if case=='timestamp-nanos': env['FIXTURE_LEGACY_TIME']='1'
        if case=='scan-timeout': env['FIXTURE_SCAN_TIMEOUT']='1'
        if case=='nonregular': env['FIXTURE_NONREGULAR']='1'
        def cli(mode, *extras):
            return subprocess.run([str(scripts/'hygiene.sh'),mode,'buildhost0.local',str(planpath),'--policy',str(policypath),*extras],text=True,capture_output=True,env=env)
        planned=cli('plan')
        if planned.returncode!=0: raise FixtureInfrastructureError('initial plan execution failed: '+planned.stderr)
        plan=json.loads(planpath.read_text())
        if case=='exact-list':
            state['containers'][C2]=container(C2,'newly-eligible'); state['nix'][N2]=dict(inode=2,mtime=0,size=222)
        elif case=='identity': state['containers'][C]['Name']='/changed-name'
        elif case=='cache-backend': state['backend']='replaced-builder-endpoint'
        elif case=='cache-error': state['cache_error']=True
        elif case=='ownership': policy['claims']=[]
        elif case=='missing-record': record.unlink()
        elif case=='compose-reference': (wt/'compose.yml').write_text('services:\n  peer:\n    container_name: owned-old\n')
        elif case=='inventory-error':
            state['images'][I]=dict(Id=I); state['inventory_error']=True
        elif case=='new-root': state['nix'][N]['live']=True
        elif case in ('host-mismatch','uid-mismatch'):
            plan['machine' if case=='host-mismatch' else 'uid']='other-host' if case=='host-mismatch' else -1
            planpath.write_text(json.dumps(plan))
        elif case=='tmp-owner':
            for e in plan['entries']:
                if e['kind']=='tmp': e['eligible']=True; e['owner']='lane'
            plan['tmp_owner']='released'; planpath.write_text(json.dumps(plan))
        elif case=='nix-independent': policy['projects_root']=str(d/'missing-project-root')
        save()
        checksum=hashlib.sha256(planpath.read_bytes()).hexdigest()
        applied=cli('apply','--owner','lane','--reviewed-sha256','bad-digest' if case=='digest' else checksum)
        calls=[json.loads(line) for line in logfile.read_text().splitlines()] if logfile.exists() else []
        removed=[c[-1] for c in calls if c[0]=='docker' and c[2]=='rm']
        nremoved=[p for c in calls if c[:2]==['nix-store','--delete'] for p in c[2:]]
        if case=='digest':
            assert applied.returncode!=0 and not calls,'digest accepted'
        elif case in ('host-mismatch','uid-mismatch'):
            assert applied.returncode!=0 and not calls,'host/user mismatch accepted'
        elif case in ('docker-noop','nix-noop'):
            assert applied.returncode!=0,'no-op delete reported success'
            response=json.loads(applied.stdout)
            assert any(r['kind']==('container' if case=='docker-noop' else 'nix') and r['action']=='failed' for r in response['results']),'missing failed absence receipt'
        elif case=='partial-failure':
            assert applied.returncode!=0, 'failure reported success'
            response=json.loads(applied.stdout)
            assert any(r['id']==C and r['action']=='deleted' for r in response['results']), 'lost prior success receipt'
            assert any(r['id']==C2 and r['action']=='failed' for r in response['results']), 'lost failure receipt'
            assert not nremoved,'continued after failure'
        else:
            if applied.returncode!=0: raise FixtureInfrastructureError('unexpected apply execution failed: '+applied.stderr)
            response=json.loads(applied.stdout)
            if case=='exact-list':
                final=json.loads(statepath.read_text())
                assert removed==[C] and nremoved==[N] and C not in final['containers'] and C2 in final['containers'] and N not in final['nix'] and N2 in final['nix'], 'deleted outside saved list or no absence proof'
            elif case in ('identity','age','running','ownership','missing-record','compose-reference','inventory-error','scan-timeout','nonregular','missing-size','negative-size','boolean-size','symlink-directory','timestamp-offset'):
                assert C not in removed, 'deleted protected/changed container'
            elif case=='new-root': assert not nremoved, 'deleted newly rooted store path'
            elif case=='nix-independent': assert nremoved==[N], 'compose failure blocked independent Nix graph'
            elif case=='tmp-owner':
                tmpresults=[r for r in response['results'] if r['kind']=='tmp']
                assert tmpresults and all(r['action']=='retained' and 'current owner=peer-lane' in r['reason'] for r in tmpresults),'current /tmp owner not honored'
                assert oldtmp.read_text()=='keep me','peer file deleted'
            elif case in ('shared-tag','cross-owner-release'): assert I not in removed, 'shared tag deleted without release'
            elif case=='tag-release': assert I in removed, 'released private old tag not usable'
            elif case=='used-volume': assert 'private_chain' not in removed,'referenced volume deleted'
            elif case=='timestamp-nanos': assert C in removed,'nanosecond timestamp not compatible with legacy parser'
            elif case=='complete-root': assert C in removed,'complete nonsymlink root blocked ordinary candidate'
            elif case=='private-volume': assert 'private_chain' in removed,'private unreferenced compose volume not usable'
            elif case in ('tmp-directory-estimate','tmp-directory-partial'):
                records=[e for e in plan['entries'] if e['id'] in {str(p) for p in tmpdirs}]
                assert len(records)==len(tmpdirs) and all(not e['eligible'] for e in records),'directory entries omitted or eligible'
                assert all(e['size_exact'] is False for e in records),'directory estimates labeled exact'
                if case=='tmp-directory-partial':
                    assert all(e['bytes'] is None and 'partial du fixture' in e['reason'] for e in records),'failed directory sizes trusted or evidence omitted'
                else:
                    assert all(type(e['bytes']) is int and e['bytes']>=8192 for e in records),'real directory measurement absent'
                assert oldtmp.read_text()=='keep me' and all(p.exists() for p in tmpdirs),'tmp fixture deleted'
            elif case=='tmp-size':
                assert next(e['bytes'] for e in plan['entries'] if e['id']==str(oldtmp))==oldtmp.stat().st_blocks*512,'tmp allocated size not measured'
            elif case=='cache':
                prunes=[c for c in calls if c[:3]==['docker','buildx','prune']]
                assert len(prunes)==1 and 'id='+K in prunes[0] and all(f in prunes[0] for f in ('until=72h','private=true','inuse=false','immutable=true')),'missing exact cache safety filters'
                assert any(r['kind']=='cache' and r['action']=='deleted' for r in response['results']),'missing verified cache deletion receipt'
            elif case in ('cache-shared','cache-protected','cache-unknown','cache-backend','cache-error'):
                assert not any(c[:3]==['docker','buildx','prune'] for c in calls),'protected/unknown cache pruned'
            elif case=='nix-age': assert N in nremoved, 'normalized store time treated as installation age'

# These cases invoke actual GNU du in isolated state-directory fixtures. Injected
# output failures are derived from a successful real invocation, never a fake size.
def directory_scenario(case, source):
    from types import SimpleNamespace
    namespace = {"__name__": "fixture_module"}
    exec(compile(source, "hygiene-fixture", "exec"), namespace)
    with tempfile.TemporaryDirectory(prefix="hygiene-du-") as directory:
        root = Path(directory)
        paths = [root / name for name in ("space name", "line\nbreak", "-leading", "tab\tname")]
        paths.append(Path(os.fsdecode(os.fsencode(root) + b"/invalid-\xff")))
        for path in paths:
            path.mkdir()
            (path / "data").write_bytes(b"x" * 8192)
        outside = root / "outside"; outside.mkdir()
        (outside / "large").write_bytes(b"y" * 65536)
        (paths[0] / "symlink").symlink_to(outside, target_is_directory=True)
        os.link(paths[0] / "data", paths[1] / "cross-root-link")
        os.link(paths[0] / "data", paths[0] / "within-root-link")
        if case == "batch-bound":
            for index in range(257):
                path = root / ("extra-" + str(index)); path.mkdir(); paths.append(path)
        if case == "path-alias":
            real_operand = paths[0]
            alias = root / "alias"; alias.symlink_to(root, target_is_directory=True)
            paths[0] = alias / real_operand.name
        calls = []
        real_run = subprocess.run
        def measured_run(args, **kw):
            if not kw.get("input", b"").endswith(b"\0"):
                raise FixtureInfrastructureError("du fixture input was not NUL terminated")
            names = kw["input"][:-1].split(b"\0")
            calls.append(names)
            result = real_run(args, **kw)
            if result.returncode != 0:
                raise FixtureInfrastructureError("actual GNU du fixture failed: " + repr(result.stderr))
            if case == "partial":
                result.returncode = 1; result.stderr = b"permission denied fixture"
            elif case == "stderr": result.stderr = b"warning fixture"
            elif case == "large-stderr": result.stderr = b"x" * 1048576
            elif case == "missing": result.stdout = result.stdout.split(b"\0", 1)[1]
            elif case == "duplicate": result.stdout += result.stdout.split(b"\0", 1)[0] + b"\0"
            elif case == "unexpected": result.stdout += b"99\t/unrequested\0"
            elif case == "negative": result.stdout = b"-" + result.stdout
            elif case == "unterminated": result.stdout = result.stdout[:-1]
            elif case == "timeout": raise subprocess.TimeoutExpired(args, kw["timeout"], output=result.stdout)
            elif case == "identity": (paths[0] / "new-child").write_text("changed")
            return result
        namespace["subprocess"] = SimpleNamespace(run=measured_run, TimeoutExpired=subprocess.TimeoutExpired)
        if case in ("mount", "mount-change", "mountinfo-error", "path-alias"):
            class FixturePath(type(Path())):
                reads = 0
                def read_bytes(self):
                    if str(self) != "/proc/self/mountinfo": return super().read_bytes()
                    FixturePath.reads += 1
                    if case == "mountinfo-error": return b"unsupported record"
                    if case == "path-alias":
                        encoded = os.fsencode(real_operand / "bind").replace(b" ", b"\\040")
                        return b"1 0 0:1 / " + encoded + b" rw - tmpfs tmpfs rw\n"
                    if case == "mount" or FixturePath.reads > 1:
                        encoded = os.fsencode(paths[0]).replace(b" ", b"\\040")
                        return b"1 0 0:1 / " + encoded + b" rw - tmpfs tmpfs rw\n"
                    return b""
            namespace["Path"] = FixturePath
        if case == "budget":
            ticks = iter([0, 61, 62])
            namespace["time"] = SimpleNamespace(monotonic=lambda: next(ticks, 63))
        sizes, errors = namespace["directory_sizes"](paths)
        unavailable = ("partial", "stderr", "large-stderr", "missing", "duplicate", "unexpected", "negative",
                       "unterminated", "timeout", "identity", "mount-change", "mountinfo-error", "budget")
        if case in unavailable:
            assert not sizes and set(errors) == {str(p) for p in paths}, "failed batch trusted or lost entries"
            if case == "large-stderr":
                assert all("stderr_bytes=1048576" in e for e in errors.values()), "stderr byte count omitted"
                assert len(json.dumps(errors)) < 8192 * len(paths), "stderr amplification unbounded"
            if case == "partial":
                assert all("permission denied fixture" in e and "partial stdout" in e for e in errors.values()), "partial evidence omitted"
            if case in ("budget", "mount-change", "mountinfo-error"):
                assert not calls, "du ran despite unavailable mount coverage/budget"
        elif case in ("mount", "path-alias"):
            assert str(paths[0]) in errors and str(paths[0]) not in sizes, "mount traversed"
            assert all(os.fsencode(paths[0]) not in names for names in calls), "mount reached du"
        else:
            assert not errors and set(sizes) == {str(p) for p in paths}, "NUL path coverage incomplete"
            for path in paths:
                expected = real_run(["du", "-s", "-B1", "-P", "-x", "-l", "-0", "--", str(path)], capture_output=True, check=True)
                assert sizes[str(path)] == int(expected.stdout.partition(b"\t")[0]), "wrong allocated estimate or followed symlink"
            dedup = real_run(["du", "-s", "-B1", "--", str(paths[0])], capture_output=True, check=True)
            assert sizes[str(paths[0])] > int(dedup.stdout.partition(b"\t")[0]), "hardlink estimate not distinguished"
            if case == "batch-bound":
                assert len(calls) == 2 and max(map(len, calls)) <= 256, "batch not bounded"

DIRECTORY_MUTANTS = {
    "names-hardlinks": [("\"--count-links\"", "\"--dereference\"")],
    "batch-bound": [("range(0, len(paths), 256)", "range(0, len(paths), 512)"), ("paths[offset:offset + 256]", "paths[offset:offset + 512]")],
    "partial": [("if result.returncode or result.stderr:", "if result.stderr and not result.returncode:")],
    "stderr": [("if result.returncode or result.stderr:", "if result.returncode:")],
    "large-stderr": [("result.stderr[:512]", "result.stderr")],
    "path-alias": [("if not path.is_absolute() or path.resolve(strict=True) != path:", "if False:")],
    "missing": [("if set(measured) != set(batch):", "if False:")],
    "duplicate": [("or name in measured", "or False")],
    "unexpected": [("or name not in before", "or False"), ("if set(measured) != set(batch):", "if False:")],
    "negative": [("rb\"[0-9]+\", amount", "rb\"-?[0-9]+\", amount")],
    "unterminated": [("if not result.stdout.endswith(b\"\\0\"):", "if False:"), ("result.stdout[:-1].split(b\"\\0\")", "result.stdout.rstrip(b\"\\0\").split(b\"\\0\")")],
    "timeout": [("errors[os.fsdecode(name)] = \"directory measurement unavailable: \" + str(exc)", "if not isinstance(exc, subprocess.TimeoutExpired): errors[os.fsdecode(name)] = str(exc)")],
    "identity": [("if identity(Path(os.fsdecode(name))) != before[name]:", "if False:")],
    "mount": [("if any(m == name or m.startswith(name + b\"/\") for m in original_mounts):", "if False:")],
    "mount-change": [("if mounts() != original_mounts:", "if False:")],
    "mountinfo-error": [("raise RuntimeError(\"unsupported mountinfo record\")", "continue")],
    "budget": [("deadline = time.monotonic() + 60", "deadline = time.monotonic() + 600")],
}
for case, replacements in DIRECTORY_MUTANTS.items():
    directory_scenario(case, SOURCE)
    changed = SOURCE
    for before, after in replacements:
        assert before in changed, (case, "directory mutant anchor missing", before)
        changed = changed.replace(before, after)
    compile(changed, "directory-mutant-" + case, "exec")
    try:
        directory_scenario(case, changed)
    except AssertionError as exc:
        print("PASS directory-" + case + "; mutant KILLED: " + str(exc).splitlines()[0])
    else:
        raise AssertionError(case + ": directory mutant survived")
print("PASS: " + str(len(DIRECTORY_MUTANTS)) + " GNU-du directory cases, each with failing mutant")

# Every case below runs once on production source and once on a failing mutant.
MUTANTS = {
 'tmp-directory-estimate': [('entries[-1]["size_exact"] = not directory', 'entries[-1]["size_exact"] = True')],
 'tmp-directory-partial': [('sizes.get(str(path)) if directory', 'sizes.get(str(path), 0) if directory')],
'exact-list': [('for entry in plan["entries"]:', 'for entry in fresh["entries"]:')],
'digest': [('hashlib.sha256(raw).hexdigest() != args.reviewed_sha256','False')],
'identity': [('new["identity"] == entry["identity"]','True'),('digest(identity) != new["identity"]','False')],
'age': [('old = exited and now - timestamp(c["State"]["FinishedAt"]) > DAY','old = True')],
'running': [('exited = c["State"]["Status"] == "exited"','exited = True')],
'ownership': [('return matches[0]["owner"] if len(matches) == 1 and matches[0].get("idle") is True and matches[0].get("owner") else None','return "lane"')],
'missing-record': [('not record_errors if kind == "nix" else reference_ok','True')],
'compose-reference': [('and not mentioned(tokens)','and True')],
'inventory-error': [('        for entry in entries:\n            entry["eligible"] = False','        for entry in entries:\n            pass')],
'new-root': [('        dead = run("nix-store", "--gc", "--print-dead").splitlines()','        dead = ["'+N+'"]'),('dead = set(run("nix-store", "--gc", "--print-dead").splitlines())','dead = {"'+N+'"}')],
'nix-independent': [('not record_errors if kind == "nix" else reference_ok','reference_ok')],
'nix-age': [('True, "dead graph member; daemon rechecks liveness (store mtime is not installation age)"','now - st.st_mtime > 14 * DAY, "dead graph member"')],
'tmp-owner': [('str(fresh["tmp_owner"])','str(plan["tmp_owner"])')],
'timestamp-nanos': [('fraction[:6].ljust(6, "0")','fraction.ljust(6, "0")')],
'timestamp-offset': [('zone = "+00:00" if zone == "Z" else zone','zone = "+00:00"')],
'cross-owner-release': [('matches = [c for c in claims if c.get("kind") == kind and c.get("id") == ident]', 'matches = [c for c in claims if c.get("kind") == kind and c.get("id") == ident and c.get("idle") is True and c.get("owner")]')],
'shared-tag': [('(not tags or (old and release))','(not tags or old)')],
'tag-release': [('(not tags or (old and release))','not tags')],
'used-volume': [('project and name not in used_volumes and owner','project and owner')],
'cache': [('"--filter", "id=" + ident, "--filter", "until=72h",','"--filter", "until=72h",')],
'cache-shared': [('cache["Shared"] is False and cache["Mutable"] is False','cache["Mutable"] is False')],
'cache-protected': [('and not mentioned(tokens)','and True')],
'cache-unknown': [('return matches[0]["owner"] if len(matches) == 1 and matches[0].get("idle") is True and matches[0].get("owner") else None','return "lane"')],
'cache-backend': [('new["identity"] == entry["identity"]','True')],
'cache-error': [('if entry["kind"] == "cache":\n                entry["eligible"] = False','if entry["kind"] == "cache":\n                pass')],
'missing-size': [('eligible and valid_size and','eligible and')],
'negative-size': [('type(bytes_) is int and bytes_ >= 0','type(bytes_) is int')],
'boolean-size': [('type(bytes_) is int and bytes_ >= 0','isinstance(bytes_,int) and bytes_ >= 0')],
'private-volume': [('project and name not in used_volumes and owner','False and project and name not in used_volumes and owner')],
'host-mismatch': [('plan["machine"] != fresh["machine"]','False')],
'uid-mismatch': [('plan["uid"] != fresh["uid"]','False')],
'tmp-size': [('st.st_blocks * 512','st.st_size')],
'symlink-directory': [('if (Path(directory) / name).is_symlink():', 'if False:')],
'complete-root': [('if not root.is_absolute() or root.is_symlink() or not root.is_dir():', 'if True:')],
'scan-timeout': [('if time.monotonic() > deadline:', 'if False:')],
'nonregular': [('if not stat.S_ISREG(path.lstat().st_mode):','if False:')],
'docker-noop': [('if ident in remaining:', 'if False:')],
'nix-noop': [('raise RuntimeError("Nix delete returned success but exact store path remains: " + path)', 'results.append(dict(kind="nix", id=path, action="deleted"))')],
'partial-failure': [('                response["status"] = "failed"\n                return response','                response["status"] = "failed"\n                response["results"] = []\n                return response')],
}
for case,replacements in MUTANTS.items():
    scenario(case,SOURCE)
    changed=SOURCE
    for before,after in replacements:
        assert before in changed,(case,'mutant anchor missing',before)
        changed=changed.replace(before,after)
    try:
        compile(changed,'mutant-'+case,'exec')
    except SyntaxError as exc:
        raise FixtureInfrastructureError('mutant does not compile: '+case) from exc
    try:
        scenario(case,changed)
    except AssertionError as exc:
        print('PASS '+case+'; mutant KILLED: '+str(exc).splitlines()[0])
    else:
        raise AssertionError(case+': mutant survived')
print('PASS: '+str(len(MUTANTS))+' real-script fixture cases, each with failing mutant')
PY
