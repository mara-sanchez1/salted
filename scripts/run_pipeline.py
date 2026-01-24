#!/usr/bin/env python3
"""
Run the full Salted black-ice risk pipeline end-to-end.

Pipeline:
1) Pull pavement segments from Vancouver Open Data (Opendatasoft Explore API v2.1)
2) Convert GeoJSON geometry -> GeoDataFrame
3) Project to EPSG:26910 (meters)
4) Add water proximity (dist_to_water_m + humidity_proxy) via OSM (OSMnx)
5) Add bridge flag (is_bridge) via OSM (OSMnx)
6) Pull near-real-time weather (temperature + precip last 6h) via Open-Meteo
7) Add PCI risk + sun exposure + weather-derived features
8) Normalize continuous features
9) Compute black_ice_risk
10) Save outputs: outputs/top20.csv + outputs/risk_map.html

Run:
  python scripts/run_pipeline.py --outdir outputs --sample-n 5000

Optional (advanced): pass a valid ODS select clause using field IDs (snake_case):
  python scripts/run_pipeline.py --select "year,road_name,from_street,to_street,length_m,pci_rating,geom"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `import src.*` work when running `python scripts/run_pipeline.py`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse

from src.data.pavement_api import fetch_pavement_records
from src.geo.geometry import records_to_gdf
from src.data.weather_api import fetch_weather_now_open_meteo
from src.model.features import (
    add_bearing_and_sun_exposure,
    add_pci_risk,
    add_weather_features,
)
from src.model.risk import normalize_columns, compute_black_ice_risk

from src.geo.water import add_water_proximity_features
from src.geo.bridges import add_bridge_flag
from src.viz.map_folium import export_risk_map_html


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute black ice risk for Vancouver street segments.")
    p.add_argument("--place", default="Vancouver, British Columbia, Canada", help="OSM place query for water/bridges.")
    p.add_argument("--outdir", default="outputs", help="Output directory.")
    p.add_argument("--sample-n", type=int, default=4000, help="Segments to sample for the HTML map.")
    p.add_argument("--water-k", type=float, default=500.0, help="Decay constant for humidity_proxy = exp(-dist/k).")
    p.add_argument("--max-records", type=int, default=0, help="If >0, limit fetched pavement records (speed).")
    p.add_argument("--dataset", default="pavement-condition-rating", help="Vancouver Open Data dataset id.")

    # IMPORTANT: Leave select blank by default to avoid 400 errors from invalid field names.
    p.add_argument(
        "--select",
        default=None,
        help="Optional ODS select clause using field IDs (snake_case). Leave empty to fetch all fields.",
    )

    p.add_argument("--lat", type=float, default=49.2827, help="Weather query latitude.")
    p.add_argument("--lon", type=float, default=-123.1207, help="Weather query longitude.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) Fetch pavement records
    max_records = args.max_records if args.max_records and args.max_records > 0 else None
    records = fetch_pavement_records(
        dataset=args.dataset,
        select=args.select,  # None by default to avoid 400
        max_records=max_records,
    )
    if not records:
        raise RuntimeError("No records returned from the pavement dataset API.")

    # 2) Records -> GeoDataFrame (geometry field name varies by API; candidates cover common cases)
    gdf = records_to_gdf(records, geom_field_candidates=("Geom", "geo_shape", "geom", "geometry"))

    # 3) Project to Vancouver metric CRS (meters)
    gdf = gdf.to_crs(epsg=26910)

    # 4) Water proximity features
    gdf = add_water_proximity_features(gdf, place=args.place, k=args.water_k)

    # 5) Bridge flag
    gdf = add_bridge_flag(gdf, place=args.place)

    # 6) Weather now (Open-Meteo)
    w = fetch_weather_now_open_meteo(lat=args.lat, lon=args.lon)

    # 7) Feature engineering
    # PCI column name might differ depending on API field names. This handles both.
    gdf = add_pci_risk(gdf, pci_col="PCI Rating")
    gdf = add_bearing_and_sun_exposure(gdf)
    gdf = add_weather_features(gdf, temperature_c=w.temperature_c, precip_6h_mm=w.precip_last_6h_mm)

    # 8) Normalize continuous features
    gdf = normalize_columns(gdf, cols=["humidity_proxy", "sun_exposure", "pavement_risk_adj", "dist_to_water_m"])

    # 9) Compute final risk score
    gdf = compute_black_ice_risk(gdf)

    # 10) Save top-20 CSV
    top = gdf.sort_values("black_ice_risk", ascending=False).head(20).copy()

    # Keep human-readable columns if present (depends on API schema)
    display_cols = [c for c in ["Road Name", "From Street", "To Street", "PCI Rating", "road_name", "from_street", "to_street", "pci_rating"] if c in top.columns]
    # De-duplicate while preserving order
    seen = set()
    display_cols = [c for c in display_cols if not (c in seen or seen.add(c))]

    display_cols += [
        "black_ice_risk",
        "is_bridge",
        "dist_to_water_m",
        "humidity_proxy",
        "sun_exposure",
        "pavement_risk_adj",
        "recent_moisture",
        "temp_near_zero",
    ]
    display_cols = [c for c in display_cols if c in top.columns]

    top_csv_path = outdir / "top20.csv"
    top[display_cols].to_csv(top_csv_path, index=False)

    # 11) Save HTML risk map
    map_path = outdir / "risk_map.html"
    export_risk_map_html(gdf, out_path=str(map_path), sample_n=args.sample_n)

    # 12) Print summary
    print("\n=== Weather (Open-Meteo) ===")
    print(f"Temperature (°C): {w.temperature_c:.2f}")
    print(f"Precip last 1h (mm): {w.precip_last_hour_mm:.2f}")
    print(f"Precip last 6h (mm): {w.precip_last_6h_mm:.2f}")

    print("\n=== Outputs ===")
    print(f"Top 20 CSV: {top_csv_path}")
    print(f"Risk map HTML: {map_path}")

    print("\n=== Top 10 Preview ===")
    print(top[display_cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()