import streamlit as st
import pandas as pd
import math
import simplekml
import io
from geopy.distance import geodesic
import plotly.graph_objects as go

# --- HELPER FUNCTIONS ---
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

# Sidebar Inputs
with st.sidebar:
    st.header("1. Coordinates")
    st.write("**First Plot Outside Corner (P1)**")
    lat1 = st.number_input("P1 Latitude (DD)", value=-25.733, format="%.6f")
    lon1 = st.number_input("P1 Longitude (DD)", value=-53.058, format="%.6f")
    
    st.write("**Alignment Point (P2)**")
    lat2 = st.number_input("P2 Latitude (DD)", value=-25.734, format="%.6f")
    lon2 = st.number_input("P2 Longitude (DD)", value=-53.058, format="%.6f")
    
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
        "Coordinate Format", 
        options=["Decimal Degrees (DD)", "Degrees, Minutes, Seconds (GMS)"]
    )
    
    if st.button("Generate Grid", type="primary"):
        st.session_state.generated = True

# --- PROCESSING ---
if st.session_state.generated:
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
            
            # Generate ID where Column is the hundreds digit and Row is zero-padded
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
    
    mapbox_token = st.secrets["MAPBOX_TOKEN"]
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

    fig.update_layout(
        mapbox=dict(
            accesstoken=mapbox_token,
            style="satellite",
            center=dict(lat=lat1, lon=lon1),
            zoom=19 
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=600,
        showlegend=False
    )
    
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
                # Concatenate GMS using a space instead of a comma
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