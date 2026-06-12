import streamlit as st
import folium
from streamlit_folium import st_folium
import json
import os
import time
import pandas as pd
from utils.db_connector import run_query
from streamlit_autorefresh import st_autorefresh

def render_risk_map():
    """
    Renders the interactive Folium map. Dynamically colors sub-basins 
    based on the alert status of their parent main basin, and displays 
    detailed info (roads, probability) on click using a SQL JOIN.
    """
    # Initialize session state to remember the clicked basin
    if 'selected_basin' not in st.session_state:
        st.session_state.selected_basin = None

    # Auto-refresh the page every 30 seconds
    count = st_autorefresh(interval=30000, limit=None, key="risk_map_refresh")
    
    st.subheader("Regional Risk Assessment")
    st.write(f"Visualizing real-time flood risk based on ML inference.")
    st.markdown("---")
    
    # 1. Fetch live alert data for Map Coloring
    alert_sub_basins = []
    try:
        cache_buster = int(time.time() // 30)
        
        query_alerts = f"""
            /* Cache Buster: {cache_buster} */
            SELECT d.basin_name
            FROM basins d
            JOIN main_basins_status m ON d.main_basin_name = m.main_basin_name
            WHERE m.has_flood_alert = TRUE;
        """
        alerts_df = run_query(query_alerts)
        if not alerts_df.empty:
            alert_sub_basins = alerts_df['basin_name'].tolist()
    except Exception as e:
        st.toast("Could not fetch alert statuses.")
        time.sleep(1)
        st.toast("↻ Retrying to fetch data...")


    # 2. Initialize the map
    m = folium.Map(location=[31.5, 34.8], zoom_start=7, tiles="cartodbpositron")
    
    # Inject Custom CSS to remove the blue focus outline
    m.get_root().header.add_child(folium.Element("""
        <style>
        svg path:focus {
            outline: none !important;
        }
        </style>
    """))

    # 3. Load GeoJSON file
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "basins.geojson")
    
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
            
        def style_function(feature):
            """Applies default styling, keeping the selected basin permanently highlighted"""
            sub_basin_name = feature['properties'].get('b_n_eng')
            is_flooded = sub_basin_name in alert_sub_basins
            is_selected = sub_basin_name == st.session_state.selected_basin
             
            if is_selected:
                return {
                    'fillColor': '#8b0000' if is_flooded else '#00008b', # Dark Red / Dark Blue
                    'color': 'black', 
                    'weight': 3.0, 
                    'fillOpacity': 0.9
                }
            else:
                return {
                    'fillColor': '#dc3545' if is_flooded else '#1f77b4', # Normal Red / Normal Blue
                    'color': 'black', 
                    'weight': 0.5, 
                    'fillOpacity': 0.7 if is_flooded else 0.3
                }
            
        def highlight_function(feature):
            """Applies dynamic styling when hovering on a basin"""
            sub_basin_name = feature['properties'].get('b_n_eng')
            is_flooded = sub_basin_name in alert_sub_basins
             
            return {
                'fillColor': '#8b0000' if is_flooded else '#3232ff',
                'color': 'black', 
                'weight': 2.5,
                'fillOpacity': 0.9
            }
             
        folium.GeoJson(
            geojson_data,
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(fields=['b_n_eng'], aliases=['Basin:'])
        ).add_to(m)
    else:
        st.warning("GeoJSON file for basins not found. Displaying base map only.")

    # ==========================================
    # LAYOUT: Split screen
    # ==========================================
    map_col, details_col = st.columns([3, 2], gap="large")

    with map_col:
        map_data = st_folium(m, height=650, use_container_width=True, returned_objects=["last_active_drawing"])

    with details_col:
        # First, check if a click happened on the map and update session state
        if map_data and map_data.get("last_active_drawing"):
            clicked_basin = map_data["last_active_drawing"]["properties"].get("b_n_eng")
            
            if clicked_basin and st.session_state.selected_basin != clicked_basin:
                st.session_state.selected_basin = clicked_basin
                st.rerun()

        # Second, render the details based on the session state, NOT the active map click
        if st.session_state.selected_basin:
            safe_clicked_basin = st.session_state.selected_basin.replace("'", "''")
            cache_buster_detail = int(time.time())
            
            detail_query = f"""
                /* Cache Buster: {cache_buster_detail} */
                SELECT 
                    d.basin_name,
                    d.main_roads,
                    m.main_basin_name,
                    m.name_heb,
                    m.has_flood_alert,
                    m.flood_probability
                FROM basins d
                LEFT JOIN main_basins_status m ON d.main_basin_name = m.main_basin_name
                WHERE d.basin_name = '{safe_clicked_basin}'
                LIMIT 1;
            """
            
            try:
                detail_df = run_query(detail_query)
                
                if not detail_df.empty:
                    row = detail_df.iloc[0]
                    
                    st.subheader(f"{row['basin_name']}")
                    
                    parent_name = row['main_basin_name'] if isinstance(row['main_basin_name'], str) else "Unknown"
                    st.write(f"**Main Basin:** {parent_name}")
                    
                    if row['has_flood_alert'] == True:
                        st.error(f"FLOOD ALERT ACTIVE (Prob: {row['flood_probability']:.1f}%)")
                    elif row['has_flood_alert'] == False:
                        st.success(f"NO FLOOD ALERT (Prob: {row['flood_probability']:.1f}%)")
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
                    
                    st.write("**Affected Roads in this area:**")
                    
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
                    
            except Exception as e:
                st.error(f"Error retrieving basin details: {e}")
        else:
            st.info("Click on a basin on the map to view detailed risk assessment and affected routes.")