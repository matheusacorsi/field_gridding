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
    if direction.upper() in ['S', 'W']:
        dd = -dd
    return dd

def parse_coordinate(coord_str, format_type):
    if not coord_str: return 0.0
    coord_str = str(coord_str).strip()
    
    if format_type == "GMS (Single Smart Field)":
        dir_match = re.search(r'(?i)([NSEW])', coord_str)
        if not dir_match:
            raise ValueError(f"Missing compass direction (N, S, E, or W) in '{coord_str}'.")
        direction = dir_match.group(1).upper()
        
        numbers = re.findall(r'\d+(?:[.,]\d+)?', coord_str)
        if len(numbers) >= 3:
            degrees = float(numbers[0].replace(',', '.'))
            minutes = float(numbers[1].replace(',', '.'))
            seconds = float(numbers[2].replace(',', '.'))
            
            dd = degrees + (minutes / 60.0) + (seconds / 3600.0)
            if direction in ['S', 'W']: dd = -dd
            return dd
        else:
            raise ValueError(f"Could not find Degrees, Minutes, and Seconds in '{coord_str}'.")

def dd_to_dms(deg, is_lat=True):
    d = int(deg)
    m = int((abs(deg) - abs(d)) * 60)
    s = (abs(deg) - abs(d) - m/60) * 3600
    if is_lat:
        direction = "N" if deg >= 0 else "S"
    else:
        direction = "E" if deg >= 0 else "W"
    return f"{abs(d)}°{m}'{s:.2f}\"{direction}"

def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360

def move_point(start_pt, bearing, distance_m):
    if distance_m == 0: return start_pt
    new_pt = geodesic(meters=distance_m).destination(start_pt, bearing)
    return (new_pt.latitude, new_pt.longitude)

def get_centroid(corners):
    lats = [pt[0] for pt in corners]
    lons = [pt[1] for pt in corners]
    return (sum(lats) / len(corners), sum(lons) / len(corners))

def get_base_map(center_lat, center_lon, zoom=19):
    """Returns a Folium map with Esri Satellite imagery."""
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri Satellite',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Adds the live browser location tracking button (The fix for mobile)
    plugins.LocateControl(
        position="topleft",
        drawCircle=True,
        flyTo=True,
        strings={"title": "Show my live location"},
        auto_start=True  # Immediately requests location on load
    ).add_to(m)
    
    return m

# --- STREAMLIT UI SETUP ---
st.set_page_config(page_title="Field Trial Grid Generator", layout="wide")
st.title("🌱 Field Trial Plot Grid Generator")

# Initialize Session State
if 'generated' not in st.session_state: st.session_state.generated = False
if 'raw_gps_lat' not in st.session_state: st.session_state.raw_gps_lat = None
if 'raw_gps_lon' not in st.session_state: st.session_state.raw_gps_lon = None
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.73300000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.05800000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.73400000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.05800000

# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header("1. Input Coordinates")
    input_format = st.radio("Select Input Format", ["Decimal Degrees (DD)", "GMS (Single Smart Field)", "GMS (Separate Fields)"])
    st.write("---")
    
    if input_format == "Decimal Degrees (DD)":
        st.subheader("🛰️ RTK GPS Capture")
        st.caption("Use the map to walk to your spot. When ready, click to capture coordinates here, then assign.")
        
        gps_loc = streamlit_geolocation()
        if gps_loc and gps_loc.get('latitude'):
            st.session_state.raw_gps_lat = float(gps_loc['latitude'])
            st.session_state.raw_gps_lon = float(gps_loc['longitude'])
            st.success(f"📍 Captured: {st.session_state.raw_gps_lat:.6f}, {st.session_state.raw_gps_lon:.6f}")
            
            c1, c2 = st.columns(2)
            if c1.button("Set as P1"):
                st.session_state.p1_lat = st.session_state.raw_gps_lat
                st.session_state.p1_lon = st.session_state.raw_gps_lon
                st.session_state.generated = False 
            if c2.button("Set as P2"):
                st.session_state.p2_lat = st.session_state.raw_gps_lat
                st.session_state.p2_lon = st.session_state.raw_gps_lon
                st.session_state.generated = False 
                
        st.write("---")
        st.write("**First Plot Outside Corner (P1)**")
        lat1_dd = st.number_input("P1 Latitude (DD)", value=st.session_state.p1_lat, format="%.8f")
        lon1_dd = st.number_input("P1 Longitude (DD)", value=st.session_state.p1_lon, format="%.8f")
        
        st.write("**Alignment Point (P2)**")
        lat2_dd = st.number_input("P2 Latitude (DD)", value=st.session_state.p2_lat, format="%.8f")
        lon2_dd = st.number_input("P2 Longitude (DD)", value=st.session_state.p2_lon, format="%.8f")
        
    elif input_format == "GMS (Single Smart Field)":
        st.write("**First Plot Outside Corner (P1)**")
        lat1_smart = st.text_input("P1 Latitude", value="25 43 58.8 S")
        lon1_smart = st.text_input("P1 Longitude", value="53 03 28.8 W")
        st.write("**Alignment Point (P2)**")
        lat2_smart = st.text_input("P2 Latitude", value="25 44 02.4 S")
        lon2_smart = st.text_input("P2 Longitude", value="53 03 28.8 W")

    elif input_format == "GMS (Separate Fields)":
        st.write("**First Plot Outside Corner (P1)**")
        c1, c2, c3, c4 = st.columns(4)
        lat1_d, lat1_m, lat1_s, lat1_dir = c1.number_input("Lat D", 0, 90, 25), c2.number_input("M", 0, 59, 43), c3.number_input("S", 0.0, 59.9, 58.8), c4.selectbox("Dir", ["S", "N"], key="d1")
        c1, c2, c3, c4 = st.columns(4)
        lon1_d, lon1_m, lon1_s, lon1_dir = c1.number_input("Lon D", 0, 180, 53), c2.number_input("M", 0, 59, 3), c3.number_input("S", 0.0, 59.9, 28.8), c4.selectbox("Dir", ["W", "E"], key="d2")
        
        st.write("**Alignment Point (P2)**")
        c1, c2, c3, c4 = st.columns(4)
        lat2_d, lat2_m, lat2_s, lat2_dir = c1.number_input("Lat D", 0, 90, 25), c2.number_input("M", 0, 59, 44), c3.number_input("S", 0.0, 59.9, 2.4), c4.selectbox("Dir", ["S", "N"], key="d3")
        c1, c2, c3, c4 = st.columns(4)
        lon2_d, lon2_m, lon2_s, lon2_dir = c1.number_input("Lon D", 0, 180, 53), c2.number_input("M", 0, 59, 3), c3.number_input("S", 0.0, 59.9, 28.8), c4.selectbox("Dir", ["W", "E"], key="d4")
    
    st.header("2. Trial Layout")
    rows = st.number_input("Number of Rows", min_value=1, value=10, step=1)
    cols = st.number_input("Number of Columns", min_value=1, value=4, step=1)
    plot_len = st.number_input("Plot Length (meters)", min_value=0.1, value=5.0, step=0.5)
    plot_wid = st.number_input("Plot Width (meters)", min_value=0.1, value=2.0, step=0.5)
    
    st.header("3. KML Export Options")
    kml_polygons = st.checkbox("Include Polygons", value=True)
    kml_centroids = st.checkbox("Include Centroids", value=False)
    kml_corners = st.checkbox("Include Corner Waypoints", value=False)

    st.header("4. Excel Export Options")
    excel_coord_format = st.radio("Output Format", ["Decimal Degrees (DD)", "Degrees, Minutes, Seconds (GMS)"])
    
    if st.button("Generate Grid", type="primary"):
        st.session_state.generated = True

# --- DYNAMIC COORDINATE PARSING ---
try:
    if input_format == "Decimal Degrees (DD)":
        cur_lat1, cur_lon1 = lat1_dd, lon1_dd
        cur_lat2, cur_lon2 = lat2_dd, lon2_dd
    elif input_format == "GMS (Single Smart Field)":
        cur_lat1 = parse_coordinate(lat1_smart, input_format)
        cur_lon1 = parse_coordinate(lon1_smart, input_format)
        cur_lat2 = parse_coordinate(lat2_smart, input_format)
        cur_lon2 = parse_coordinate(lon2_smart, input_format)
    elif input_format == "GMS (Separate Fields)":
        cur_lat1 = dms_to_dd(lat1_d, lat1_m, lat1_s, lat1_dir)
        cur_lon1 = dms_to_dd(lon1_d, lon1_m, lon1_s, lon1_dir)
        cur_lat2 = dms_to_dd(lat2_d, lat2_m, lat2_s, lat2_dir)
        cur_lon2 = dms_to_dd(lon2_d, lon2_m, lon2_s, lon2_dir)
except Exception:
    cur_lat1, cur_lon1 = st.session_state.p1_lat, st.session_state.p1_lon
    cur_lat2, cur_lon2 = st.session_state.p2_lat, st.session_state.p2_lon


# --- MAIN DISPLAY AREA ---
if not st.session_state.generated:
    st.subheader("📍 Live Point Verification")
    st.info("The map is tracking you live. Walk to your points, capture the GPS in the sidebar, and assign them. Once aligned, click **Generate Grid**.")
    
    # Center map on user's last captured GPS if available, otherwise P1
    center_lat = st.session_state.raw_gps_lat if st.session_state.raw_gps_lat else cur_lat1
    center_lon = st.session_state.raw_gps_lon if st.session_state.raw_gps_lon else cur_lon1
    
    m_live = get_base_map(center_lat, center_lon)
    
    # Alignment Vector & Points
    folium.PolyLine([(cur_lat1, cur_lon1), (cur_lat2, cur_lon2)], color="yellow", weight=3, opacity=0.8).add_to(m_live)
    folium.Marker([cur_lat1, cur_lon1], tooltip="P1 (Start)", icon=folium.Icon(color="green")).add_to(m_live)
    folium.Marker([cur_lat2, cur_lon2], tooltip="P2 (Direction)", icon=folium.Icon(color="red")).add_to(m_live)

    # returned_objects=[] prevents the app from rerunning every time you touch the map on mobile
    st_folium(m_live, use_container_width=True, height=600, returned_objects=[])

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
                    "Row": r + 1,
                    "Col": c + 1,
                    "Corners_DD": [pt1, pt2, pt3, pt4]
                })

        grid_tl = start_point
        grid_bl = move_point(start_point, bearing, rows * plot_len)
        grid_br = move_point(grid_bl, bearing_perp, cols * plot_wid)
        grid_tr = move_point(start_point, bearing_perp, cols * plot_wid)
        outside_corners = [grid_tl, grid_bl, grid_br, grid_tr]

        st.subheader("📍 Generated Grid Map")
        m_grid = get_base_map(cur_lat1, cur_lon1)

        folium.PolyLine([(cur_lat1, cur_lon1), (cur_lat2, cur_lon2)], color="yellow", weight=3).add_to(m_grid)

        # Draw generated plots
        for plot in plot_data:
            coords = plot["Corners_DD"].copy()
            coords.append(coords[0]) # Close the polygon
            
            folium.Polygon(
                locations=coords,
                color="white",
                weight=1,
                fill=True,
                fill_color="green",
                fill_opacity=0.3,
                tooltip=f"Plot {plot['Plot_ID']}"
            ).add_to(m_grid)

        st_folium(m_grid, use_container_width=True, height=600, returned_objects=[])

        # --- GENERATE FILES ---
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

        # --- KML GENERATION ---
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

        # --- DOWNLOAD BUTTONS ---
        st.subheader("Export Files")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(label="📄 Download KML", data=kml_string, file_name="field_trial_grid.kml", mime="application/vnd.google-earth.kml+xml")
        with col2:
            st.download_button(label="📊 Download Excel", data=excel_buffer, file_name="field_trial_coordinates.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    except Exception as e:
        st.error(f"⚠️ Error processing coordinates: {e}")
