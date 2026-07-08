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

# Quick profile selector
if profiles:
    st.write("**Quick Select Active Profile:**")
    profile_options = ["None (use already-logged-in terminal)"] + list(profiles.keys())
    current_index = 0
    if active_name and active_name in profiles:
        current_index = list(profiles.keys()).index(active_name) + 1
    
    selected_profile = st.selectbox(
        "Active Profile",
        options=profile_options,
        index=current_index,
        key="quick_profile_select",
        label_visibility="collapsed"
    )
    
    if selected_profile != "None (use already-logged-in terminal)" and selected_profile != active_name:
        set_active_profile(cfg, selected_profile)
        st.rerun()
    elif selected_profile == "None (use already-logged-in terminal)" and active_name is not None:
        set_active_profile(cfg, None)
        st.rerun()

st.divider()

# Profile management cards
if profiles:
    st.write("**Manage Profiles:**")
    for name, profile in profiles.items():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            with c1:
                label = f"**{name}**"
                if name == active_name:
                    label += " 🟢 *active*"
                st.markdown(label)
                st.caption(f"Server: {profile.get('server') or '—'} · Login: {profile.get('login') or '—'}")
                if profile.get("terminal_path"):
                    st.caption(f"Terminal: {profile['terminal_path']}")
            with c2:
                if st.button("✏️ Edit", key=f"edit_{name}", width="stretch"):
                    st.session_state[f"edit_profile_{name}"] = True
                    st.rerun()
            with c3:
                if st.button("🟢 Set Active", key=f"activate_{name}", disabled=name == active_name, width="stretch"):
                    set_active_profile(cfg, name)
                    st.rerun()
            with c4:
                if st.button("🗑️ Delete", key=f"delete_{name}", width="stretch"):
                    delete_profile(cfg, name)
                    st.rerun()
else:
    st.caption("No broker profiles saved yet. Add one below.")

st.divider()

# Check if we're editing a profile
editing_profile = None
for name in profiles.keys():
    if st.session_state.get(f"edit_profile_{name}"):
        editing_profile = name
        # Clear the edit state after detecting it
        st.session_state[f"edit_profile_{name}"] = False
        break

st.subheader("Add / Edit Broker Profile")
if editing_profile:
    st.write(f"**Editing profile: {editing_profile}**")
    existing_profile = profiles.get(editing_profile, {})
else:
    st.write("**Add new profile**")

with st.form("broker_profile_form", clear_on_submit=True):
    if editing_profile:
        profile_name = st.text_input("Profile name", value=editing_profile, disabled=True)
        terminal_path = st.text_input(
            "MT5 terminal path (optional)",
            value=existing_profile.get("terminal_path", ""),
            placeholder=r"C:\Program Files\MetaTrader 5\terminal64.exe",
            help="Leave blank to use the default installed terminal.",
        )
        login = st.text_input("Login (account number)", value=existing_profile.get("login", ""))
        password = st.text_input("Password", value=existing_profile.get("password", ""), type="password")
        server = st.text_input("Server", value=existing_profile.get("server", ""), placeholder="e.g. Deriv-Server")
        form_button_label = "Update Profile"
    else:
        profile_name = st.text_input("Profile name", placeholder="e.g. Deriv Main, Weltrade Pro")
        terminal_path = st.text_input(
            "MT5 terminal path (optional)",
            placeholder=r"C:\Program Files\MetaTrader 5\terminal64.exe",
            help="Leave blank to use the default installed terminal.",
        )
        login = st.text_input("Login (account number)")
        password = st.text_input("Password", type="password")
        server = st.text_input("Server", placeholder="e.g. Deriv-Server")
        form_button_label = "Save Profile"

    submitted = st.form_submit_button(form_button_label, width="stretch")
    if submitted:
        if not profile_name.strip():
            st.warning("Profile name is required.")
        else:
            target_name = editing_profile if editing_profile else profile_name.strip()
            upsert_profile(cfg, target_name, terminal_path, login, password, server)
            if not cfg.get("active_profile") and not editing_profile:
                set_active_profile(cfg, target_name)
            action = "Updated" if editing_profile else "Saved"
            st.success(f"{action} profile '{target_name}'.")
            st.rerun()

if editing_profile:
    if st.button("Cancel Edit", width="stretch"):
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
st.caption(
    "Account Balance is now pulled automatically from your connected MT5 account on the "
    "Indices Advisor page and can't be edited there. The value below is only used as a "
    "fallback if MT5 is briefly unreachable."
)
r1, r2 = st.columns(2)
with r1:
    account_size = st.number_input(
        "Account Balance ($) — offline fallback", min_value=1.0, value=float(cfg["risk"]["account_size"]), step=1.0
    )
with r2:
    risk_percentage = st.slider(
        "Risk Tolerance (%)", min_value=1.0, max_value=100.0, value=float(cfg["risk"]["risk_percentage"])
    )

if st.button("Save Risk Defaults", width="stretch"):
    set_risk_params(cfg, account_size, risk_percentage)
    st.success("Risk defaults saved.")