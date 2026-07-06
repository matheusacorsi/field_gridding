import streamlit as st
import pandas as pd
import math
import simplekml
import io
import os
import re
import json
import tempfile
import zipfile
from geopy.distance import geodesic
import folium
from folium import plugins
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

# Try importing geopandas for Shapefile creation
try:
    import geopandas as gpd
    HAS_GPD = True
except ImportError:
    HAS_GPD = False

# --- HELPER FUNCTIONS ---
def dms_to_dd(deg, min, sec, direction):
    dd = float(deg) + (float(min) / 60.0) + (float(sec) / 3600.0)
    if direction.upper() in ['S', 'W']: return -dd
    return dd

def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def move_point(start_pt, bearing, distance_m):
    if distance_m == 0: return start_pt
    new_pt = geodesic(meters=distance_m).destination(start_pt, bearing)
    return (new_pt.latitude, new_pt.longitude)

def get_base_map(center_lat, center_lon, zoom=18):
    """Returns a Folium map optimized for mobile tracking with no auto-refreshing."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True, max_zoom=30)
    
    # max_native_zoom prevents the map from turning gray when you zoom in close
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Satellite', max_native_zoom=18, max_zoom=30, overlay=False
    ).add_to(m)
    
    # Tracks the user smoothly via Javascript without telling Python (prevents flashing)
    plugins.LocateControl(
        position="topleft", drawCircle=True, flyTo=True, keepCurrentZoomLevel=True,
        strings={"title": "Track my live location"}, auto_start=True,
        locateOptions={"enableHighAccuracy": True, "maximumAge": 0, "timeout": 10000, "watch": True}
    ).add_to(m)
    
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid", layout="centered")
st.title("🌱 Field Trial Grid")

# Initialize Session State Variables
if 'generated' not in st.session_state: st.session_state.generated = False
if 'p1_saved' not in st.session_state: st.session_state.p1_saved = False
if 'p2_saved' not in st.session_state: st.session_state.p2_saved = False

# Grid Dimension State 
if 'rows' not in st.session_state: st.session_state.rows = 10
if 'cols' not in st.session_state: st.session_state.cols = 4
if 'plot_len' not in st.session_state: st.session_state.plot_len = 5.0
if 'plot_wid' not in st.session_state: st.session_state.plot_wid = 2.0

# Starting Default Location 
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -22.4471995785483
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -47.07321466883996
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -22.4481995785483 # Slightly offset for alignment vector
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -47.07321466883996


# ==========================================
# 1. TOP SECTION: THE MAP CONTAINER
# ==========================================
map_container = st.container()


# ==========================================
# 2. BOTTOM SECTION: CAPTURE HUB
# ==========================================
if not st.session_state.generated:
    st.divider()
    st.subheader("🎯 Capture Location")
    st.caption("1. Tap the icon below to read your GNSS. 2. Choose A or B to save it.")
    
    # The Geolocation Button
    gps_loc = streamlit_geolocation()
    
    # Save Buttons
    c1, c2 = st.columns(2)
    if c1.button("📍 Save Point A (Start)", use_container_width=True):
        if gps_loc and gps_loc.get('latitude'):
            st.session_state.p1_lat = float(gps_loc['latitude'])
            st.session_state.p1_lon = float(gps_loc['longitude'])
            st.session_state.p1_saved = True
            st.rerun()
        else:
            st.warning("⚠️ Tap the 'Get Location' icon above first!")
            
    if c2.button("📍 Save Point B (Aim)", use_container_width=True):
        if gps_loc and gps_loc.get('latitude'):
            st.session_state.p2_lat = float(gps_loc['latitude'])
            st.session_state.p2_lon = float(gps_loc['longitude'])
            st.session_state.p2_saved = True
            st.rerun()
        else:
            st.warning("⚠️ Tap the 'Get Location' icon above first!")

    # Grid Configuration (Saved firmly to session_state)
    with st.expander("📐 Grid Dimensions", expanded=True):
        col1, col2 = st.columns(2)
        st.session_state.rows = col1.number_input("Rows", min_value=1, value=st.session_state.rows, step=1)
        st.session_state.cols = col2.number_input("Columns", min_value=1, value=st.session_state.cols, step=1)
        col3, col4 = st.columns(2)
        st.session_state.plot_len = col3.number_input("Length (m)", min_value=0.1, value=st.session_state.plot_len, step=0.5)
        st.session_state.plot_wid = col4.number_input("Width (m)", min_value=0.1, value=st.session_state.plot_wid, step=0.5)
        
    # Manual Coordinate View/Edit
    with st.expander("✏️ View/Edit Coordinates", expanded=False):
        input_format = st.radio("Format", ["Decimal Degrees (DD)", "GMS (Single Smart Field)"])
        
        if input_format == "Decimal Degrees (DD)":
            st.write("Edit manually if needed. Coordinates update automatically when you save points above.")
            new_p1_lat = st.number_input("Point A Lat", value=st.session_state.p1_lat, format="%.8f")
            new_p1_lon = st.number_input("Point A Lon", value=st.session_state.p1_lon, format="%.8f")
            new_p2_lat = st.number_input("Point B Lat", value=st.session_state.p2_lat, format="%.8f")
            new_p2_lon = st.number_input("Point B Lon", value=st.session_state.p2_lon, format="%.8f")
            
            if st.button("Apply Manual Edit", use_container_width=True):
                st.session_state.p1_lat, st.session_state.p1_lon = new_p1_lat, new_p1_lon
                st.session_state.p2_lat, st.session_state.p2_lon = new_p2_lat, new_p2_lon
                st.session_state.p1_saved = True
                st.session_state.p2_saved = True
                st.rerun()
                
        elif input_format == "GMS (Single Smart Field)":
            st.write("**Point A (Start)**")
            lat1_smart = st.text_input("A Lat", value="22 26 49.9 S")
            lon1_smart = st.text_input("A Lon", value="47 04 23.6 W")
            st.write("**Point B (Direction)**")
            lat2_smart = st.text_input("B Lat", value="22 26 53.5 S")
            lon2_smart = st.text_input("B Lon", value="47 04 23.6 W")
            st.info("The Smart Field parsing handles coordinates on generation.")

    st.divider()

    # Generate Button
    if st.button("🚀 GENERATE FIELD GRID", type="primary", use_container_width=True):
        if not (st.session_state.p1_saved and st.session_state.p2_saved):
            st.warning("⚠️ Please save both Point A and Point B first.")
        else:
            st.session_state.generated = True
            st.rerun()


# ==========================================
# 3. RENDER LOGIC (Inside Map Container)
# ==========================================
with map_container:
    # --- PHASE 1: ALIGNMENT & CAPTURE ---
    if not st.session_state.generated:
        # Start the map at P1, Zoom 18 (~200m scale)
        m_live = get_base_map(st.session_state.p1_lat, st.session_state.p1_lon, zoom=18)
        
        # Draw the points if the user has saved them
        if st.session_state.p1_saved:
            folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A", icon=folium.Icon(color="green")).add_to(m_live)
        if st.session_state.p2_saved:
            folium.Marker([st.session_state.p2_lat, st.session_state.p2_lon], tooltip="Point B", icon=folium.Icon(color="red")).add_to(m_live)
        if st.session_state.p1_saved and st.session_state.p2_saved:
            folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_live)

        # returned_objects=[] guarantees the map never flashes or forces Streamlit to rerun
        st_folium(m_live, use_container_width=True, height=450, returned_objects=[])

    # --- PHASE 2: GRID GENERATION & EXPORTS ---
    else:
        start_point = (st.session_state.p1_lat, st.session_state.p1_lon)
        bearing = calculate_bearing(st.session_state.p1_lat, st.session_state.p1_lon, st.session_state.p2_lat, st.session_state.p2_lon)
        bearing_perp = (bearing + 90) % 360
        
        plot_data = []
        # Uses session_state for grid dimensions here
        for r in range(st.session_state.rows):
            for c in range(st.session_state.cols):
                dist_down = r * st.session_state.plot_len
                dist_across = c * st.session_state.plot_wid
                
                pt1 = move_point(move_point(start_point, bearing, dist_down), bearing_perp, dist_across) 
                pt2 = move_point(pt1, bearing, distance_m=st.session_state.plot_len) 
                pt3 = move_point(pt2, bearing_perp, distance_m=st.session_state.plot_wid) 
                pt4 = move_point(pt1, bearing_perp, distance_m=st.session_state.plot_wid) 
                
                plot_data.append({
                    "Plot_ID": f"{c+1}{(r+1):02d}", "Row": r + 1, "Col": c + 1,
                    "Corners_DD": [pt1, pt2, pt3, pt4]
                })

        outside_corners = [
            start_point, 
            move_point(start_point, bearing, st.session_state.rows * st.session_state.plot_len), 
            move_point(move_point(start_point, bearing, st.session_state.rows * st.session_state.plot_len), bearing_perp, st.session_state.cols * st.session_state.plot_wid), 
            move_point(start_point, bearing_perp, st.session_state.cols * st.session_state.plot_wid)
        ]

        st.success("✅ Grid Generated! Review on the map before exporting.")
        
        m_grid = get_base_map(start_point[0], start_point[1], zoom=19)

        # Draw the Alignment Vector and Plots
        folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_grid)
        folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A", icon=folium.Icon(color="green")).add_to(m_grid)
        
        for plot in plot_data:
            coords = plot["Corners_DD"].copy()
            coords.append(coords[0]) 
            folium.Polygon(locations=coords, color="white", weight=1, fill=True, fill_color="green", fill_opacity=0.3, tooltip=f"Plot {plot['Plot_ID']}").add_to(m_grid)

        # Auto-zoom map to fit the generated grid perfectly
        sw = (min([lat for lat, lon in outside_corners]), min([lon for lat, lon in outside_corners]))
        ne = (max([lat for lat, lon in outside_corners]), max([lon for lat, lon in outside_corners]))
        m_grid.fit_bounds([sw, ne])

        st_folium(m_grid, use_container_width=True, height=450, returned_objects=[])

        # --- EXPORT LOGIC ---
        st.subheader("💾 Download Formats")
        
        # 1. Serpentine Stakeout Routing (For Emlid Flow)
        stake_points = []
        stake_id = 1
        for r in range(st.session_state.rows):
            col_sequence = range(st.session_state.cols) if r % 2 == 0 else reversed(range(st.session_state.cols))
            for c in col_sequence:
                p = next(plot for plot in plot_data if plot["Row"] == r+1 and plot["Col"] == c+1)
                bl_lat, bl_lon = p["Corners_DD"][0] 
                stake_points.append({"Stake_ID": f"S{stake_id:03d}", "Plot_ID": p["Plot_ID"], "Lat": bl_lat, "Lon": bl_lon})
                stake_id += 1

        # 2. KML File Generation
        kml = simplekml.Kml()
        fold_poly = kml.newfolder(name="Plots")
        for p in plot_data:
            coords = [(lon, lat) for lat, lon in p["Corners_DD"]]
            coords.append(coords[0])
            pol = fold_poly.newpolygon(name=p["Plot_ID"], outerboundaryis=coords)
            pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)
        
        fold_stakes = kml.newfolder(name="Serpentine Stakeout")
        for st_pt in stake_points:
            pnt = fold_stakes.newpoint(name=st_pt["Stake_ID"], description=f"Plot {st_pt['Plot_ID']} BL", coords=[(st_pt["Lon"], st_pt["Lat"])])
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_square.png'
        kml_string = kml.kml()

        # 3. GeoJSON Generation
        features = []
        for p in plot_data:
            coords = [[lon, lat] for lat, lon in p["Corners_DD"]]
            coords.append(coords[0]) 
            features.append({"type": "Feature", "properties": {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]}, "geometry": {"type": "Polygon", "coordinates": [coords]}})
        geojson_str = json.dumps({"type": "FeatureCollection", "features": features})

        # 4. Render Buttons
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button("📥 KML (Polygons & Serpentine)", data=kml_string, file_name="field_grid.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
        with dl_col2:
            st.download_button("📥 GeoJSON File", data=geojson_str, file_name="field_grid.geojson", mime="application/geo+json", use_container_width=True)

        # 5. Shapefile Generation
        if HAS_GPD:
            try:
                gdf = gpd.GeoDataFrame.from_features(json.loads(geojson_str)["features"])
                gdf.set_crs(epsg=4326, inplace=True)
                
                shp_io = io.BytesIO()
                with tempfile.TemporaryDirectory() as tmpdir:
                    gdf.to_file(os.path.join(tmpdir, "field_grid.shp"))
                    with zipfile.ZipFile(shp_io, 'w') as zipf:
                        for filename in os.listdir(tmpdir):
                            zipf.write(os.path.join(tmpdir, filename), filename)
                shp_io.seek(0)
                st.download_button("📥 Shapefile (ZIP format)", data=shp_io, file_name="field_grid_shapefile.zip", mime="application/zip", use_container_width=True)
            except Exception as e:
                st.error(f"Shapefile generation error: {e}")
        else:
            st.info("💡 Tip: Add `geopandas` to your requirements.txt to enable Shapefile downloads.")

        st.write("---")
        if st.button("🔙 Adjust Grid Settings", use_container_width=True):
            st.session_state.generated = False
            st.rerun()
