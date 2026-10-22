"""Fyers credentials, login flow, token persistence and thin API wrappers."""
import hmac
import json
import os
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel
import config

try:  # Python 3.11+
    import tomllib

    def _load_toml(path):
        with open(path, "rb") as f:
            return tomllib.load(f)
except ModuleNotFoundError:  # older Python
    import toml

    def _load_toml(path):
        with open(path, "r") as f:
            return toml.load(f)


class AuthError(RuntimeError):
    """Token missing, expired or rejected by Fyers."""


# ------------------------------------------------------------ credentials
def _profiles_from_streamlit_secrets() -> dict:
    """Profiles pasted into Streamlit Cloud's Settings -> Secrets (same TOML format as user_data.toml)."""
    try:
        import streamlit as st
        return {k: dict(v) for k, v in st.secrets.items() if hasattr(v, "keys") and "app_id" in v}
    except Exception:  # not running under Streamlit, or no secrets configured
        return {}


def load_profiles() -> dict:
    # 1) local file (your Mac / own server)  2) Streamlit secrets (Streamlit Community Cloud)
    if os.path.exists(config.USER_DATA_FILE):
        return _load_toml(config.USER_DATA_FILE)
    profiles = _profiles_from_streamlit_secrets()
    if profiles:
        return profiles
    raise FileNotFoundError(
        f"No credentials found. Put user_data.toml at {config.USER_DATA_FILE}, "
        "or on Streamlit Cloud paste its contents into the app's Settings -> Secrets."
    )


def get_profile(name: str) -> dict:
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(f"Profile '{name}' not found in {config.USER_DATA_FILE}")
    return profiles[name]


def verify_app_user(username: str, password: str):
    """Return the profile name if username/password match a profile in user_data.toml."""
    for name, p in load_profiles().items():
        if str(p.get("user", name)) == username.strip() and hmac.compare_digest(
            str(p.get("password", "")), password
        ):
            return name
    return None


# ------------------------------------------------------------ login flow
def _session(profile_name: str) -> fyersModel.SessionModel:
    p = get_profile(profile_name)
    return fyersModel.SessionModel(
        client_id=p["app_id"],
        secret_key=p["secret_key"],
        redirect_uri=p["redirect_uri"],
        response_type="code",
        grant_type="authorization_code",
        state=profile_name,  # echoed back on redirect -> tells us which profile logged in
    )


def auth_url(profile_name: str) -> str:
    return _session(profile_name).generate_authcode()


def extract_auth_code(text: str) -> str:
    """Accept either the raw auth_code or the full redirected URL."""
    text = text.strip()
    if "auth_code=" in text:
        qs = parse_qs(urlparse(text).query)
        if qs.get("auth_code"):
            return qs["auth_code"][0]
        return text.split("auth_code=", 1)[1].split("&", 1)[0]
    return text


def exchange_auth_code(profile_name: str, auth_code: str) -> str:
    session = _session(profile_name)
    session.set_token(extract_auth_code(auth_code))
    resp = session.generate_token()
    token = resp.get("access_token") if isinstance(resp, dict) else None
    if not token:
        raise AuthError(f"Fyers rejected the auth code: {resp}")
    save_token(profile_name, get_profile(profile_name)["app_id"], token)
    return token


# ------------------------------------------------------------ token store
def _today():
    return datetime.now(config.TZ).date().isoformat()


def save_token(profile_name: str, client_id: str, access_token: str):
    data = {
        "profile": profile_name,
        "client_id": client_id,
        "access_token": access_token,
        "date": _today(),
        "created_at": datetime.now(config.TZ).isoformat(timespec="seconds"),
    }
    tmp = config.TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, config.TOKEN_FILE)  # atomic: collector never sees a half-written file


def load_token():
    """Return the stored token dict with an extra 'valid' flag (Fyers tokens are valid for the day)."""
    if not os.path.exists(config.TOKEN_FILE):
        return None
    try:
        with open(config.TOKEN_FILE) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    data["valid"] = data.get("date") == _today() and bool(data.get("access_token"))
    return data


def clear_token():
    if os.path.exists(config.TOKEN_FILE):
        os.remove(config.TOKEN_FILE)


# ------------------------------------------------------------ API
def make_client(token: dict) -> fyersModel.FyersModel:
    return fyersModel.FyersModel(
        client_id=token["client_id"],
        token=token["access_token"],
        is_async=False,
        log_path=config.LOG_DIR,
    )


def _check(resp, what):
    if not isinstance(resp, dict):
        raise RuntimeError(f"{what}: unexpected response {resp!r}")
    if resp.get("s") == "ok":
        return resp
    msg = str(resp.get("message", resp))
    if resp.get("code") in (-8, -15, -16, -17) or "token" in msg.lower() or "authenticate" in msg.lower():
        raise AuthError(f"{what}: {msg}")
    raise RuntimeError(f"{what}: {msg}")


def get_quote(fyers, symbol: str) -> dict:
    resp = _check(fyers.quotes({"symbols": symbol}), "quotes")
    return resp["d"][0]["v"]


def get_option_chain(fyers, symbol: str, strikecount: int) -> dict:
    resp = _check(
        fyers.optionchain(data={"symbol": symbol, "strikecount": strikecount, "timestamp": ""}),
        "optionchain",
    )
    return resp["data"]
