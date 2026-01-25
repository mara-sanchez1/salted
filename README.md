# SALTED

**Preventing Slippery Roads in Vancouver**

SALTED predicts black ice risk across Vancouver's road network by combining pavement condition data with weather features like temperature, moisture, and sun exposure. The model generates a composite risk score for each road segment, enabling safer route planning and targeted winter maintenance.

> Hackathon Project 2026

## Features

- Interactive road condition map using PyDeck
- Black ice risk scoring model
- Feature engineering pipeline combining weather and pavement data
- Route optimization based on risk ratings

## Risk Model

```python
black_ice_risk = 0.35 * temp_near_zero + 0.25 * recent_moisture + 0.15 * humidity_proxy+ 0.15 * sun_exposure + 0.15 * pavement_risk_adj + 0.30 * is_bridge
```

### Features Used

| Feature | Description |
|---------|-------------|
| `temp_near_zero` | Temperature risk score peaking near 0°C |
| `recent_moisture` | Recent precipitation indicator |
| `humidity_proxy` | Proximity to water bodies |
| `sun_exposure` | Solar exposure based on street orientation |
| `is_bridge` | Bridge segment indicator |
| `pavement_risk_adj` | Pavement condition risk score |

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data Source

[City of Vancouver Open Data Portal](https://opendata.vancouver.ca/explore/dataset/pavement-condition-rating/)

## Acknowledgments

- City of Vancouver Open Data Portal
- Streamlit & PyDeck
