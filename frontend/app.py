import streamlit as st
import os
import time
from datetime import datetime
from utils.db_connector import run_query
from utils.permissions import has_access
from components.risk_map import render_risk_map
from streamlit_js_eval import get_geolocation
from datetime import datetime
from zoneinfo import ZoneInfo

def _format_relative_time(ts):
    try:
        ts = ts.to_pydatetime()
    except AttributeError:
        pass

    delta_seconds = (datetime.utcnow() - ts).total_seconds()
    if delta_seconds < 60:
        return "just now"
    if delta_seconds < 3600:
        return f"{int(delta_seconds // 60)} min ago"
    if delta_seconds < 86400:
        return f"{int(delta_seconds // 3600)}h ago"
    return f"{int(delta_seconds // 86400)}d ago"

def get_nearest_city(lat, lon):
    query = f"""
        SELECT name_eng
        FROM settlements
        ORDER BY location <-> ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)
        LIMIT 1;
    """
    try:
        df = run_query(query)
        if not df.empty:
            return df.iloc[0]['name_eng']
    except Exception:
        pass
    return None

current_dir = os.path.dirname(os.path.abspath(__file__))
logo_path = os.path.join(current_dir, "assets", "logo.jpg")
favicon_path = os.path.join(current_dir, "assets", "favicon.jpg")

st.set_page_config(
    page_title="AegisEco Dashboard",
    page_icon=favicon_path,
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    .agent-meta {
        color: #6c757d;
        font-size: 0.8rem;
    }
    .agent-status-badge {
        display: inline-block;
        float: right;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 1.5px;
        padding: 3px 10px;
        border-radius: 999px;
        border: 1px solid;
        white-space: nowrap;
    }
    .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a, .stMarkdown h4 a {
    display: none !important;
    }
    [data-testid="stSidebar"] {
        width: 150px !important;
    }
    </style>
    """, unsafe_allow_html=True)

city_list = []
try:
    settlements_df = run_query("SELECT DISTINCT name_eng FROM settlements ORDER BY name_eng;")
    if not settlements_df.empty:
        city_list = settlements_df['name_eng'].tolist()
except Exception as e:
    st.error(f"Failed to fetch settlements from DB: {e}")

if 'is_authenticated' not in st.session_state:
    st.session_state.is_authenticated = False
    st.session_state.user_role = None
    st.session_state.specific_entity = None
    st.session_state.selected_city = None
    st.session_state.user_lat = None
    st.session_state.user_lon = None
    st.session_state.request_location = False

if not st.session_state.is_authenticated:
    col1, col2, col3 = st.columns([1.5, 1.2, 1.5])
    
    with col2:
        img_col1, img_col2, img_col3 = st.columns([1, 2, 1])
        with img_col2:
            st.image(logo_path, use_container_width=True)
            
        st.markdown("<h3 style='text-align: center; margin-top: -15px;'>Welcome to AegisEco</h3>", unsafe_allow_html=True)
        st.divider()
        
        selected_role = st.selectbox(
            "Select your entity type:",
            ["Citizen", "City", "Authority"],
            index=None,
            placeholder="Select Role..."
        )
        
        selected_entity = None
        
        if selected_role == "City":
            auto_city = None
            if st.session_state.get('user_lat') is not None:
                auto_city = get_nearest_city(st.session_state.user_lat, st.session_state.user_lon)
                
            default_idx = city_list.index(auto_city) if auto_city in city_list else None
            
            col_sel, col_btn = st.columns([4, 2])
            
            with col_sel:
                selected_entity = st.selectbox(
                    "Select Municipality:",
                    options=city_list,
                    index=default_idx,
                    placeholder="Choose"
                )
                
            with col_btn:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                
                if st.button("Use my location", use_container_width=True):
                    st.session_state.request_location = True
                    st.toast("Loading location...")

            if st.session_state.get('request_location', False):
                loc = get_geolocation()
                if loc:
                    st.session_state.user_lat = loc['coords']['latitude']
                    st.session_state.user_lon = loc['coords']['longitude']
                    st.session_state.request_location = False
                    time.sleep(1)
                    st.rerun()

        elif selected_role == "Authority":
            selected_entity = st.selectbox(
                "Select Emergency Force:",
                options=["Police", "Fire & Rescue",],
                index=None,
                placeholder="Select Force..."
            )
            
        st.write("")
        
        login_disabled = True
        if selected_role == "Citizen":
            login_disabled = False
        elif selected_role in ["City", "Authority"] and selected_entity is not None:
            login_disabled = False
            
        if st.button("Enter AegisEco System", use_container_width=True, disabled=login_disabled, type="primary"):
            st.session_state.is_authenticated = True
            st.session_state.user_role = selected_role
            st.session_state.specific_entity = selected_entity
            st.rerun()
            
    st.stop()

user_role = st.session_state.user_role
active_entity = st.session_state.specific_entity

with st.sidebar:
    st.image(logo_path, use_container_width=True)
    st.divider()
    
    st.markdown("### Profile")
    st.write(f"**Role:** {user_role}")
    if active_entity:
        st.write(f"**Entity:** {active_entity}")
        
    st.divider()
    
    if st.button("Switch Profile", use_container_width=True):
        st.session_state.is_authenticated = False
        st.session_state.user_role = None
        st.session_state.specific_entity = None
        st.session_state.selected_city = None
        st.rerun()

alert_basins = []
try:
    banner_query = """
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

if 'db_offline_since' not in st.session_state:
    st.session_state.db_offline_since = None
if 'last_successful_update' not in st.session_state:
    st.session_state.last_successful_update = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime('%H:%M')

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

available_tabs = []
if has_access(user_role, "view_risk_map"):
    available_tabs.append("Risk Map")
if has_access(user_role, "view_city_dashboard"):
    available_tabs.append("City Control Center")
if has_access(user_role, "view_basins_data"):
    available_tabs.append("Councils Info")
if has_access(user_role, "view_social_feed"):
    available_tabs.append("Social Updates")

tabs = st.tabs(available_tabs)
tab_index = 0

if has_access(user_role, "view_risk_map"):
    with tabs[tab_index]:
        render_risk_map()
    tab_index += 1

if has_access(user_role, "view_city_dashboard"):
    with tabs[tab_index]:
        st.subheader("City Level Information")

        active_city = None

        if user_role == "City":
            active_city = st.session_state.specific_entity
            st.write(f"Displaying localized data and alerts for **{active_city}**.")
        else:
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
                        st.success(f"NO FLOOD ALERT for {city_row['name_eng']}.")
                        
                    st.write("") 
                    
                    has_forecast = city_row['current_6h_forecast'] != -1 and city_row['next_6h_forecast'] != -1

                    if has_forecast:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric(label="Current 6H Forecast (mm)", value=city_row['current_6h_forecast'])
                        with col2:
                            st.metric(label="Next 6H Forecast (mm)", value=city_row['next_6h_forecast'])
                    else:
                        pass

            except Exception as e:
                st.error(f"Error loading data for {active_city}: {e}")

    tab_index += 1

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

if has_access(user_role, "view_social_feed"):
    with tabs[tab_index]:
        st.subheader("Social & Field Intelligence")
        st.write("Live check-ins from the verification agents — what each one looked at, and what it found.")

        try:
            updates_df = run_query("""
                SELECT DISTINCT ON (agent_name)
                    agent_name, source_type, status, summary, details, created_at
                FROM social_updates
                ORDER BY agent_name, created_at DESC;
            """)
        except Exception:
            updates_df = None

        if updates_df is None or updates_df.empty:
            st.info("No agent activity yet. Once the agent pipeline runs, each agent's latest "
                    "check-in (OSINT, RSS, Telegram, IMS Warnings) will appear here.")
        else:
            AGENT_ORDER = ["OSINT Analyst", "RSS Analyst", "Telegram Analyst", "Warnings Monitor"]
            AGENT_ICONS = {
                "OSINT Analyst": "🔍",
                "RSS Analyst": "📰",
                "Telegram Analyst": "📡",
                "Warnings Monitor": "⚠️",
            }
            STATUS_STYLES = {
                "findings": ("FINDINGS", "#fd7e14"),
                "no_findings": ("ALL CLEAR", "#28a745"),
                "error": ("UNAVAILABLE", "#dc3545"),
            }

            updates_df["sort_order"] = updates_df["agent_name"].apply(
                lambda a: AGENT_ORDER.index(a) if a in AGENT_ORDER else len(AGENT_ORDER)
            )
            updates_df = updates_df.sort_values("sort_order")

            for _, row in updates_df.iterrows():
                icon = AGENT_ICONS.get(row["agent_name"], "🤖")
                badge_label, badge_color = STATUS_STYLES.get(row["status"], ("UPDATE", "#6c757d"))
                time_str = _format_relative_time(row["created_at"])

                with st.container(border=True):
                    head_col1, head_col2 = st.columns([5, 1])
                    with head_col1:
                        st.markdown(
                            f"**{icon} {row['agent_name']}** &nbsp;·&nbsp; <span class='agent-meta'>{time_str}</span>",
                            unsafe_allow_html=True
                        )
                    with head_col2:
                        st.markdown(
                            f'<span class="agent-status-badge" style="color:{badge_color}; border-color:{badge_color};">{badge_label}</span>',
                            unsafe_allow_html=True
                        )

                    st.write(row["summary"])

                    details = row["details"]
                    if details:
                        with st.expander(f"View {len(details)} item(s)"):
                            for item in details:
                                source_type = row["source_type"]
                                if source_type in ("rss", "osint"):
                                    title = item.get("title", "Untitled")
                                    url = item.get("url")
                                    if url:
                                        st.markdown(f"- [{title}]({url})")
                                    else:
                                        st.markdown(f"- {title}")
                                elif source_type == "telegram":
                                    st.markdown(f"- **@{item.get('channel')}** ({item.get('time')}): {item.get('text')}")
                                elif source_type == "ims_warning":
                                    st.markdown(f"- **{item.get('title')}** — {item.get('description')}")
    tab_index += 1