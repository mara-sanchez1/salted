# src/model/risk.py
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler


def normalize_columns(gdf: gpd.GeoDataFrame, cols: list[str]) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    cols = [c for c in cols if c in gdf.columns]
    if not cols:
        return gdf

    # numeric + inf handling
    for c in cols:
        gdf[c] = pd.to_numeric(gdf[c], errors="coerce")
    gdf[cols] = gdf[cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    scaler = MinMaxScaler()
    gdf[cols] = scaler.fit_transform(gdf[cols])
    return gdf


def compute_black_ice_risk(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Requires columns:
      - temp_near_zero, recent_moisture
      - humidity_proxy, sun_exposure, pavement_risk_adj, is_bridge
    """
    gdf = gdf.copy()
    for c in ["temp_near_zero", "humidity_proxy", "sun_exposure", "pavement_risk_adj"]:
        if c in gdf.columns:
            gdf[c] = gdf[c].clip(0, 1)

    # bridges are a strong boost; clip final to [0,1]
    gdf["black_ice_risk"] = (
        0.35 * gdf.get("temp_near_zero", 0.0) +
        0.25 * gdf.get("recent_moisture", 0.0) +
        0.15 * gdf.get("humidity_proxy", 0.0) +
        0.15 * gdf.get("sun_exposure", 0.0) +
        0.15 * gdf.get("pavement_risk_adj", 0.0) +
        0.30 * gdf.get("is_bridge", 0.0)
    ).clip(0, 1)

    return gdf