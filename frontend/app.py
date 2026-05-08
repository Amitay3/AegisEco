import streamlit as st
import os
from utils.db_connector import run_query
from utils.permissions import has_access

# Calculate the exact absolute path to the images
current_dir = os.path.dirname(os.path.abspath(__file__))
logo_path = os.path.join(current_dir, "assets", "logo.jpg")
favicon_path = os.path.join(current_dir, "assets", "favicon.jpg")

# 1. PAGE CONFIGURATION (Must be the first Streamlit command)
st.set_page_config(
    page_title="AegisEco Dashboard",
    page_icon=favicon_path,
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. CUSTOM CSS - Styling for the Status Banner and UI elements
st.markdown("""
    <style>
    /* Main Status Banner Styling */
    .main-status-box {
        padding: 25px;
        border-radius: 12px;
        color: white;
        text-align: center;
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 20px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    }
    .status-ok {
        background: linear-gradient(90deg, #28a745, #218838);
    }
    .status-danger {
        background: linear-gradient(90deg, #dc3545, #c82333);
        animation: pulse-red 2s infinite;
    }
    
    /* Animation for the danger status */
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(220, 53, 69, 0.7); }
        70% { box-shadow: 0 0 0 15px rgba(220, 53, 69, 0); }
        100% { box-shadow: 0 0 0 0 rgba(220, 53, 69, 0); }
    }
    </style>
    """, unsafe_allow_html=True)

# 3. SIDEBAR - Branding and Navigation
with st.sidebar:
    # Use the absolute path to load the logo
    st.image(logo_path, use_container_width=True)
    st.divider()
    
    st.header("System Settings")
    user_role = st.selectbox(
        "Select User Role:",
        ["Citizen", "City", "Authority"],
        help="Change access level to view different system modules"
    )
    
    st.sidebar.divider()
    st.sidebar.info(f"Connected as: **{user_role}**")

# 4. GLOBAL STATUS BANNER (MOCK)
is_flood_danger = False 
if is_flood_danger:
    st.markdown(
        '<div class="main-status-box status-danger">⚠️ FLOOD DANGER DETECTED - EMERGENCY PROTOCOLS ACTIVE</div>', 
        unsafe_allow_html=True
    )
else:
    st.markdown(
        '<div class="main-status-box status-ok">✅ ALL SYSTEMS NORMAL - NO IMMEDIATE THREATS</div>', 
        unsafe_allow_html=True
    )

# 5. DYNAMIC TABS GENERATION - Based on permissions.py logic
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

# Create the tabs object
tabs = st.tabs(available_tabs)
tab_index = 0

# --- TAB: RISK MAP ---
if has_access(user_role, "view_risk_map"):
    with tabs[tab_index]:
        st.subheader("Regional Risk Assessment")
        st.write("Visualizing real-time sensor data and hydrological analysis.")
        st.info("The GIS mapping component is currently being integrated with PostGIS.")
    tab_index += 1

# --- TAB: CITY CONTROL CENTER ---
if has_access(user_role, "view_city_dashboard"):
    with tabs[tab_index]:
        st.subheader("🏙️ City Level Dashboard")
        st.write("Search and select your municipality to view localized data and alerts.")
        
        # Fetch the list of all settlements
        try:
            # Updated query to use name_eng instead of name
            settlements_df = run_query("SELECT DISTINCT name_eng FROM settlements ORDER BY name_eng;")
            city_list = settlements_df['name_eng'].tolist() if not settlements_df.empty else []
        except Exception as e:
            st.error(f"Failed to fetch settlements from DB: {e}")
            city_list = []

        if city_list:
            selected_city = st.selectbox("Type to search for your city:", city_list)
            st.divider()

            if selected_city:
                safe_city_name = selected_city.replace("'", "''") 
                try:
                    # Updated query to use name_eng instead of name
                    city_data_query = f"""
                        SELECT name_eng, current_6h_forecast, next_6h_forecast 
                        FROM settlements 
                        WHERE name_eng = '{safe_city_name}' 
                        LIMIT 1;
                    """
                    city_df = run_query(city_data_query)

                    if not city_df.empty:
                        city_row = city_df.iloc[0]
                        
                        # Updated to use name_eng
                        st.markdown(f"### Status for **{city_row['name_eng']}**")
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric(label="Current 6H Forecast (mm)", value=city_row['current_6h_forecast'])
                        with col2:
                            st.metric(label="Next 6H Forecast (mm)", value=city_row['next_6h_forecast'])
                        with col3:
                            # Placeholder for future feature
                            st.metric(label="Rainfall Last Hour (mm)", value="to be implemented", delta="to be implemented", delta_color="yellow")
                        
                        st.write("") 
                        
                        # Mock alert logic based on forecast values
                        has_local_alert = city_row['current_6h_forecast'] > 0 or city_row['next_6h_forecast'] > 0  # temporary condition for demonstration
                        
                        if has_local_alert:
                            # Updated to use name_eng
                            st.error(f"🚨 ACTIVE FLOOD WARNING FOR {city_row['name_eng'].upper()}")
                            st.warning("""
                            **Required Municipality Actions:**
                            1. Deploy municipal pumps to known low-elevation areas.
                            2. Clear drainage grates and sewage entries immediately.
                            3. Prepare emergency response teams for deployment.
                            """)
                        else:
                            # Updated to use name_eng
                            st.success(f"✅ No active warnings for {city_row['name_eng']}. Conditions are optimal.")
                            
                except Exception as e:
                    st.error(f"Error loading data for {selected_city}: {e}")
        else:
            st.warning("No cities found in the database. Please check the 'settlements' table.")
            
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