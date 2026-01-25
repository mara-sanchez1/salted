# src/data/pavement_api.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests


VANCOUVER_PAVEMENT_DATASET = "pavement-condition-rating"


def fetch_pavement_records(
    dataset: str = VANCOUVER_PAVEMENT_DATASET,
    base_url: str = "https://opendata.vancouver.ca",
    limit: int = 100,
    max_records: Optional[int] = None,
    where: Optional[str] = None,
    select: Optional[str] = None,
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    endpoint = f"{base_url}/api/explore/v2.1/catalog/datasets/{dataset}/records"
    offset = 0
    out: List[Dict[str, Any]] = []

    while True:
        params = {"limit": limit, "offset": offset}
        if where:
            params["where"] = where
        if select:
            params["select"] = select

        r = requests.get(endpoint, params=params, timeout=timeout)

        # If select is invalid (common when using display labels), retry without select.
        if r.status_code == 400 and select:
            params.pop("select", None)
            r = requests.get(endpoint, params=params, timeout=timeout)

        r.raise_for_status()
        data = r.json()

        results = data.get("results", [])
        if not results:
            break

        out.extend(results)
        offset += limit

        if max_records is not None and len(out) >= max_records:
            return out[:max_records]

    return out