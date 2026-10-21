# NIFTY OI Tracker (Fyers + Streamlit)

Minute-by-minute NIFTY option-chain OI, saved to disk so the charts always show the full day from 09:15.

## Files

| File | Role |
|---|---|
| `app.py` | Streamlit UI — sidebar with **Main** (charts) and **Login** |
| `collector.py` | Background job: fetches the option chain every minute, Mon–Fri 09:15–15:30 IST |
| `fyers_client.py` | Reads `user_data.toml`, Fyers auth-code login, token store, API calls |
| `storage.py` | Per-day CSV history + day metadata (open, center strike) |
| `config.py` | Symbol, strike window, paths (all overridable by env vars) |

## Setup

```bash
pip install -r requirements.txt
cp /path/to/user_data.toml .        # same format you already use
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Daily flow

1. Open **Login**, sign in with the `user` / `password` from `user_data.toml`.
2. Click **Open Fyers login**, finish the Fyers login, then paste the redirected URL (or the `auth_code`) and click **Save token**.
3. Do this any time before 09:15. The collector starts on its own at 09:15 and stops at 15:30.

Fyers tokens are valid for one day, so log in once each trading morning.

**Optional — skip the copy/paste:** set the redirect URI in the Fyers API dashboard *and* in `user_data.toml` to your app URL
(e.g. `http://139.59.18.167:8501/`). After Fyers login you land back on the app, and the token is saved automatically.

## How the numbers are computed

- **Center strike** = nearest 50-point strike to the day's **open** (e.g. open 23150.85 → 23150). It is fixed for the whole day and saved in `data/day_meta_YYYY-MM-DD.json`.
- Totals are summed over **center ± 10 strikes** (`STRIKES_EACH_SIDE`), so the strike set never drifts as spot moves.
- OI change = `oi − prev_oi` (vs previous day's close), summed per side.
- Chart 3 = Σ PE OI change − Σ CE OI change, with an adjustable SMA.

## Data

Saved in `data/`: `oi_history_YYYY-MM-DD.csv` (one row per minute), `day_meta_*.json`, `strikes_latest_*.csv`, `token.json`.
Past days can be opened from the **Trading day** picker on the Main page.

## Running 24/7 on a server (recommended)

The collector starts automatically inside Streamlit on the first page visit after a server start. To keep collecting even
if Streamlit restarts, run it as its own service — a file lock makes sure only one collector writes at a time:

```ini
# /etc/systemd/system/oi-collector.service
[Unit]
Description=NIFTY OI collector
After=network-online.target

[Service]
WorkingDirectory=/opt/nifty_oi
ExecStart=/usr/bin/python3 collector.py
Restart=always

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now oi-collector`

## Config (env vars)

`STRIKES_EACH_SIDE` (10) · `FETCH_STRIKECOUNT` (30) · `UI_REFRESH_SECONDS` (30) · `OI_DATA_DIR` · `USER_DATA_FILE`
