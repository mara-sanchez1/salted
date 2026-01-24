# src/geo/water.py
from __future__ import annotations

import numpy as np
import geopandas as gpd
import osmnx as ox


def add_water_proximity_features(
    gdf: gpd.GeoDataFrame,
    place: str = "Vancouver, British Columbia, Canada",
    k: float = 500.0,
) -> gpd.GeoDataFrame:
    """
    Adds:
      - dist_to_water_m
      - humidity_proxy = exp(-dist/k)
    Requires gdf in a metric CRS (meters), e.g., EPSG:26910.
    """
    gdf = gdf.copy()
    if gdf.crs is None:
        raise ValueError("gdf must have a CRS")
    if "26910" not in str(gdf.crs):
        # must be meters for distances
        gdf = gdf.to_crs(epsg=26910)

    tags = {"natural": "water"}
    water = ox.features_from_place(place, tags=tags)
    water = water[water.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    water = water.to_crs(gdf.crs)

    water_union = water.unary_union
    gdf["dist_to_water_m"] = gdf.geometry.apply(lambda geom: geom.distance(water_union))
    gdf["humidity_proxy"] = np.exp(-gdf["dist_to_water_m"] / k)
    return gdf