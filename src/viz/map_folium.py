# src/viz/map_folium.py
from __future__ import annotations

import folium
import geopandas as gpd


def export_risk_map_html(
    gdf: gpd.GeoDataFrame,
    out_path: str = "risk_map.html",
    sample_n: int = 4000,
) -> str:
    gdf_ll = gdf.to_crs(epsg=4326)
    center = [49.2827, -123.1207]
    m = folium.Map(location=center, zoom_start=12)

    if len(gdf_ll) > sample_n:
        gdf_ll = gdf_ll.sample(sample_n, random_state=0)

    def style_fn(feat):
        r = feat["properties"].get("black_ice_risk", 0)
        if r >= 0.75:
            color = "#d7191c"
        elif r >= 0.5:
            color = "#fdae61"
        else:
            color = "#1a9641"
        return {"color": color, "weight": 3, "opacity": 0.85}

    tooltip_fields = [c for c in ["Road Name","From Street","To Street","black_ice_risk","is_bridge","dist_to_water_m"] if c in gdf_ll.columns]

    folium.GeoJson(
        gdf_ll,
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields)
    ).add_to(m)

    m.save(out_path)
    return out_path