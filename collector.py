"""
Minute-by-minute NIFTY option-chain collector.

* Runs Mon–Fri, 09:15–15:30 IST, one fetch per minute.
* The center strike is fixed for the whole day: nearest strike to the day's OPEN.
  Totals are summed over center ± STRIKES_EACH_SIDE strikes, so the strike set never drifts intraday.
* Every minute is appended to data/oi_history_YYYY-MM-DD.csv.

Can run inside the Streamlit process (started automatically by app.py) or standalone:
    python collector.py
A file lock guarantees only one collector writes at a time, whichever way it is started.
"""
import math
import threading
import time
from datetime import datetime, timedelta

import pandas as pd

import config
import fyers_client
import storage


class NotLoggedIn(RuntimeError):
    pass


class NoTradingToday(RuntimeError):
    pass


# ---------------------------------------------------------------- pure helpers
def now_ist() -> datetime:
    return datetime.now(config.TZ)


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and config.MARKET_START <= now.time() <= config.MARKET_END


def nearest_strike(price: float, step: int = config.STRIKE_STEP) -> float:
    return float(math.floor(price / step + 0.5) * step)  # half-up, avoids banker's rounding


def prepare_option_chain(chain: dict) -> pd.DataFrame:
    df = pd.DataFrame(chain["optionsChain"])
    df = df[df["option_type"].isin(["CE", "PE"])].copy()
    if "prev_oi" in df:
        df["oi_ch"] = df["oi"] - df["prev_oi"]
    else:
        df["oi_ch"] = df["oich"]

    def side(kind):
        s = df[df["option_type"] == kind][["strike_price", "oi", "oi_ch"]]
        return s.rename(columns={"oi": f"{kind}_OI", "oi_ch": f"{kind}_OI_CH"})

    out = (
        pd.merge(side("CE"), side("PE"), on="strike_price", how="outer")
        .fillna(0)
        .sort_values("strike_price")
        .reset_index(drop=True)
    )
    out["OI_DIFF"] = out["PE_OI"] - out["CE_OI"]
    return out


def _quote_is_today(quote: dict, now: datetime) -> bool:
    tt = quote.get("tt")
    try:
        tt = int(tt)
    except (TypeError, ValueError):
        return True  # field missing -> can't tell, assume ok
    return tt <= 0 or datetime.fromtimestamp(tt, config.TZ).date() == now.date()


def get_or_create_day_meta(quote: dict, now: datetime) -> dict:
    day = now.date()
    meta = storage.load_meta(day)
    if meta:
        return meta
    open_price = float(quote.get("open_price") or 0)
    if open_price <= 0:
        raise RuntimeError("Day open not available yet")
    center = nearest_strike(open_price)
    n = config.STRIKES_EACH_SIDE
    meta = {
        "date": day.isoformat(),
        "open": open_price,
        "center_strike": center,
        "strike_step": config.STRIKE_STEP,
        "strikes_each_side": n,
        "strikes": [center + i * config.STRIKE_STEP for i in range(-n, n + 1)],
        "created_at": now.isoformat(timespec="seconds"),
    }
    storage.save_meta(day, meta)
    return meta


# ---------------------------------------------------------------- one fetch
def collect_once(now: datetime = None) -> dict:
    now = now or now_ist()
    token = fyers_client.load_token()
    if not token or not token["valid"]:
        raise NotLoggedIn("No valid Fyers token for today. Log in from the Login page.")

    fyers = fyers_client.make_client(token)
    quote = fyers_client.get_quote(fyers, config.SYMBOL)
    if not _quote_is_today(quote, now):
        # before the first tick (or on a holiday) the quote still carries the previous session;
        # never lock today's center strike on stale data
        raise NoTradingToday("No trades yet today (market holiday or pre-open).")

    meta = get_or_create_day_meta(quote, now)
    chain = fyers_client.get_option_chain(fyers, config.SYMBOL, config.FETCH_STRIKECOUNT)
    df = prepare_option_chain(chain)
    window = df[df["strike_price"].isin(meta["strikes"])]
    missing = sorted(set(meta["strikes"]) - set(window["strike_price"]))

    ts = now.replace(second=0, microsecond=0)
    row = {
        "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
        "spot": quote.get("lp"),
        "center_strike": meta["center_strike"],
        "CE_OI": window["CE_OI"].sum(),
        "PE_OI": window["PE_OI"].sum(),
        "CE_OI_CH": window["CE_OI_CH"].sum(),
        "PE_OI_CH": window["PE_OI_CH"].sum(),
    }
    row["PE_CE_CH_DIFF"] = row["PE_OI_CH"] - row["CE_OI_CH"]
    storage.append_row(row, now.date())
    storage.save_snapshot(window, now.date())

    msg = f"Saved {ts:%H:%M}"
    if missing:
        msg += f" (strikes missing from API: {missing[:5]}{'…' if len(missing) > 5 else ''})"
    storage.save_status("running", msg, last_ok=ts.isoformat())
    return row


# ---------------------------------------------------------------- loop
def _sleep_to_next_minute():
    nxt = (now_ist() + timedelta(minutes=1)).replace(second=1, microsecond=0)
    time.sleep(max((nxt - now_ist()).total_seconds(), 1))


def run_forever(stop: threading.Event = None):
    stop = stop or threading.Event()
    while not stop.is_set():
        now = now_ist()
        if not in_session(now):
            storage.save_status("idle", "Outside market hours (Mon–Fri 09:15–15:30 IST)")
            time.sleep(15)
            continue
        try:
            collect_once(now)
        except NotLoggedIn as e:
            storage.save_status("waiting_login", str(e))
            time.sleep(10)  # check again soon, so data starts as soon as you log in
            continue
        except NoTradingToday as e:
            storage.save_status("idle", str(e))
        except fyers_client.AuthError as e:
            storage.save_status("auth_error", f"{e}. Log in again from the Login page.")
        except Exception as e:  # network/API hiccup: keep the loop alive
            storage.save_status("error", f"{now:%H:%M:%S} fetch failed: {e}")
        _sleep_to_next_minute()


# ---------------------------------------------------------------- single-instance guard
_lock_handle = None


def _try_lock() -> bool:
    global _lock_handle
    try:
        import fcntl
    except ImportError:  # Windows: no guard, run a single instance yourself
        return True
    f = open(config.LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f  # keep it open for the lifetime of the process
    return True


def _guarded_loop():
    # If another collector (e.g. a systemd service) already holds the lock, stand by and retry,
    # so collection resumes automatically if that one stops.
    while not _try_lock():
        time.sleep(60)
    run_forever()


def start_in_background() -> threading.Thread:
    th = threading.Thread(target=_guarded_loop, name="oi-collector", daemon=True)
    th.start()
    return th


if __name__ == "__main__":
    print("Starting NIFTY OI collector (Ctrl+C to stop)…")
    _guarded_loop()
