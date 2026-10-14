# GOLD_AI Client / Server Contract

## No heartbeat
There is no periodic license heartbeat. Authorization is enforced:
1. when the desktop client starts/reconnects;
2. whenever the server issues or the client requests a new trade instruction;
3. whenever protected account/user settings are changed.

If the owner revokes a customer, the server stops issuing new instructions and rejects subsequent authorization requests. Existing MT5 positions retain their local SL/TP protection.

## Owner-side identity
The server stores:
- internal client/license id
- owner-defined display name, e.g. `SOSA`
- status: ACTIVE / PAUSED / REVOKED / EXPIRED
- allowed MT5 login/server
- Telegram mapping (optional)
- app/device registrations

The end user does not need to see the internal license id. A short one-time pairing code can be used during onboarding.

## Proposed endpoints
- `POST /v1/client/authorize`
- `POST /v1/client/telegram`
- `GET /v1/client/profile`
- WebSocket `/v1/stream` for server-pushed signals/status
- `POST /v1/execution/ack`
- `POST /v1/execution/position`

Every trade instruction is re-authorized server-side before delivery.
