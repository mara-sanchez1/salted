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
8) Normalize continuous features WITHOUT overwriting originals (creates *_s columns)
9) Compute black_ice_risk using scaled features
10) Save outputs:
    - outputs/top20.csv
    - outputs/risk_map.html
    - outputs/final_segments.gpkg      (best for geometry)
    - outputs/final_segments.geojson   (optional)
    - outputs/final_segments.csv       (optional, no geometry)

Run:
  python scripts/run_pipeline.py --outdir outputs --sample-n 5000 --round-output
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
# IMPORTANT: your src/model/risk.py must be the NEW version where
# normalize_columns returns (gdf, scaled_cols) and does NOT overwrite originals.
from src.model.risk import normalize_columns, compute_black_ice_risk

from src.geo.water import add_water_proximity_features
from src.geo.bridges import add_bridge_flag
from src.viz.map_folium import export_risk_map_html
from src.viz.route import main as find_route


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute black ice risk for Vancouver street segments.")
    p.add_argument("--place", default="Vancouver, British Columbia, Canada", help="OSM place query for water/bridges.")
    p.add_argument("--outdir", default="outputs", help="Output directory.")
    p.add_argument("--sample-n", type=int, default=4000, help="Segments to sample for the HTML map.")
    p.add_argument("--water-k", type=float, default=500.0, help="Decay constant for humidity_proxy = exp(-dist/k).")
    p.add_argument("--max-records", type=int, default=0, help="If >0, limit fetched pavement records (speed).")
    p.add_argument("--dataset", default="pavement-condition-rating", help="Vancouver Open Data dataset id.")
    p.add_argument(
        "--select",
        default=None,
        help="Optional ODS select clause using field IDs (snake_case). Leave empty to fetch all fields.",
    )
    p.add_argument("--lat", type=float, default=49.2827, help="Weather query latitude.")
    p.add_argument("--lon", type=float, default=-123.1207, help="Weather query longitude.")
    p.add_argument("--export-geojson", action="store_true", help="Also export GeoJSON (web-friendly, larger file).")
    p.add_argument("--export-csv", action="store_true", help="Also export CSV (no geometry).")
    p.add_argument("--round-output", action="store_true", help="Round numeric columns in final outputs for readability.")
    return p.parse_args()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1) Fetch pavement records
    max_records = args.max_records if args.max_records and args.max_records > 0 else None
    records = fetch_pavement_records(
        dataset=args.dataset,
        select=args.select,
        max_records=max_records,
    )
    if not records:
        raise RuntimeError("No records returned from the pavement dataset API.")

    # 2) Records -> GeoDataFrame
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
    gdf = add_pci_risk(gdf, pci_col="PCI Rating")
    gdf = add_bearing_and_sun_exposure(gdf)
    gdf = add_weather_features(gdf, temperature_c=w.temperature_c, precip_6h_mm=w.precip_last_6h_mm)

    # --- sanity check: dist_to_water_m should be meters BEFORE scaling
    if "dist_to_water_m" in gdf.columns and gdf["dist_to_water_m"].notna().any():
        # It is totally possible min is near 0, but max should usually be >> 1 meter
        if float(gdf["dist_to_water_m"].max()) <= 1.0:
            raise RuntimeError(
                "dist_to_water_m is already in [0,1] before scaling. "
                "Something upstream is overwriting meters."
            )

    # 8) Normalize continuous features WITHOUT overwriting originals (creates *_s)
    gdf, _scaled_cols = normalize_columns(
        gdf,
        cols=["humidity_proxy", "sun_exposure", "pavement_risk_adj", "dist_to_water_m", "temp_near_zero"],
        suffix="_s",
    )

    # --- sanity check: dist_to_water_m should STILL be meters AFTER scaling
    if "dist_to_water_m" in gdf.columns and gdf["dist_to_water_m"].notna().any():
        if float(gdf["dist_to_water_m"].max()) <= 1.0:
            raise RuntimeError(
                "dist_to_water_m got scaled to [0,1]. "
                "Your normalize_columns() is overwriting originals. "
                "Replace src/model/risk.py with the new version that creates *_s columns."
            )

    # 9) Compute risk using scaled columns (raw columns remain unchanged for output)
    gdf = compute_black_ice_risk(gdf, use_scaled=True, suffix="_s")

    # -------------------------
    # Output: final dataset for plotting (RAW values, clean for audience)
    # -------------------------
    plot_cols = [
        # identifiers
        "Road Name", "From Street", "To Street", "PCI Rating",
        "road_name", "from_street", "to_street", "pci_rating",

        # raw features
        "dist_to_water_m", "humidity_proxy",
        "pavement_risk", "pci_missing", "pavement_risk_adj",
        "bearing_deg", "sun_exposure", "is_bridge",
        "recent_moisture", "temp_near_zero",

        # output
        "black_ice_risk",
        "geometry",
    ]
    plot_cols = [c for c in plot_cols if c in gdf.columns]
    gdf_plot = gdf[plot_cols].copy()

    if args.round_output:
        for c in ["black_ice_risk", "humidity_proxy", "pavement_risk_adj", "sun_exposure", "temp_near_zero"]:
            if c in gdf_plot.columns:
                gdf_plot[c] = gdf_plot[c].round(3)
        if "dist_to_water_m" in gdf_plot.columns:
            gdf_plot["dist_to_water_m"] = gdf_plot["dist_to_water_m"].round(1)

    # Export final dataset for plotting
    gpkg_path = outdir / "final_segments.gpkg"
    gdf_plot.to_file(gpkg_path, driver="GPKG", layer="segments")

    if args.export_geojson:
        geojson_path = outdir / "final_segments.geojson"
        gdf_plot.to_crs(epsg=4326).to_file(geojson_path, driver="GeoJSON")

    if args.export_csv:
        csv_path = outdir / "final_segments.csv"
        gdf_plot.drop(columns=["geometry"], errors="ignore").to_csv(csv_path, index=False)

    # -------------------------
    # Output: Top-20 table
    # -------------------------
    top = gdf_plot.sort_values("black_ice_risk", ascending=False).head(20).copy()

    id_cols = _dedupe_keep_order(
        [c for c in ["Road Name", "From Street", "To Street", "road_name", "from_street", "to_street"] if c in top.columns]
    )

    top_cols = id_cols + [
        "black_ice_risk",
        "is_bridge",
        "dist_to_water_m",
        "humidity_proxy",
        "sun_exposure",
        "pavement_risk_adj",
        "recent_moisture",
        "temp_near_zero",
    ]
    top_cols = [c for c in top_cols if c in top.columns]

    top_csv_path = outdir / "top20.csv"
    top[top_cols].to_csv(top_csv_path, index=False)

    # -------------------------
    # Output: HTML risk map
    # -------------------------
    map_path = outdir / "risk_map.html"
    export_risk_map_html(gdf_plot, out_path=str(map_path), sample_n=args.sample_n)

    # Print summary
    print("\n=== Weather (Open-Meteo) ===")
    print(f"Temperature (°C): {w.temperature_c:.2f}")
    print(f"Precip last 1h (mm): {w.precip_last_hour_mm:.2f}")
    print(f"Precip last 6h (mm): {w.precip_last_6h_mm:.2f}")

    print("\n=== Outputs ===")
    print(f"Top 20 CSV: {top_csv_path}")
    print(f"Risk map HTML: {map_path}")
    print(f"Final segments (GeoPackage): {gpkg_path}")
    if args.export_geojson:
        print(f"Final segments (GeoJSON): {outdir / 'final_segments.geojson'}")
    if args.export_csv:
        print(f"Final segments (CSV, no geometry): {outdir / 'final_segments.csv'}")

    print("\n=== Top 10 Preview ===")
    print(top[top_cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()