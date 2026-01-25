"""
Vancouver Pavement Condition Data Viewer
Streamlit app for viewing pavement condition data from Vancouver Open Data.

This version:
✅ Fetches data with pagination (API limit is capped)
✅ Draws COLORED ROAD LINES using PyDeck (LineLayer)
✅ Handles LineString and MultiLineString geometries
✅ Includes clear comments for each section
✅ Multi-page layout with sidebar navigation
"""

# =========================
# 1) Imports
# =========================
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import pydeck as pdk
import requests


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
# 4) Data Loading (API → DataFrame) with Pagination
# =========================
@st.cache_data
def load_pavement_data(max_records: int = 1000) -> pd.DataFrame:
    """
    Fetch pavement condition records from the ODS API.

    Important:
    - This endpoint caps `limit` at 100.
    - So we page through results using `offset`.

    Returns a DataFrame with:
    - road_name, pci_rating, pci_score, year
    - path: list of [lon, lat] coordinates (for drawing line segments)
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
            params = {
                "limit": page_size,
                "offset": offset,
            }

            resp = requests.get(base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                break  # no more rows available

            # Helper: add one road segment row
            def add_path(rec: dict, path: list):
                if isinstance(path, list) and len(path) > 1:
                    records.append(
                        {
                            "road_name": rec.get("road_name", "Unknown"),
                            "pci_rating": rec.get("pci_rating", "Unknown"),
                            "pci_score": rec.get("pci_score", 0),
                            "year": rec.get("year", "Unknown"),
                            "path": path,  # [[lon, lat], [lon, lat], ...]
                        }
                    )

            for rec in results:
                geom = rec.get("geom")
                if not geom or not geom.get("geometry"):
                    continue

                geometry = geom["geometry"]
                gtype = geometry.get("type")
                coords = geometry.get("coordinates", [])

                # Geometry can be LineString or MultiLineString
                if gtype == "LineString":
                    add_path(rec, coords)
                elif gtype == "MultiLineString":
                    for part in coords:
                        add_path(rec, part)

                if len(records) >= max_records:
                    break

            offset += page_size  # next page

        return pd.DataFrame(records)

    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()


# =========================
# 5) Page: Data Exploration
# =========================
def page_data_exploration():
    """Data Exploration page with map and data table."""
    st.title("Preventing Slippery Roads of Vancouver")
    st.markdown("<p style='font-size: 1.2rem;'>Combining weather patterns with pavement conditions to identify and prevent slippery road hazards across Vancouver.</p>", unsafe_allow_html=True)




    # Load + Clean Data
    df = load_pavement_data(max_records=10000)

    if not df.empty:
        # Normalize rating strings so they match our color_map keys
        df["pci_rating"] = df["pci_rating"].astype(str).str.strip().str.title()

    # PyDeck Map (Colored Road Segments)
    st.subheader("Vancouver Interactive Map")
    st.caption("Source: [City of Vancouver Open Data Portal](https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/map/?disjunctive.road_name&disjunctive.pci_rating&disjunctive.year)")

    if df.empty:
        st.warning("No data available for PyDeck map.")
    else:
        # --- Color mapping (RGBA makes it extra clear) ---
        color_map = {
            "Very Good": [0, 200, 0, 220],
            "Good": [50, 205, 50, 220],
            "Fair": [255, 220, 0, 220],
            "Poor": [255, 140, 0, 220],
            "Very Poor": [220, 20, 20, 220],
        }

        df["pci_rating"] = df["pci_rating"].astype(str).str.strip().str.title()
        df["color"] = df["pci_rating"].apply(
            lambda x: color_map.get(x, [180, 180, 180, 220])
        )

        # --- Compute a good map center from the data (so your lines are on-screen) ---
        # Take the first coordinate of each path as a representative point
        sample_points = (
            df["path"]
            .apply(lambda p: p[0] if isinstance(p, list) and len(p) > 0 else None)
            .dropna()
        )

        # Each point is [lon, lat]
        lons = sample_points.apply(lambda pt: pt[0])
        lats = sample_points.apply(lambda pt: pt[1])

        center_lon = float(lons.mean())
        center_lat = float(lats.mean())

        # Debug (optional): confirm ranges look like Vancouver
        with st.expander("Debug: coordinate ranges"):
            st.write(
                {
                    "lon_min": float(lons.min()),
                    "lon_max": float(lons.max()),
                    "lat_min": float(lats.min()),
                    "lat_max": float(lats.max()),
                    "center_lon": center_lon,
                    "center_lat": center_lat,
                    "rows": int(len(df)),
                }
            )

        # --- Use PathLayer (usually more visible / road-like than LineLayer) ---
        layer = pdk.Layer(
            "PathLayer",
            data=df,
            get_path="path",
            get_color="color",
            width_scale=30,  # makes paths thicker
            width_min_pixels=3,  # ensures visibility when zoomed out
            pickable=True,
        )

        # --- View state: center on the data ---
        view_state = pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=11.5,
            pitch=0,
        )

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip={
                "text": "Road: {road_name}\nRating: {pci_rating}\nScore: {pci_score}\nYear: {year}"
            },
        )

        st.pydeck_chart(deck)

        # Styled legend with colored boxes
        legend_html = """
        <div style="display: flex; flex-wrap: wrap; gap: 20px; align-items: center; padding: 10px 0;">
            <span style="font-weight: 600; margin-right: 8px;">Road Condition Legend:</span>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 16px; height: 16px; background-color: rgb(30, 80, 160); border-radius: 3px;"></div>
                <span>Very Good</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 16px; height: 16px; background-color: rgb(50, 205, 50); border-radius: 3px;"></div>
                <span>Good</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 16px; height: 16px; background-color: rgb(255, 220, 0); border-radius: 3px;"></div>
                <span>Fair</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 16px; height: 16px; background-color: rgb(255, 140, 0); border-radius: 3px;"></div>
                <span>Poor</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 16px; height: 16px; background-color: rgb(220, 20, 20); border-radius: 3px;"></div>
                <span>Very Poor</span>
            </div>
        </div>
        """
        st.markdown(legend_html, unsafe_allow_html=True)

    st.divider()

    # Full Data Table (iframe embed)
    st.subheader("City of Vancouver Open Data Portal")
    st.caption("[Source:](https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/map/?disjunctive.road_name&disjunctive.pci_rating&disjunctive.year)")

    components.iframe(
        src="https://opendata.vancouver.ca/explore/embed/dataset/pavement-condition-rating/table/"
        "?disjunctive.road_name&disjunctive.pci_rating&disjunctive.year"
        "&static=false&datasetcard=false",
        width=1200,
        height=500,
        scrolling=True,
    )


# =========================
# 6) Page: Insights
# =========================
def page_insights():
    """Insights page with analytics and summaries."""
    st.title("Analyze Features with Weather Data.")


    # =========================
    # HTML Embed Section 
    # =========================
    st.subheader("Feature Engineering Weather Data with Pavement Condition Data.")
    
    html_file_path = "outputs/risk_map.html"
    
    try:
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=600, scrolling=True)
    except FileNotFoundError:
        st.info("HTML visualization placeholder - update the file path in the code to display your visualization.")


    # =========================
    # CSV Data Preview Section 
    # =========================
    st.subheader("Feature Engineering Data Preview")
    
    csv_file_path = "outputs/final_segments.csv"
    
    try:
        csv_df = pd.read_csv(csv_file_path)
        st.dataframe(csv_df, use_container_width=True)
    except FileNotFoundError:
        st.info("CSV data preview placeholder - update the file path in the code to display your data.")
    
    st.markdown("""
    <style>
        .green-var { color: #2e7d32; font-weight: 600; font-family: monospace; }
        .feature-section { margin-bottom: 1.5rem; }
        .section-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem; color: #1a1a1a; }
        .feature-desc { margin-left: 1rem; margin-bottom: 0.3rem; }
        .model-eq { background-color: #f5f5f5; padding: 12px; border-radius: 6px; font-family: monospace; font-size: 0.9rem; margin: 1rem 0; }
    </style>
    
    <div class="feature-section">
        <p style="color: #666; margin-bottom: 0.5rem;">Features capturing whether conditions are favorable for ice formation.</p>
        <ul>
            <li><span class="green-var">temp_near_zero</span> - A non-linear temperature risk score (0-1) that peaks when air temperature is close to 0°C, where black ice is most likely to form.</li>
            <li><span class="green-var">recent_moisture</span> - Binary indicator (0/1) capturing whether there has been recent precipitation (rain or snow) in the last 6 hours.</li>
        </ul>
    </div>
    
    <div class="feature-section">
        <p style="color: #666; margin-bottom: 0.5rem;">Features approximating how likely moisture persists on the road surface.</p>
        <ul>
            <li><span class="green-var">dist_to_water_m</span> - Distance (in meters) from the street segment to the nearest water body (rivers, ocean, lakes). Used as a physical proxy for localized humidity and fog.</li>
            <li><span class="green-var">humidity_proxy</span> - A derived feature (0-1) computed as an exponential decay of distance to water. Streets closer to water are assumed to have higher ambient moisture.</li>
        </ul>
    </div>
    
    <div class="feature-section">
        <p style="color: #666; margin-bottom: 0.5rem;">Features capturing how quickly ice may melt during daylight hours.</p>
        <ul>
            <li><span class="green-var">bearing_deg</span> - The orientation of the street segment in degrees (0-360).</li>
            <li><span class="green-var">sun_exposure</span> - A heuristic score representing expected winter solar exposure based on street orientation. North-facing streets receive less sunlight and are more prone to persistent ice.</li>
        </ul>
    </div>
    
    <div class="feature-section">
        <p style="color: #666; margin-bottom: 0.5rem;">Features accounting for structural factors affecting freezing behavior.</p>
        <ul>
            <li><span class="green-var">is_bridge</span> - Binary indicator (0/1) identifying bridge segments. Bridges cool faster and freeze earlier due to air exposure on all sides.</li>
            <li><span class="green-var">pavement_risk_adj</span> - A normalized risk score (0-1) derived from the Pavement Condition Index (PCI). Poorer pavement increases water retention and uneven freezing.</li>
            <li><span class="green-var">pci_missing</span> - Flag indicating missing pavement condition data, allowing the model to handle incomplete inspections explicitly.</li>
        </ul>
    </div>
    
    
    <div class="feature-section">
        <ul>
            <li><span class="green-var">black_ice_risk</span> - A composite risk score (0-1) combining all features using weighted contributions. It represents relative risk, not a calibrated probability, and is designed for prioritization.</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

    # Model Equation
    st.subheader("Model Equation")
    st.code(
        "black_ice_risk = 0.35 * temp_near_zero + 0.25 * recent_moisture + 0.15 * humidity_proxy\n"
        "                + 0.15 * sun_exposure + 0.15 * pavement_risk_adj + 0.30 * is_bridge",
        language="python"
    )

# =========================
# 7) Page: Future Directions
# =========================
def page_future_directions():
    """Future Directions page with route optimization."""
    st.title("Future Directions")
    
    st.markdown("""
    <p style='font-size: 1.2rem;'>
    Searching for the most optimum route based on current state of roads using the black ice risk rating.
    </p>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    # =========================
    # Route Map Section
    # =========================
    st.subheader("Optimized Route Map")
    st.caption("Route optimization considering black ice risk factors across Vancouver road segments.")
    
    route_html_path = "outputs/route_map.html"
    
    try:
        with open(route_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=600, scrolling=True)
    except FileNotFoundError:
        st.info("Route map placeholder - add your route_map.html file to the outputs folder.")
    
    st.divider()
    
    # =========================
    # Future Work Description
    # =========================
    st.subheader("Planned Enhancements")
    
    st.markdown("""
    <style>
        .future-item { margin-bottom: 1rem; }
        .future-title { font-weight: 600; color: #1a1a1a; }
    </style>
    
    <div class="future-item">
        <p class="future-title">Real-time Route Optimization</p>
        <p style="color: #666;">Integrate live weather data to dynamically calculate the safest route between two points, minimizing exposure to high black ice risk segments.</p>
    </div>
    
    <div class="future-item">
        <p class="future-title">Multi-factor Cost Function</p>
        <p style="color: #666;">Develop a routing algorithm that balances travel time, distance, and black ice risk to find optimal paths for different user preferences.</p>
    </div>
    
    <div class="future-item">
        <p class="future-title">Predictive Alerts</p>
        <p style="color: #666;">Implement a notification system that warns drivers of hazardous conditions along their planned route based on weather forecasts.</p>
    </div>
    
    <div class="future-item">
        <p class="future-title">Historical Analysis</p>
        <p style="color: #666;">Analyze historical accident data to validate and improve the black ice risk model predictions.</p>
    </div>
    
    <div class="future-item">
        <p class="future-title">Mobile Integration</p>
        <p style="color: #666;">Develop a mobile-friendly interface for real-time navigation with black ice risk awareness.</p>
    </div>
    """, unsafe_allow_html=True)


# =========================
# 8) Main App Router
# =========================
if page == "Data Exploration":
    page_data_exploration()
elif page == "Insights":
    page_insights()
elif page == "Future Directions":
    page_future_directions()
