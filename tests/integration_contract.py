"""Run with owner .venv Python; all server records live in a temporary database."""
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime,timezone
from unittest.mock import patch

client_root=Path(__file__).resolve().parents[1]
owner_root=Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="azt-contract-") as folder:
    os.environ["GOLD_AI_DB_PATH"]=str(Path(folder)/"server.db")
    os.environ["GOLD_AI_STATE_DIR"]=folder
    os.environ["GOLD_AI_OWNER_TELEGRAM_ENABLED"]="false"
    os.environ["GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN"]=""
    os.environ["AZT_CLIENT_HOME"]=folder
    sys.path.insert(0,str(owner_root));sys.path.insert(0,str(client_root))
    sys.path.append(str(client_root/".venv/Lib/site-packages"))
    from server import store,azt_store
    from server.app import app
    from fastapi.testclient import TestClient
    from client.api import GoldAIServer
    from client.models import ClientProfile
    client,code=store.create_client("Contract client")
    azt_store.save_plan("STARTER",name="Starter",amount=20,currency="USD",duration_days=30,max_mt5_accounts=2)
    azt_store.edit_client(client.id,max_mt5_accounts=2)
    azt_store.renew_subscription(client.id,30,plan_code="STARTER",max_mt5_accounts=2)
    server=TestClient(app)
    profile=ClientProfile(pairing_code=code,server_url="https://testserver",mt5_login=123,mt5_server="Broker",display_timezone="Africa/Kampala")
    api=GoldAIServer(profile)
    def request(method,url,headers=None,timeout=None,**kwargs):
        return server.request(method,url.split("testserver",1)[1],headers=headers,**kwargs)
    with patch("client.api.httpx.request",side_effect=request):
        auth=api.authorize()
        assert auth.allowed and auth.session_token and auth.max_mt5_accounts==2,auth
        token=auth.session_token
        api.preferences(token,"Africa/Kampala")
        overview=api.overview(token)
        assert overview["allowed"] and overview["display_timezone"]=="Africa/Kampala",overview
        assert api.plans(token)["plans"][0]["code"]=="STARTER"
        assert len(api.payment_methods(token)["methods"])==8
        azt_store.send_message(client.id,"Welcome","Private in-app message",also_telegram=False)
        message=api.messages(token)["messages"][0]
        assert not message["read_utc"]
        api.mark_read(token,message["id"])
        assert api.messages(token)["messages"][0]["read_utc"]
        payment=api.submit_payment(token,"STARTER","USDT_TRC20",transaction_hash="a"*64)
        assert payment["status"]=="PENDING",payment
        assert api.payments(token)["payments"][0]["id"]==payment["id"]
        azt_store.review_payment(payment["id"],True)
        assert api.payments(token)["payments"][0]["status"]=="APPROVED"
        assert api.referrals(token)["code"]
        azt_store.save_promo("TEST-ACCESS",plan_code="STARTER",duration_days=1,max_redemptions=2,max_mt5_accounts=2)
        api.redeem(token,"TEST-ACCESS")
        now=datetime.now(timezone.utc).isoformat()
        api.telemetry(token,{"observed_utc":now,"account":{"login":123,"server":"Broker","currency":"USD","balance":100,"equity":102},
            "positions":[],"trades":[{"ticket":"17","position_id":"7","symbol":"XAUUSD.m","direction":"BUY","pnl":2,"closed_utc":now,"strategy":"TEST"}]})
        assert api.trades(token)["trades"][0]["pnl"]==2
        assert api.journal(token)["trades_taken"]==1
        assert api.next_instruction(token,now)["available"] is False
    server.close()
    print("Client/server contract passed: auth, expiry/preferences, plans/methods, in-app messages/read, pending/approved payments, promos/referrals, telemetry/trades/journal and no-backlog query. No MT5 or external network calls.")
