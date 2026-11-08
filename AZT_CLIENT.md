# AGORA ZION TRADER Client

Verified release: 28 October 2026. The final source includes the existing upstream main history through c409e0f and the AZT merge e07b483. Validation: 33 client tests, responsive source/frozen checks and the isolated real client/server API contract passed. No live orders were placed. Final Windows EXE SHA256: DA2951C1A804C3E7398EE711F76C073CF724B151E2B9F9BCCF7B5B507B8C91D9.

The server durably reserves a delivery before returning it and allows only one unresolved dispatch per MT5 account. A lost response is never automatically replayed. After an unresolved dispatch, Admin must reconcile the actual broker history in Clients → Accounts → Execution Review, then mark it reviewed; this permits fresh signals without resending the old one. Other authorized accounts continue independently.

AZT Client keeps protected strategies on the owner server. This customer application authorizes each MT5 account, displays its subscription/messages/trades/journal, and executes only fresh authorized instructions on the selected local terminal.

## Start and setup

Open AZT_Client.exe. The window starts maximized and can be restored/resized. Dashboard, Trades, Journal, Referrals and Payments have scrolling content; the Start/Stop footer stays reachable. The background and original profit/loss assets are bundled without changing their originals.

On Dashboard, Add account, Browse / Detect the installed terminal64.exe, verify login/server, enter the pairing code and Save. Each additional MT5 account requires its own terminal installation. The server enforces the plan/user/promo account limit; adding a local entry does not grant access. Choose the display timezone (UTC by default, any valid IANA timezone supported) and reconnect settings. Server URL retains the existing public default and is configurable.

Connect / Refresh allows subscription and payment access even when trading is expired. Start Automated Trading explicitly enables the selected account and persists that choice before any network request; an outage already present at Start does not require another click. The worker authorizes before accepting any order. Stop disables that account's desired trading state. Each account's Start choice is persisted; enabled workers resume when this app is opened again. Serious access/account safety failures persist a disabled choice independently per account. A quick Stop followed by Start waits for the old worker to exit before starting its replacement. Use Stop before exiting if you do not want that account to resume next time. Closing the app closes its child workers, while broker positions and SL/TP remain with the broker.

Each terminal runs in a separate hidden process. A per-account Windows lock prevents two AZT execution processes for that account. A workspace lock prevents duplicate UIs from sharing the same profile. Transient server/MT5/network outages retain the Start choice, retry with backoff, and show RECONNECTING/DEGRADED/RECOVERED states. Subscription revocation/expiry or account-identity safety errors disable new automated entries.

Execution claims are committed to a local SQLite ledger before submission. An interrupted/ambiguous submission becomes ERROR_REVIEW and is never resubmitted automatically. Failed acknowledgements retry the acknowledgement only. After Start or reconnect, the request cutoff is advanced to current UTC and old queued instructions are discarded. Signals older than 20 minutes or more than 60 seconds ahead are rejected. The client independently resolves the generic market to its own validated broker symbol; owner suffixes are not copied. Verified UTC broker-clock calibration, stale-quote checks, current server risk/news checks, account identity, complete position/history availability and a hard single-trade risk ceiling of 2% protect execution.

The selected per-trade policy is also a strict risk cap: a broker minimum lot risking 1.5% is rejected when the policy is 0.9%, even though it is below the absolute 2% ceiling. All API requests retain ngrok bypass and an explicit AZT Client User-Agent; the existing subscription API wrapper remains available alongside the new overview.

## Messages, payments and referrals

Admin messages appear in Dashboard without requiring Telegram. Select a message to read it and mark it read. Trades and journals use stored UTC data converted into your chosen display timezone. PnL across different currencies stays separate; missing trade details are not fabricated.

Payments shows only the selected receiving method. Check its prominently displayed network. MTN and Binance UID use PNG/JPEG screenshots (client maximum 2 MB). Crypto methods use a transaction hash. Submission is PENDING until local Admin approval; this client does not claim automatic verification or send funds. No QR codes are generated. Plans without configured prices cannot be purchased. Referral rates and promo entitlements are set by Admin; no commission percentage is hard-coded.

The legacy local profile directory is retained: %USERPROFILE%\.gold_ai_client. Profiles, per-account desired-state files, runtime JSON, logs and execution_ledger.db stay outside the EXE. Independent desired-state files prevent a worker's safety shutdown from overwriting another account's settings or being undone by a cached UI profile save. AZT_CLIENT_HOME can select an isolated profile folder for testing. Never delete execution_ledger.db to retry uncertain broker submissions; reconcile them manually instead.

## Verification/build

The November 9 recovery build reauthorizes after an outage, advances the cutoff before requesting a reserved delivery, and validates the complete risk policy again just before submission. Daily loss and profit checks query the UTC day using the calibrated broker clock. Worker status distinguishes a process that is starting, a worker that exited, and an overdue heartbeat, with allowance for configured reconnect backoff.

The recovery Client EXE is built in `dist_rebuild_20261109` with the existing `build/GOLD_AI_Client.spec`. The simulated contract now runs the actual Client runtime and order guard against the owner API and a mock MT5 adapter, covering the outage, fresh reservation, risk approval, durable acknowledgment, and duplicate suppression.

The November 4 rebuild includes automatic recovery from interrupted HTTP responses and UTC-normalized MT5 history. If the full history query fails, the Client tries a two-day window and reports whether history is partial or unavailable. Open positions keep refreshing while the owner retains previously recorded closed deals. Existing order checks still require complete risk data.

The distributor build is named `AZT_Trial_Client.exe`. Use an owner-issued pairing code to activate a 30-day trial on the first authorized MT5 pairing. The owner server controls the UTC expiry and whether the account may trade. Both builds share the Windows Client profile and account controls.

Run from this repository:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tests\smoke_client_exe.py --source
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_rebuild_20261104 --workpath build/rebuild_20261104_pyi build/GOLD_AI_Client.spec
$env:AZT_TEST_EXE = 'C:\Users\USER\Desktop\Bots\GOLD_AI_client\dist_rebuild_20261104\AZT_Client.exe'
.venv\Scripts\python.exe tests\smoke_client_exe.py
```

Build the distributor edition with `.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_rebuild_20261104 --workpath build/rebuild_20261104_pyi build/AZT_Trial_Client.spec`. Point `AZT_TEST_EXE` at the resulting EXE to run the same isolated smoke check.

The smoke path uses a private empty profile and mock display data. `tests/integration_contract.py` accepts the current owner repository path and runs the real client API wrapper against an in-process FastAPI server with a temporary database. It verifies the trial lease and the positions/history fallback without contacting MT5 or an external network.
