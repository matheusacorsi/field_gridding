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

def parse_coordinate(coord_str, format_type):
    if not coord_str: return 0.0
    coord_str = str(coord_str).strip()
    if format_type == "GMS (Single Smart Field)":
        dir_match = re.search(r'(?i)([NSEW])', coord_str)
        if not dir_match: raise ValueError("Missing direction (N, S, E, W)")
        direction = dir_match.group(1).upper()
        numbers = re.findall(r'\d+(?:[.,]\d+)?', coord_str)
        if len(numbers) >= 3:
            deg = float(numbers[0].replace(',', '.'))
            min_ = float(numbers[1].replace(',', '.'))
            sec = float(numbers[2].replace(',', '.'))
            dd = deg + (min_ / 60.0) + (sec / 3600.0)
            if direction in ['S', 'W']: dd = -dd
            return dd
        raise ValueError("Could not find Deg, Min, Sec")

def dd_to_dms(deg, is_lat=True):
    d = int(deg)
    m = int((abs(deg) - abs(d)) * 60)
    s = (abs(deg) - abs(d) - m/60) * 3600
    dir_ = "N" if deg >= 0 else "S" if is_lat else "E" if deg >= 0 else "W"
    return f"{abs(d)}°{m}'{s:.2f}\"{dir_}"

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

def get_centroid(corners):
    lats, lons = [pt[0] for pt in corners], [pt[1] for pt in corners]
    return (sum(lats) / len(corners), sum(lons) / len(corners))

def get_base_map(center_lat, center_lon, zoom):
    """Returns a Folium map starting at ~200m scale that tracks the live GPS location."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True, max_zoom=30)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Satellite', max_native_zoom=18, max_zoom=30, overlay=False
    ).add_to(m)
    
    # Auto-tracking plugin: Instantly flies to GPS on load and maintains the ~200m zoom level
    plugins.LocateControl(
        position="topleft", drawCircle=True, flyTo=True, keepCurrentZoomLevel=True,
        strings={"title": "Track my live location"}, auto_start=True,
        locateOptions={"enableHighAccuracy": True, "maximumAge": 0, "timeout": 10000, "watch": True}
    ).add_to(m)
    
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid", layout="centered")
st.title("🌱 Field Trial Grid")

# Initialize Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 18 # ~200m scale
if 'p1_saved' not in st.session_state: st.session_state.p1_saved = False
if 'p2_saved' not in st.session_state: st.session_state.p2_saved = False

# Default Coordinates (Used just to render the map before the GPS locks on)
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.73300000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.05800000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.73400000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.05800000


# ==========================================
# 1. TOP SECTION: THE MAP
# ==========================================
map_container = st.container()

with map_container:
    if not st.session_state.generated:
        st.info("**1.** Walk to your spot. **2. Tap the map** on your location. **3.** Click Save below.")
        
        m_live = get_base_map(st.session_state.p1_lat, st.session_state.p1_lon, st.session_state.map_zoom)
        
        # Draw saved points so the user sees their progress
        if st.session_state.p1_saved:
            folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A", icon=folium.Icon(color="green")).add_to(m_live)
        if st.session_state.p2_saved:
            folium.Marker([st.session_state.p2_lat, st.session_state.p2_lon], tooltip="Point B", icon=folium.Icon(color="red")).add_to(m_live)
        if st.session_state.p1_saved and st.session_state.p2_saved:
            folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_live)

        # Render the map and fetch clicks & zoom
        map_data = st_folium(m_live, use_container_width=True, height=450, returned_objects=["last_clicked", "zoom"])
        
        # Keep python state updated with the user's zoom so it doesn't reset on save
        if map_data and map_data.get("zoom"):
            st.session_state.map_zoom = map_data["zoom"]


# ==========================================
# 2. BOTTOM SECTION: CAPTURE BUTTONS
# ==========================================
st.divider()

if not st.session_state.generated:
    c1, c2 = st.columns(2)
    
    if c1.button("📍 Save Point A (Start)", use_container_width=True):
        if map_data and map_data.get("last_clicked"):
            st.session_state.p1_lat = map_data["last_clicked"]["lat"]
            st.session_state.p1_lon = map_data["last_clicked"]["lng"]
            st.session_state.p1_saved = True
            st.rerun()
        else:
            st.warning("⚠️ Please TAP the map on your location first, then click Save.")
            
    if c2.button("📍 Save Point B (Aim)", use_container_width=True):
        if map_data and map_data.get("last_clicked"):
            # Check if they forgot to tap a new location for Point B
            if map_data["last_clicked"]["lat"] == st.session_state.p1_lat and map_data["last_clicked"]["lng"] == st.session_state.p1_lon:
                st.warning("⚠️ You must tap the map at your NEW location for Point B before saving.")
            else:
                st.session_state.p2_lat = map_data["last_clicked"]["lat"]
                st.session_state.p2_lon = map_data["last_clicked"]["lng"]
                st.session_state.p2_saved = True
                st.rerun()
        else:
            st.warning("⚠️ Please TAP the map on your location first, then click Save.")

# --- Config Expanders ---
with st.expander("✏️ Manual Coordinate Edit", expanded=False):
    input_format = st.radio("Format", ["Decimal Degrees (DD)", "GMS (Single Smart Field)"])
    if input_format == "Decimal Degrees (DD)":
        lat1_dd = st.number_input("A Lat (DD)", value=st.session_state.p1_lat, format="%.8f")
        lon1_dd = st.number_input("A Lon (DD)", value=st.session_state.p1_lon, format="%.8f")
        lat2_dd = st.number_input("B Lat (DD)", value=st.session_state.p2_lat, format="%.8f")
        lon2_dd = st.number_input("B Lon (DD)", value=st.session_state.p2_lon, format="%.8f")
    elif input_format == "GMS (Single Smart Field)":
        lat1_smart = st.text_input("A Lat", value="25 43 58.8 S")
        lon1_smart = st.text_input("A Lon", value="53 03 28.8 W")
        lat2_smart = st.text_input("B Lat", value="25 44 02.4 S")
        lon2_smart = st.text_input("B Lon", value="53 03 28.8 W")

with st.expander("📐 Grid Dimensions", expanded=True):
    col1, col2 = st.columns(2)
    rows = col1.number_input("Rows", min_value=1, value=10, step=1)
    cols = col2.number_input("Columns", min_value=1, value=4, step=1)
    col3, col4 = st.columns(2)
    plot_len = col3.number_input("Length (m)", min_value=0.1, value=5.0, step=0.5)
    plot_wid = col4.number_input("Width (m)", min_value=0.1, value=2.0, step=0.5)

st.divider()

# ==========================================
# 3. GENERATION & GRID RENDER LOGIC
# ==========================================
if not st.session_state.generated:
    if st.button("🚀 GENERATE FIELD GRID", type="primary", use_container_width=True):
        if not (st.session_state.p1_saved and st.session_state.p2_saved):
            st.warning("Make sure both Point A and Point B are saved!")
        else:
            # Sync any manual overrides from the expander before generating
            if input_format == "Decimal Degrees (DD)":
                st.session_state.p1_lat, st.session_state.p1_lon = lat1_dd, lon1_dd
                st.session_state.p2_lat, st.session_state.p2_lon = lat2_dd, lon2_dd
            elif input_format == "GMS (Single Smart Field)":
                try:
                    st.session_state.p1_lat, st.session_state.p1_lon = parse_coordinate(lat1_smart, input_format), parse_coordinate(lon1_smart, input_format)
                    st.session_state.p2_lat, st.session_state.p2_lon = parse_coordinate(lat2_smart, input_format), parse_coordinate(lon2_smart, input_format)
                except Exception as e:
                    st.error(f"Format Error: {e}")
                    st.stop()
                    
            st.session_state.generated = True
            st.rerun()

else:
    with map_container:
        # Calculate Grid
        start_point = (st.session_state.p1_lat, st.session_state.p1_lon)
        bearing = calculate_bearing(st.session_state.p1_lat, st.session_state.p1_lon, st.session_state.p2_lat, st.session_state.p2_lon)
        bearing_perp = (bearing + 90) % 360
        
        plot_data = []
        for r in range(rows):
            for c in range(cols):
                dist_down = r * plot_len
                dist_across = c * plot_wid
                
                pt1 = move_point(move_point(start_point, bearing, dist_down), bearing_perp, dist_across) 
                pt2 = move_point(pt1, bearing, plot_len) 
                pt3 = move_point(pt2, bearing_perp, plot_wid) 
                pt4 = move_point(pt1, bearing_perp, plot_wid) 
                
                plot_data.append({
                    "Plot_ID": f"{c+1}{(r+1):02d}", "Row": r + 1, "Col": c + 1,
                    "Corners_DD": [pt1, pt2, pt3, pt4]
                })

        outside_corners = [start_point, move_point(start_point, bearing, rows * plot_len), move_point(move_point(start_point, bearing, rows * plot_len), bearing_perp, cols * plot_wid), move_point(start_point, bearing_perp, cols * plot_wid)]

        st.success("✅ Grid Generated Successfully!")
        m_grid = get_base_map(start_point[0], start_point[1], 19)

        folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_grid)

        for plot in plot_data:
            coords = plot["Corners_DD"].copy()
            coords.append(coords[0]) 
            folium.Polygon(locations=coords, color="white", weight=1, fill=True, fill_color="green", fill_opacity=0.3, tooltip=f"Plot {plot['Plot_ID']}").add_to(m_grid)

        # Fit bounds to see the whole grid
        sw = (min([lat for lat, lon in outside_corners]), min([lon for lat, lon in outside_corners]))
        ne = (max([lat for lat, lon in outside_corners]), max([lon for lat, lon in outside_corners]))
        m_grid.fit_bounds([sw, ne])

        st_folium(m_grid, use_container_width=True, height=450, returned_objects=[])

        # ==========================================
        # 4. EXPORT LOGIC 
        # ==========================================
        st.subheader("💾 Download Formats")
        
        stake_points = []
        stake_id = 1
        for r in range(rows):
            col_sequence = range(cols) if r % 2 == 0 else reversed(range(cols))
            for c in col_sequence:
                p = next(plot for plot in plot_data if plot["Row"] == r+1 and plot["Col"] == c+1)
                bl_lat, bl_lon = p["Corners_DD"][0] 
                stake_points.append({"Stake_ID": f"S{stake_id:03d}", "Plot_ID": p["Plot_ID"], "Lat": bl_lat, "Lon": bl_lon})
                stake_id += 1

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

        features = []
        for p in plot_data:
            coords = [[lon, lat] for lat, lon in p["Corners_DD"]]
            coords.append(coords[0]) 
            features.append({"type": "Feature", "properties": {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]}, "geometry": {"type": "Polygon", "coordinates": [coords]}})
        geojson_str = json.dumps({"type": "FeatureCollection", "features": features})

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button("📥 KML (Polygons + Stakes)", data=kml_string, file_name="field_grid.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
        with dl_col2:
            st.download_button("📥 GeoJSON", data=geojson_str, file_name="field_grid.geojson", mime="application/geo+json", use_container_width=True)

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
                st.download_button("📥 Shapefile (ZIP)", data=shp_io, file_name="field_grid_shapefile.zip", mime="application/zip", use_container_width=True)
            except Exception as e:
                st.error(f"Shapefile error: {e}")

        if st.button("🔙 Adjust Grid", use_container_width=True):
            st.session_state.generated = False
            st.rerun()
