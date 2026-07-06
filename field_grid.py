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

# Try importing geopandas for Shapefile creation. 
try:
    import geopandas as gpd
    from shapely.geometry import Polygon, Point
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

def get_centroid(corners):
    lats, lons = [pt[0] for pt in corners], [pt[1] for pt in corners]
    return (sum(lats) / len(corners), sum(lons) / len(corners))

def get_base_map(center_lat=None, center_lon=None, zoom=19):
    """Returns a Folium map with Esri Satellite imagery and active tracking."""
    kwargs = {"control_scale": True, "max_zoom": 30}
    if center_lat and center_lon:
        kwargs["location"] = [center_lat, center_lon]
        kwargs["zoom_start"] = zoom

    m = folium.Map(**kwargs)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Satellite', max_native_zoom=18, max_zoom=30, overlay=False
    ).add_to(m)
    
    # Auto-tracking plugin (Forces browser to continuously update live location)
    plugins.LocateControl(
        position="topleft", drawCircle=True, flyTo=True, keepCurrentZoomLevel=True,
        strings={"title": "Track my live location"}, auto_start=True,
        locateOptions={"enableHighAccuracy": True, "maximumAge": 0, "timeout": 10000, "watch": True}
    ).add_to(m)
    
    # Add a crosshair to the center of the screen so user knows exactly what coordinate is being captured
    plugins.FloatImage(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c5/Crosshair.svg/512px-Crosshair.svg.png",
        bottom=45, left=45, width=10
    ).add_to(m)
    
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid", layout="centered")
st.title("🌱 Field Trial Grid")

# Initialize Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.73300000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.05800000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.73400000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.05800000


# ==========================================
# 1. TOP SECTION: THE MAP
# ==========================================
map_container = st.container()


# ==========================================
# 2. BOTTOM SECTION: CAPTURE & CONFIG
# ==========================================
st.divider()
st.subheader("🎯 GNSS Capture")
st.caption("Let the blue dot align, or drag the map to place the center crosshair on your exact target. Then click save.")

c1, c2 = st.columns(2)
btn_a = c1.button("📍 Save Point A (Start)", use_container_width=True)
btn_b = c2.button("📍 Save Point B (Aim)", use_container_width=True)

# Expanders for clean mobile view
with st.expander("✏️ Manual Coordinate Edit", expanded=False):
    st.write("**Point A (Start)**")
    lat1_dd = st.number_input("A Lat (DD)", value=st.session_state.p1_lat, format="%.8f")
    lon1_dd = st.number_input("A Lon (DD)", value=st.session_state.p1_lon, format="%.8f")
    st.write("**Point B (Direction)**")
    lat2_dd = st.number_input("B Lat (DD)", value=st.session_state.p2_lat, format="%.8f")
    lon2_dd = st.number_input("B Lon (DD)", value=st.session_state.p2_lon, format="%.8f")

with st.expander("📐 Grid Dimensions", expanded=True):
    col1, col2 = st.columns(2)
    rows = col1.number_input("Rows", min_value=1, value=10, step=1)
    cols = col2.number_input("Columns", min_value=1, value=4, step=1)
    col3, col4 = st.columns(2)
    plot_len = col3.number_input("Length (m)", min_value=0.1, value=5.0, step=0.5)
    plot_wid = col4.number_input("Width (m)", min_value=0.1, value=2.0, step=0.5)

st.divider()

if st.button("🚀 GENERATE FIELD GRID", type="primary", use_container_width=True):
    # Ensure manual changes sync before generation
    st.session_state.p1_lat, st.session_state.p1_lon = lat1_dd, lon1_dd
    st.session_state.p2_lat, st.session_state.p2_lon = lat2_dd, lon2_dd
    st.session_state.generated = True
    st.rerun()


# ==========================================
# 3. MAP RENDERING & LOGIC
# ==========================================
with map_container:
    if not st.session_state.generated:
        m_live = get_base_map()
        
        folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_live)
        folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A", icon=folium.Icon(color="green")).add_to(m_live)
        folium.Marker([st.session_state.p2_lat, st.session_state.p2_lon], tooltip="Point B", icon=folium.Icon(color="red")).add_to(m_live)

        # Retrieve the center of the map from Python (Updates when map is dragged or live GPS moves)
        map_data = st_folium(m_live, use_container_width=True, height=450, returned_objects=["center"])

        # Capture Logic
        if btn_a and map_data and "center" in map_data:
            st.session_state.p1_lat = map_data["center"]["lat"]
            st.session_state.p1_lon = map_data["center"]["lng"]
            # Bring P2 close to P1 so the map doesn't zoom out across the world
            st.session_state.p2_lat = st.session_state.p1_lat - 0.0001
            st.session_state.p2_lon = st.session_state.p1_lon
            st.rerun()
            
        if btn_b and map_data and "center" in map_data:
            st.session_state.p2_lat = map_data["center"]["lat"]
            st.session_state.p2_lon = map_data["center"]["lng"]
            st.rerun()

    else:
        # Generate Grid Data
        start_point = (st.session_state.p1_lat, st.session_state.p1_lon)
        bearing = calculate_bearing(st.session_state.p1_lat, st.session_state.p1_lon, st.session_state.p2_lat, st.session_state.p2_lon)
        bearing_perp = (bearing + 90) % 360
        
        plot_data = []
        for r in range(rows):
            for c in range(cols):
                dist_down = r * plot_len
                dist_across = c * plot_wid
                
                pt1 = move_point(move_point(start_point, bearing, dist_down), bearing_perp, dist_across) # Bottom-Left
                pt2 = move_point(pt1, bearing, plot_len) # Top-Left
                pt3 = move_point(pt2, bearing_perp, plot_wid) # Top-Right
                pt4 = move_point(pt1, bearing_perp, plot_wid) # Bottom-Right
                
                plot_data.append({
                    "Plot_ID": f"{c+1}{(r+1):02d}", "Row": r + 1, "Col": c + 1,
                    "Corners_DD": [pt1, pt2, pt3, pt4]
                })

        # Render Final Map
        st.success("✅ Grid Generated Successfully!")
        m_grid = get_base_map(center_lat=start_point[0], center_lon=start_point[1], zoom=20)
        
        for plot in plot_data:
            coords = plot["Corners_DD"].copy()
            coords.append(coords[0]) 
            folium.Polygon(
                locations=coords, color="white", weight=1, fill=True,
                fill_color="green", fill_opacity=0.3, tooltip=f"Plot {plot['Plot_ID']}"
            ).add_to(m_grid)

        st_folium(m_grid, use_container_width=True, height=450, returned_objects=[])

        # ==========================================
        # 4. EXPORT LOGIC (Serpentine, KML, GeoJSON, Shapefile)
        # ==========================================
        st.subheader("💾 Download Formats")
        
        # 1. GENERATE SERPENTINE STAKEOUT (Emlid Flow ready)
        stake_points = []
        stake_id = 1
        for r in range(rows):
            # Alternate columns direction based on row for serpentine path
            col_sequence = range(cols) if r % 2 == 0 else reversed(range(cols))
            for c in col_sequence:
                p = next(plot for plot in plot_data if plot["Row"] == r+1 and plot["Col"] == c+1)
                bl_lat, bl_lon = p["Corners_DD"][0] # Always stake Bottom-Left
                stake_points.append({
                    "Stake_ID": f"S{stake_id:03d}",
                    "Plot_ID": p["Plot_ID"],
                    "Lat": bl_lat, "Lon": bl_lon
                })
                stake_id += 1

        # 2. CREATE KML
        kml = simplekml.Kml()
        # Polygons
        fold_poly = kml.newfolder(name="Plots")
        for p in plot_data:
            coords = [(lon, lat) for lat, lon in p["Corners_DD"]]
            coords.append(coords[0])
            pol = fold_poly.newpolygon(name=p["Plot_ID"], outerboundaryis=coords)
            pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)
        
        # Serpentine Waypoints
        fold_stakes = kml.newfolder(name="Serpentine Stakeout")
        for st_pt in stake_points:
            pnt = fold_stakes.newpoint(name=st_pt["Stake_ID"], description=f"Plot {st_pt['Plot_ID']} BL", coords=[(st_pt["Lon"], st_pt["Lat"])])
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_square.png'
        kml_string = kml.kml()

        # 3. CREATE GEOJSON
        features = []
        for p in plot_data:
            coords = [[lon, lat] for lat, lon in p["Corners_DD"]]
            coords.append(coords[0]) # Close poly
            features.append({
                "type": "Feature",
                "properties": {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]},
                "geometry": {"type": "Polygon", "coordinates": [coords]}
            })
        geojson_str = json.dumps({"type": "FeatureCollection", "features": features})

        # Render Buttons
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button("📥 KML (Polygons + Serpentine)", data=kml_string, file_name="field_grid.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
        with dl_col2:
            st.download_button("📥 GeoJSON", data=geojson_str, file_name="field_grid.geojson", mime="application/geo+json", use_container_width=True)

        # 4. CREATE SHAPEFILE (Requires GeoPandas)
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
                st.error(f"Shapefile generation error: {e}")
        else:
            st.info("💡 To enable Shapefile exports, add `geopandas` to your requirements.txt")

        # Back button
        if st.button("🔙 Adjust Grid", use_container_width=True):
            st.session_state.generated = False
            st.rerun()
