"""Source/frozen UI startup in a private profile, with all trading disabled."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="azt-client-smoke-") as folder:
    env={**os.environ,"AZT_CLIENT_HOME":folder,"PYTHONPATH":str(root)}
    command=[sys.executable,str(root/"app.py")] if "--source" in sys.argv else [os.getenv("AZT_TEST_EXE",str(root/"dist_azt/AZT_Client.exe"))]
    process=subprocess.run([*command,"--smoke-test"],env=env,cwd=root,capture_output=True,text=True,timeout=60)
    print(process.stdout)
    assert process.returncode==0,process.stderr
    assert not (Path(folder)/"execution_ledger.db").exists(),"UI smoke initialized execution"
    assert not (Path(folder)/"profile.json").exists(),"UI smoke modified settings"
    print("Client isolated EXE/source smoke passed; no MT5, server or order calls.")
