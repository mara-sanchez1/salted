# src/model/features.py
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd


def add_bearing_and_sun_exposure(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()

    def bearing_deg(line):
        (x1, y1), (x2, y2) = list(line.coords)[0], list(line.coords)[-1]
        ang = np.degrees(np.arctan2(x2 - x1, y2 - y1))
        return (ang + 360) % 360

    gdf["bearing_deg"] = gdf.geometry.apply(bearing_deg)

    def sun_exposure_score(b):
        # heuristic: north-ish = higher risk, south-ish = lower risk
        if 135 <= b <= 225:
            return 0.2
        elif b <= 45 or b >= 315:
            return 0.8
        else:
            return 0.5

    gdf["sun_exposure"] = gdf["bearing_deg"].apply(sun_exposure_score)
    return gdf


def add_pci_risk(gdf: gpd.GeoDataFrame, pci_col: str = "PCI Rating") -> gpd.GeoDataFrame:
    """
    Map PCI categories -> numeric risk, create missing flags + adjusted pci feature.
    """
    gdf = gdf.copy()

    pci_map = {
        "VERY GOOD": 0.1,
        "GOOD": 0.3,
        "FAIR": 0.5,
        "POOR": 0.8,
        "VERY POOR": 0.95,
    }

    # try common column names
    col = pci_col if pci_col in gdf.columns else ("pci_rating" if "pci_rating" in gdf.columns else None)
    if col is None:
        gdf["pavement_risk"] = np.nan
    else:
        gdf["pavement_risk"] = gdf[col].map(pci_map)

    gdf["pci_missing"] = gdf["pavement_risk"].isna().astype(int)
    default_pci = float(gdf["pavement_risk"].median()) if gdf["pavement_risk"].notna().any() else 0.5
    gdf["pavement_risk"] = gdf["pavement_risk"].fillna(default_pci)

    # discount PCI impact slightly when missing (reduces overconfidence)
    gdf["pavement_risk_adj"] = gdf["pavement_risk"] * (1 - 0.2 * gdf["pci_missing"])
    return gdf


def add_weather_features(gdf: gpd.GeoDataFrame, temperature_c: float, precip_6h_mm: float) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["recent_moisture"] = int(precip_6h_mm > 0)
    gdf["temp_near_zero"] = max(0.0, 1.0 - abs(temperature_c) / 5.0)  # peak at 0C, fades by +-5C
    return gdf