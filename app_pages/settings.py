import os
import subprocess
import sys
import streamlit as st

from core import mt5_client
from core.config import (
    load_config,
    upsert_profile,
    delete_profile,
    set_active_profile,
    set_risk_params,
    link_plan_to_profile,
    unlink_plan_from_profile,
    set_screenshot_folder,
    set_enabled_index_classes,
    get_active_profile,
)
from core.broker_universe import (
    get_profile_broker_type,
    get_profile_universe,
    available_index_classes,
    get_enabled_index_classes,
    advisor_title,
)

st.title("⚙️ Settings")

cfg = st.session_state.setdefault("app_config", load_config())

st.info(
    "Broker credentials are stored **locally in plain text** in `broker_config.json` "
    "next to app.py, so this tool can log in to MT5 for you automatically. "
    "Don't commit that file to source control or share the machine's disk with others.",
    icon="🔒",
)

# ── HELPER: Open Folder Dialog via Subprocess ────────────────────────────────
def open_folder_dialog_subprocess() -> str | None:
    """
    Open a native folder picker by spawning a separate Python process.
    This avoids tkinter's 'main thread is not in main loop' error.
    """
    dialog_script = '''
import tkinter as tk
from tkinter import filedialog
import sys

root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)

folder = filedialog.askdirectory(title="Select Screenshot Folder", mustexist=True)
root.destroy()

if folder:
    print(folder, end='')
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", dialog_script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return os.path.normpath(result.stdout.strip())
        return None
    except subprocess.TimeoutExpired:
        st.error("Folder dialog timed out.")
        return None
    except Exception as e:
        st.error(f"Could not open folder dialog: {e}")
        return None


def open_folder_in_explorer(path: str) -> None:
    """Open the given folder in the OS file explorer."""
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=True)
        else:
            subprocess.run(["xdg-open", path], check=True)
    except Exception as e:
        st.error(f"Could not open folder: {e}")


# ── SESSION STATE FOR FOLDER SELECTION ───────────────────────────────────────
if "screenshot_folder_selected" not in st.session_state:
    st.session_state.screenshot_folder_selected = None

# Secondary navigation tabs
tab1, tab2, tab3, tab4 = st.tabs(
    ["Broker Profiles", "Index Classes", "Risk Parameters", "Screenshot Folder"]
)

# Tab 1: Broker Profiles
with tab1:
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
        trading_plans = cfg.get("trading_plans", {})
        for name, profile in profiles.items():
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
                with c1:
                    label = f"**{name}**"
                    if name == active_name:
                        label += " 🟢 *active*"
                    st.markdown(label)
                    st.caption(f"Server: {profile.get('server') or '—'} · Login: {profile.get('login') or '—'}")
                    if profile.get("terminal_path"):
                        st.caption(f"Terminal: {profile['terminal_path']}")
                    linked_plan = profile.get("trading_plan")
                    if linked_plan and linked_plan in trading_plans:
                        st.caption(f"📈 Plan: {linked_plan}")
                with c2:
                    if trading_plans:
                        plan_options = ["None"] + list(trading_plans.keys())
                        current_plan = linked_plan if linked_plan in trading_plans else "None"
                        
                        selected_plan = st.selectbox(
                            "Link Trading Plan",
                            options=plan_options,
                            index=plan_options.index(current_plan),
                            key=f"plan_{name}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_plan != current_plan:
                            if selected_plan == "None":
                                unlink_plan_from_profile(cfg, name)
                                st.rerun()
                            else:
                                link_plan_to_profile(cfg, selected_plan, name)
                                st.rerun()
                    else:
                        st.caption("No plans available")
                with c3:
                    if st.button("✏️ Edit", key=f"edit_{name}", use_container_width=True):
                        st.session_state[f"edit_profile_{name}"] = True
                        st.rerun()
                with c4:
                    if st.button("🟢 Set Active", key=f"activate_{name}", disabled=name == active_name, use_container_width=True):
                        set_active_profile(cfg, name)
                        st.rerun()
                with c5:
                    if st.button("🗑️ Delete", key=f"delete_{name}", use_container_width=True):
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
    
        submitted = st.form_submit_button(form_button_label, use_container_width=True)
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
        if st.button("Cancel Edit", use_container_width=True):
            st.rerun()
    
    st.divider()
    
    st.subheader("Test Connection")
    if st.button("🔌 Test Connection with Active Profile", use_container_width=True):
        ok, msg = mt5_client.ensure_connection(cfg, force=True)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

# Tab 2: Index Classes (per active profile / broker)
with tab2:
    st.subheader("Index Classes")
    st.caption(
        "Choose which index classes belong to this login profile. "
        "Selected classes are scanned in Indices Advisor and can be synced into MT5 Market Watch."
    )

    profile_name, profile = get_active_profile(cfg)
    if not profile_name or not profile:
        st.warning("Select an active broker profile first (Broker Profiles tab).")
    else:
        broker_type = get_profile_broker_type(profile_name, profile)
        universe = get_profile_universe(profile_name, profile)
        catalog = available_index_classes(universe)
        enabled = get_enabled_index_classes(profile_name, profile)

        st.markdown(f"**Profile:** `{profile_name}`")
        st.caption(f"{advisor_title(broker_type)} · `{broker_type}`")

        if not catalog:
            st.info("This broker type has no predefined index classes.")
        else:
            widget_key = f"index_classes_{profile_name}"
            selected = st.multiselect(
                "Enabled index classes",
                options=catalog,
                default=enabled,
                help="Remove a class here to exclude it from scanning and Market Watch sync.",
                key=widget_key,
            )

            c_save, c_all, c_none = st.columns(3)
            with c_save:
                save_clicked = st.button("💾 Save classes", width="stretch")
            with c_all:
                if st.button("Select all", width="stretch"):
                    set_enabled_index_classes(cfg, profile_name, catalog)
                    st.session_state.pop(widget_key, None)
                    st.session_state.pop("asset_data", None)
                    st.session_state.pop("velocity_cache", None)
                    st.success("All classes enabled.")
                    st.rerun()
            with c_none:
                if st.button("Clear all", width="stretch"):
                    set_enabled_index_classes(cfg, profile_name, [])
                    st.session_state.pop(widget_key, None)
                    st.session_state.pop("asset_data", None)
                    st.session_state.pop("velocity_cache", None)
                    st.success("All classes disabled.")
                    st.rerun()

            if save_clicked:
                set_enabled_index_classes(cfg, profile_name, selected)
                st.session_state.pop(widget_key, None)
                st.session_state.pop("asset_data", None)
                st.session_state.pop("velocity_cache", None)
                st.success(
                    f"Saved {len(selected)} class(es) for `{profile_name}`."
                )
                st.rerun()

            st.divider()
            st.markdown("**MT5 Market Watch**")
            st.caption(
                "Adds symbols for enabled classes to Market Watch, and removes "
                "symbols for disabled classes that belong to this broker universe."
            )
            if st.button("📡 Sync selected classes to Market Watch", width="stretch"):
                ok, msg = mt5_client.ensure_connection(cfg, force=True)
                if not ok:
                    st.error(msg)
                else:
                    # Reload profile after possible saves in this session.
                    cfg = load_config()
                    st.session_state.app_config = cfg
                    _, profile = get_active_profile(cfg)
                    universe = get_profile_universe(profile_name, profile)
                    with st.spinner("Updating MT5 Market Watch..."):
                        result = mt5_client.sync_universe_to_market_watch(universe)
                    st.success(
                        f"Market Watch updated · added {len(result['added'])} · "
                        f"removed {len(result['removed'])} · "
                        f"classes: {', '.join(result['enabled_classes']) or 'none'}"
                    )
                    if result["skipped"]:
                        st.warning(
                            f"Could not select {len(result['skipped'])} symbol(s): "
                            + ", ".join(result["skipped"][:8])
                            + ("…" if len(result["skipped"]) > 8 else "")
                        )

# Tab 3: Risk Parameters
with tab3:
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
    
    if st.button("Save Risk Defaults", use_container_width=True):
        set_risk_params(cfg, account_size, risk_percentage)
        st.success("Risk defaults saved.")

# Tab 4: Screenshot Folder ─────────────────────────────────────────────────────
with tab4:
    st.subheader("📁 Screenshot Folder")
    st.caption(
        "Set the folder where all uploaded screenshots and images will be saved. "
        "This path is used across the app (Journal, Trading Plan, etc.)."
    )
    
    current_folder = cfg.get("screenshot_folder", "")
    
    # Display current path
    if current_folder and os.path.isdir(current_folder):
        st.success(f"**Current folder:** `{current_folder}`")
    elif current_folder:
        st.warning(f"**Current folder:** `{current_folder}` (folder not found)")
    else:
        st.info("No screenshot folder set. Select one below.")
    
    # Handle folder selection from dialog
    if st.session_state.screenshot_folder_selected:
        selected = st.session_state.screenshot_folder_selected
        st.session_state.screenshot_folder_selected = None  # Clear after use
        set_screenshot_folder(cfg, selected)
        st.success(f"Folder selected: `{selected}`")
        st.rerun()
    
    # Folder selection UI
    c1, c2, c3 = st.columns([2, 1, 1])
    
    with c1:
        manual_path = st.text_input(
            "Folder path",
            value=current_folder,
            placeholder=r"C:\Users\YourName\Pictures\Screenshots",
            label_visibility="collapsed",
            key="screenshot_path_input",
        )
    
    with c2:
        if st.button("📂 Open Folder", use_container_width=True, key="open_folder_btn"):
            selected = open_folder_dialog_subprocess()
            if selected:
                st.session_state.screenshot_folder_selected = selected
                st.rerun()
    
    with c3:
        if current_folder and os.path.isdir(current_folder):
            if st.button("👁️ View in Explorer", use_container_width=True, key="view_folder_btn"):
                open_folder_in_explorer(current_folder)
        else:
            st.button("👁️ View in Explorer", use_container_width=True, disabled=True, key="view_folder_btn_disabled")
    
    # Save manual path
    if manual_path != current_folder:
        if st.button("💾 Save Path", use_container_width=True, key="save_manual_path"):
            if os.path.isdir(manual_path):
                set_screenshot_folder(cfg, manual_path)
                st.success(f"Screenshot folder saved: `{manual_path}`")
                st.rerun()
            else:
                st.error("The specified path does not exist. Please create the folder first or use the Open Folder button.")