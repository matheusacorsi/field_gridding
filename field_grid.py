import streamlit as st
import pandas as pd
import math
import simplekml
import io
import re
from geopy.distance import geodesic
import folium
from folium import plugins
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

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
    lats = [pt[0] for pt in corners]
    lons = [pt[1] for pt in corners]
    return (sum(lats) / len(corners), sum(lons) / len(corners))

def get_base_map():
    """Returns a Folium map that allows extreme digital zooming without losing the satellite image."""
    m = folium.Map(control_scale=True, max_zoom=30)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satellite',
        max_native_zoom=18, # Esri stops providing new tiles at zoom 18
        max_zoom=30,        # Digitally stretch the zoom 18 tiles all the way to zoom 30
        overlay=False,
        control=True
    ).add_to(m)
    
    plugins.LocateControl(
        position="topleft",
        drawCircle=True,
        flyTo=True,
        keepCurrentZoomLevel=True,
        strings={"title": "Track my live location"},
        locateOptions={"enableHighAccuracy": True, "maximumAge": 0, "timeout": 10000, "watch": True}
    ).add_to(m)
    
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid Generator", layout="centered")
st.title("🌱 Field Trial Grid")

# Initialize Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'raw_gps_lat' not in st.session_state: st.session_state.raw_gps_lat = None
if 'raw_gps_lon' not in st.session_state: st.session_state.raw_gps_lon = None
# Starting default coords 
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.73300000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.05800000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.73400000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.05800000


# ==========================================
# 1. TOP SECTION: THE MAP (Always visible)
# ==========================================
map_container = st.container()


# ==========================================
# 2. BOTTOM SECTION: CONFIG & CAPTURE
# ==========================================
st.divider()
st.subheader("📡 GNSS Capture Hub")
st.caption("1. Tap 'Get Location' below. 2. Choose which point to save it to.")

gps_loc = streamlit_geolocation()
if gps_loc and gps_loc.get('latitude'):
    st.session_state.raw_gps_lat = float(gps_loc['latitude'])
    st.session_state.raw_gps_lon = float(gps_loc['longitude'])
    st.success(f"📍 Signal Acquired: {st.session_state.raw_gps_lat:.6f}, {st.session_state.raw_gps_lon:.6f}")
    
    c1, c2 = st.columns(2)
    if c1.button("Save as Point A (Start)", use_container_width=True):
        st.session_state.p1_lat = st.session_state.raw_gps_lat
        st.session_state.p1_lon = st.session_state.raw_gps_lon
        st.session_state.p2_lat = st.session_state.raw_gps_lat - 0.0001 # Bring P2 near P1 to avoid map zooming out
        st.session_state.p2_lon = st.session_state.raw_gps_lon
        st.session_state.generated = False 
        st.rerun() 
        
    if c2.button("Save as Point B (Aim)", use_container_width=True):
        st.session_state.p2_lat = st.session_state.raw_gps_lat
        st.session_state.p2_lon = st.session_state.raw_gps_lon
        st.session_state.generated = False 
        st.rerun() 

# --- Manual Coordinate Inputs ---
with st.expander("✏️ Manual Coordinate Edit (Optional)", expanded=False):
    input_format = st.radio("Format", ["Decimal Degrees (DD)", "GMS (Single Smart Field)"])
    
    if input_format == "Decimal Degrees (DD)":
        st.write("**Point A (Start)**")
        lat1_dd = st.number_input("A Lat (DD)", value=st.session_state.p1_lat, format="%.8f")
        lon1_dd = st.number_input("A Lon (DD)", value=st.session_state.p1_lon, format="%.8f")
        st.write("**Point B (Direction)**")
        lat2_dd = st.number_input("B Lat (DD)", value=st.session_state.p2_lat, format="%.8f")
        lon2_dd = st.number_input("B Lon (DD)", value=st.session_state.p2_lon, format="%.8f")
        
    elif input_format == "GMS (Single Smart Field)":
        st.write("**Point A (Start)**")
        lat1_smart = st.text_input("A Lat", value="25 43 58.8 S")
        lon1_smart = st.text_input("A Lon", value="53 03 28.8 W")
        st.write("**Point B (Direction)**")
        lat2_smart = st.text_input("B Lat", value="25 44 02.4 S")
        lon2_smart = st.text_input("B Lon", value="53 03 28.8 W")

# Extract final coordinates based on format
try:
    if input_format == "Decimal Degrees (DD)":
        cur_lat1, cur_lon1, cur_lat2, cur_lon2 = lat1_dd, lon1_dd, lat2_dd, lon2_dd
    elif input_format == "GMS (Single Smart Field)":
        cur_lat1 = parse_coordinate(lat1_smart, input_format)
        cur_lon1 = parse_coordinate(lon1_smart, input_format)
        cur_lat2 = parse_coordinate(lat2_smart, input_format)
        cur_lon2 = parse_coordinate(lon2_smart, input_format)
except Exception:
    cur_lat1, cur_lon1 = st.session_state.p1_lat, st.session_state.p1_lon
    cur_lat2, cur_lon2 = st.session_state.p2_lat, st.session_state.p2_lon

# --- Grid Configuration ---
with st.expander("📐 Grid Dimensions", expanded=True):
    c1, c2 = st.columns(2)
    rows = c1.number_input("Rows", min_value=1, value=10, step=1)
    cols = c2.number_input("Columns", min_value=1, value=4, step=1)
    c3, c4 = st.columns(2)
    plot_len = c3.number_input("Length (m)", min_value=0.1, value=5.0, step=0.5)
    plot_wid = c4.number_input("Width (m)", min_value=0.1, value=2.0, step=0.5)

# --- Export Configuration ---
with st.expander("💾 Export Options", expanded=False):
    kml_polygons = st.checkbox("KML: Include Polygons", value=True)
    kml_centroids = st.checkbox("KML: Include Centroids", value=False)
    kml_corners = st.checkbox("KML: Include Corners", value=False)
    excel_coord_format = st.radio("Excel Format", ["Decimal Degrees (DD)", "Degrees, Minutes, Seconds (GMS)"])

st.divider()

if st.button("🚀 GENERATE FIELD GRID", type="primary", use_container_width=True):
    st.session_state.generated = True


# ==========================================
# 3. MAP RENDERING LOGIC (Rendered inside Top Container)
# ==========================================
with map_container:
    if not st.session_state.generated:
        st.info("Align your points. The map will digitally stretch if you zoom in close.")
        m_live = get_base_map()
        
        # Draw Points
        folium.PolyLine([(cur_lat1, cur_lon1), (cur_lat2, cur_lon2)], color="yellow", weight=4, opacity=0.9).add_to(m_live)
        folium.Marker([cur_lat1, cur_lon1], tooltip="Point A (Start)", icon=folium.Icon(color="green")).add_to(m_live)
        folium.Marker([cur_lat2, cur_lon2], tooltip="Point B (Aim)", icon=folium.Icon(color="red")).add_to(m_live)

        # Fit bounds slightly padded
        sw = (min(cur_lat1, cur_lat2), min(cur_lon1, cur_lon2))
        ne = (max(cur_lat1, cur_lat2), max(cur_lon1, cur_lon2))
        buffer = 0.00005 
        m_live.fit_bounds([(sw[0]-buffer, sw[1]-buffer), (ne[0]+buffer, ne[1]+buffer)])

        st_folium(m_live, use_container_width=True, height=450, returned_objects=[])

    else:
        try:
            start_point = (cur_lat1, cur_lon1)
            bearing = calculate_bearing(cur_lat1, cur_lon1, cur_lat2, cur_lon2)
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
                        "Plot_ID": f"{c+1}{(r+1):02d}",
                        "Row": r + 1, "Col": c + 1, "Corners_DD": [pt1, pt2, pt3, pt4]
                    })

            grid_tl = start_point
            grid_bl = move_point(start_point, bearing, rows * plot_len)
            grid_br = move_point(grid_bl, bearing_perp, cols * plot_wid)
            grid_tr = move_point(start_point, bearing_perp, cols * plot_wid)
            outside_corners = [grid_tl, grid_bl, grid_br, grid_tr]

            st.success("✅ Grid Generated Successfully!")
            m_grid = get_base_map()

            folium.PolyLine([(cur_lat1, cur_lon1), (cur_lat2, cur_lon2)], color="yellow", weight=4).add_to(m_grid)

            for plot in plot_data:
                coords = plot["Corners_DD"].copy()
                coords.append(coords[0]) 
                folium.Polygon(
                    locations=coords, color="white", weight=1, fill=True,
                    fill_color="green", fill_opacity=0.3, tooltip=f"Plot {plot['Plot_ID']}"
                ).add_to(m_grid)

            sw = (min([lat for lat, lon in outside_corners]), min([lon for lat, lon in outside_corners]))
            ne = (max([lat for lat, lon in outside_corners]), max([lon for lat, lon in outside_corners]))
            m_grid.fit_bounds([sw, ne])

            st_folium(m_grid, use_container_width=True, height=450, returned_objects=[])

            # --- GENERATE EXPORT FILES ---
            is_dd = (excel_coord_format == "Decimal Degrees (DD)")
            excel_rows_plots = []
            for p in plot_data:
                row_dict = {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]}
                for i, (lat, lon) in enumerate(p["Corners_DD"]):
                    if is_dd:
                        row_dict[f"Corner_{i+1}_Lat"], row_dict[f"Corner_{i+1}_Lon"] = lat, lon
                    else:
                        row_dict[f"Corner_{i+1}_GMS"] = f"{dd_to_dms(lat, True)} {dd_to_dms(lon, False)}"
                c_lat, c_lon = get_centroid(p["Corners_DD"])
                if is_dd:
                    row_dict["Centroid_Lat"], row_dict["Centroid_Lon"] = c_lat, c_lon
                else:
                    row_dict["Centroid_GMS"] = f"{dd_to_dms(c_lat, True)} {dd_to_dms(c_lon, False)}"
                excel_rows_plots.append(row_dict)
                
            df_plots = pd.DataFrame(excel_rows_plots)
            
            excel_rows_outside = []
            corner_labels = ["Start (P1)", "Bottom-Left", "Bottom-Right", "Top-Right"]
            for label, (lat, lon) in zip(corner_labels, outside_corners):
                row_dict = {"Corner": label}
                if is_dd:
                    row_dict["Lat"], row_dict["Lon"] = lat, lon
                else:
                    row_dict["Coordinates_GMS"] = f"{dd_to_dms(lat, True)} {dd_to_dms(lon, False)}"
                excel_rows_outside.append(row_dict)
                
            df_outside = pd.DataFrame(excel_rows_outside)

            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_plots.to_excel(writer, index=False, sheet_name='Plot Coordinates')
                df_outside.to_excel(writer, index=False, sheet_name='Outside Boundaries')
            excel_buffer.seek(0)

            kml = simplekml.Kml()
            for p in plot_data:
                if kml_polygons:
                    kml_coords = [(lon, lat) for lat, lon in p["Corners_DD"]]
                    kml_coords.append(kml_coords[0]) 
                    pol = kml.newpolygon(name=p["Plot_ID"], outerboundaryis=kml_coords)
                    pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)
                    pol.style.linestyle.color = simplekml.Color.white

                if kml_centroids:
                    c_lat, c_lon = get_centroid(p["Corners_DD"])
                    pnt = kml.newpoint(name=f"{p['Plot_ID']}_Centroid", coords=[(c_lon, c_lat)])
                    pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/target.png'

                if kml_corners:
                    for i, (lat, lon) in enumerate(p["Corners_DD"]):
                        pnt = kml.newpoint(name=f"{p['Plot_ID']}_C{i+1}", coords=[(lon, lat)])
                        pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_square.png'

            kml_string = kml.kml()

            c1, c2 = st.columns(2)
            with c1:
                st.download_button("📄 Download KML", data=kml_string, file_name="field_trial_grid.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)
            with c2:
                st.download_button("📊 Download Excel", data=excel_buffer, file_name="field_trial_coordinates.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

        except Exception as e:
            st.error(f"⚠️ Error: {e}")
