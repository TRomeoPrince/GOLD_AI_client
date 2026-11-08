"""Run with owner .venv Python; all server records live in a temporary database."""
import os
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import Mock,patch

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
    from server import store,azt_store,trial_licenses
    from server.app import app
    from fastapi.testclient import TestClient
    from client.api import ClientAccessRevoked,GoldAIServer
    from client import executor,runtime
    from client.ledger import Ledger
    from client.models import ClientProfile
    import httpx
    from client.telemetry import capture_mt5
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
            "positions":[],"trades":[{"ticket":"17","position_id":"7","symbol":"XAUUSD.m","direction":"BUY","pnl":2,"closed_utc":now,"strategy":"TEST"}],
            "history_sync":"OK","history_window_failures":0})
        assert api.trades(token)["trades"][0]["pnl"]==2
        assert api.journal(token)["trades_taken"]==1
        assert api.next_instruction(token,now)["available"] is False

        # Post the real Client capture format from an already attached MT5 mock.
        # A history-only failure must preserve prior closes and refresh positions.
        mt5=Mock(POSITION_TYPE_BUY=0)
        mt5.account_info.return_value=SimpleNamespace(login=123,server="Broker",currency="USD",balance=100,equity=101)
        mt5.terminal_info.return_value=SimpleNamespace(connected=True)
        mt5.positions_get.return_value=[SimpleNamespace(ticket=18,symbol="XAUUSD.m",type=0,volume=.01,
            price_open=2000,price_current=2001,sl=1995,tp=2010,profit=1,swap=0,time=datetime.now(timezone.utc).timestamp(),comment="AZT:TEST")]
        mt5.history_deals_get.return_value=None
        api.telemetry(token,capture_mt5(mt5))
        trades=api.trades(token)
        assert [row["ticket"] for row in trades["positions"]]==["18"],trades
        assert [row["ticket"] for row in trades["trades"]]==["17"],trades
        assert trades["accounts"][0]["history_sync"]=="UNAVAILABLE",trades
        assert trades["accounts"][0]["history_window_failures"]==2,trades
        assert trades["accounts"][0]["history_last_success_utc"]==now,trades
        mt5.initialize.assert_not_called()
        mt5.order_send.assert_not_called()

        # Exercise actual recovery, durable owner reservation, Client risk
        # approval, mock broker submission and ACK through the real API.
        account = {"id":"contract","mt5_login":123,"mt5_server":"Broker","desired_running":True}
        stop = threading.Event()
        ledger = Ledger(Path(folder)/"execution_ledger.db")
        states = []
        deliveries = []
        polls = [0]
        waits = [0]

        def report(**state):
            states.append(state)
            if state.get("message", "").startswith("EXECUTED:"):
                stop.set()

        def bounded_wait(_delay):
            waits[0] += 1
            if waits[0] >= 6:
                stop.set()
            return stop.is_set()

        def payload():
            return json.dumps({"setup_time":runtime.utc_now(),"market":"GOLD","direction":"BUY",
                               "stop_loss":1995,"take_profit":2010,"strategy_id":"CONTRACT"})

        def recovering_request(method, url, **kwargs):
            path = url.split("testserver",1)[1]
            if path == "/v1/instructions/next":
                polls[0] += 1
                if polls[0] == 1:
                    raise httpx.RemoteProtocolError("simulated owner outage")
                if polls[0] == 2:
                    assert store.enqueue_instruction(client.id,"contract-fresh",payload())
                response = request(method,url,**kwargs)
                if response.json().get("available"):
                    deliveries.append(response.json())
                return response
            if path == "/v1/client/authorize":
                assert store.enqueue_instruction(client.id,"contract-backlog",payload())
            return request(method,url,**kwargs)

        broker = Mock(ORDER_TYPE_BUY=0,TRADE_ACTION_DEAL=1,ORDER_TIME_GTC=0,
                      ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,ORDER_FILLING_RETURN=2,
                      TRADE_RETCODE_DONE=10009,TRADE_RETCODE_DONE_PARTIAL=10010)
        broker.account_info.return_value = SimpleNamespace(login=123,server="Broker",equity=1000,
                                                            balance=1000,currency="USC",trade_allowed=True,trade_expert=True)
        broker.terminal_info.return_value = SimpleNamespace(connected=True,trade_allowed=True,tradeapi_disabled=False)
        broker.symbol_info_tick.side_effect = lambda _symbol: SimpleNamespace(ask=2000,bid=1999.9,time=time.time())
        broker.symbol_info.return_value = SimpleNamespace(volume_min=.01,volume_max=1,volume_step=.01,filling_mode=1)
        broker.history_deals_get.return_value = []
        broker.positions_get.return_value = []
        broker.order_calc_profit.side_effect = lambda _side,_symbol,volume,_entry,_sl: -500*volume
        broker.order_check.return_value = SimpleNamespace(retcode=0)
        broker.order_send.return_value = SimpleNamespace(retcode=10009,order=12345,comment="mock execution")
        worker = runtime.ClientRuntime(profile,account,stop,api=api,ledger=ledger,report=report)
        worker.clock = SimpleNamespace(offset_seconds=0)
        worker.token = token
        worker.last_telemetry = time.time()
        with patch("client.api.httpx.request",side_effect=recovering_request),patch.object(stop,"wait",side_effect=bounded_wait),patch.object(runtime,"mt5",broker),patch.object(executor,"mt5",broker),patch.object(executor,"_resolve_symbol",return_value="XAUUSD.m"),patch.object(executor,"tick_utc_epoch",side_effect=lambda _api,_symbol,tick:tick.time):
            worker.run()
            assert deliveries and len(deliveries)==1 and deliveries[0]["signal_key"]=="contract-fresh", deliveries
            broker.order_send.assert_called_once()
            assert broker.order_send.call_args.args[0]["volume"]==.01,broker.order_send.call_args
            worker.process(deliveries[0])
            broker.order_send.assert_called_once()
        assert [row["state"] for row in states if row["state"] in {"RECONNECTING","RECOVERED"}]==["RECONNECTING","RECOVERED"],states
        saved, = azt_store.instruction_deliveries(client.id)
        assert saved["status"]=="EXECUTED" and saved["signal_key"]=="contract-fresh",saved
        assert not ledger.pending_acks(worker.key)
        broker.initialize.assert_not_called()

        # Both EXEs use this same authorization flow. Expiry is enforced by the
        # owner server even for a token obtained before the 30-day deadline.
        trial,trial_code=store.create_client("Trial contract client")
        trial_licenses.issue(trial.id)
        trial_api=GoldAIServer(ClientProfile(pairing_code=trial_code,server_url="https://testserver",mt5_login=321,mt5_server="Broker"))
        trial_auth=trial_api.authorize()
        assert trial_auth.allowed and trial_auth.status=="TRIAL",trial_auth
        lease=trial_api.overview(trial_auth.session_token)["subscription"]
        expiry=datetime.fromisoformat(lease["expires_utc"])
        assert expiry-datetime.fromisoformat(lease["starts_utc"])==timedelta(days=30),lease
        second=trial_api.authorize()
        assert trial_api.overview(second.session_token)["subscription"]["expires_utc"]==lease["expires_utc"]
        with patch("server.trial_licenses._now",return_value=expiry):
            assert not trial_api.authorize().allowed
            try:
                trial_api.next_instruction(second.session_token)
            except ClientAccessRevoked:
                pass
            else:
                raise AssertionError("Expired distributor trial received trading access")
    server.close()
    print("Client/server contract passed: authorization, payments, referrals, history recovery, trial expiry, outage recovery, fresh reservation, mock execution, acknowledgment and duplicate suppression. No live MT5 or external network calls.")
