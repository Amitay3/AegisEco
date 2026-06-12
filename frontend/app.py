import streamlit as st
import os
import time 
from utils.db_connector import run_query
from utils.permissions import has_access
from components.risk_map import render_risk_map

# Calculate the exact absolute path to the images
current_dir = os.path.dirname(os.path.abspath(__file__))
logo_path = os.path.join(current_dir, "assets", "logo.jpg")
favicon_path = os.path.join(current_dir, "assets", "favicon.jpg")

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="AegisEco Dashboard",
    page_icon=favicon_path,
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. CUSTOM CSS
st.markdown("""
    <style>
    .main-status-box {
        padding: 25px;
        border-radius: 12px;
        color: white;
        text-align: center;
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 10px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }
    .status-ok {
        background: linear-gradient(90deg, #28a745, #218838);
    }
    .status-danger {
        background: linear-gradient(90deg, #dc3545, #c82333);
        animation: pulse-red 2s infinite;
    }
    .danger-subtext {
        font-size: 18px;
        font-weight: normal;
        margin-top: 10px;
    }
    .connection-badge {
        text-align: right;
        font-size: 14px;
        font-weight: 500;
        margin-bottom: 20px;
        padding-right: 5px;
    }
    .conn-online {
        color: #28a745;
    }
    .conn-offline {
        color: #dc3545;
        font-weight: bold;
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(220, 53, 69, 0.7); }
        70% { box-shadow: 0 0 0 15px rgba(220, 53, 69, 0); }
        100% { box-shadow: 0 0 0 0 rgba(220, 53, 69, 0); }
    }
    </style>
    """, unsafe_allow_html=True)

# Fetch the global city list once to be used in both the sidebar and the main tab
city_list = []
try:
    settlements_df = run_query("SELECT DISTINCT name_eng FROM settlements ORDER BY name_eng;")
    if not settlements_df.empty:
        city_list = settlements_df['name_eng'].tolist()
except Exception as e:
    st.error(f"Failed to fetch settlements from DB: {e}")

# Initialize global state for the selected city
if 'selected_city' not in st.session_state:
    st.session_state.selected_city = None

# 3. SIDEBAR
with st.sidebar:
    st.image(logo_path, use_container_width=True)
    st.divider()
    
    st.header("System Settings")
    user_role = st.selectbox(
        "Select User Role:",
        ["Citizen", "City", "Authority"],
        help="Change access level to view different system modules"
    )
    
    # Contextual input for City role
    if user_role == "City":
        st.write("Municipality Configuration")
        sidebar_city = st.selectbox(
            "Select your municipality:",
            options=city_list,
            index=None,
            placeholder="Type to search..."
        )
        if sidebar_city:
            st.session_state.selected_city = sidebar_city
    else:
        # Clear the specific city context if role changes
        st.session_state.selected_city = None
    
    st.sidebar.divider()
    st.sidebar.info(f"Connected as: {user_role}")

# 4. GLOBAL STATUS BANNER
alert_basins = []
try:
    cache_buster = int(time.time() // 30)
    banner_query = f"""
        /* Cache Buster: {cache_buster} */
        SELECT main_basin_name 
        FROM main_basins_status 
        WHERE has_flood_alert = TRUE;
    """
    banner_df = run_query(banner_query)
    if not banner_df.empty:
        alert_basins = banner_df['main_basin_name'].tolist()
except Exception as e:
    pass

if alert_basins:
    basins_str = ", ".join(alert_basins)
    st.markdown(
        f'<div class="main-status-box status-danger">FLOOD DANGER DETECTED IN: {basins_str.upper()}<div class="danger-subtext">EMERGENCY PROTOCOLS ACTIVE</div></div>', 
        unsafe_allow_html=True
    )
else:
    st.markdown('<div class="main-status-box status-ok">ALL SYSTEMS NORMAL - NO IMMEDIATE THREATS</div>', unsafe_allow_html=True)

# LIVE CONNECTION STATUS INDICATOR
if 'db_offline_since' not in st.session_state:
    st.session_state.db_offline_since = None
if 'last_successful_update' not in st.session_state:
    st.session_state.last_successful_update = time.strftime('%H:%M')

is_stale = False
if st.session_state.db_offline_since is not None:
    if (time.time() - st.session_state.db_offline_since) > 60:
        is_stale = True

if is_stale:
    st.markdown(
        f'<div class="connection-badge conn-offline">SYSTEM OFFLINE - CONNECTION ISSUES - LAST UPDATE {st.session_state.last_successful_update}</div>', 
        unsafe_allow_html=True
    )
else:
    st.markdown(
        f'<div class="connection-badge conn-online">SYSTEM ONLINE - LAST UPDATE {st.session_state.last_successful_update}</div>', 
        unsafe_allow_html=True
    )

# 5. DYNAMIC TABS GENERATION
available_tabs = []
if has_access(user_role, "view_risk_map"):
    available_tabs.append("Risk Map")
if has_access(user_role, "view_city_dashboard"):
    available_tabs.append("City Control Center")
if has_access(user_role, "view_basins_data"):
    available_tabs.append("Councils Info")
if has_access(user_role, "view_system_logs"):
    available_tabs.append("System Logs")
if has_access(user_role, "view_social_feed"):
    available_tabs.append("Social Updates")

tabs = st.tabs(available_tabs)
tab_index = 0

# --- TAB: RISK MAP ---
if has_access(user_role, "view_risk_map"):
    with tabs[tab_index]:
        render_risk_map()
    tab_index += 1

# --- TAB: CITY CONTROL CENTER ---
if has_access(user_role, "view_city_dashboard"):
    with tabs[tab_index]:
        st.subheader("City Level Dashboard")
        
        # Determine which city to display based on user role and state
        active_city = None
        
        if user_role == "City":
            if st.session_state.selected_city:
                active_city = st.session_state.selected_city
                st.write("Displaying localized data and alerts for your configured municipality.")
            else:
                st.info("Please configure your municipality in the sidebar menu.")
        else:
            # For Authority or Citizen, allow searching globally
            st.write("Search and select a municipality to view localized data and alerts.")
            if city_list:
                active_city = st.selectbox(
                    "Search Database:",
                    options=city_list,
                    index=None,
                    placeholder="Start typing..."
                )

        st.divider()

        if active_city:
            safe_city_name = active_city.replace("'", "''") 
            try:
                city_data_query = f"""
                    SELECT 
                        s.name_eng, 
                        s.current_6h_forecast, 
                        s.next_6h_forecast,
                        m.has_flood_alert
                    FROM settlements s
                    LEFT JOIN basins b ON s.basin_name = b.basin_name
                    LEFT JOIN main_basins_status m ON b.main_basin_name = m.main_basin_name
                    WHERE s.name_eng = '{safe_city_name}' 
                    LIMIT 1;
                """
                city_df = run_query(city_data_query)

                if not city_df.empty:
                    city_row = city_df.iloc[0]
                    
                    st.markdown(f"### Status for **{city_row['name_eng']}**")
                    
                    # 1. Display Alert Status First
                    has_local_alert = city_row.get('has_flood_alert', False) == True
                    
                    if has_local_alert:
                        st.error(f"ACTIVE FLOOD WARNING FOR {city_row['name_eng'].upper()} AREA")
                        st.warning(
                            "**Required Municipality Actions:**\n"
                            "1. Deploy municipal pumps to known low-elevation areas.\n"
                            "2. Clear drainage grates and sewage entries immediately.\n"
                            "3. Prepare emergency response teams for deployment."
                        )
                    else:
                        st.success(f"NO FLOOD ALERT. Conditions are optimal for {city_row['name_eng']}.")
                        
                    st.write("") 
                    
                    # 2. Conditional Forecast Display
                    has_forecast = city_row['current_6h_forecast'] != -1 and city_row['next_6h_forecast'] != -1
                    
                    if has_forecast:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric(label="Current 6H Forecast (mm)", value=city_row['current_6h_forecast'])
                        with col2:
                            st.metric(label="Next 6H Forecast (mm)", value=city_row['next_6h_forecast'])
                    else:
                        st.info("No 6-hour forecast data available for this municipality.")
                        
            except Exception as e:
                st.error(f"Error loading data for {active_city}: {e}")

    tab_index += 1

# --- TAB: COUNCILS INFO ---
if has_access(user_role, "view_basins_data"):
    with tabs[tab_index]:
        st.subheader("Regional Councils Registry")
        st.write("Live data from the 'councils' database table:")
        try:
            councils_df = run_query("SELECT * FROM councils;") 
            st.dataframe(councils_df, use_container_width=True)
        except Exception as e:
            st.error(f"Error fetching data: {e}")
    tab_index += 1

# --- TAB: SYSTEM LOGS ---
if has_access(user_role, "view_system_logs"):
    with tabs[tab_index]:
        st.subheader("Live Agent Activity")
        st.write("Monitoring internal communications between AI agents:")
        st.code("""
        real time logs will be displayed here
        """, language="bash")
    tab_index += 1

# --- TAB: SOCIAL UPDATES ---
if has_access(user_role, "view_social_feed"):
    with tabs[tab_index]:
        st.subheader("Social Media Monitoring")
        st.write("Aggregated reports from Twitter and Facebook:")
        st.warning("Social listening agents are currently inactive.")
    tab_index += 1