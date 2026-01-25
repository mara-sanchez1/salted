# src/data/weather_api.py
from __future__ import annotations

from dataclasses import dataclass
import requests


@dataclass(frozen=True)
class WeatherNow:
    temperature_c: float
    precip_last_hour_mm: float
    precip_last_6h_mm: float


def fetch_weather_now_open_meteo(
    lat: float = 49.2827,
    lon: float = -123.1207,
    timeout: int = 30,
) -> WeatherNow:
    """
    Fetch near-real-time weather for Vancouver using Open-Meteo.

    We request:
    - current temperature_2m
    - hourly precipitation (mm), then compute last 1h and last 6h totals

    Docs: Open-Meteo API
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m",
        "hourly": "precipitation",
        "timezone": "America/Vancouver",
        "forecast_days": 1,
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    temp_c = float(data["current"]["temperature_2m"])

    # hourly precip is an array aligned with hourly time stamps
    precip = data["hourly"]["precipitation"]
    # Use last complete hour if available; simple hackathon-safe approach:
    precip_last_hour = float(precip[-1]) if len(precip) >= 1 else 0.0
    precip_last_6h = float(sum(precip[-6:])) if len(precip) >= 6 else float(sum(precip))

    return WeatherNow(
        temperature_c=temp_c,
        precip_last_hour_mm=precip_last_hour,
        precip_last_6h_mm=precip_last_6h,
    )