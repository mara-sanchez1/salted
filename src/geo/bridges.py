# src/geo/bridges.py
from __future__ import annotations

import geopandas as gpd
import osmnx as ox


def add_bridge_flag(
    gdf: gpd.GeoDataFrame,
    place: str = "Vancouver, British Columbia, Canada",
) -> gpd.GeoDataFrame:
    """
    Adds:
      - is_bridge (0/1)
    Requires gdf in a projected CRS (meters is fine).
    """
    gdf = gdf.copy()
    if gdf.crs is None:
        raise ValueError("gdf must have a CRS")

    tags = {"bridge": "yes"}
    bridges = ox.features_from_place(place, tags=tags)
    bridges = bridges[bridges.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    bridges = bridges.to_crs(gdf.crs)

    bridges_union = bridges.unary_union
    gdf["is_bridge"] = gdf.geometry.apply(lambda geom: geom.intersects(bridges_union)).astype(int)
    return gdf