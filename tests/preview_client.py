"""Private UI review only; no account, API requests or execution workers."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='azt-client-preview-') as folder:
    os.environ['AZT_CLIENT_HOME']=folder
    from app import GoldAIClientApp
    app=GoldAIClientApp(smoke=True)
    app.title('AZT Client • ISOLATED UI PREVIEW')
    app.status.set('ISOLATED PREVIEW — no server, MT5 account or trading worker enabled.')
    app.after(180000,app.on_close)
    app.mainloop()
