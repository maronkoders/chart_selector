import streamlit as st

from core import mt5_client
from core.config import (
    load_config,
    upsert_profile,
    delete_profile,
    set_active_profile,
    set_risk_params,
)

st.title("⚙️ Settings")

cfg = st.session_state.setdefault("app_config", load_config())

st.info(
    "Broker credentials are stored **locally in plain text** in `broker_config.json` "
    "next to app.py, so this tool can log in to MT5 for you automatically. "
    "Don't commit that file to source control or share the machine's disk with others.",
    icon="🔒",
)

st.subheader("Broker Profiles")

profiles = cfg.get("profiles", {})
active_name = cfg.get("active_profile")

if profiles:
    for name, profile in profiles.items():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 1])
            with c1:
                label = f"**{name}**"
                if name == active_name:
                    label += " 🟢 *active*"
                st.markdown(label)
                st.caption(f"Server: {profile.get('server') or '—'} · Login: {profile.get('login') or '—'}")
                if profile.get("terminal_path"):
                    st.caption(f"Terminal path: {profile['terminal_path']}")
            with c2:
                if st.button("Set Active", key=f"activate_{name}", disabled=name == active_name, width="stretch"):
                    set_active_profile(cfg, name)
                    st.rerun()
            with c3:
                if st.button("Delete", key=f"delete_{name}", width="stretch"):
                    delete_profile(cfg, name)
                    st.rerun()
else:
    st.caption("No broker profiles saved yet. Add one below.")

if st.button("Use no stored profile (rely on already-logged-in terminal)", disabled=active_name is None):
    set_active_profile(cfg, None)
    st.rerun()

st.divider()

st.subheader("Add / Edit Broker Profile")
with st.form("broker_profile_form", clear_on_submit=True):
    profile_name = st.text_input("Profile name", placeholder="e.g. Deriv Main, Weltrade Pro")
    terminal_path = st.text_input(
        "MT5 terminal path (optional)",
        placeholder=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        help="Leave blank to use the default installed terminal.",
    )
    login = st.text_input("Login (account number)")
    password = st.text_input("Password", type="password")
    server = st.text_input("Server", placeholder="e.g. Deriv-Server")

    submitted = st.form_submit_button("Save Profile", width="stretch")
    if submitted:
        if not profile_name.strip():
            st.warning("Profile name is required.")
        else:
            upsert_profile(cfg, profile_name.strip(), terminal_path, login, password, server)
            if not cfg.get("active_profile"):
                set_active_profile(cfg, profile_name.strip())
            st.success(f"Saved profile '{profile_name.strip()}'.")
            st.rerun()

st.divider()

st.subheader("Test Connection")
if st.button("🔌 Test Connection with Active Profile", width="stretch"):
    ok, msg = mt5_client.ensure_connection(cfg, force=True)
    if ok:
        st.success(msg)
    else:
        st.error(msg)

st.divider()

st.subheader("Default Risk Parameters")
st.caption("These defaults are used by the Indices Advisor scanner and can also be adjusted there.")
r1, r2 = st.columns(2)
with r1:
    account_size = st.number_input(
        "Account Balance ($)", min_value=1.0, value=float(cfg["risk"]["account_size"]), step=1.0
    )
with r2:
    risk_percentage = st.slider(
        "Risk Tolerance (%)", min_value=1.0, max_value=100.0, value=float(cfg["risk"]["risk_percentage"])
    )

if st.button("Save Risk Defaults", width="stretch"):
    set_risk_params(cfg, account_size, risk_percentage)
    st.success("Risk defaults saved.")