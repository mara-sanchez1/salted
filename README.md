# SALTED

**Preventing Slippery Roads in Vancouver**

SALTED predicts black ice risk across Vancouver's road network by combining pavement condition data with weather features like temperature, moisture, and sun exposure. The model generates a composite risk score for each road segment, enabling safer route planning and targeted winter maintenance.

> Hackathon Project 2026

## Demo Video

[![SALTED Demo Video](https://cdn.loom.com/sessions/thumbnails/8c3c0934beef4601bfacd5c9ee27a628-fcfb08cdb3188cc7-full.jpg#t=0.1)](https://www.loom.com/share/8c3c0934beef4601bfacd5c9ee27a628)

🎥 Click the image above to watch a short demo of SALTED in action.

## Features

- Interactive road condition map using PyDeck
- Black ice risk scoring model
- Feature engineering pipeline combining weather and pavement data
- Route optimization based on risk ratings

## Risk Model

The black ice risk score is computed as a weighted combination of
environmental and infrastructure features:

```python
black_ice_risk = (
    0.35 * temp_near_zero +
    0.25 * recent_moisture +
    0.15 * humidity_proxy +
    0.15 * sun_exposure +
    0.15 * pavement_risk_adj +
    0.30 * is_bridge
)
```
The final score is clipped to the range [0, 1].
All features are normalized internally for scoring, but raw values are preserved in outputs for transparency.

### Features Used

| Feature | Description |
|---------|-------------|
| `temp_near_zero` | Temperature risk score peaking near 0°C |
| `recent_moisture` | Recent precipitation indicator |
| `humidity_proxy` | Proximity to water bodies |
| `sun_exposure` | Solar exposure based on street orientation |
| `is_bridge` | Bridge segment indicator |
| `pavement_risk_adj` | Pavement condition risk score |

## Risk Model Assumptions

The current black ice risk model is heuristic and rule-based.

All feature weights were chosen based on:
- Domain intuition from transportation safety and winter road conditions
- Relative importance suggested by public safety literature
- Engineering judgment rather than labeled ground-truth data

No supervised labels (e.g., confirmed black ice incidents) were available at
the time of development.

As a result:
- The model is intended for relative risk ranking, not absolute prediction
- Scores should be interpreted comparatively across street segments
- Weights can be tuned or learned in future iterations

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## How to Run

### 1. Create Environment

### Option 1: Conda (recommended)
```bash
conda env create -f environment.yml
conda activate salted
```

### Option 2: Generate `requirements.txt` from conda

```bash
conda activate salted
pip freeze > requirements.txt
```

### 2. Run with real weather
```bash
python scripts/run_pipeline.py --outdir outputs --round-output
```
### 3. Run demo scenario (freezing rain)
```bash
python scripts/run_pipeline.py \
  --outdir outputs \
  --export-csv \
  --round-output \
  --demo-freezing-rain
```
This simulates 0 °C and recent precipitation, and it identifies structurally dangerous streets

## Outputs

File                         | Description
-----------------------------|---------------------------------------------
outputs/top20.csv            | Highest-risk street segments
outputs/final_segments.csv   | Full dataset (no geometry)
outputs/final_segments.gpkg  | Full geospatial dataset
outputs/risk_map.html        | Interactive map (hover for details)

## Data Sources

City of Vancouver Open Data Portal
- Pavement Condition Rating dataset
- Contains street segment geometries and PCI scores
- Used to estimate surface vulnerability

Dataset:
https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/

API documentation (Opendatasoft):
https://help.opendatasoft.com/apis/ods-search-v2/

Field descriptions:
https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/information/


OpenStreetMap (via OSMnx)
- Water bodies (oceans, rivers, lakes)
- Bridge infrastructure

OSM:
https://www.openstreetmap.org/

OSMnx docs:
https://osmnx.readthedocs.io/


Open-Meteo Weather API
- Near-real-time temperature
- Recent precipitation (1h / 6h)

API docs:
https://open-meteo.com/en/docs

## Acknowledgments

- City of Vancouver Open Data Portal
- OpenStreetMap contributors
- Open-Meteo Weather API
- GeoPandas, OSMnx, Folium
