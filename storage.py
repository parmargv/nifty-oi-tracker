"""File-based persistence. One CSV per trading day, so the chart can always be rebuilt from 09:15."""
import csv
import glob
import json
import os
import threading
from datetime import date, datetime

import pandas as pd

import config

COLUMNS = ["timestamp", "spot", "center_strike", "CE_OI", "PE_OI", "CE_OI_CH", "PE_OI_CH", "PE_CE_CH_DIFF"]
_lock = threading.Lock()


def _path(prefix: str, day: date, ext: str) -> str:
    return os.path.join(config.DATA_DIR, f"{prefix}_{day:%Y-%m-%d}.{ext}")


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- history
def append_row(row: dict, day: date):
    """Append one minute to the day's CSV (O(1), no full rewrite)."""
    path = _path("oi_history", day, "csv")
    with _lock:
        new_file = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerow(row)


def load_history(day: date) -> pd.DataFrame:
    path = _path("oi_history", day, "csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    with _lock:
        df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return (
        df.drop_duplicates(subset="timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def available_days():
    days = []
    for p in glob.glob(os.path.join(config.DATA_DIR, "oi_history_*.csv")):
        try:
            days.append(datetime.strptime(os.path.basename(p)[11:21], "%Y-%m-%d").date())
        except ValueError:
            pass
    return sorted(days, reverse=True)


# ---------------------------------------------------------------- day meta (open / center strike)
def load_meta(day: date):
    return _read_json(_path("day_meta", day, "json"))


def save_meta(day: date, meta: dict):
    _write_json(_path("day_meta", day, "json"), meta)


# ---------------------------------------------------------------- latest strike-wise snapshot
def save_snapshot(df: pd.DataFrame, day: date):
    path = _path("strikes_latest", day, "csv")
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def load_snapshot(day: date):
    path = _path("strikes_latest", day, "csv")
    return pd.read_csv(path) if os.path.exists(path) else None


# ---------------------------------------------------------------- collector status
def save_status(state: str, message: str = "", **extra):
    data = _read_json(config.STATUS_FILE) or {}
    data.update(
        state=state,
        message=message,
        updated=datetime.now(config.TZ).isoformat(timespec="seconds"),
        **extra,
    )
    _write_json(config.STATUS_FILE, data)


def load_status():
    return _read_json(config.STATUS_FILE) or {}
