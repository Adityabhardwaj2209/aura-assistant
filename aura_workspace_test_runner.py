"""Explicitly reviewed tests in a temporary subprocess, NOT an OS security sandbox."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
from aura_workspace_tools import text,validate_python

TIMEOUT_SECONDS=15

RUNNER='''import sys,os,unittest
sys.stdout.reconfigure(encoding="utf-8",errors="replace")
sys.stderr.reconfigure(encoding="utf-8",errors="replace")
sys.path.insert(0,os.getcwd())
suite=unittest.defaultTestLoader.discover(".",pattern="test_candidate.py")
count=suite.countTestCases()
if not count:
 print("No test cases discovered");sys.exit(2)
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''


def run_reviewed(source,tests,reviewed=False):
    if reviewed is not True:raise ValueError('Review source and tests and explicitly enable test execution first')
    source=text(source,100000,False);tests=text(tests,50000)
    for value in (source,tests):
        if not validate_python(value)['ok']:raise ValueError('Fix Python syntax before running tests')
    with tempfile.TemporaryDirectory(prefix='aura_reviewed_tests_') as folder:
        root=Path(folder);(root/'candidate.py').write_text(source,encoding='utf-8');(root/'test_candidate.py').write_text(tests,encoding='utf-8')
        # No provider keys or other parent environment secrets are inherited.
        env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP')}
        proc=subprocess.Popen([sys.executable,'-I','-c',RUNNER],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        output=bytearray();limited=threading.Event()
        def collect():
            try:
                while True:
                    chunk=proc.stdout.read(1024)
                    if not chunk:break
                    room=64000-len(output);output.extend(chunk[:max(0,room)])
                    if len(chunk)>room:limited.set();proc.kill();break
            except (OSError,ValueError):pass
        thread=threading.Thread(target=collect,daemon=True);thread.start();timed_out=False
        try:proc.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:timed_out=True;proc.kill();proc.wait(timeout=3)
        thread.join(timeout=2)
        proc.stdout.close()
        return {'passed':proc.returncode==0 and not timed_out and not limited.is_set(),'exit_code':proc.returncode,'timed_out':timed_out,'output_limited':limited.is_set(),'output':output.decode('utf-8','replace'),'isolation':'Temporary working folder and separate Python process only. Not an OS security sandbox; reviewed code has your user-account permissions.'}
