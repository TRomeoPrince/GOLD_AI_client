"""Read-only historical MT5 deal synchronization tests. No broker/credentials/orders."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest

from client.telemetry import capture_mt5


class HistorySyncTests(unittest.TestCase):
    def api(self):
        api=Mock()
        api.POSITION_TYPE_BUY=0
        api.DEAL_TYPE_BUY=0
        api.DEAL_TYPE_SELL=1
        api.DEAL_ENTRY_IN=0
        api.DEAL_ENTRY_OUT=1
        api.DEAL_ENTRY_INOUT=2
        api.DEAL_ENTRY_OUT_BY=3
        api.DEAL_REASON_SL, api.DEAL_REASON_TP, api.DEAL_REASON_SO = 4, 5, 6
        api.account_info.return_value=NS(login=123,server="Broker",currency="USC",balance=1000,
                                         equity=1000,margin=0,margin_free=1000)
        api.terminal_info.return_value=NS(connected=True)
        api.positions_get.return_value=[]
        return api

    def test_today_closed_deal_is_included_with_broker_clock_offset(self):
        now=datetime.now(timezone.utc)
        shifted=10800
        in_deal=NS(ticket=15,position_id=500,symbol="XAUUSD.m",type=0,entry=0,
                   volume=.05,price=4050.,profit=0.,commission=0.,swap=0.,fee=0.,
                   time=now.timestamp()+shifted-3600,comment="AZT:M15_BREAKOUT")
        out_deal=NS(ticket=16,position_id=500,symbol="XAUUSD.m",type=1,entry=1,
                    volume=.05,price=4051.,profit=5.,commission=0.,swap=0.,fee=0.,
                    time=now.timestamp()+shifted-60,reason=5,comment="")
        api=self.api()
        api.history_deals_get.side_effect=lambda start,end:[
            d for d in (in_deal,out_deal) if start.timestamp() <= d.time <= end.timestamp()
        ]
        result=capture_mt5(api,clock_offset_seconds=shifted)
        self.assertEqual(result["history_sync"],"OK")
        self.assertEqual(result["history_window_failures"],0)
        self.assertEqual(len(result["trades"]),1)
        trade=result["trades"][0]
        self.assertEqual(trade["position_id"],"500")
        self.assertEqual(trade["strategy"],"M15_BREAKOUT")
        self.assertAlmostEqual(trade["pnl"],5.)
        self.assertLess(abs((datetime.fromisoformat(trade["closed_utc"]) - (now - timedelta(seconds=60))).total_seconds()), 5)
        api.history_deals_get.assert_called_once()
        self.assertGreater(api.history_deals_get.call_args_list[0].args[1],now+timedelta(hours=2))
        api.order_send.assert_not_called()
        api.initialize.assert_not_called()

    def test_two_history_errors_do_not_hide_live_open_positions(self):
        api=self.api()
        api.positions_get.return_value=[NS(ticket=41,type=1,symbol="XAUUSD.m",
            volume=.02,price_open=4000.,price_current=3999.,
            sl=4005.,tp=3990.,profit=2.,swap=0.,comment="AZT:MOMENTUM_SCALP",
            time=datetime.now(timezone.utc).timestamp())]
        api.history_deals_get.return_value=None
        result=capture_mt5(api)
        self.assertEqual(result["history_sync"],"UNAVAILABLE")
        self.assertEqual(result["history_window_failures"],2)
        self.assertEqual(len(result["positions"]),1)
        self.assertEqual(result["trades"],[])
        api.order_send.assert_not_called()

    def test_fallback_keeps_partial_48h_history(self):
        api=self.api()
        api.history_deals_get.side_effect=[None,[]]
        result=capture_mt5(api)
        self.assertEqual(result["history_sync"],"DEGRADED")
        self.assertEqual(result["history_window_failures"],1)

    def test_invalid_offset_is_rejected_without_order(self):
        api=self.api()
        with self.assertRaises(ValueError):
            capture_mt5(api,clock_offset_seconds=float("nan"))
        api.order_send.assert_not_called()


if __name__=="__main__":
    unittest.main()
