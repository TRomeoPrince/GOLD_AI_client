from dataclasses import replace
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from client import executor,runtime,storage
from client.api import GoldAIServer,ClientAccessRevoked,SessionExpired,ServerUnavailable
from client.ledger import Ledger
from client.models import ClientProfile,AuthorizationResult
from client.symbols import resolve_symbol
from client.timezones import display_time,valid_zone

class Stop:
    def __init__(self):self.flag=False;self.waits=[]
    def is_set(self):return self.flag
    def set(self):self.flag=True
    def wait(self,delay):self.waits.append(delay);return self.flag

class SymbolTests(unittest.TestCase):
    def api(self,names):
        api=Mock()
        api.symbols_get.return_value=[NS(name=name) for name in names]
        api.symbol_info.side_effect=lambda name:NS(visible=True,volume_min=.01,volume_max=100,volume_step=.01,
                trade_contract_size=100,point=.01,trade_mode=4,currency_base="XAU",currency_profit="USD",path="Metals")
        return api
    def test_owner_suffix_is_never_required_on_client_broker(self):
        for local in ("XAUUSD.m","XAUUSD.a","XAUUSD","GOLD","GOLD.pro","m.XAUUSD"):
            with self.subTest(local=local):self.assertEqual(resolve_symbol(self.api([local]),"XAUUSD.c"),local)
    def test_other_gold_currencies_and_disabled_contracts_are_rejected(self):
        with self.assertRaises(RuntimeError):resolve_symbol(self.api(["XAUEUR","GOLDINDEX"]),"GOLD")
        api=self.api(["XAUUSD"]);api.symbol_info.side_effect=lambda _:NS(trade_mode=0)
        with self.assertRaises(RuntimeError):resolve_symbol(api,"GOLD")
    def test_contract_specs_must_be_positive(self):
        api=self.api(["XAUUSD"]);api.symbol_info.side_effect=lambda _:NS(volume_step=0)
        with self.assertRaises(RuntimeError):resolve_symbol(api,"GOLD")

class StorageAndTimeTests(unittest.TestCase):
    def test_initial_start_persists_desired_before_any_server_authorization(self):
        from app import GoldAIClientApp
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,"PROFILE_PATH",Path(folder)/"profile.json"):
            account={"id":"account","mt5_login":123,"mt5_server":"Broker","desired_running":False}
            fake=NS(profile=ClientProfile(accounts=[account]),manager=Mock(),status=Mock(),save=Mock(return_value=True),connect=Mock())
            fake.account=lambda:account
            fake._start_selected=lambda:GoldAIClientApp._start_selected(fake)
            with patch.object(runtime,"execute_instruction") as execute:
                GoldAIClientApp.start(fake)
            self.assertTrue(storage.load_profile().accounts[0]["desired_running"])
            fake.manager.start.assert_called_once_with(account)
            fake.connect.assert_not_called();execute.assert_not_called()
    def test_safety_disable_cannot_be_undone_by_stale_ui_profile_save(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,"PROFILE_PATH",Path(folder)/"profile.json"):
            profile=ClientProfile(accounts=[{"id":"first","desired_running":True},{"id":"second","desired_running":True}])
            storage.save_profile(profile)
            storage.set_desired_state("first",False)
            storage.save_profile(profile)  # Cached UI still had True.
            current=storage.load_profile()
            self.assertFalse(current.accounts[0]["desired_running"])
            self.assertTrue(current.accounts[1]["desired_running"])
    def test_only_one_workspace_can_own_a_profile_lock(self):
        from client.instance import acquire
        with tempfile.TemporaryDirectory() as folder:
            first=acquire(Path(folder)/".client.lock")
            try:
                with self.assertRaises(RuntimeError):acquire(Path(folder)/".client.lock")
            finally:first.close()
            acquire(Path(folder)/".client.lock").close()
    def test_legacy_profile_migrates_without_resetting_custom_server(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,"PROFILE_PATH",Path(folder)/"profile.json"):
            storage.PROFILE_PATH.write_text(json.dumps({"pairing_code":"code","mt5_login":123,"server_url":"https://owner.example"}))
            profile=storage.load_profile()
            self.assertEqual((profile.server_url,profile.mt5_login),("https://owner.example",123));self.assertEqual(profile.display_timezone,"UTC")
    def test_desired_state_is_persisted_per_account(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,"PROFILE_PATH",Path(folder)/"profile.json"):
            profile=ClientProfile(accounts=[{"id":"one","desired_running":True},{"id":"two","desired_running":False}])
            storage.save_profile(profile)
            self.assertTrue(storage.load_profile().accounts[0]["desired_running"]);self.assertFalse(storage.load_profile().accounts[1]["desired_running"])
    def test_atomic_profile_retries_permission_lock_and_preserves_complete_json(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage.os,"replace",side_effect=[PermissionError("lock"),None]) as replace_file,patch("time.sleep"):
            storage.atomic_json(Path(folder)/"profile.json",{"value":123})
            self.assertEqual(replace_file.call_count,2)
    def test_utc_display_converts_and_handles_london_dst(self):
        self.assertIn("11:00",display_time("2026-10-26T08:00:00+00:00","Africa/Kampala"))
        self.assertIn("09:00",display_time("2026-07-26T08:00:00+00:00","Europe/London"))
        self.assertIn("08:00",display_time("2026-12-26T08:00:00+00:00","Europe/London"))
        self.assertEqual(valid_zone("EAT"),"Africa/Kampala")

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.terminal=Path(self.folder.name)/"terminal64.exe";self.terminal.touch()
        desired_patch=patch.object(storage,"PROFILE_PATH",Path(self.folder.name)/"profile.json")
        desired_patch.start();self.addCleanup(desired_patch.stop)
        self.account={"id":"test","mt5_login":123,"mt5_server":"Broker","terminal_path":str(self.terminal),"desired_running":True}
        self.profile=ClientProfile(retry_interval=1,retry_cap=3,retries_before_alert=2,accounts=[self.account])
        self.api=Mock();self.api.authorize.return_value=AuthorizationResult(True,session_token="test")
        self.stop=Stop();self.status=[]
        self.worker=runtime.ClientRuntime(self.profile,self.account,self.stop,api=self.api,ledger=Ledger(Path(self.folder.name)/"test.db"),report=lambda **state:self.status.append(state))
        self.worker.token="test"
    def signal(self,age=0):
        return {"setup_time":datetime.fromtimestamp(runtime.time.time()-age,timezone.utc).isoformat(),"market":"GOLD","direction":"BUY","stop_loss":90,"take_profit":110}
    def instruction(self):
        return {"instruction_id":1,"signal_key":"signal","created_utc":datetime.fromtimestamp(self.worker.since+1, timezone.utc).isoformat(),"payload":self.signal()}
    def test_fresh_signals_pass_but_stale_future_and_naive_are_rejected(self):
        runtime.validate_signal(self.signal(age=10))
        for payload in (self.signal(age=1201),self.signal(age=-61),{"setup_time":"2026-10-26T12:00:00"}):
            with self.assertRaises(ValueError):runtime.validate_signal(payload)
    def test_nonfinite_signal_timestamp_cannot_bypass_freshness_checks(self):
        for value in (float("nan"),float("inf"),float("-inf")):
            with self.assertRaises(ValueError):runtime.validate_signal({"setup_time":value})
        with self.assertRaises(ValueError):runtime.validate_signal(self.signal(),now=float("nan"))
    def test_backlog_is_saved_as_skipped_without_execution(self):
        data=self.instruction();data["created_utc"]=datetime.fromtimestamp(self.worker.since-1,timezone.utc).isoformat()
        with patch.object(runtime,"execute_instruction") as execute:self.worker.process(data)
        execute.assert_not_called();self.api.acknowledge.assert_called_once()
        self.assertEqual(self.api.acknowledge.call_args.args[2],"SKIPPED")
    def test_stop_during_final_server_policy_request_blocks_order_submission(self):
        policy={"risk_per_trade_pct":.9,"max_open_risk_pct":40,"max_daily_loss_pct":5}
        count=[0]
        def risk_policy(_token):
            count[0]+=1
            if count[0]==2:self.stop.set()
            return policy
        self.api.risk_policy.side_effect=risk_policy
        send=Mock()
        def execute(*_args,**kwargs):
            kwargs["before_send"]()
            send()
        with patch.object(runtime,"connection_account"),patch.object(runtime,"execute_instruction",side_effect=execute):
            with self.assertRaises(runtime.SafetyStop):self.worker.process(self.instruction())
        send.assert_not_called()
    def test_ambiguous_order_and_failed_ack_never_resubmit_after_restart(self):
        data=self.instruction();self.api.risk_policy.return_value={"risk_per_trade_pct":.9,"max_open_risk_pct":40,"max_daily_loss_pct":5}
        self.api.acknowledge.side_effect=[ServerUnavailable("offline"),{}]
        with patch.object(runtime,"connection_account"),patch.object(runtime,"execute_instruction",side_effect=RuntimeError("MT5 returned no confirmation")) as execute:
            with self.assertRaises(ServerUnavailable):self.worker.process(data)
            restarted=runtime.ClientRuntime(self.profile,self.account,self.stop,api=self.api,ledger=Ledger(Path(self.folder.name)/"test.db"),report=lambda **_:None)
            restarted.token="test";restarted.process(data)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(self.api.acknowledge.call_args.args[2],"ERROR_REVIEW")
    def test_interrupted_submission_becomes_review_ack_without_reexecution(self):
        data=self.instruction();self.worker.ledger.claim(self.worker.key,"signal",1)
        with patch.object(runtime,"execute_instruction") as execute:self.worker.process(data)
        execute.assert_not_called();self.assertEqual(self.api.acknowledge.call_args.args[2],"ERROR_REVIEW")
    def test_ledger_dedup_survives_restart_and_is_account_scoped(self):
        self.assertTrue(self.worker.ledger.claim("Broker|123","key",1))
        again=Ledger(Path(self.folder.name)/"test.db")
        self.assertFalse(again.claim("Broker|123","key",1));self.assertTrue(again.claim("Broker|456","key",1))
    def test_network_recovery_keeps_desired_on_and_discards_outage_response(self):
        self.worker.token="";self.api.next_instruction.side_effect=[ServerUnavailable("offline"),{"available":True,"instruction_id":1},{"available":True,"instruction_id":2}]
        def process(data):self.assertEqual(data["instruction_id"],2);self.stop.set()
        with patch.object(runtime.mt5,"shutdown"),patch.object(runtime.mt5,"initialize",return_value=True),patch.object(runtime,"connection_account"),patch.object(runtime.BrokerClock,"detect",return_value=NS(offset_seconds=0)),patch.object(runtime,"resolve_symbol",return_value="XAUUSD"),patch.object(runtime,"snapshot",return_value={}),patch.object(self.worker,"process",side_effect=process) as execute:
            self.worker.run()
        self.assertTrue(self.account["desired_running"])
        self.assertEqual(execute.call_count,1)
        self.assertIn("RECONNECTING",[row["state"] for row in self.status]);self.assertIn("RECOVERED",[row["state"] for row in self.status])
    def test_mt5_disconnect_reinitializes_and_keeps_desired_state(self):
        self.api.next_instruction.side_effect=[{"available":False},{"available":True,"instruction_id":2}]
        def process(data):self.stop.set()
        with patch.object(runtime.mt5,"shutdown"),patch.object(runtime.mt5,"initialize",return_value=True) as initialize,patch.object(runtime,"connection_account"),patch.object(runtime.BrokerClock,"detect",side_effect=[runtime.MT5Disconnected("offline"),NS(offset_seconds=0)]),patch.object(runtime,"resolve_symbol",return_value="GOLD"),patch.object(runtime,"snapshot",return_value={}),patch.object(self.worker,"process",side_effect=process):
            self.worker.run()
        self.assertEqual(initialize.call_count,2);self.assertTrue(self.account["desired_running"])
    def test_revoked_access_disables_execution_instead_of_retrying(self):
        storage.set_desired_state(self.account["id"],True)
        self.api.next_instruction.side_effect=ClientAccessRevoked("Subscription expired")
        with patch.object(runtime.mt5,"shutdown"),patch.object(runtime.mt5,"initialize",return_value=True),patch.object(runtime,"connection_account"),patch.object(runtime.BrokerClock,"detect",return_value=NS(offset_seconds=0)),patch.object(runtime,"resolve_symbol",return_value="GOLD"):
            self.worker.run()
        self.assertEqual(self.status[-1]["state"],"ACCESS_DISABLED");self.assertFalse(self.status[-1]["desired"])
        self.assertFalse(storage.desired_state(self.account["id"],True))
    def test_initial_authorization_outage_retries_without_any_order(self):
        self.worker.token=""
        self.api.authorize.side_effect=ServerUnavailable("offline at Start")
        storage.set_desired_state(self.account["id"],True)
        def wait(delay):
            self.stop.waits.append(delay)
            if len(self.stop.waits)>=3:self.stop.set()
            return self.stop.flag
        self.stop.wait=wait
        with patch.object(runtime.mt5,"shutdown"),patch.object(runtime.mt5,"initialize",return_value=True),patch.object(runtime,"connection_account"),patch.object(runtime.BrokerClock,"detect",return_value=NS(offset_seconds=0)),patch.object(runtime,"resolve_symbol",return_value="GOLD"),patch.object(runtime,"execute_instruction") as execute:
            self.worker.run()
        execute.assert_not_called();self.api.next_instruction.assert_not_called()
        self.assertEqual(self.api.authorize.call_count,3)
        self.assertTrue(storage.desired_state(self.account["id"]))
        self.assertEqual(self.stop.waits,[1,2,3])
    def test_initial_unavailable_mt5_retries_instead_of_disabling_desired(self):
        self.worker.token=""
        storage.set_desired_state(self.account["id"],True)
        def wait(delay):
            self.stop.waits.append(delay)
            if len(self.stop.waits)>=2:self.stop.set()
            return self.stop.flag
        self.stop.wait=wait
        with patch.object(runtime.mt5,"shutdown"),patch.object(runtime.mt5,"initialize",return_value=False),patch.object(runtime,"execute_instruction") as execute:
            self.worker.run()
        execute.assert_not_called();self.api.authorize.assert_not_called()
        self.assertTrue(storage.desired_state(self.account["id"]))
        self.assertIn("DEGRADED",[state["state"] for state in self.status])
    def test_account_switch_is_a_safety_stop(self):
        with patch.object(runtime.mt5,"account_info",return_value=NS(login=999,server="Broker")),patch.object(runtime.mt5,"terminal_info",return_value=NS(connected=True)):
            with self.assertRaises(runtime.SafetyStop):runtime.connection_account(self.account)
    def test_client_uses_same_account_lock_namespace_as_owner_routes(self):
        import hashlib
        with patch.dict(runtime.os.environ,{"LOCALAPPDATA":self.folder.name}):
            expected=Path(self.folder.name)/"GOLD_AI"/"personal_locks"/(hashlib.sha256(b"Broker|123").hexdigest()+".lock")
            self.assertEqual(runtime.account_lock_path(self.account),expected)

class ApiTests(unittest.TestCase):
    def test_subscription_compatibility_and_ngrok_user_agent_headers(self):
        api=GoldAIServer(ClientProfile())
        response=Mock(status_code=200);response.json.return_value={"subscription":{"plan_code":"STARTER"}}
        with patch("client.api.httpx.request",return_value=response) as request:
            self.assertEqual(api.subscription(session_token="private")["subscription"]["plan_code"],"STARTER")
            self.assertTrue(request.call_args.args[1].endswith("/v1/mobile/subscription"))
            for call in (lambda:api.authorize(),lambda:api.next_instruction("private"),lambda:api.acknowledge("private",1,"SKIPPED")):
                call()
                headers=request.call_args.kwargs["headers"]
                self.assertEqual(headers["ngrok-skip-browser-warning"],"true")
                self.assertEqual(headers["User-Agent"],"AZT_Client/2.0")
            self.assertEqual(request.call_args.kwargs["headers"]["Authorization"],"Bearer private")
    def test_since_cutoff_and_telemetry_are_sent_to_account_bound_endpoints(self):
        api=GoldAIServer(ClientProfile())
        response=Mock(status_code=200);response.json.return_value={"ok":True}
        with patch("client.api.httpx.request",return_value=response) as request:
            api.next_instruction("private","2026-10-26T08:00:00+00:00")
            self.assertEqual(request.call_args.kwargs["params"]["since"],"2026-10-26T08:00:00+00:00")
            api.telemetry("private",{"positions":[]})
            self.assertEqual(request.call_args.kwargs["json"],{"snapshot":{"positions":[]}})
    def test_invalid_session_and_revocation_are_distinguished(self):
        api=GoldAIServer(ClientProfile())
        for code,error in ((401,SessionExpired),(403,ClientAccessRevoked),(503,ServerUnavailable)):
            response=Mock(status_code=code);response.json.return_value={"detail":"blocked"}
            with patch("client.api.httpx.request",return_value=response),self.assertRaises(error):api.overview("private")

class ManagerTests(unittest.TestCase):
    def test_rapid_stop_start_waits_for_prior_exit_then_starts_once(self):
        from client.manager import WorkerManager
        manager=WorkerManager();old=Mock();old.poll.return_value=None;old.stdin.closed=False
        old.stdin.close.side_effect=lambda:setattr(old.stdin,"closed",True)
        manager.processes["one"]=old
        manager.stop("one");manager.start({"id":"one"})
        self.assertIn("one",manager.pending)
        self.assertEqual(manager.status("one")["state"],"STOPPING")
        with patch.object(manager,"start") as start:
            manager.poll();start.assert_not_called()
            old.poll.return_value=0
            manager.poll();start.assert_called_once_with({"id":"one"})
        self.assertNotIn("one",manager.pending)
    def test_later_stop_cancels_queued_restart(self):
        from client.manager import WorkerManager
        manager=WorkerManager();old=Mock();old.poll.return_value=None;old.stdin.closed=True
        manager.processes["one"]=old
        manager.start({"id":"one"});manager.stop("one")
        self.assertNotIn("one",manager.pending)

class ExecutorSafetyTests(unittest.TestCase):
    def test_broker_minimum_above_policy_risk_is_blocked_even_below_two_percent(self):
        account=NS(equity=100,balance=100)
        terminal=NS(connected=True,trade_allowed=True)
        info=NS(volume_min=.01,volume_max=100,volume_step=.01,filling_mode=3)
        payload={"market":"GOLD","direction":"BUY","stop_loss":90,"take_profit":110}
        with patch.object(executor.mt5,"terminal_info",return_value=terminal),patch.object(executor.mt5,"account_info",return_value=account),patch.object(executor,"_daily_loss_pct",return_value=0),patch.object(executor,"_resolve_symbol",return_value="GOLD"),patch.object(executor.mt5,"symbol_info_tick",return_value=NS(ask=100,bid=99)),patch.object(executor,"tick_utc_epoch",return_value=executor.time.time()),patch.object(executor.mt5,"symbol_info",return_value=info),patch.object(executor.mt5,"order_calc_profit",side_effect=lambda _side,_symbol,volume,_entry,_sl:-150*volume),patch.object(executor.mt5,"order_send") as send:
            result=executor.execute_instruction(payload,risk_per_trade_pct=.9,max_single_risk_pct=2)
        self.assertFalse(result.sent)
        self.assertIn("RISK_BLOCKED",result.message)
        self.assertAlmostEqual(result.planned_risk_pct,1.5)
        send.assert_not_called()
    def test_nonfinite_position_risk_is_fail_closed(self):
        position=NS(magic=executor.MAGIC,sl=90,type=0,symbol="GOLD",volume=.01,price_open=100)
        with patch.object(executor.mt5,"account_info",return_value=NS(equity=100)),patch.object(executor.mt5,"positions_get",return_value=[position]),patch.object(executor.mt5,"order_calc_profit",return_value=float("nan")):
            self.assertEqual(executor._open_risk_pct(True),float("inf"))
            with self.assertRaises(RuntimeError):executor._loss("BUY","GOLD",.01,100,90)
    def test_missing_positions_are_fail_closed(self):
        with patch.object(executor.mt5,"account_info",return_value=NS(equity=100)),patch.object(executor.mt5,"positions_get",return_value=None):
            self.assertEqual(executor._open_risk_pct(True),float("inf"))
    def test_ambiguous_submission_is_not_retried_with_another_filling_mode(self):
        account=NS(equity=100,balance=100)
        terminal=NS(connected=True,trade_allowed=True)
        payload={"market":"GOLD","direction":"BUY","stop_loss":90,"take_profit":110}
        with patch.object(executor.mt5,"terminal_info",return_value=terminal),patch.object(executor.mt5,"account_info",return_value=account),patch.object(executor,"_daily_loss_pct",return_value=0),patch.object(executor,"_resolve_symbol",return_value="GOLD"),patch.object(executor.mt5,"symbol_info_tick",return_value=NS(ask=100,bid=99)),patch.object(executor,"tick_utc_epoch",return_value=executor.time.time()),patch.object(executor,"_volume_for_risk",return_value=(.01,.9)),patch.object(executor,"_open_risk_pct",return_value=0),patch.object(executor.mt5,"symbol_info",return_value=NS(filling_mode=3)),patch.object(executor.mt5,"order_check",return_value=NS(retcode=0)),patch.object(executor.mt5,"order_send",return_value=None) as send:
            with self.assertRaisesRegex(RuntimeError,"no result"):executor.execute_instruction(payload)
        send.assert_called_once()

if __name__=="__main__":unittest.main()
