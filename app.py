"""
NIFTY OI tracker — Streamlit app.
Run:  streamlit run app.py
"""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import collector
import config
import fyers_client
import storage

st.set_page_config(page_title="NIFTY OI Tracker", page_icon="📊", layout="wide")

UNITS = {"Lakh": 1e5, "Crore": 1e7}
CE_COLOR, PE_COLOR, DIFF_COLOR, SMA_COLOR = "#d62728", "#2ca02c", "#1f5fbf", "#ff9f1c"


@st.cache_resource
def start_collector():
    """Starts once per server process (not per browser refresh)."""
    return collector.start_in_background()


start_collector()


# ---------------------------------------------------------------- auto-capture redirect
def handle_redirect():
    """If the Fyers redirect_uri points at this app, the auth_code arrives as a query param."""
    qp = st.query_params
    code, profile = qp.get("auth_code"), qp.get("state")
    if not code:
        return
    try:
        fyers_client.get_profile(profile)
        fyers_client.exchange_auth_code(profile, code)
        st.toast("Fyers login saved. Data collection is on.", icon="✅")
    except Exception as e:
        st.error(f"Could not complete Fyers login: {e}")
    st.query_params.clear()


handle_redirect()


# ---------------------------------------------------------------- sidebar
def sidebar():
    st.sidebar.title("📊 NIFTY OI")
    page = st.sidebar.radio("Go to", ["Main", "Login"], label_visibility="collapsed")

    st.sidebar.divider()
    tok = fyers_client.load_token()
    if tok and tok["valid"]:
        st.sidebar.success(f"Fyers: logged in ({tok['profile']})")
    else:
        st.sidebar.warning("Fyers: not logged in today")

    status = storage.load_status()
    if status:
        icon = {"running": "🟢", "idle": "⚪", "waiting_login": "🟡"}.get(status.get("state"), "🔴")
        st.sidebar.caption(f"{icon} Collector: {status.get('message', '')}")
        st.sidebar.caption(f"Checked {status.get('updated', '')[11:19]}")
    return page


# ---------------------------------------------------------------- charts
def _time_axis(fig, day):
    start = datetime.combine(day, config.MARKET_START)
    end = datetime.combine(day, config.MARKET_END)
    fig.update_xaxes(range=[start, end], tickformat="%H:%M", dtick=30 * 60 * 1000, showgrid=True)


def _layout(fig, title, ytitle, day):
    _time_axis(fig, day)
    fig.update_layout(
        title=title,
        yaxis_title=ytitle,
        height=360,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def line(fig, x, y, name, color, dash=None):
    fig.add_trace(go.Scatter(x=x, y=y, name=name, mode="lines",
                             line=dict(color=color, width=2, dash=dash)))


def chart_total_oi(h, div, unit, day):
    fig = go.Figure()
    line(fig, h["timestamp"], h["CE_OI"] / div, "Total CE OI", CE_COLOR)
    line(fig, h["timestamp"], h["PE_OI"] / div, "Total PE OI", PE_COLOR)
    return _layout(fig, "1. Total CE OI vs Total PE OI", f"OI ({unit})", day)


def chart_oi_change(h, div, unit, day):
    fig = go.Figure()
    line(fig, h["timestamp"], h["CE_OI_CH"] / div, "Change in CE OI", CE_COLOR)
    line(fig, h["timestamp"], h["PE_OI_CH"] / div, "Change in PE OI", PE_COLOR)
    fig.add_hline(y=0, line_width=1, line_color="gray")
    return _layout(fig, "2. Change in CE OI vs Change in PE OI", f"OI change ({unit})", day)


def chart_diff(h, div, unit, day, sma):
    diff = h["PE_CE_CH_DIFF"] / div
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=h["timestamp"], y=diff, name="PE OI change − CE OI change",
                             mode="lines", line=dict(color=DIFF_COLOR, width=2),
                             fill="tozeroy", fillcolor="rgba(31,95,191,0.12)"))
    if sma > 1:
        line(fig, h["timestamp"], diff.rolling(sma, min_periods=1).mean(), f"SMA ({sma})", SMA_COLOR, "dash")
    fig.add_hline(y=0, line_width=1, line_color="gray")
    return _layout(fig, "3. PE OI change − CE OI change", unit, day)


# ---------------------------------------------------------------- main page
def main_page():
    today = collector.now_ist().date()
    days = storage.available_days()
    if today not in days:
        days = [today] + days

    c1, c2, c3 = st.columns([2, 1, 1])
    day = c1.selectbox("Trading day", days, format_func=lambda d: f"{d:%a, %d %b %Y}")
    unit = c2.selectbox("Units", list(UNITS), index=0)
    sma = c3.slider("SMA window (min)", 1, 60, 10)

    if day == today:
        render_live(day, unit, sma)      # auto-refreshes every UI_REFRESH_SECONDS
    else:
        render_dashboard(day, unit, sma)


@st.fragment(run_every=config.UI_REFRESH_SECONDS)
def render_live(day, unit, sma):
    render_dashboard(day, unit, sma)


def render_dashboard(day, unit, sma):
    div = UNITS[unit]
    hist = storage.load_history(day)
    meta = storage.load_meta(day) or {}

    if hist.empty:
        tok = fyers_client.load_token()
        if not (tok and tok["valid"]):
            st.info("Log in to Fyers from the **Login** page. Data collection starts at 09:15 IST.")
        else:
            st.info("Logged in. Waiting for the first data point (Mon–Fri 09:15–15:30 IST).")
        return

    last = hist.iloc[-1]
    pcr = last.PE_OI / last.CE_OI if last.CE_OI else float("nan")
    m = st.columns(6)
    m[0].metric("Spot", f"{last.spot:,.2f}" if pd.notna(last.spot) else "–")
    m[1].metric("Day open", f"{meta.get('open', 0):,.2f}")
    m[2].metric("Center strike", f"{meta.get('center_strike', last.center_strike):,.0f}")
    m[3].metric(f"CE OI ({unit})", f"{last.CE_OI / div:,.2f}", f"{last.CE_OI_CH / div:+,.2f}", delta_color="inverse")
    m[4].metric(f"PE OI ({unit})", f"{last.PE_OI / div:,.2f}", f"{last.PE_OI_CH / div:+,.2f}")
    m[5].metric("PCR", f"{pcr:.2f}")

    n = meta.get("strikes_each_side", config.STRIKES_EACH_SIDE)
    st.caption(
        f"Last update {last.timestamp:%H:%M} · {len(hist)} points · "
        f"strikes {meta.get('center_strike', 0) - n * config.STRIKE_STEP:,.0f}–"
        f"{meta.get('center_strike', 0) + n * config.STRIKE_STEP:,.0f} (center ± {n})"
    )

    st.plotly_chart(chart_total_oi(hist, div, unit, day), width="stretch")
    st.plotly_chart(chart_oi_change(hist, div, unit, day), width="stretch")
    st.plotly_chart(chart_diff(hist, div, unit, day, sma), width="stretch")

    snap = storage.load_snapshot(day)
    if snap is not None:
        with st.expander("Strike-wise OI (latest minute)"):
            show = snap.copy()
            for c in ["CE_OI", "CE_OI_CH", "PE_OI", "PE_OI_CH", "OI_DIFF"]:
                show[c] = (show[c] / div).round(2)
            st.dataframe(show, hide_index=True, width="stretch")


# ---------------------------------------------------------------- login page
def login_page():
    st.header("Login")

    if "profile" not in st.session_state:
        with st.form("app_login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in")
        if ok:
            try:
                profile = fyers_client.verify_app_user(u, p)
            except FileNotFoundError as e:
                st.error(str(e))
                return
            if profile:
                st.session_state.profile = profile
                st.rerun()
            st.error("Username or password is incorrect.")
        return

    profile = st.session_state.profile
    p = fyers_client.get_profile(profile)
    st.write(f"Signed in as **{profile}** · Fyers app `{p['app_id']}`")

    tok = fyers_client.load_token()
    if tok and tok["valid"]:
        st.success(f"Fyers token for today is saved ({tok['created_at'][11:16]}). Collection runs automatically.")

    st.subheader("Fyers login")
    st.markdown("**Step 1.** Open Fyers and complete the login (mobile/PIN/TOTP).")
    try:
        st.link_button("Open Fyers login", fyers_client.auth_url(profile))
    except Exception as e:
        st.error(f"Could not build the Fyers login link: {e}")

    st.markdown("**Step 2.** Paste the full redirected URL (or just the `auth_code`).")
    code = st.text_area("Redirected URL or auth_code", height=90)
    if st.button("Save token", type="primary", disabled=not code.strip()):
        try:
            fyers_client.exchange_auth_code(profile, code)
            st.success("Token saved. Charts start filling from the next minute in market hours.")
        except Exception as e:
            st.error(str(e))

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("Delete today's token"):
        fyers_client.clear_token()
        st.rerun()
    if c2.button("Sign out"):
        del st.session_state["profile"]
        st.rerun()


# ---------------------------------------------------------------- router
page = sidebar()
if page == "Main":
    main_page()
else:
    login_page()
