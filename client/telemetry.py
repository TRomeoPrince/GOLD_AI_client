from datetime import datetime, timedelta, timezone as utc_timezone
import math

def utc_iso(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Invalid UTC timestamp')
    return datetime.fromtimestamp(value, utc_timezone.utc).isoformat()

def capture_mt5(api, *, clock_offset_seconds=0, lookback_days=30):
    """Snapshot an already attached, verified account. Does not initialize MT5.

    Pass the connection's calibrated raw-feed-minus-UTC offset. No historical
    time is re-labelled as local time or adjusted using an old candle.
    """
    account = api.account_info()
    terminal = api.terminal_info()
    if account is None or terminal is None or not bool(getattr(terminal, "connected", False)):
        raise RuntimeError("MT5 telemetry unavailable while disconnected.")
    if not isinstance(getattr(account, "login", None), int):
        raise RuntimeError("MT5 telemetry requires a real verified account identity.")
    now = datetime.now(utc_timezone.utc)
    positions = api.positions_get()
    if positions is None:
        raise RuntimeError("MT5 open positions unavailable; prior snapshot retained.")

    # MT5 broker feeds may encode their wall-clock time in raw epoch seconds.
    # The timestamp() function below subtracts the calibrated feed offset.
    # The HISTORY QUERY needs the same offset, or a deal closed now can lie
    # outside the request's UTC end and today's results appear to be missing.
    if not isinstance(clock_offset_seconds, (int, float)) or not math.isfinite(clock_offset_seconds) or abs(clock_offset_seconds) > 14 * 3600:
        raise ValueError("Invalid calibrated MT5 broker offset.")
    feed_now = now + timedelta(seconds=clock_offset_seconds)
    periods = (
        (feed_now - timedelta(days=max(1, min(365, lookback_days))), feed_now + timedelta(minutes=2)),
        (feed_now - timedelta(days=2), feed_now + timedelta(minutes=2)),
    )
    deals_by_ticket = {}
    failed_windows = 0
    for start, end in periods:
        try:
            result = api.history_deals_get(start, end)
        except (RuntimeError, OSError, ValueError):
            result = None
        if result is None:
            failed_windows += 1
            continue
        for deal in result:
            ticket = getattr(deal, "ticket", None)
            if ticket is None:
                continue
            deals_by_ticket[str(ticket)] = deal
    deals = sorted(deals_by_ticket.values(), key=lambda item: (getattr(item, "time", 0), getattr(item, "ticket", 0)))
    history_status = "OK" if failed_windows == 0 else "DEGRADED" if failed_windows < len(periods) else "UNAVAILABLE"
    # Even when both history ranges fail, open positions must be refreshed;
    # existing closed deals remain in the DB and will be reconciled later.

    def timestamp(item, name="time"):
        value = float(getattr(item, name, 0) or 0)
        return utc_iso(value - clock_offset_seconds) if value > 0 else None
    def strategy(item):
        comment = str(getattr(item, "comment", "") or "")
        return comment.split(":", 1)[1] if comment.startswith(("GOLD_AI:", "AZT:")) else "—"
    open_rows = []
    for item in positions:
        open_rows.append({"ticket": str(item.ticket), "position_id": str(item.ticket), "symbol": str(item.symbol),
                          "direction": "BUY" if int(item.type) == int(api.POSITION_TYPE_BUY) else "SELL",
                          "volume": float(item.volume), "entry": float(item.price_open),
                          "current_price": float(item.price_current), "sl": float(item.sl), "tp": float(item.tp),
                          "pnl": float(item.profit) + float(getattr(item, "swap", 0) or 0),
                          "strategy": strategy(item), "opened_utc": timestamp(item)})
    grouped = {}
    for deal in deals:
        if int(getattr(deal, "type", -1)) not in {int(getattr(api, "DEAL_TYPE_BUY", 0)), int(getattr(api, "DEAL_TYPE_SELL", 1))}:
            continue
        grouped.setdefault(str(deal.position_id), []).append(deal)
    closed = []
    open_ids = {row["position_id"] for row in open_rows}
    for position_id, group in grouped.items():
        entries = [deal for deal in group if int(getattr(deal, "entry", -1)) in {int(getattr(api, "DEAL_ENTRY_IN", 0)), int(getattr(api, "DEAL_ENTRY_INOUT", 2))}]
        exits = [deal for deal in group if int(getattr(deal, "entry", -1)) in {int(getattr(api, "DEAL_ENTRY_OUT", 1)), int(getattr(api, "DEAL_ENTRY_OUT_BY", 3))}]
        if not exits:
            continue
        first = min(entries or group, key=lambda item: item.time)
        volume_in = sum(float(item.volume) for item in entries)
        entry_cost = sum(float(getattr(item, field, 0) or 0) for item in entries for field in ("commission", "swap", "fee"))
        for last in exits:
            # Each confirmed exit deal is immutable. This includes realized PnL
            # from partial closes while the rest remains in the open-position view.
            portion = min(1, float(last.volume) / volume_in) if volume_in > 0 else 0
            pnl = sum(float(getattr(last, field, 0) or 0) for field in ("profit", "commission", "swap", "fee")) + entry_cost * portion
            closed.append({"ticket": str(getattr(last, "ticket", position_id)), "position_id": position_id, "symbol": str(first.symbol),
                           "direction": "SELL" if int(last.type) == int(getattr(api, "DEAL_TYPE_BUY", 0)) else "BUY",
                           "volume": float(last.volume), "entry": sum(float(item.price) * float(item.volume) for item in entries) / volume_in if volume_in > 0 else None,
                           "exit": float(last.price), "pnl": pnl, "profit": pnl, "strategy": strategy(first),
                           "opened_utc": timestamp(first) if entries else None, "closed_utc": timestamp(last),
                           "is_partial_close": position_id in open_ids,
                           "notes": "Partial close; remaining volume is still open." if position_id in open_ids else "",
                           "close_reason": {int(getattr(api, "DEAL_REASON_SL", 4)): "SL HIT", int(getattr(api, "DEAL_REASON_TP", 5)): "TP HIT", int(getattr(api, "DEAL_REASON_SO", 6)): "STOP OUT"}.get(int(getattr(last, "reason", -1)), "")})
    summary = {name: getattr(account, name, None) for name in ("login", "server", "currency", "balance", "equity", "margin", "margin_free")}
    return {"observed_utc": now.isoformat(), "account": summary, "positions": open_rows, "trades": closed,
            "history_sync": history_status, "history_window_failures": failed_windows}
