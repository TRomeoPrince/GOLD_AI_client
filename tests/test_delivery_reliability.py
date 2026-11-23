"""No-live-trade regression tests for account ACK, news, and client entry geometry."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest

from client.api import GoldAIServer
from client.executor import client_sl_tp
from client.ledger import Ledger
from client.models import ClientProfile
from client.runtime import ClientRuntime


def payload(direction, entry, sl, tp):
    return {"direction": direction, "market": "GOLD",
            "setup_time": datetime.now(timezone.utc).isoformat(),
            "stop_loss": sl, "take_profit": tp, "metadata": {"entry": entry}}


class EntryGeometryTests(unittest.TestCase):
    def test_buy_exact_300_points_allowed_301_rejected(self):
        signal = payload("BUY", 2000, 1995.5, 2006.75)
        sl, tp, mode = client_sl_tp(signal,"BUY",2003.00,0.01,2)
        self.assertEqual((sl,tp),(1998.5,2009.75))
        self.assertEqual(mode,"FAVORABLE_SHIFTED_GEOMETRY")
        with self.assertRaisesRegex(ValueError,"ENTRY_TOO_FAR_IN_PROFIT"):
            client_sl_tp(signal,"BUY",2003.01,0.01,2)

    def test_buy_adverse_has_no_distance_cap_but_fixed_sl_and_same_rr(self):
        signal=payload("BUY",2000,1995.5,2006.75)
        sl,tp,mode=client_sl_tp(signal,"BUY",1997,0.01,2)
        self.assertEqual((sl,tp,mode),(1995.5,1999.25,"ADVERSE_FIXED_OWNER_SL"))
        self.assertAlmostEqual((tp-1997)/(1997-sl),1.5)
        with self.assertRaisesRegex(ValueError,"STALE_SIGNAL"):
            client_sl_tp(signal,"BUY",1995.49,0.01,2)

    def test_sell_favorable_and_adverse(self):
        signal=payload("SELL",2000,2004.5,1993.25)
        self.assertEqual(client_sl_tp(signal,"SELL",1997,0.01,2)[:2],(2001.5,1990.25))
        with self.assertRaisesRegex(ValueError,"ENTRY_TOO_FAR_IN_PROFIT"):
            client_sl_tp(signal,"SELL",1996.99,0.01,2)
        sl,tp,mode=client_sl_tp(signal,"SELL",2002,0.01,2)
        self.assertEqual((sl,tp,mode),(2004.5,1998.25,"ADVERSE_FIXED_OWNER_SL"))

    def test_missing_owner_entry_never_guesses(self):
        with self.assertRaisesRegex(ValueError,"owner entry"):
            client_sl_tp({"stop_loss":1990,"take_profit":2010},"BUY",2000,0.01,2)


class ClientDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.account={"id":"unit","mt5_login":123,"mt5_server":"Broker","desired_running":True}
        self.profile=ClientProfile(accounts=[self.account])
        self.api=Mock()
        self.ledger=Ledger(Path(self.folder.name)/"claims.db")
        self.status=[]
        self.worker=ClientRuntime(self.profile,self.account,NS(is_set=lambda:False),
                                  api=self.api,ledger=self.ledger,
                                  report=lambda **kwargs:self.status.append(kwargs))
        self.worker.token="authorized"

    def test_three_rejected_acks_dead_letter_without_resending_trade(self):
        self.ledger.claim(self.worker.key,"signal-one",21)
        self.ledger.finish(self.worker.key,"signal-one","EXECUTED","ticket=42")
        self.api.acknowledge.side_effect=ValueError("Instruction not pending")
        for _ in range(3):
            self.worker.flush_acks()
        self.assertEqual(self.api.acknowledge.call_count,3)
        self.assertEqual(self.ledger.pending_acks(self.worker.key),[])
        dead=self.ledger.dead_letters(self.worker.key)
        self.assertEqual(len(dead),1)
        self.assertEqual(dead[0]["state"],"EXECUTED") # Never reexecute.
        self.assertEqual(dead[0]["ack_failures"],3)

    def test_mid_submission_news_lock_skips_not_disables(self):
        signal=payload("BUY",2000,1995.5,2006.75)
        instruction={"instruction_id":1,"signal_key":"new-one",
                     "created_utc":datetime.now(timezone.utc).isoformat(),"payload":signal}
        policy={"risk_per_trade_pct":.9,"max_open_risk_pct":40,"max_daily_loss_pct":5,
                "max_single_risk_pct":2,"news_lock":False,
                "daily_profit_target_enabled":False,"daily_profit_target_pct":0}
        self.api.risk_policy.side_effect=[policy,{**policy,"news_lock":True}]
        with patch("client.runtime.connection_account"), \
             patch("client.runtime.execute_instruction") as execute:
            def guarded(*_args,**kwargs):
                kwargs["before_send"]()
            execute.side_effect=guarded
            self.worker.process(instruction)
        self.assertEqual(self.api.acknowledge.call_args.args[2],"SKIPPED")
        self.assertTrue(self.account["desired_running"])
        self.assertTrue(any("SKIPPED" in x.get("message","") for x in self.status))


if __name__=="__main__":
    unittest.main()
