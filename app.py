"""
Vancouver Pavement Condition + Black Ice Risk Viewer

Features:
- Consistent PyDeck map across all tabs
- Data Exploration: visualize any available parameter on the map
- Insights: show calculated scores with same map style
- Future Directions: always show map, then highlight safest path after user input
- Legends for both categorical and numeric layers
- Weather summary cards for temperature / precipitation used in the model
"""

# =========================
# 1) Imports
# =========================
from math import cos, radians, sqrt
from pathlib import Path

import json
import networkx as nx
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
import streamlit.components.v1 as components
from shapely.geometry import LineString, MultiLineString

# =========================
# Demo Weather Context
# =========================
DEMO_TEMPERATURE_C = 0.0
DEMO_PRECIP_1H_MM = 1.0
DEMO_PRECIP_6H_MM = 4.0

# =========================
# 2) Streamlit Page Settings
# =========================
st.set_page_config(
    page_title="Vancouver Pavement Condition",
    layout="wide",
)


# =========================
# 3) Sidebar Navigation
# =========================
st.sidebar.title("Menu")
page = st.sidebar.radio(
    "Select a page:",
    ["Data Exploration", "Insights", "Future Directions"],
    index=0,
)

st.sidebar.divider()
st.sidebar.markdown("**AI at the edge of innovation**")
st.sidebar.caption("Hackathon Project 2026")


# =========================
# 4) Basic Helpers
# =========================
def approx_segment_length_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mean_lat = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * 111320 * cos(radians(mean_lat))
    dy = (lat2 - lat1) * 110540
    return sqrt(dx * dx + dy * dy)


def approx_point_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mean_lat = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * 111320 * cos(radians(mean_lat))
    dy = (lat2 - lat1) * 110540
    return sqrt(dx * dx + dy * dy)


def safe_mean(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    return float(s.mean()) if not s.empty else None


def format_metric_value(value, suffix=""):
    if value is None:
        return "N/A"
    if abs(value) >= 100:
        return f"{value:.1f}{suffix}"
    return f"{value:.3f}{suffix}"


# =========================
# 5) Data Loading (Open Data API)
# =========================
@st.cache_data
def load_pavement_data(max_records: int = 1000) -> pd.DataFrame:
    """
    Fetch pavement condition records from Vancouver Open Data API.
    Returns DataFrame with road_name, pci_rating, pci_score, year, path.
    """
    base_url = (
        "https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/"
        "pavement-condition-rating/records"
    )

    page_size = 100
    offset = 0
    records = []

    try:
        while len(records) < max_records:
            params = {"limit": page_size, "offset": offset}
            resp = requests.get(base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                break

            def add_path(rec: dict, path: list):
                if isinstance(path, list) and len(path) > 1:
                    records.append(
                        {
                            "road_name": rec.get("road_name", "Unknown"),
                            "pci_rating": rec.get("pci_rating", "Unknown"),
                            "pci_score": rec.get("pci_score", 0),
                            "year": rec.get("year", "Unknown"),
                            "path": path,
                        }
                    )

            for rec in results:
                geom = rec.get("geom")
                if not geom or not geom.get("geometry"):
                    continue

                geometry = geom["geometry"]
                gtype = geometry.get("type")
                coords = geometry.get("coordinates", [])

                if gtype == "LineString":
                    add_path(rec, coords)
                elif gtype == "MultiLineString":
                    for part in coords:
                        add_path(rec, part)

                if len(records) >= max_records:
                    break

            offset += page_size

        return pd.DataFrame(records)

    except Exception as e:
        st.error(f"Error fetching pavement data: {e}")
        return pd.DataFrame()


# =========================
# 6) Model / Segments Data
# =========================
@st.cache_data
def load_segments_gdf() -> pd.DataFrame:
    """
    Load road segments with engineered features and risk scores from GeoJSON.
    Returns a pandas DataFrame with a `geometry` column containing GeoJSON geometry dicts.
    """
    path = Path("outputs/final_segments.geojson")
    if not path.exists():
        return pd.DataFrame()

    with open(path, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    features = geojson_data.get("features", [])
    if not features:
        return pd.DataFrame()

    rows = []
    for feature in features:
        props = feature.get("properties", {}).copy()
        props["geometry"] = feature.get("geometry")
        rows.append(props)

    df = pd.DataFrame(rows)

    for col in [
        "black_ice_risk",
        "pci_score",
        "temp_near_zero",
        "recent_moisture",
        "dist_to_water_m",
        "humidity_proxy",
        "bearing_deg",
        "sun_exposure",
        "is_bridge",
        "pavement_risk_adj",
        "pci_missing",
        "air_temp_c",
        "temperature_c",
        "temp_c",
        "temperature",
        "air_temperature",
        "precip_mm",
        "precipitation_mm",
        "precipitation",
        "recent_precip_mm",
        "recent_precipitation_mm",
        "rain_mm",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "pci_rating" in df.columns:
        df["pci_rating"] = df["pci_rating"].astype(str).str.strip().str.title()
    else:
        df["pci_rating"] = "Unknown"

    if "road_name" not in df.columns:
        df["road_name"] = "Unknown"

    return df

@st.cache_data
def load_segments_table() -> pd.DataFrame:
    path = Path("outputs/final_segments.csv")
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)

    for col in df.columns:
        if df[col].dtype == "object":
            try:
                df[col] = pd.to_numeric(df[col])
            except Exception:
                pass

    return df


def get_map_center_from_gdf(gdf: pd.DataFrame):
    if gdf.empty:
        return 49.2827, -123.1207

    sample_points = []
    for geom in gdf["geometry"]:
        if not geom:
            continue

        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "LineString" and coords:
            sample_points.append(coords[0])
        elif gtype == "MultiLineString" and coords and coords[0]:
            sample_points.append(coords[0][0])

    if not sample_points:
        return 49.2827, -123.1207

    lons = [pt[0] for pt in sample_points]
    lats = [pt[1] for pt in sample_points]
    return float(sum(lats) / len(lats)), float(sum(lons) / len(lons))


def geometry_to_path(geom):
    if not geom:
        return None

    gtype = geom.get("type")
    coords = geom.get("coordinates", [])

    if gtype == "LineString":
        return [[lon, lat] for lon, lat in coords] if len(coords) > 1 else None

    if gtype == "MultiLineString":
        longest = None
        longest_len = -1
        for part in coords:
            if len(part) > longest_len:
                longest_len = len(part)
                longest = part
        if longest and len(longest) > 1:
            return [[lon, lat] for lon, lat in longest]

    return None


def prepare_map_dataframe(gdf: pd.DataFrame) -> pd.DataFrame:
    if gdf.empty:
        return pd.DataFrame()

    df = gdf.copy()
    df["path"] = df["geometry"].apply(geometry_to_path)
    df = df[df["path"].notna()].copy()

    if "road_name" not in df.columns:
        df["road_name"] = "Unknown"

    if "pci_rating" in df.columns:
        df["pci_rating"] = df["pci_rating"].astype(str).str.strip().str.title()
    else:
        df["pci_rating"] = "Unknown"

    return df.drop(columns="geometry")


# =========================
# 7) Weather / Parameter Discovery
# =========================
def detect_weather_columns(df: pd.DataFrame):
    temp_candidates = [
        "air_temp_c",
        "temperature_c",
        "temp_c",
        "temperature",
        "air_temperature",
    ]
    precip_candidates = [
        "precip_mm",
        "precipitation_mm",
        "precipitation",
        "recent_precip_mm",
        "recent_precipitation_mm",
        "rain_mm",
    ]

    temp_col = next((c for c in temp_candidates if c in df.columns), None)
    precip_col = next((c for c in precip_candidates if c in df.columns), None)

    return temp_col, precip_col


def get_parameter_catalog(df: pd.DataFrame):
    """
    Parameter options for Data Exploration.
    """
    options = []

    if "pci_rating" in df.columns:
        options.append(("Pavement Rating (categorical)", "pci_rating", "categorical"))

    for label, col in [
        ("PCI Score", "pci_score"),
        ("Black Ice Risk", "black_ice_risk"),
        ("Temperature Risk Near 0°C", "temp_near_zero"),
        ("Recent Moisture", "recent_moisture"),
        ("Distance to Water (m)", "dist_to_water_m"),
        ("Humidity Proxy", "humidity_proxy"),
        ("Bearing (deg)", "bearing_deg"),
        ("Sun Exposure", "sun_exposure"),
        ("Bridge Flag", "is_bridge"),
        ("Pavement Risk Adjustment", "pavement_risk_adj"),
        ("PCI Missing Flag", "pci_missing"),
        ("Current Temperature (°C)", "air_temp_c"),
        ("Current Temperature (°C)", "temperature_c"),
        ("Current Temperature (°C)", "temp_c"),
        ("Current Temperature (°C)", "temperature"),
        ("Current Temperature (°C)", "air_temperature"),
        ("Current Precipitation (mm)", "precip_mm"),
        ("Current Precipitation (mm)", "precipitation_mm"),
        ("Current Precipitation (mm)", "precipitation"),
        ("Current Precipitation (mm)", "recent_precip_mm"),
        ("Current Precipitation (mm)", "recent_precipitation_mm"),
        ("Current Precipitation (mm)", "rain_mm"),
    ]:
        if col in df.columns:
            options.append((label, col, "numeric"))

    # de-duplicate labels if same concept appears twice
    seen = set()
    deduped = []
    for item in options:
        key = (item[0], item[1])
        if key not in seen:
            deduped.append(item)
            seen.add(key)

    return deduped


# =========================
# 8) Map Styling Helpers
# =========================
def categorical_rating_color(rating: str):
    color_map = {
        "Very Good": [0, 200, 0, 220],
        "Good": [50, 205, 50, 220],
        "Fair": [255, 220, 0, 220],
        "Poor": [255, 140, 0, 220],
        "Very Poor": [220, 20, 20, 220],
    }
    return color_map.get(str(rating).strip().title(), [180, 180, 180, 220])


def numeric_color_scale(val, vmin, vmax):
    if pd.isna(val):
        return [180, 180, 180, 180]

    if vmax <= vmin:
        t = 0.5
    else:
        t = (float(val) - float(vmin)) / (float(vmax) - float(vmin))
        t = max(0.0, min(1.0, t))

    # blue -> yellow -> red
    if t < 0.5:
        local = t / 0.5
        r = int(30 + local * (255 - 30))
        g = int(144 + local * (220 - 144))
        b = int(255 + local * (0 - 255))
    else:
        local = (t - 0.5) / 0.5
        r = 255
        g = int(220 + local * (60 - 220))
        b = 0

    return [r, g, b, 220]


def add_map_colors(df: pd.DataFrame, selected_col: str, mode: str):
    out = df.copy()

    if mode == "categorical":
        out["color"] = out[selected_col].apply(categorical_rating_color)
        return out, None, None

    series = pd.to_numeric(out[selected_col], errors="coerce")
    vmin = float(series.quantile(0.05)) if series.notna().any() else 0.0
    vmax = float(series.quantile(0.95)) if series.notna().any() else 1.0
    out["color"] = series.apply(lambda x: numeric_color_scale(x, vmin, vmax))
    return out, vmin, vmax


def render_legend(selected_label: str, mode: str, vmin=None, vmax=None):
    if mode == "categorical":
        legend_html = f"""
        <div style="margin-top:10px; padding:12px; border:1px solid #ddd; border-radius:10px;">
            <div style="font-weight:700; margin-bottom:8px;">Legend — {selected_label}</div>
            <div style="display:flex; flex-wrap:wrap; gap:16px;">
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(0,200,0); border-radius:3px;"></div>
                    <span>Very Good</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(50,205,50); border-radius:3px;"></div>
                    <span>Good</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(255,220,0); border-radius:3px;"></div>
                    <span>Fair</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(255,140,0); border-radius:3px;"></div>
                    <span>Poor</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(220,20,20); border-radius:3px;"></div>
                    <span>Very Poor</span>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <div style="width:16px; height:16px; background-color:rgb(180,180,180); border-radius:3px;"></div>
                    <span>Missing / Unknown</span>
                </div>
            </div>
        </div>
        """
    else:
        legend_html = f"""
        <div style="margin-top:10px; padding:12px; border:1px solid #ddd; border-radius:10px;">
            <div style="font-weight:700; margin-bottom:8px;">Legend — {selected_label}</div>
            <div style="display:flex; align-items:center; gap:12px;">
                <span>{vmin:.3f}</span>
                <div style="width:260px; height:16px; border-radius:8px;
                            background: linear-gradient(to right,
                            rgb(30,144,255), rgb(255,220,0), rgb(255,60,0));">
                </div>
                <span>{vmax:.3f}</span>
            </div>
            <div style="margin-top:6px; color:#666; font-size:0.9rem;">
                Lower values shown in blue, mid values in yellow, higher values in red.
            </div>
        </div>
        """

    st.markdown(legend_html, unsafe_allow_html=True)


def build_tooltip(selected_label: str, selected_col: str):
    return {
        "html": f"""
        <b>Road:</b> {{road_name}}<br/>
        <b>{selected_label}:</b> {{{selected_col}}}<br/>
        <b>PCI Rating:</b> {{pci_rating}}<br/>
        <b>Black Ice Risk:</b> {{black_ice_risk}}<br/>
        <b>Demo Temp:</b> {DEMO_TEMPERATURE_C:.1f} °C<br/>
        <b>Demo Precip (1h):</b> {DEMO_PRECIP_1H_MM:.1f} mm<br/>
        <b>Demo Precip (6h):</b> {DEMO_PRECIP_6H_MM:.1f} mm
        """
    }


def render_shared_map(
    gdf: pd.DataFrame,
    selected_label: str,
    selected_col: str,
    mode: str,
    route_coords=None,
    origin_point=None,
    destination_point=None,
):
    if gdf.empty:
        st.warning("No model segment data available.")
        return

    df_map = prepare_map_dataframe(gdf)
    if df_map.empty:
        st.warning("No drawable road geometries available.")
        return

    if selected_col not in df_map.columns:
        st.warning(f"Column '{selected_col}' not found in segment data.")
        return

    df_map, vmin, vmax = add_map_colors(df_map, selected_col, mode)
    center_lat, center_lon = get_map_center_from_gdf(gdf)

    base_layer = pdk.Layer(
        "PathLayer",
        data=df_map,
        get_path="path",
        get_color="color",
        width_scale=30,
        width_min_pixels=3,
        pickable=True,
    )

    layers = [base_layer]

    if route_coords is not None and len(route_coords) > 1:
        route_df = pd.DataFrame([{"path": route_coords}])
        route_layer = pdk.Layer(
            "PathLayer",
            data=route_df,
            get_path="path",
            get_color=[155, 0, 255, 240],
            width_scale=45,
            width_min_pixels=7,
            pickable=False,
        )
        layers.append(route_layer)

    if origin_point is not None or destination_point is not None:
        point_rows = []

        if origin_point is not None:
            point_rows.append(
                {
                    "label": "Origin",
                    "lon": origin_point["lon"],
                    "lat": origin_point["lat"],
                    "color": [0, 102, 204, 220],
                }
            )

        if destination_point is not None:
            point_rows.append(
                {
                    "label": "Destination",
                    "lon": destination_point["lon"],
                    "lat": destination_point["lat"],
                    "color": [220, 20, 20, 220],
                }
            )

        point_df = pd.DataFrame(point_rows)

        point_layer = pdk.Layer(
            "ScatterplotLayer",
            data=point_df,
            get_position="[lon, lat]",
            get_radius=45,
            get_fill_color="color",
            pickable=True,
        )
        layers.append(point_layer)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=11.5,
            pitch=0,
        ),
        tooltip=build_tooltip(selected_label, selected_col),
    )

    st.pydeck_chart(deck, use_container_width=True)
    render_legend(selected_label, mode, vmin, vmax)


def render_weather_summary():
    st.caption("Demo weather context used for this prototype.")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("Temperature", f"{DEMO_TEMPERATURE_C:.1f} °C")

    with c2:
        st.metric("Precip (1h)", f"{DEMO_PRECIP_1H_MM:.1f} mm")

    with c3:
        st.metric("Precip (6h)", f"{DEMO_PRECIP_6H_MM:.1f} mm")


# =========================
# 9) Routing Helpers
# =========================
@st.cache_data
def geocode_location(query: str):
    if not query or not query.strip():
        return None

    search_query = f"{query}, Vancouver, BC, Canada"
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "salted-streamlit-app/1.0"}
    params = {"q": search_query, "format": "jsonv2", "limit": 1}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        return None


@st.cache_resource
def build_road_graph():
    gdf = load_segments_gdf()
    if gdf.empty:
        return None

    if "black_ice_risk" not in gdf.columns:
        raise ValueError("`black_ice_risk` column not found in outputs/final_segments.geojson")

    G = nx.Graph()

    def add_linestring_to_graph(coords, risk: float, row_data: dict):
        if len(coords) < 2:
            return

        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i + 1]

            u = (round(lon1, 5), round(lat1, 5))
            v = (round(lon2, 5), round(lat2, 5))

            length_m = approx_segment_length_m(lon1, lat1, lon2, lat2)
            weight = max(0.0001, float(length_m) * float(risk))

            G.add_node(u, pos=u)
            G.add_node(v, pos=v)

            G.add_edge(
                u,
                v,
                weight=weight,
                risk=float(risk),
                length_m=float(length_m),
                geometry=[[lon1, lat1], [lon2, lat2]],
                road_name=row_data.get("road_name", "Unknown"),
            )

    for _, row in gdf.iterrows():
        geom = row["geometry"]
        risk = row["black_ice_risk"]

        if pd.isna(risk):
            risk = 0.5

        if not geom:
            continue

        gtype = geom.get("type")
        coords = geom.get("coordinates", [])

        if gtype == "LineString":
            add_linestring_to_graph(coords, risk, row)
        elif gtype == "MultiLineString":
            for part in coords:
                add_linestring_to_graph(part, risk, row)

    return G


def nearest_graph_node(G, lon: float, lat: float):
    best_node = None
    best_dist = float("inf")

    for node in G.nodes:
        dist_m = approx_point_distance_m(lon, lat, node[0], node[1])
        if dist_m < best_dist:
            best_dist = dist_m
            best_node = node

    return best_node, best_dist


def extract_route_geometry(G, node_path):
    route_coords = []
    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]
        edge = G[u][v]
        geom = edge["geometry"]

        if i == 0:
            route_coords.extend(geom)
        else:
            route_coords.extend(geom[1:])

    return route_coords


def summarize_route(G, node_path):
    total_risk_cost = 0.0
    total_length_m = 0.0
    segment_risks = []

    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]
        edge = G[u][v]
        total_risk_cost += edge["weight"]
        total_length_m += edge["length_m"]
        segment_risks.append(edge["risk"])

    avg_risk = sum(segment_risks) / len(segment_risks) if segment_risks else 0.0

    return {
        "risk_cost": total_risk_cost,
        "length_km": total_length_m / 1000.0,
        "avg_risk": avg_risk,
        "segments": max(0, len(node_path) - 1),
    }


def compute_low_risk_route(origin_text: str, destination_text: str):
    G = build_road_graph()
    if G is None or G.number_of_nodes() == 0:
        raise ValueError("Road graph could not be built.")

    largest_cc = max(nx.connected_components(G), key=len)
    G_main = G.subgraph(largest_cc).copy()

    origin_coords = geocode_location(origin_text)
    dest_coords = geocode_location(destination_text)

    if origin_coords is None:
        raise ValueError(f"Could not geocode origin: {origin_text}")
    if dest_coords is None:
        raise ValueError(f"Could not geocode destination: {destination_text}")

    origin_lat, origin_lon = origin_coords
    dest_lat, dest_lon = dest_coords

    source, source_dist_m = nearest_graph_node(G_main, origin_lon, origin_lat)
    target, target_dist_m = nearest_graph_node(G_main, dest_lon, dest_lat)

    max_snap_distance_m = 1000
    if source is None or source_dist_m > max_snap_distance_m:
        raise ValueError(f"Origin is too far from the connected road network ({source_dist_m:.0f} m).")
    if target is None or target_dist_m > max_snap_distance_m:
        raise ValueError(f"Destination is too far from the connected road network ({target_dist_m:.0f} m).")

    try:
        node_path = nx.shortest_path(G_main, source=source, target=target, weight="weight")
    except nx.NetworkXNoPath:
        raise ValueError("No connected low-risk path was found between the selected locations.")

    route_coords = extract_route_geometry(G_main, node_path)
    summary = summarize_route(G_main, node_path)

    return {
        "origin": {"text": origin_text, "lat": origin_lat, "lon": origin_lon, "snap_distance_m": source_dist_m},
        "destination": {"text": destination_text, "lat": dest_lat, "lon": dest_lon, "snap_distance_m": target_dist_m},
        "route_coords": route_coords,
        "summary": summary,
    }


# =========================
# 10) Shared Section Helpers
# =========================
def get_default_map_selection(df: pd.DataFrame, preferred="black_ice_risk"):
    catalog = get_parameter_catalog(df)
    if not catalog:
        return None

    for label, col, mode in catalog:
        if col == preferred:
            return label, col, mode

    return catalog[0]


def render_parameter_selector(df: pd.DataFrame, key_prefix: str, preferred="black_ice_risk"):
    catalog = get_parameter_catalog(df)
    if not catalog:
        st.warning("No mappable parameters found in segment outputs.")
        return None

    labels = [item[0] for item in catalog]
    preferred_idx = 0
    for i, (_, col, _) in enumerate(catalog):
        if col == preferred:
            preferred_idx = i
            break

    selected_label = st.selectbox(
        "Select parameter to visualize",
        labels,
        index=preferred_idx,
        key=f"{key_prefix}_parameter_select",
    )

    selected = next(item for item in catalog if item[0] == selected_label)
    return selected


# =========================
# 11) Page: Data Exploration
# =========================
def page_data_exploration():
    st.title("Preventing Slippery Roads of Vancouver")
    st.markdown(
        "<p style='font-size: 1.2rem;'>Explore pavement condition, weather-linked factors, and model inputs across Vancouver road segments.</p>",
        unsafe_allow_html=True,
    )

    gdf = load_segments_gdf()
    segments_df = load_segments_table()
    pavement_df = load_pavement_data(max_records=10000)

    st.subheader("Weather Inputs Used in the Model")
    render_weather_summary()

    st.divider()

    st.subheader("Interactive Parameter Map")
    selection = render_parameter_selector(
        segments_df if not segments_df.empty else pd.DataFrame(gdf.drop(columns="geometry", errors="ignore")),
        key_prefix="explore",
        preferred="black_ice_risk",
    )

    if selection is not None:
        selected_label, selected_col, mode = selection
        render_shared_map(gdf, selected_label, selected_col, mode)

    st.divider()

    st.subheader("Raw Pavement Condition Open Data")
    st.caption(
        "Source: [City of Vancouver Open Data Portal](https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/map/?disjunctive.road_name&disjunctive.pci_rating&disjunctive.year)"
    )

    if pavement_df.empty:
        st.warning("No pavement data available from the Open Data API.")
    else:
        st.write(f"Loaded {len(pavement_df):,} pavement records.")
        st.dataframe(
            pavement_df[["road_name", "pci_rating", "pci_score", "year"]].head(200),
            use_container_width=True,
        )


# =========================
# 12) Page: Insights
# =========================
def page_insights():
    st.title("Insights")
    st.markdown(
        "<p style='font-size: 1.1rem;'>Review calculated black ice risk scores and the engineered features behind them, using the same map style as the exploration page.</p>",
        unsafe_allow_html=True,
    )

    gdf = load_segments_gdf()
    csv_df = load_segments_table()

    st.subheader("Weather Inputs Used in the Model")
    st.caption("For the demo, the app uses a fixed weather context rather than live weather data.")
    render_weather_summary()

    st.divider()

    st.subheader("Risk Score Map")
    selection = get_default_map_selection(
        csv_df if not csv_df.empty else pd.DataFrame(gdf.drop(columns="geometry", errors="ignore")),
        preferred="black_ice_risk",
    )
    if selection is not None:
        selected_label, selected_col, mode = selection
        render_shared_map(gdf, selected_label, selected_col, mode)

    st.divider()

    st.subheader("Feature Engineering Data Preview")
    if not csv_df.empty:
        st.dataframe(csv_df.head(200), use_container_width=True)
    else:
        st.info("CSV preview unavailable. Ensure outputs/final_segments.csv exists.")

    st.subheader("Feature Definitions")
    st.markdown(
        """
    <div style="line-height:1.7;">
        <b>temp_near_zero</b> — temperature-based risk score that peaks near 0°C.<br/>
        <b>recent_moisture</b> — indicator of recent rain / snow conditions.<br/>
        <b>dist_to_water_m</b> — distance to nearest water body, used as a moisture proxy.<br/>
        <b>humidity_proxy</b> — estimated humidity influence from distance to water.<br/>
        <b>bearing_deg</b> — segment orientation in degrees.<br/>
        <b>sun_exposure</b> — heuristic for winter solar exposure on the road.<br/>
        <b>is_bridge</b> — indicator for bridge segments.<br/>
        <b>pavement_risk_adj</b> — pavement-condition-based freezing adjustment.<br/>
        <b>pci_missing</b> — missing pavement inspection flag.<br/>
        <b>black_ice_risk</b> — composite risk score used for prioritization and routing.
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.subheader("Model Equation")
    st.code(
        "black_ice_risk = 0.35 * temp_near_zero + 0.25 * recent_moisture + 0.15 * humidity_proxy\n"
        "                + 0.15 * sun_exposure + 0.15 * pavement_risk_adj + 0.30 * is_bridge",
        language="python",
    )


# =========================
# 13) Page: Future Directions
# =========================
def page_future_directions():
    st.title("Future Directions")

    st.markdown(
        "<p style='font-size: 1.1rem;'>The map is always visible. After the user specifies origin and destination, the safest route is highlighted on top of the same map.</p>",
        unsafe_allow_html=True,
    )

    gdf = load_segments_gdf()
    csv_df = load_segments_table()

    st.subheader("Weather Inputs Used in the Model")
    render_weather_summary()

    st.divider()
    st.subheader("Safest Route Map")

    # Always show the same base map style first
    base_selection = get_default_map_selection(
        csv_df if not csv_df.empty else pd.DataFrame(gdf.drop(columns="geometry", errors="ignore")),
        preferred="black_ice_risk",
    )

    route_result = None

    col1, col2 = st.columns(2)
    with col1:
        origin = st.text_input("Origin", placeholder="e.g. UBC Vancouver")
    with col2:
        destination = st.text_input("Destination", placeholder="e.g. Vancouver General Hospital")

    run_route = st.button("Find Lowest-Risk Route", type="primary")

    st.caption("The base map always shows black ice risk by road segment. After a route is computed, the lowest-risk path is highlighted in purple, with origin and destination markers.")

    if run_route:
        if not origin or not destination:
            st.warning("Please enter both an origin and a destination.")
        else:
            try:
                with st.spinner("Computing safest route..."):
                    route_result = compute_low_risk_route(origin, destination)
            except Exception as e:
                st.error(f"Routing failed: {e}")

    # Always render the map
    if base_selection is not None:
        selected_label, selected_col, mode = base_selection
        render_shared_map(
            gdf,
            selected_label,
            selected_col,
            mode,
            route_coords=route_result["route_coords"] if route_result else None,
            origin_point=route_result["origin"] if route_result else None,
            destination_point=route_result["destination"] if route_result else None,
        )

    if route_result is not None:
        st.markdown(
            """
            <div style="margin-top:10px; padding:12px; border:1px solid #ddd; border-radius:10px;">
                <div style="font-weight:700; margin-bottom:8px;">Route Overlay Legend</div>
                <div style="display:flex; gap:18px; flex-wrap:wrap;">
                    <div style="display:flex; align-items:center; gap:6px;">
                        <div style="width:16px; height:16px; background-color:rgb(155,0,255); border-radius:3px;"></div>
                        <span>Lowest-risk route</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <div style="width:16px; height:16px; background-color:rgb(0,102,204); border-radius:50%;"></div>
                        <span>Origin</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <div style="width:16px; height:16px; background-color:rgb(220,20,20); border-radius:50%;"></div>
                        <span>Destination</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
    if route_result is not None:
        st.subheader("Route Summary")

        m1, m2, m3 = st.columns(3)
        m1.metric("Route length", f"{route_result['summary']['length_km']:.2f} km")
        m2.metric("Average segment risk", f"{route_result['summary']['avg_risk']:.3f}")
        m3.metric("Segments crossed", f"{route_result['summary']['segments']}")

        with st.expander("Route details"):
            st.write(
                {
                    "origin": route_result["origin"]["text"],
                    "destination": route_result["destination"]["text"],
                    "origin_snap_distance_m": round(route_result["origin"]["snap_distance_m"], 1),
                    "destination_snap_distance_m": round(route_result["destination"]["snap_distance_m"], 1),
                    "risk_cost": round(route_result["summary"]["risk_cost"], 3),
                    "avg_risk": round(route_result["summary"]["avg_risk"], 3),
                    "length_km": round(route_result["summary"]["length_km"], 3),
                    "segments": route_result["summary"]["segments"],
                }
            )

    st.divider()
    st.subheader("Planned Enhancements")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Live Weather Integration**")
        st.caption("Refresh road segment risk scores dynamically from current and forecast weather conditions before routing.")

        st.markdown("**Risk vs Time Tradeoff**")
        st.caption("Allow users to choose the safest route, the fastest route, or a balanced option.")

    with col2:
        st.markdown("**Turn-by-turn Directions**")
        st.caption("Integrate with a routing engine to provide instruction-level navigation.")

        st.markdown("**Road Closures and Incidents**")
        st.caption("Add dynamic constraints such as closures, snowfall events, and collision reports.")

# =========================
# Main App Router
# =========================
if page == "Data Exploration":
    page_data_exploration()
elif page == "Insights":
    page_insights()
elif page == "Future Directions":
    page_future_directions()
