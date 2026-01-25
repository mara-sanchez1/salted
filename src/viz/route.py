"""
Route finding and visualization based on black ice risk.

This module provides functionality to:
1. Enrich street networks with black ice risk data from pavement segments
2. Find the safest route between two points based on risk-weighted paths
3. Visualize routes and risk data on an interactive Folium map
"""

from __future__ import annotations

import numpy as np
import geopandas as gpd
import osmnx as ox
import folium
from typing import Tuple


def enrich_street_network(
    gdf: gpd.GeoDataFrame,
    place: str = "Vancouver, British Columbia, Canada",
    network_type: str = "walk",
    distance_threshold: float = 300.0,
    max_distance: float = 500.0,
) -> Tuple[ox.graph, gpd.GeoDataFrame]:
    """
    Enrich a street network with black ice risk data from pavement segments.

    Args:
        gdf: GeoDataFrame with pavement segments containing 'black_ice_risk' column
        place: Place name for OSMnx to fetch street network
        network_type: Type of network ('walk', 'drive', 'bike')
        distance_threshold: Distance in meters for high confidence risk assignment
        max_distance: Maximum distance (meters) to search for nearest pavement (speeds up sjoin_nearest)

    Returns:
        Tuple of (networkx graph, enriched edges GeoDataFrame)
    """
    # Ensure gdf is a proper GeoDataFrame
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=gdf.crs)

    print("Fetching street network from OSM...")
    print("  (This can take 2-5 minutes for Vancouver - downloading ~10,000+ street segments)")
    import sys
    sys.stdout.flush()  # Ensure message appears immediately
    # Fetch street network
    G_full = ox.graph_from_place(place, network_type=network_type)
    nodes_full, edges_full = ox.graph_to_gdfs(G_full)
    print(f"  Found {len(edges_full)} street segments")

    # Ensure same CRS
    edges_full = edges_full.to_crs(gdf.crs)

    # --- Pavement midpoints (keep 'midpoint' as active geometry) ---
    pav = gdf.copy()
    pav["midpoint"] = pav.geometry.interpolate(0.5, normalized=True)
    pav_mid = pav.set_geometry("midpoint")
    pav_mid = pav_mid.set_crs(gdf.crs, allow_override=True)

    # Keep only needed columns BUT keep 'midpoint' because it's the active geometry
    # Select only columns that exist in the GeoDataFrame
    available_cols = [
        "black_ice_risk",
        "pavement_risk_adj",
        "pci_rating",
        "year",
        "risk_drivers",
        "midpoint",
    ]
    cols_to_keep = [col for col in available_cols if col in pav_mid.columns]
    cols_to_keep.append("midpoint")  # Always include midpoint (geometry)
    cols_to_keep = list(set(cols_to_keep))  # Remove duplicates
    pav_mid = pav_mid[cols_to_keep]

    # --- Full streets midpoints ---
    streets = edges_full.copy()
    streets["midpoint"] = streets.geometry.interpolate(0.5, normalized=True)
    streets_mid = streets.set_geometry("midpoint")
    streets_mid = streets_mid.set_crs(edges_full.crs, allow_override=True)

    # --- Ensure both are same CRS ---
    pav_mid = pav_mid.to_crs(streets_mid.crs)

    # --- Nearest join ---
    # This is the slowest step - computing nearest pavement for each street segment
    print(f"Matching {len(streets_mid)} street segments to {len(pav_mid)} pavement segments...")
    print("  (This may take a minute or two...)")
    enriched = gpd.sjoin_nearest(
        streets_mid,
        pav_mid,
        how="left",
        distance_col="dist_to_pavement",
        max_distance=max_distance,  # Limit search radius to speed up
    )
    print("  Matching complete!")

    edges_full["black_ice_risk"] = enriched["black_ice_risk"].values
    edges_full["dist_to_pavement"] = enriched["dist_to_pavement"].values
    
    # Add risk_drivers if it exists in enriched data
    if "risk_drivers" in enriched.columns:
        edges_full["risk_drivers"] = enriched["risk_drivers"].fillna(
            "estimated from nearest pavement segment"
        ).values
    else:
        edges_full["risk_drivers"] = "estimated from nearest pavement segment"

    # Fill missing values with median risk
    median_risk = float(np.nanmedian(edges_full["black_ice_risk"]))
    edges_full["black_ice_risk"] = edges_full["black_ice_risk"].fillna(median_risk)

    # Confidence based on distance to nearest pavement measurement
    edges_full["risk_confidence"] = np.where(
        edges_full["dist_to_pavement"] <= distance_threshold, "high", "low"
    )

    return G_full, edges_full


def find_safest_route(
    G: ox.graph,
    edges_full: gpd.GeoDataFrame,
    start_lonlat: Tuple[float, float],
    end_lonlat: Tuple[float, float],
    alpha: float = 8.0,
) -> gpd.GeoDataFrame:
    """
    Find the safest route between two points based on black ice risk.

    Args:
        G: NetworkX graph from OSMnx
        edges_full: GeoDataFrame with enriched edge data including 'black_ice_risk'
        start_lonlat: (longitude, latitude) of start point
        end_lonlat: (longitude, latitude) of end point
        alpha: Weight factor for prioritizing safety (higher = more safety-focused)

    Returns:
        GeoDataFrame of route edges in EPSG:4326
    """
    # Calculate median risk for fallback
    median_risk = float(np.nanmedian(edges_full["black_ice_risk"]))

    # Add weights to graph edges
    print(f"Assigning risk weights to {len(G.edges())} graph edges...")
    for u, v, k, data in G.edges(keys=True, data=True):
        try:
            risk = float(edges_full.loc[(u, v, k), "black_ice_risk"])
        except (KeyError, ValueError):
            risk = median_risk

        length = data.get("length", 1.0)

        # Weight favors low-risk streets
        data["weight"] = length * (1 + alpha * risk)
    
    print("  Weight assignment complete!")

    # Find nearest nodes to start and end points
    print("Finding safest route...")
    orig = ox.nearest_nodes(G, X=start_lonlat[0], Y=start_lonlat[1])
    dest = ox.nearest_nodes(G, X=end_lonlat[0], Y=end_lonlat[1])

    # Find shortest path (weighted by risk)
    route_nodes = ox.shortest_path(G, orig, dest, weight="weight")

    print(f"Route length (nodes): {len(route_nodes)}")

    # Convert route nodes to edges
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)

    # route_nodes is a list of node IDs; edges are between consecutive nodes
    route_edges = edges_gdf.loc[
        [(u, v, 0) for u, v in zip(route_nodes[:-1], route_nodes[1:])]
    ]
    route_edges = route_edges.to_crs("EPSG:4326")

    return route_edges


def visualize_route(
    gdf: gpd.GeoDataFrame,
    route_edges: gpd.GeoDataFrame,
    center_lat: float = 49.2827,
    center_lon: float = -123.1207,
    sample_n: int = 4000,
    zoom_start: int = 12,
) -> folium.Map:
    """
    Create an interactive Folium map showing risk data and the safest route.

    Args:
        gdf: GeoDataFrame with pavement segments and risk data
        route_edges: GeoDataFrame of route edges to display
        center_lat: Latitude for map center
        center_lon: Longitude for map center
        sample_n: Number of pavement segments to sample for display
        zoom_start: Initial zoom level

    Returns:
        Folium Map object
    """
    # --- Ensure both are lat/lon for Folium ---
    gdf_ll = gdf.to_crs(epsg=4326)
    route_edges_ll = route_edges.to_crs(epsg=4326)

    # Base map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)

    # --- Layer 1: Citywide black ice risk (sampled) ---
    sample = gdf_ll.sample(min(sample_n, len(gdf_ll)), random_state=0)

    def style_fn(feat):
        r = feat["properties"].get("black_ice_risk", 0)
        if r >= 0.75:
            color = "#d7191c"
        elif r >= 0.5:
            color = "#fdae61"
        else:
            color = "#1a9641"
        return {"color": color, "weight": 3, "opacity": 0.6}

    tooltip_fields = [
        c
        for c in [
            "road_name",
            "from_street",
            "to_street",
            "black_ice_risk",
            "risk_drivers",
            "pci_rating",
            "is_bridge",
        ]
        if c in sample.columns
    ]

    risk_layer = folium.FeatureGroup(name="Black ice risk (sample)", show=True)

    folium.GeoJson(
        sample,
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
    ).add_to(risk_layer)

    risk_layer.add_to(m)

    # --- Layer 2: Route overlay (on top) ---
    route_layer = folium.FeatureGroup(name="Safest route", show=True)

    folium.GeoJson(
        route_edges_ll,
        style_function=lambda feat: {"color": "#000000", "weight": 7, "opacity": 0.95},
        tooltip=folium.GeoJsonTooltip(
            fields=[
                c
                for c in ["name", "black_ice_risk", "risk_confidence"]
                if c in route_edges_ll.columns
            ]
        ),
    ).add_to(route_layer)

    route_layer.add_to(m)

    # Optional: fit map to route bounds
    bounds = route_edges_ll.total_bounds  # [minx, miny, maxx, maxy]
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    # Toggle layers
    folium.LayerControl().add_to(m)

    return m


def main(
    gdf: gpd.GeoDataFrame,
    start_lonlat: Tuple[float, float] = (-123.1207, 49.2827),
    end_lonlat: Tuple[float, float] = (-123.1140, 49.2635),
    place: str = "Vancouver, British Columbia, Canada",
    alpha: float = 8.0,
    max_distance: float = 500.0,
) -> Tuple[folium.Map, gpd.GeoDataFrame]:
    """
    Main function to find and visualize the safest route.

    Args:
        gdf: GeoDataFrame with pavement segments containing risk data
        start_lonlat: (longitude, latitude) of start point
        end_lonlat: (longitude, latitude) of end point
        place: Place name for OSMnx
        alpha: Safety prioritization factor
        max_distance: Maximum distance (meters) to search for nearest pavement

    Returns:
        Tuple of (Folium map, route edges GeoDataFrame)
    """
    print("Starting route finding process...")
    print("  Step 1: Enriching street network with risk data...")
    # Enrich street network with risk data
    G_full, edges_full = enrich_street_network(gdf, place=place, max_distance=max_distance)

    print("  Step 2: Finding safest route...")
    # Find safest route
    route_edges = find_safest_route(
        G_full, edges_full, start_lonlat, end_lonlat, alpha=alpha
    )

    print("  Step 3: Creating visualization...")
    # Create visualization
    m = visualize_route(gdf, route_edges)
    print("Route finding complete!")

    return m, route_edges
