import streamlit as st

from core.config import load_config

# Page config must be called exactly once, in the entry-point script.
st.set_page_config(layout="wide", page_title="Deriv Synthetic Indices Dashboard", page_icon="🎯")

# Load config once per session; individual pages read/write st.session_state.app_config
# so changes (broker profile switch, risk params) are immediately visible everywhere.
if "app_config" not in st.session_state:
    st.session_state.app_config = load_config()

dashboard_page = st.Page("app_pages/dashboard.py", title="Dashboard", icon="📊", default=True)
advisor_page = st.Page("app_pages/indices_advisor.py", title="Indices Advisor", icon="🎯")
journal_page = st.Page("app_pages/journal.py", title="Journal", icon="📓")
trading_plan_page = st.Page("app_pages/trading_plan.py", title="Trading Plan", icon="📈")
settings_page = st.Page("app_pages/settings.py", title="Settings", icon="⚙️")

pg = st.navigation([dashboard_page, advisor_page, journal_page, trading_plan_page, settings_page])
pg.run()