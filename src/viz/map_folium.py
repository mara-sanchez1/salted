# src/viz/map_folium.py
from __future__ import annotations

import folium
import geopandas as gpd
import numpy as np


def export_risk_map_html(
    gdf: gpd.GeoDataFrame,
    out_path: str = "risk_map.html",
    sample_n: int = 4000,
    temperature_c: float | None = None,
    precip_last_1h_mm: float | None = None,
    precip_last_6h_mm: float | None = None,
) -> str:
    """
    Export an interactive HTML map showing black ice risk.

    Hover tooltip shows ALL features used in the analysis.
    A weather badge (temperature + precipitation) is displayed on the map.
    """

    # Convert to lat/lon for Folium
    gdf_ll = gdf.to_crs(epsg=4326)

    # Optional sampling for performance
    if len(gdf_ll) > sample_n:
        gdf_ll = gdf_ll.sample(sample_n, random_state=0)

    # Center map on data bounds
    minx, miny, maxx, maxy = gdf_ll.total_bounds
    center = [(miny + maxy) / 2, (minx + maxx) / 2]

    m = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    # -------------------------
    # Tooltip: ALL analysis features
    # -------------------------
    tooltip_fields = [
        # identifiers
        "road_name", "Road Name",
        "from_street", "From Street",
        "to_street", "To Street",

        # model inputs
        "black_ice_risk",
        "is_bridge",
        "dist_to_water_m",
        "humidity_proxy",
        "sun_exposure",
        "pavement_risk_adj",
        "recent_moisture",
        "temp_near_zero",
    ]
    tooltip_fields = [c for c in tooltip_fields if c in gdf_ll.columns]

    tooltip_aliases = {
        "road_name": "Road",
        "Road Name": "Road",
        "from_street": "From",
        "From Street": "From",
        "to_street": "To",
        "To Street": "To",
        "black_ice_risk": "Black ice risk (0–1)",
        "is_bridge": "Bridge (0/1)",
        "dist_to_water_m": "Distance to water (m)",
        "humidity_proxy": "Humidity proxy (0–1)",
        "sun_exposure": "Sun exposure (0–1)",
        "pavement_risk_adj": "Pavement risk (0–1)",
        "recent_moisture": "Recent moisture (0/1)",
        "temp_near_zero": "Temp near 0°C (0–1)",
    }

    tooltip = folium.GeoJsonTooltip(
        fields=tooltip_fields,
        aliases=[tooltip_aliases[c] + ": " for c in tooltip_fields],
        sticky=True,
        localize=True,
        labels=True,
    )

    # -------------------------
    # Styling based on risk
    # -------------------------
    def style_fn(feat):
        r = feat["properties"].get("black_ice_risk", 0.0) or 0.0
        try:
            r = float(r)
        except Exception:
            r = 0.0

        if r >= 0.75:
            color = "#d7191c"   # red
        elif r >= 0.5:
            color = "#fdae61"   # orange
        else:
            color = "#1a9641"   # green

        return {
            "color": color,
            "weight": 2 + 4 * r,
            "opacity": 0.4 + 0.5 * r,
        }

    folium.GeoJson(
        gdf_ll,
        style_function=style_fn,
        tooltip=tooltip,
        name="Black ice risk",
    ).add_to(m)

    # -------------------------
    # Weather badge (top-right)
    # -------------------------
    if temperature_c is not None or precip_last_1h_mm is not None or precip_last_6h_mm is not None:
        t = "—" if temperature_c is None else f"{temperature_c:.1f} °C"
        p1 = "—" if precip_last_1h_mm is None else f"{precip_last_1h_mm:.1f} mm"
        p6 = "—" if precip_last_6h_mm is None else f"{precip_last_6h_mm:.1f} mm"

        badge_html = f"""
        <div style="
            position: fixed;
            top: 12px;
            right: 12px;
            z-index: 9999;
            background: rgba(255,255,255,0.95);
            padding: 10px 12px;
            border-radius: 10px;
            border: 1px solid rgba(0,0,0,0.2);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            font-size: 13px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.15);
        ">
          <div style="font-weight: 700; margin-bottom: 4px;">Weather context</div>
          <div>Temperature: <b>{t}</b></div>
          <div>Precip (1h): <b>{p1}</b></div>
          <div>Precip (6h): <b>{p6}</b></div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(badge_html))

    folium.LayerControl(collapsed=True).add_to(m)
    m.save(out_path)
    return out_path