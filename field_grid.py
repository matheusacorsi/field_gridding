import streamlit as st
import pandas as pd
import math
import simplekml
import io
import os
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

def get_base_map(center_lat, center_lon, zoom, show_crosshair=False):
    """Returns a Folium map with Esri Satellite imagery."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True, max_zoom=30)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Esri Satellite', max_native_zoom=18, max_zoom=30, overlay=False
    ).add_to(m)
    
    # Auto-tracking plugin: tracks live GPS but doesn't override manual panning
    plugins.LocateControl(
        position="topleft", drawCircle=True, flyTo=False, setView=False, keepCurrentZoomLevel=True,
        strings={"title": "Show my live location"}, watch=True,
        locateOptions={"enableHighAccuracy": True, "maximumAge": 0, "timeout": 10000}
    ).add_to(m)
    
    # Inject a fixed red crosshair into the center of the map view for precise targeting
    if show_crosshair:
        crosshair_html = """
        <style>
        .center-crosshair {
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            font-size: 38px; color: #ff0000; z-index: 1000; pointer-events: none;
            text-shadow: -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff;
        }
        </style>
        <div class="center-crosshair">⌖</div>
        """
        m.get_root().html.add_child(folium.Element(crosshair_html))
        
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid", layout="centered")
st.title("🌱 Field Trial Grid")

# Initialize Session State Variables
if 'generated' not in st.session_state: st.session_state.generated = False

# Live map tracking state
if 'live_lat' not in st.session_state: st.session_state.live_lat = -25.733000
if 'live_lon' not in st.session_state: st.session_state.live_lon = -53.058000
if 'live_zoom' not in st.session_state: st.session_state.live_zoom = 19 # ~100-200m scale

# Saved Point State
if 'p1_saved' not in st.session_state: st.session_state.p1_saved = False
if 'p2_saved' not in st.session_state: st.session_state.p2_saved = False
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.733000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.058000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.734000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.058000


# ==========================================
# 1. TOP SECTION: THE MAP CONTAINER
# ==========================================
map_container = st.container()

# Sync the live coordinates from the map back to Python seamlessly
with map_container:
    if not st.session_state.generated:
        st.info("🎯 **Aim & Save:** Drag the map so the red crosshair is exactly on your target, then click Save.")
        
        # Build the map at the exact last known center and zoom level (prevents zoom jumping)
        m_live = get_base_map(st.session_state.live_lat, st.session_state.live_lon, st.session_state.live_zoom, show_crosshair=True)
        
        # Draw saved points so user sees them before generating
        if st.session_state.p1_saved:
            folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A (Start)", icon=folium.Icon(color="green")).add_to(m_live)
        if st.session_state.p2_saved:
            folium.Marker([st.session_state.p2_lat, st.session_state.p2_lon], tooltip="Point B (Aim)", icon=folium.Icon(color="red")).add_to(m_live)
        if st.session_state.p1_saved and st.session_state.p2_saved:
            folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_live)

        # Render Map and extract the center coordinate where the crosshair is currently resting
        map_data = st_folium(m_live, use_container_width=True, height=450, returned_objects=["center", "zoom"])
        
        # Update session state with the latest center and zoom as the user drags the map
        if map_data and isinstance(map_data, dict):
            if map_data.get("center"):
                st.session_state.live_lat = map_data["center"]["lat"]
                st.session_state.live_lon = map_data["center"]["lng"]
            if map_data.get("zoom"):
                st.session_state.live_zoom = map_data["zoom"]


# ==========================================
# 2. BOTTOM SECTION: CAPTURE & CONFIG
# ==========================================
st.divider()

if not st.session_state.generated:
    c1, c2 = st.columns(2)
    
    # Save Point A Button
    if c1.button("📍 Save Point A (Start)", use_container_width=True):
        st.session_state.p1_lat = st.session_state.live_lat
        st.session_state.p1_lon = st.session_state.live_lon
        st.session_state.p1_saved = True
        st.rerun() # Instantly redraw map with the green marker
            
    # Save Point B Button
    if c2.button("📍 Save Point B (Aim)", use_container_width=True):
        st.session_state.p2_lat = st.session_state.live_lat
        st.session_state.p2_lon = st.session_state.live_lon
        st.session_state.p2_saved = True
        st.rerun() # Instantly redraw map with the red marker and line

    # Grid Configuration
    with st.expander("📐 Grid Dimensions", expanded=True):
        col1, col2 = st.columns(2)
        rows = col1.number_input("Rows", min_value=1, value=10, step=1)
        cols = col2.number_input("Columns", min_value=1, value=4, step=1)
        col3, col4 = st.columns(2)
        plot_len = col3.number_input("Length (m)", min_value=0.1, value=5.0, step=0.5)
        plot_wid = col4.number_input("Width (m)", min_value=0.1, value=2.0, step=0.5)
        
    # Manual Override (Optional)
    with st.expander("✏️ Manual Coordinate Edit", expanded=False):
        new_p1_lat = st.number_input("A Lat (DD)", value=st.session_state.p1_lat, format="%.8f")
        new_p1_lon = st.number_input("A Lon (DD)", value=st.session_state.p1_lon, format="%.8f")
        new_p2_lat = st.number_input("B Lat (DD)", value=st.session_state.p2_lat, format="%.8f")
        new_p2_lon = st.number_input("B Lon (DD)", value=st.session_state.p2_lon, format="%.8f")
        
        if st.button("Apply Manual Coordinates"):
            st.session_state.p1_lat, st.session_state.p1_lon = new_p1_lat, new_p1_lon
            st.session_state.p2_lat, st.session_state.p2_lon = new_p2_lat, new_p2_lon
            st.session_state.p1_saved = True
            st.session_state.p2_saved = True
            # Center map on new manual coordinates
            st.session_state.live_lat = new_p1_lat
            st.session_state.live_lon = new_p1_lon
            st.rerun()

    st.divider()

    # Generation Trigger
    if st.button("🚀 GENERATE FIELD GRID", type="primary", use_container_width=True):
        if not (st.session_state.p1_saved and st.session_state.p2_saved):
            st.warning("⚠️ Make sure both Point A and Point B are saved!")
        else:
            st.session_state.generated = True
            st.rerun()

# ==========================================
# 3. GENERATED VIEW & EXPORTS
# ==========================================
else:
    with map_container:
        # 1. Grid Math Calculation
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

        # 2. Render Final Grid Map
        st.success("✅ Grid Generated Successfully! Review below before exporting.")
        m_grid = get_base_map(start_point[0], start_point[1], 19, show_crosshair=False)

        folium.PolyLine([(st.session_state.p1_lat, st.session_state.p1_lon), (st.session_state.p2_lat, st.session_state.p2_lon)], color="yellow", weight=4).add_to(m_grid)
        folium.Marker([st.session_state.p1_lat, st.session_state.p1_lon], tooltip="Point A", icon=folium.Icon(color="green")).add_to(m_grid)
        folium.Marker([st.session_state.p2_lat, st.session_state.p2_lon], tooltip="Point B", icon=folium.Icon(color="red")).add_to(m_grid)

        for plot in plot_data:
            coords = plot["Corners_DD"].copy()
            coords.append(coords[0]) 
            folium.Polygon(locations=coords, color="white", weight=1, fill=True, fill_color="green", fill_opacity=0.3, tooltip=f"Plot {plot['Plot_ID']}").add_to(m_grid)

        # Auto-zoom the map so the entire generated grid fits perfectly on the screen
        sw = (min([lat for lat, lon in outside_corners]), min([lon for lat, lon in outside_corners]))
        ne = (max([lat for lat, lon in outside_corners]), max([lon for lat, lon in outside_corners]))
        m_grid.fit_bounds([sw, ne])

        st_folium(m_grid, use_container_width=True, height=450, returned_objects=[])

        # ==========================================
        # 4. DOWNLOAD LOGIC (KML, GeoJSON, Shapefile)
        # ==========================================
        st.subheader("💾 Download Formats")
        
        # A. Build Serpentine Stakeout List
        stake_points = []
        stake_id = 1
        for r in range(rows):
            col_sequence = range(cols) if r % 2 == 0 else reversed(range(cols))
            for c in col_sequence:
                p = next(plot for plot in plot_data if plot["Row"] == r+1 and plot["Col"] == c+1)
                bl_lat, bl_lon = p["Corners_DD"][0] 
                stake_points.append({"Stake_ID": f"S{stake_id:03d}", "Plot_ID": p["Plot_ID"], "Lat": bl_lat, "Lon": bl_lon})
                stake_id += 1

        # B. Generate KML
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

        # C. Generate GeoJSON
        features = []
        for p in plot_data:
            coords = [[lon, lat] for lat, lon in p["Corners_DD"]]
            coords.append(coords[0]) 
            features.append({"type": "Feature", "properties": {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]}, "geometry": {"type": "Polygon", "coordinates": [coords]}})
        geojson_str = json.dumps({"type": "FeatureCollection", "features": features})

        # Render Download Buttons
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button("📥 KML (Polygons + Stakes)", data=kml_string, file_name="field_grid.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
        with dl_col2:
            st.download_button("📥 GeoJSON", data=geojson_str, file_name="field_grid.geojson", mime="application/geo+json", use_container_width=True)

        # D. Generate Shapefile (if Geopandas is installed)
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
        else:
            st.info("💡 To enable Shapefile exports, ensure `geopandas` is in your requirements.txt")

        # Back to Edit Button
        st.write("---")
        if st.button("🔙 Adjust Points or Dimensions", use_container_width=True):
            st.session_state.generated = False
            st.rerun()
