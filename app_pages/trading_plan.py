import streamlit as st
import pandas as pd
import datetime as dt

from core import mt5_client
from core.config import (
    load_config,
    save_trading_plan,
    delete_trading_plan,
    link_plan_to_profile,
    unlink_plan_from_profile,
    get_profile_plan,
    calculate_plan_progress,
)

st.title("📈 Trading Plan")

cfg = st.session_state.setdefault("app_config", load_config())

st.info(
    "Calculate your trading plan with compound growth. "
    "The formula used: End Balance = Starting Balance × (1 + TP%)^day",
    icon="📊",
)

# Tab navigation for creating/managing plans
tab1, tab2 = st.tabs(["Create New Plan", "Manage Saved Plans"])

# Tab 1: Create New Plan
with tab1:
    st.subheader("Plan Parameters")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        plan_name = st.text_input("Plan Name", placeholder="e.g. 30-Day Growth Plan")
    
    with col2:
        start_capital = st.number_input(
            "Starting Balance ($)",
            min_value=1.0,
            value=100.0,
            step=1.0,
            help="Initial capital to start trading with"
        )
    
    with col3:
        trading_days = st.number_input(
            "Trading Days",
            min_value=1,
            value=10,
            step=1,
            help="Total number of trading days"
        )
    
    with col4:
        challenge_duration = st.selectbox(
            "Challenge Duration",
            options=[1, 3, 6, 12],
            format_func=lambda x: f"{x} month{'s' if x > 1 else ''}",
            help="Total duration in months to spread trading days"
        )
    
    with col5:
        tp_percentage = st.number_input(
            "Daily TP (%)",
            min_value=0.1,
            value=100.0,
            step=0.1,
            help="Target profit percentage per day (compound)"
        )
    
    start_date = st.date_input(
        "Plan Start Date",
        value=dt.date.today(),
        help="The day you start following this plan"
    )
    
    st.divider()
    
    # Generate and save trading plan
    col1, col2 = st.columns(2)
    with col1:
        generate_btn = st.button("Generate Trading Plan", type="primary")
    with col2:
        save_btn = st.button("💾 Save Plan", type="secondary")
    
    if generate_btn or save_btn:
        if not plan_name.strip() and save_btn:
            st.warning("Please enter a plan name to save.")
        else:
            # Calculate the trading plan
            data = []
            
            for day in range(1, trading_days + 1):
                # Calculate end balance for this day using compound formula
                end_balance = start_capital * ((1 + tp_percentage / 100) ** day)
                
                data.append({
                    "Day": day,
                    "Starting Balance": f"${start_capital * ((1 + tp_percentage / 100) ** (day - 1)):,.2f}",
                    "Daily Profit (%)": f"{tp_percentage:.2f}%",
                    "End Balance": f"${end_balance:,.2f}",
                    "Total Growth (%)": f"{((end_balance / start_capital) - 1) * 100:.2f}%"
                })
            
            # Create DataFrame
            df = pd.DataFrame(data)
            
            # Display the table
            st.subheader("Trading Plan Table")
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
            
            # Summary statistics
            st.divider()
            st.subheader("Summary")
            
            final_balance = start_capital * ((1 + tp_percentage / 100) ** trading_days)
            total_profit = final_balance - start_capital
            total_growth = ((final_balance / start_capital) - 1) * 100
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Starting Balance", f"${start_capital:,.2f}")
            with col2:
                st.metric("Final Balance", f"${final_balance:,.2f}")
            with col3:
                st.metric("Total Profit", f"${total_profit:,.2f}", f"{total_growth:.2f}%")
            
            # Calculate trade frequency distribution
            st.divider()
            st.subheader("Trade Frequency Distribution")
            
            # Calculate weeks in the challenge duration
            weeks_in_duration = challenge_duration * 4  # Approximate 4 weeks per month
            
            # Distribute trading days across weeks
            base_trades_per_week = trading_days // weeks_in_duration
            remaining_trades = trading_days % weeks_in_duration
            
            weekly_distribution = []
            for week in range(weeks_in_duration):
                trades_this_week = base_trades_per_week + (1 if week < remaining_trades else 0)
                weekly_distribution.append(trades_this_week)
            
            # Display weekly distribution
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write("**Weekly Trading Schedule:**")
                for week_num, trades in enumerate(weekly_distribution, 1):
                    st.write(f"Week {week_num}: {trades} trade{'s' if trades != 1 else ''}")
                
                st.caption(f"Total: {sum(weekly_distribution)} trading days over {challenge_duration} month{'s' if challenge_duration > 1 else ''}")
            
            with col2:
                st.write("**Distribution Pattern:**")
                pattern = ",".join(map(str, weekly_distribution))
                st.code(pattern, language="text")
                st.caption("Pattern shows trades per week")
            
            # Display mini calendar with trade frequency
            st.divider()
            st.subheader("Calendar View")
            
            # Create a simple calendar view for the first month
            calendar_col, freq_col = st.columns([3, 1])
            
            with calendar_col:
                st.write("**Month 1 Calendar**")
                # Generate a simple calendar grid for the first month
                first_month_start = start_date
                if first_month_start.day != 1:
                    first_month_start = first_month_start.replace(day=1)
                
                # Get the first day of the month and number of days
                from calendar import monthcalendar, month_name
                cal = monthcalendar(first_month_start.year, first_month_start.month)
                
                # Display calendar
                st.write(f"**{month_name[first_month_start.month]} {first_month_start.year}**")
                days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                st.write(" | ".join(days_of_week))
                
                for week in cal:
                    week_str = " | ".join([f"{day:2}" if day != 0 else "  " for day in week])
                    st.write(week_str)
            
            with freq_col:
                st.write("**Weekly Freq**")
                for week_num, trades in enumerate(weekly_distribution[:4], 1):  # Show first 4 weeks
                    st.metric(f"W{week_num}", f"{trades}d")
            
            # Save the plan if save button was clicked
            if save_btn and plan_name.strip():
                save_trading_plan(cfg, plan_name.strip(), start_capital, trading_days, tp_percentage, start_date.strftime("%Y-%m-%d"), challenge_duration)
                st.success(f"Plan '{plan_name}' saved successfully!")
                st.rerun()

# Tab 2: Manage Saved Plans
with tab2:
    st.subheader("Saved Trading Plans")
    
    trading_plans = cfg.get("trading_plans", {})
    
    if not trading_plans:
        st.info("No saved trading plans yet. Create one in the 'Create New Plan' tab.", icon="📝")
    else:
        for plan_name, plan_data in trading_plans.items():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                
                with c1:
                    st.markdown(f"**{plan_name}**")
                    duration = plan_data.get("challenge_duration", 1)
                    st.caption(f"Start: ${plan_data['start_capital']:,.2f} · Days: {plan_data['trading_days']} · TP: {plan_data['tp_percentage']}% · {duration} month{'s' if duration > 1 else ''}")
                    if plan_data.get("start_date"):
                        st.caption(f"Start Date: {plan_data['start_date']}")
                
                with c2:
                    linked_profile = plan_data.get("linked_profile")
                    if linked_profile:
                        st.success(f"🔗 Linked to: {linked_profile}")
                    else:
                        st.caption("Not linked to any profile")
                
                with c3:
                    # Link to profile dropdown
                    profiles = cfg.get("profiles", {})
                    if profiles:
                        profile_options = ["None"] + list(profiles.keys())
                        current_profile = linked_profile if linked_profile in profiles else "None"
                        
                        selected_profile = st.selectbox(
                            "Link to Profile",
                            options=profile_options,
                            index=profile_options.index(current_profile),
                            key=f"link_{plan_name}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_profile != current_profile:
                            if selected_profile == "None":
                                unlink_plan_from_profile(cfg, linked_profile)
                                st.rerun()
                            else:
                                link_plan_to_profile(cfg, plan_name, selected_profile)
                                st.rerun()
                
                with c4:
                    if st.button("🗑️", key=f"delete_{plan_name}", help="Delete plan"):
                        delete_trading_plan(cfg, plan_name)
                        st.rerun()
            
            # Show plan progress if it has a start date
            if plan_data.get("start_date"):
                # Fetch trade history for current month for automatic tracking
                today = dt.date.today()
                month_start = dt.datetime.combine(today.replace(day=1), dt.time.min)
                month_end = dt.datetime.combine(today.replace(day=28) + dt.timedelta(days=4), dt.time.min).replace(day=1) if today.month == 12 else dt.datetime.combine(today.replace(day=1), dt.time.min).replace(month=today.month + 1)
                
                try:
                    trade_history = mt5_client.get_history_deals_df(month_start, month_end)
                except:
                    trade_history = None
                
                progress = calculate_plan_progress(plan_data, None, trade_history)
                st.divider()
                st.markdown(f"**Plan Progress for {plan_name}:**")
                
                # Display "Day X, Y days to final target" format
                if progress['current_day'] > 0:
                    st.info(f"**Day {progress['current_day']}, {progress['remaining_days']} days to get to '${progress['final_balance']:,.2f}'**", icon="🎯")
                else:
                    st.info(f"**Plan starts on {progress['start_date'].strftime('%B %d, %Y')}**", icon="📅")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Current Day", f"{progress['current_day']}/{progress['total_days']}")
                col2.metric("Expected Balance", f"${progress['expected_balance']:,.2f}")
                col3.metric("Remaining Days", progress['remaining_days'])
                col4.metric("Final Target", f"${progress['final_balance']:,.2f}")
                st.caption(f"Start Date: {progress['start_date'].strftime('%Y-%m-%d')}")
                st.divider()
