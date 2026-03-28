import streamlit as st
import json
import os
import pandas as pd
import time
import sqlite3 # Added sqlite3 import

STATE_FILE = "state.json" # This file is no longer used for loading state, but might be referenced elsewhere or kept for legacy.
DB_FILE = "grid_state.db" # New constant for the database file

st.set_page_config(page_title="Grid Bot Dashboard", layout="wide")
st.title("🤖 Grid Bot 2026 Dashboard")

@st.cache_data(ttl=5)
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error reading state: {e}")
    return None

state = load_state()

if not state:
    st.warning(f"No {STATE_FILE} found. Is the bot running? Ensure you are in the bot directory.")
else:
    st.header(f"📈 Symbol: {state.get('symbol', 'UNKNOWN')}")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Profit", f"${state.get('total_profit', 0):.2f}")
    with col2:
        st.metric("Total Trades", state.get('total_trades', 0))
    with col3:
        st.metric("Grid Upper", f"{state.get('upper', 0):.4f}")
    with col4:
        st.metric("Grid Lower", f"{state.get('lower', 0):.4f}")
        
    st.divider()
    
    st.subheader("Active Grid Levels")
    levels = state.get("levels", [])
    if levels:
        df = pd.DataFrame(levels)
        
        # Format the dataframe columns if they exist
        if 'filled_at' in df.columns:
            df['filled_at'] = df['filled_at'].fillna('-')
            
        # Optional: Add colors for Buy/Sell
        def style_sides(row):
            if row['side'] == 'Buy':
                return ['background-color: rgba(0, 255, 0, 0.1)'] * len(row)
            elif row['side'] == 'Sell':
                return ['background-color: rgba(255, 0, 0, 0.1)'] * len(row)
            return [''] * len(row)
            
        st.dataframe(df.style.apply(style_sides, axis=1), use_container_width=True)
    else:
        st.info("No active grid levels found in state.")

    # Refresh button using fragment / rerun logic loosely
    st.button("🔄 Refresh Data")
    
    start = state.get('started_at', 'Unknown')
    st.caption(f"Bot started at: {start}")
