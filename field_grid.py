import streamlit as st
import pandas as pd
import math
import simplekml
import io
import re
from geopy.distance import geodesic
import plotly.graph_objects as go
from streamlit_geolocation import streamlit_geolocation

# --- HELPER FUNCTIONS ---
def dms_to_dd(deg, min, sec, direction):
    """Converts Degrees, Minutes, Seconds to Decimal Degrees."""
    dd = float(deg) + (float(min) / 60.0) + (float(sec) / 3600.0)
    if direction.upper() in ['S', 'W']:
        dd = -dd
    return dd

def parse_coordinate(coord_str, format_type):
    """Parses the coordinate string for the Single Smart Field option."""
    if not coord_str:
        return 0.0
    
    coord_str = str(coord_str).strip()
    
    if format_type == "GMS (Single Smart Field)":
        # 1. Find the compass direction first (N, S, E, or W)
        dir_match = re.search(r'(?i)([NSEW])', coord_str)
        if not dir_match:
            raise ValueError(f"Missing compass direction (N, S, E, or W) in '{coord_str}'.")
        direction = dir_match.group(1).upper()
        
        # 2. Extract all numbers from the string (handles both dots and commas for decimals)
        numbers = re.findall(r'\d+(?:[.,]\d+)?', coord_str)
        
        if len(numbers) >= 3:
            degrees = float(numbers[0].replace(',', '.'))
            minutes = float(numbers[1].replace(',', '.'))
            seconds = float(numbers[2].replace(',', '.'))
            
            dd = degrees + (minutes / 60.0) + (seconds / 3600.0)
            if direction in ['S', 'W']:
                dd = -dd
            return dd
        else:
            raise ValueError(f"Could not find Degrees, Minutes, and Seconds in '{coord_str}'.")

def dd_to_dms(deg, is_lat=True):
    """Converts Decimal Degrees to Degrees Minutes Seconds format."""
    d = int(deg)
    m = int((abs(deg) - abs(d)) * 60)
    s = (abs(deg) - abs(d) - m/60) * 3600
    if is_lat:
        direction = "N" if deg >= 0 else "S"
    else:
        direction = "E" if deg >= 0 else "W"
    return f"{abs(d)}°{m}'{s:.2f}\"{direction}"

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculates the initial bearing from point 1 to point 2."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360

def move_point(start_pt, bearing, distance_m):
    """Returns a new (lat, lon) after moving a distance at a given bearing."""
    if distance_m == 0:
        return start_pt
    new_pt = geodesic(meters=distance_m).destination(start_pt, bearing)
    return (new_pt.latitude, new_pt.longitude)

def get_centroid(corners):
    """Calculates the center point (lat, lon) of a polygon."""
    lats = [pt[0] for pt in corners]
    lons = [pt[1] for pt in corners]
    return (sum(lats) / len(corners), sum(lons) / len(corners))

# --- STREAMLIT UI ---
st.set_page_config(page_title="Field Trial Grid Generator", layout="wide")
st.title("🌱 Field Trial Plot Grid Generator")
st.write("Generate a field trial grid from a starting coordinate and an alignment coordinate.")

if 'generated' not in st.session_state:
    st.session_state.generated = False

# Initialize Session State for GPS Coordinates
if 'p1_lat' not in st.session_state: st.session_state.p1_lat = -25.73300000
if 'p1_lon' not in st.session_state: st.session_state.p1_lon = -53.05800000
if 'p2_lat' not in st.session_state: st.session_state.p2_lat = -25.73400000
if 'p2_lon' not in st.session_state: st.session_state.p2_lon = -53.05800000

# Sidebar Inputs
with st.sidebar:
    st.header("1. Input Coordinates")
    
    input_format = st.radio(
        "Select Input Format", 
        options=["Decimal Degrees (DD)", "GMS (Single Smart Field)", "GMS (Separate Fields)"]
    )
    
    st.write("---")
    
    # OPTION 1: Decimal Degrees (With GPS Integration)
    if input_format == "Decimal Degrees (DD)":
        st.write("**First Plot Outside Corner (P1)**")
        
        # Geolocation Button for P1
        p1_loc = streamlit_geolocation(key="p1_geo")
        if p1_loc and p1_loc.get('latitude'):
            st.session_state.p1_lat = p1_loc['latitude']
            st.session_state.p1_lon = p1_loc['longitude']
            
        lat1_dd = st.number_input("P1 Latitude (DD)", value=st.session_state.p1_lat, format="%.8f")
        lon1_dd = st.number_input("P1 Longitude (DD)", value=st.session_state.p1_lon, format="%.8f")
        
        st.write("---")
        st.write("**Alignment Point (P2)**")
        
        # Geolocation Button for P2
        p2_loc = streamlit_geolocation(key="p2_geo")
        if p2_loc and p2_loc.get('latitude'):
            st.session_state.p2_lat = p2_loc['latitude']
            st.session_state.p2_lon = p2_loc['longitude']
            
        lat2_dd = st.number_input("P2 Latitude (DD)", value=st.session_state.p2_lat, format="%.8f")
        lon2_dd = st.number_input("P2 Longitude (DD)", value=st.session_state.p2_lon, format="%.8f")
        
    # OPTION 2: Single Smart Field
    elif input_format == "GMS (Single Smart Field)":
        st.caption("✨ **Smart Input:** Just type numbers separated by spaces (e.g., `25 43 58.8 S`).")
        
        st.write("**First Plot Outside Corner (P1)**")
        lat1_smart = st.text_input("P1 Latitude", value="25 43 58.8 S")
        lon1_smart = st.text_input("P1 Longitude", value="53 03 28.8 W")
        
        st.write("**Alignment Point (P2)**")
        lat2_smart = st.text_input("P2 Latitude", value="25 44 02.4 S")
        lon2_smart = st.text_input("P2 Longitude", value="53 03 28.8 W")

    # OPTION 3: Separate Fields
    elif input_format == "GMS (Separate Fields)":
        st.write("**First Plot Outside Corner (P1)**")
        c1, c2, c3, c4 = st.columns(4)
        lat1_d = c1.number_input("Lat D", 0, 90, 25, key="l1_d")
        lat1_m = c2.number_input("M", 0, 59, 43, key="l1_m")
        lat1_s = c3.number_input("S", 0.0, 59.9, 58.8, format="%.1f", key="l1_s")
        lat1_dir = c4.selectbox("Dir", ["S", "N"], key="l1_dir")
        
        c1, c2, c3, c4 = st.columns(4)
        lon1_d = c1.number_input("Lon D", 0, 180, 53, key="lo1_d")
        lon1_m = c2.number_input("M", 0, 59, 3, key="lo1_m")
        lon1_s = c3.number_input("S", 0.0, 59.9, 28.8, format="%.1f", key="lo1_s")
        lon1_dir = c4.selectbox("Dir", ["W", "E"], key="lo1_dir")
        
        st.write("**Alignment Point (P2)**")
        c1, c2, c3, c4 = st.columns(4)
        lat2_d = c1.number_input("Lat D", 0, 90, 25, key="l2_d")
        lat2_m = c2.number_input("M", 0, 59, 44, key="l2_m")
        lat2_s = c3.number_input("S", 0.0, 59.9, 2.4, format="%.1f", key="l2_s")
        lat2_dir = c4.selectbox("Dir", ["S", "N"], key="l2_dir")
        
        c1, c2, c3, c4 = st.columns(4)
        lon2_d = c1.number_input("Lon D", 0, 180, 53, key="lo2_d")
        lon2_m = c2.number_input("M", 0, 59, 3, key="lo2_m")
        lon2_s = c3.number_input("S", 0.0, 59.9, 28.8, format="%.1f", key="lo2_s")
        lon2_dir = c4.selectbox("Dir", ["W", "E"], key="lo2_dir")
    
    st.header("2. Trial Layout")
    rows = st.number_input("Number of Rows", min_value=1, value=10, step=1)
    cols = st.number_input("Number of Columns", min_value=1, value=4, step=1)
    plot_len = st.number_input("Plot Length (meters)", min_value=0.1, value=5.0, step=0.5)
    plot_wid = st.number_input("Plot Width (meters)", min_value=0.1, value=2.0, step=0.5)
    
    st.header("3. KML Export Options")
    kml_polygons = st.checkbox("Include Polygons", value=True)
    kml_centroids = st.checkbox("Include Centroids (Center points)", value=False)
    kml_corners = st.checkbox("Include Corner Waypoints", value=False)

    st.header("4. Excel Export Options")
    excel_coord_format = st.radio(
        "Output Coordinate Format", 
        options=["Decimal Degrees (DD)", "Degrees, Minutes, Seconds (GMS)"]
    )
    
    if st.button("Generate Grid", type="primary"):
        st.session_state.generated = True

# --- PROCESSING ---
if st.session_state.generated:
    try:
        # Determine coordinates based on user selected input method
        if input_format == "Decimal Degrees (DD)":
            lat1, lon1 = lat1_dd, lon1_dd
            lat2, lon2 = lat2_dd, lon2_dd
        elif input_format == "GMS (Single Smart Field)":
            lat1 = parse_coordinate(lat1_smart, input_format)
            lon1 = parse_coordinate(lon1_smart, input_format)
            lat2 = parse_coordinate(lat2_smart, input_format)
            lon2 = parse_coordinate(lon2_smart, input_format)
        elif input_format == "GMS (Separate Fields)":
            lat1 = dms_to_dd(lat1_d, lat1_m, lat1_s, lat1_dir)
            lon1 = dms_to_dd(lon1_d, lon1_m, lon1_s, lon1_dir)
            lat2 = dms_to_dd(lat2_d, lat2_m, lat2_s, lat2_dir)
            lon2 = dms_to_dd(lon2_d, lon2_m, lon2_s, lon2_dir)
        
        start_point = (lat1, lon1)
        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
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
                
                plot_id = f"{c+1}{(r+1):02d}"
                
                plot_data.append({
                    "Plot_ID": plot_id,
                    "Row": r + 1,
                    "Col": c + 1,
                    "Corners_DD": [pt1, pt2, pt3, pt4]
                })

        grid_tl = start_point
        grid_bl = move_point(start_point, bearing, rows * plot_len)
        grid_br = move_point(grid_bl, bearing_perp, cols * plot_wid)
        grid_tr = move_point(start_point, bearing_perp, cols * plot_wid)
        outside_corners = [grid_tl, grid_bl, grid_br, grid_tr]

        # --- PLOTLY MAP VISUALIZATION ---
        st.subheader("Plotly Mapbox Satellite View")
        
        mapbox_token = st.secrets.get("MAPBOX_TOKEN", "")
        fig = go.Figure()

        fig.add_trace(go.Scattermapbox(
            mode="lines",
            lon=[lon1, lon2],
            lat=[lat1, lat2],
            line=dict(color='yellow', width=2),
            name="Alignment Vector",
            hoverinfo="name"
        ))

        for plot in plot_data:
            lats = [pt[0] for pt in plot["Corners_DD"]] + [plot["Corners_DD"][0][0]]
            lons = [pt[1] for pt in plot["Corners_DD"]] + [plot["Corners_DD"][0][1]]
            
            fig.add_trace(go.Scattermapbox(
                mode="lines",
                fill="toself",
                fillcolor="rgba(0, 128, 0, 0.3)",
                line=dict(color='white', width=1),
                lon=lons,
                lat=lats,
                name=f"Plot {plot['Plot_ID']}",
                text=f"Plot {plot['Plot_ID']}",
                hoverinfo="text"
            ))

        # Check if Mapbox token exists, fallback to open-source map if not
        layout_args = dict(
            margin=dict(l=0, r=0, t=0, b=0),
            height=600,
            showlegend=False
        )
        
        if mapbox_token:
            layout_args["mapbox"] = dict(
                accesstoken=mapbox_token,
                style="satellite",
                center=dict(lat=lat1, lon=lon1),
                zoom=19 
            )
        else:
            layout_args["mapbox"] = dict(
                style="open-street-map",
                center=dict(lat=lat1, lon=lon1),
                zoom=19 
            )

        fig.update_layout(**layout_args)
        st.plotly_chart(fig, use_container_width=True)

        # --- EXCEL GENERATION ---
        excel_rows_plots = []
        is_dd = (excel_coord_format == "Decimal Degrees (DD)")

        for p in plot_data:
            row_dict = {"Plot_ID": p["Plot_ID"], "Row": p["Row"], "Col": p["Col"]}
            
            for i, (lat, lon) in enumerate(p["Corners_DD"]):
                if is_dd:
                    row_dict[f"Corner_{i+1}_Lat"] = lat
                    row_dict[f"Corner_{i+1}_Lon"] = lon
                else:
                    row_dict[f"Corner_{i+1}_GMS"] = f"{dd_to_dms(lat, True)} {dd_to_dms(lon, False)}"
            
            c_lat, c_lon = get_centroid(p["Corners_DD"])
            if is_dd:
                row_dict["Centroid_Lat"] = c_lat
                row_dict["Centroid_Lon"] = c_lon
            else:
                row_dict["Centroid_GMS"] = f"{dd_to_dms(c_lat, True)} {dd_to_dms(c_lon, False)}"
                
            excel_rows_plots.append(row_dict)
            
        df_plots = pd.DataFrame(excel_rows_plots)
        
        excel_rows_outside = []
        corner_labels = ["Start (P1)", "Bottom-Left", "Bottom-Right", "Top-Right"]
        for label, (lat, lon) in zip(corner_labels, outside_corners):
            row_dict = {"Corner": label}
            if is_dd:
                row_dict["Lat"] = lat
                row_dict["Lon"] = lon
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
            st.download_button(
                label="📄 Download KML",
                data=kml_string,
                file_name="field_trial_grid.kml",
                mime="application/vnd.google-earth.kml+xml"
            )
        with col2:
            st.download_button(
                label="📊 Download Excel Coordinates",
                data=excel_buffer,
                file_name="field_trial_coordinates.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"⚠️ Error processing coordinates: {e}")
        st.stop()
