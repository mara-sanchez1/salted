"""
Vancouver Pavement Condition Data Viewer
Streamlit app for viewing pavement condition data from Vancouver Open Data.

This version:
✅ Fetches data with pagination (API limit is capped)
✅ Draws COLORED ROAD LINES using PyDeck (LineLayer)
✅ Handles LineString and MultiLineString geometries
✅ Includes clear comments for each section
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
    page_icon="🛣️",
    layout="wide",
)

st.title("🛣️ Vancouver Pavement Condition Rating")
st.write("Explore pavement condition data from the City of Vancouver Open Data Portal.")


# =========================
# 3) Data Loading (API → DataFrame) with Pagination
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

    page_size = 100  # ✅ ODS cap for this endpoint
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
# 4) Load + Clean Data
# =========================
df = load_pavement_data(max_records=25000)

if not df.empty:
    # Normalize rating strings so they match our color_map keys
    df["pci_rating"] = df["pci_rating"].astype(str).str.strip().str.title()


# =========================
# 5) PyDeck Map (Colored Road Segments)
# =========================
st.subheader("Interactive PyDeck Map (Colored Road Segments)")

if df.empty:
    st.warning("No data available for PyDeck map.")
else:
    # --- Color mapping (RGBA makes it extra clear) ---
    color_map = {
        "Excellent": [0, 200, 0, 220],
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
    st.markdown("**Legend:** 🟢 Excellent | 🟩 Good | 🟡 Fair | 🟠 Poor | 🔴 Very Poor")


st.divider()


# =========================
# 7) Full Data Table (iframe embed)
# =========================
st.subheader("Full Data Table")
components.iframe(
    src="https://opendata.vancouver.ca/explore/embed/dataset/pavement-condition-rating/table/"
    "?disjunctive.road_name&disjunctive.pci_rating&disjunctive.year"
    "&static=false&datasetcard=false",
    width=1200,
    height=500,
    scrolling=True,
)
