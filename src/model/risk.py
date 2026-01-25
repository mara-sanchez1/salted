# src/model/risk.py
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler


def normalize_columns(
    gdf: gpd.GeoDataFrame,
    cols: list[str],
    suffix: str = "_s",
) -> tuple[gpd.GeoDataFrame, list[str]]:
    """
    Create scaled versions of columns WITHOUT modifying originals.

    Example:
      dist_to_water_m (meters) stays unchanged
      dist_to_water_m_s is created in [0, 1] for modeling

    Returns:
      (gdf_with_scaled_cols, scaled_col_names)
    """
    gdf = gdf.copy()
    cols = [c for c in cols if c in gdf.columns]
    if not cols:
        return gdf, []

    # Build a clean numeric matrix without touching gdf[cols]
    X = gdf[cols].copy()
    for c in cols:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    scaler = MinMaxScaler()
    Xs = scaler.fit_transform(X.values)

    scaled_cols: list[str] = []
    for i, c in enumerate(cols):
        sc = f"{c}{suffix}"
        gdf[sc] = Xs[:, i]
        scaled_cols.append(sc)

    return gdf, scaled_cols


def compute_black_ice_risk(
    gdf: gpd.GeoDataFrame,
    use_scaled: bool = True,
    suffix: str = "_s",
) -> gpd.GeoDataFrame:
    """
    Compute black_ice_risk.

    Requires (raw columns):
      - temp_near_zero, recent_moisture
      - humidity_proxy, sun_exposure, pavement_risk_adj, is_bridge

    If use_scaled=True and scaled versions exist (e.g., humidity_proxy_s),
    it will use the scaled columns for continuous features.
    Binary features remain unscaled: recent_moisture, is_bridge.
    """
    gdf = gdf.copy()

    def pick(name: str) -> str:
        sc = f"{name}{suffix}"
        return sc if (use_scaled and sc in gdf.columns) else name

    # Clip continuous inputs if present
    for base in ["temp_near_zero", "humidity_proxy", "sun_exposure", "pavement_risk_adj"]:
        c = pick(base)
        if c in gdf.columns:
            gdf[c] = pd.to_numeric(gdf[c], errors="coerce").fillna(0.0).clip(0, 1)

    # Ensure binary inputs clean
    if "recent_moisture" in gdf.columns:
        gdf["recent_moisture"] = pd.to_numeric(gdf["recent_moisture"], errors="coerce").fillna(0).astype(int)
    if "is_bridge" in gdf.columns:
        gdf["is_bridge"] = pd.to_numeric(gdf["is_bridge"], errors="coerce").fillna(0).astype(int)

    gdf["black_ice_risk"] = (
        0.35 * gdf.get(pick("temp_near_zero"), 0.0) +
        0.25 * gdf.get("recent_moisture", 0.0) +
        0.15 * gdf.get(pick("humidity_proxy"), 0.0) +
        0.15 * gdf.get(pick("sun_exposure"), 0.0) +
        0.15 * gdf.get(pick("pavement_risk_adj"), 0.0) +
        0.30 * gdf.get("is_bridge", 0.0)
    ).clip(0, 1)

    return gdf