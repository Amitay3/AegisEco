import streamlit as st
import folium
from streamlit_folium import st_folium
import json
import os
import pandas as pd
from utils.db_connector import run_query
from streamlit_autorefresh import st_autorefresh

@st.cache_data
def load_geojson_data(file_path: str):
    """Loads cached GeoJSON geometry data."""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

@st.cache_data(ttl=120)
def fetch_all_basins_data():
    """Fetches and caches all basin data and statuses."""
    query = """
        SELECT 
            d.basin_name,
            d.main_roads,
            m.main_basin_name,
            m.name_heb,
            m.has_flood_alert,
            m.flood_probability
        FROM basins d
        LEFT JOIN main_basins_status m ON d.main_basin_name = m.main_basin_name;
    """
    try:
        return run_query(query)
    except Exception as e:
        st.toast(f"Error fetching basins data: {e}")
        return pd.DataFrame()

@st.fragment
def map_and_details_fragment(all_data_df, alert_sub_basins, geojson_data):
    center_loc = [31.5, 34.8]
    zoom_lvl = 7
    
    has_location = st.session_state.get('user_lat') is not None and st.session_state.get('user_lon') is not None
    
    if has_location:
        center_loc = [st.session_state.user_lat, st.session_state.user_lon]
        zoom_lvl = 8 
        
    m = folium.Map(location=center_loc, zoom_start=zoom_lvl, tiles="cartodbpositron")
    
    m.get_root().header.add_child(folium.Element("""
        <style>svg path:focus { outline: none !important; }</style>
    """))

    if has_location:
        folium.Marker(
            location=[st.session_state.user_lat, st.session_state.user_lon],
            tooltip="My Location",
            icon=folium.Icon(color="green", icon="map-marker", prefix='fa') 
        ).add_to(m)

    if geojson_data:
        def style_function(feature):
            sub_basin_name = feature['properties'].get('b_n_eng')
            is_flooded = sub_basin_name in alert_sub_basins
            is_selected = sub_basin_name == st.session_state.selected_basin
             
            if is_selected:
                return {
                    'fillColor': '#8b0000' if is_flooded else '#00008b',
                    'color': 'black', 
                    'weight': 3.0, 
                    'fillOpacity': 0.9
                }
            return {
                'fillColor': '#dc3545' if is_flooded else '#1f77b4',
                'color': 'black', 
                'weight': 0.8, 
                'fillOpacity': 0.7 if is_flooded else 0.3
            }

        def highlight_function(feature):
            sub_basin_name = feature['properties'].get('b_n_eng')
            is_flooded = sub_basin_name in alert_sub_basins
            
            return {
                'fillColor': '#8b0000' if is_flooded else '#003366', 
                'color': 'black',
                'weight': 2.0, 
                'fillOpacity': 0.9
            }
             
        folium.GeoJson(
            geojson_data,
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(fields=['b_n_eng'], aliases=['Basin:'], labels=True),
        ).add_to(m)
    else:
        st.warning("GeoJSON file for basins not found. Displaying base map only.")

    map_col, details_col = st.columns([3, 2], gap="large")

    with map_col:
        map_data = st_folium(m, height=650, use_container_width=True, returned_objects=["last_active_drawing"])

    with details_col:
        if map_data and map_data.get("last_active_drawing"):
            clicked_basin = map_data["last_active_drawing"]["properties"].get("b_n_eng")
            
            if clicked_basin and st.session_state.selected_basin != clicked_basin:
                st.session_state.selected_basin = clicked_basin
                st.rerun()

        if st.session_state.selected_basin:
            if not all_data_df.empty:
                basin_data = all_data_df[all_data_df['basin_name'] == st.session_state.selected_basin]
                
                if not basin_data.empty:
                    row = basin_data.iloc[0]
                    
                    st.subheader(f"{row['basin_name']}", anchor=False)
                    
                    parent_name = row['main_basin_name'] if isinstance(row['main_basin_name'], str) else "Unknown"
                    st.write(f"**Main Basin:** {parent_name}")
                    
                    if row['has_flood_alert'] == True:
                        st.error(f"FLOOD ALERT ACTIVE (Probability Index: {row['flood_probability']:.1f})")
                    elif row['has_flood_alert'] == False:
                        st.success(f"NO FLOOD ALERT (Probability Index: {row['flood_probability']:.1f})")
                    else:
                        st.info("No ML inference data available yet.")

                    st.write("")
                    
                    roads_data = row['main_roads']
                    roads_list = []
                    
                    if isinstance(roads_data, (list, tuple)):
                        roads_list = list(roads_data)
                    elif isinstance(roads_data, str) and roads_data.strip():
                        clean_str = roads_data.replace('""', '"').replace('[', '').replace(']', '').replace('{', '').replace('}', '')
                        roads_list = [r.strip(' "\'') for r in clean_str.split(',') if r.strip(' "\'')]
                    
                    st.write("**Affected Routes in this area:**")
                    
                    if roads_list and roads_list[0].lower() != 'null':
                        main_highways = []
                        local_routes = []
                        
                        for r in roads_list:
                            try:
                                road_num = int(r)
                                if road_num < 100:
                                    main_highways.append(road_num)
                                else:
                                    local_routes.append(road_num)
                            except ValueError:
                                pass
                                
                        main_highways.sort()
                        local_routes.sort()
                        
                        if main_highways:
                            st.markdown(f"**Main Routes:** {', '.join(map(str, main_highways))}")
                        if local_routes:
                            st.markdown(f"**Small Routes:** {', '.join(map(str, local_routes))}")
                        
                        if not main_highways and not local_routes:
                            st.write("None / Unknown")
                    else:
                        st.write("None / Unknown")

                else:
                    st.warning(f"No database records found for sub-basin: {st.session_state.selected_basin}")
            else:
                st.error("Cannot load basin details: Database data is currently unavailable.")
        else:
            st.info("Click on a region on the map to view detailed risk assessment and affected routes.")

def render_risk_map():
    if 'selected_basin' not in st.session_state:
        st.session_state.selected_basin = None

    # Auto-refresh every 2 minutes
    count = st_autorefresh(interval=120000, limit=None, key="risk_map_refresh")
    
    st.subheader("Regional Alerts Map", anchor=False)
    st.write("Visualizing real-time flood risk")
    st.markdown("---")
    
    all_data_df = fetch_all_basins_data()
    
    alert_sub_basins = set() 
    if not all_data_df.empty:
        alerts_df = all_data_df[all_data_df['has_flood_alert'] == True]
        alert_sub_basins = set(alerts_df['basin_name'].tolist())

    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "basins.geojson")
    geojson_data = load_geojson_data(data_path)
    
    map_and_details_fragment(all_data_df, alert_sub_basins, geojson_data)