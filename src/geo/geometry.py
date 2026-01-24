# src/geo/geometry.py
from __future__ import annotations

from typing import Any, Dict, Optional
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape, LineString, MultiLineString


def geojson_to_linestring(obj: Any) -> Optional[LineString]:
    """
    Accepts GeoJSON geometry as dict (or already-parsed), returns a LineString.
    If MultiLineString, returns the longest component.
    """
    if obj is None or (isinstance(obj, float) and pd.isna(obj)):
        return None
    if not isinstance(obj, dict):
        return None

    gtype = obj.get("type")
    coords = obj.get("coordinates")

    if gtype == "LineString":
        if not coords or len(coords) < 2:
            return None
        return LineString(coords)

    if gtype == "MultiLineString":
        if not coords:
            return None
        parts = [LineString(c) for c in coords if c and len(c) >= 2]
        if not parts:
            return None
        return max(parts, key=lambda ln: ln.length)

    # fallback: try shapely.shape
    try:
        geom = shape(obj)
        if isinstance(geom, MultiLineString):
            return max(list(geom.geoms), key=lambda g: g.length)
        if isinstance(geom, LineString):
            return geom
    except Exception:
        return None

    return None


def records_to_gdf(
    records: list[dict],
    geom_field_candidates: tuple[str, ...] = ("Geom", "geom", "geo_shape", "geometry"),
    crs_epsg: int = 4326,
) -> gpd.GeoDataFrame:
    """
    Convert Opendatasoft records -> GeoDataFrame. Tries common geometry field names.
    """
    df = pd.DataFrame(records)

    geom_field = None
    for c in geom_field_candidates:
        if c in df.columns:
            geom_field = c
            break
    if geom_field is None:
        raise ValueError(f"No geometry field found. Columns: {list(df.columns)}")

    df["geometry"] = df[geom_field].apply(geojson_to_linestring)
    df = df.dropna(subset=["geometry"]).reset_index(drop=True)

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=f"EPSG:{crs_epsg}")
    return gdf