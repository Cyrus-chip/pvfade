"""Photovoltaic generation modeling built on pvlib.

This module wraps pvlib's modeling chain

    solar position -> clear-sky irradiance -> transposition ->
    cell temperature -> DC -> AC

into a single function returning an AC power time series. With no
``weather`` input the chain runs on an Ineichen clear-sky model scaled by a
clearness factor, returning one hourly row per year; where on-site
measurements are available, pass them via ``weather`` and the output follows
the input timestamps instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib


def synthetic_ambient_temperature(
    times: pd.DatetimeIndex,
    t_mean: float = 17.0,
    t_annual_amp: float = 12.0,
    t_daily_amp: float = 4.0,
) -> pd.Series:
    """Simple annual + diurnal ambient temperature model (°C).

    Parameters
    ----------
    times : pd.DatetimeIndex
        Time steps to evaluate.
    t_mean : float
        Annual mean ambient temperature in °C.
    t_annual_amp : float
        Amplitude of the annual cycle in °C (coldest ~mid-January).
    t_daily_amp : float
        Amplitude of the diurnal cycle in °C (warmest ~14:00).

    Returns
    -------
    pd.Series
        Ambient temperature in °C.
    """
    doy = times.dayofyear.to_numpy(dtype=float)
    hod = times.hour.to_numpy(dtype=float) + times.minute.to_numpy(dtype=float) / 60.0
    temp = (
        t_mean
        - t_annual_amp * np.cos(2.0 * np.pi * (doy - 15.0) / 365.25)
        + t_daily_amp * np.cos(2.0 * np.pi * (hod - 14.0) / 24.0)
    )
    return pd.Series(temp, index=times, name="temp_air_c")


def _prepare_weather(
    weather: pd.DataFrame,
    tz: str,
    t_mean: float,
) -> tuple[pd.DatetimeIndex, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Validate and normalise a user-provided weather frame.

    Required columns are ``ghi``, ``dni`` and ``dhi`` in W/m².  ``temp_air``
    (°C) and ``wind_speed`` (m/s) are optional and fall back to the same
    transparent defaults used by the synthetic-weather path.
    """
    if not isinstance(weather, pd.DataFrame):
        raise TypeError("weather must be a pandas DataFrame")
    if weather.empty:
        raise ValueError("weather must contain at least one row")

    try:
        times = pd.DatetimeIndex(pd.to_datetime(weather.index))
    except (TypeError, ValueError) as exc:
        raise ValueError("weather index must contain valid datetimes") from exc
    if times.tz is None:
        times = times.tz_localize(tz)
    else:
        times = times.tz_convert(tz)
    if times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("weather index must be sorted and contain no duplicates")

    required = ("ghi", "dni", "dhi")
    missing = [column for column in required if column not in weather.columns]
    if missing:
        raise ValueError(f"weather is missing required columns: {', '.join(missing)}")

    frame = weather.copy()
    frame.index = times
    for column in (*required, "temp_air", "wind_speed"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    irradiance = frame[list(required)]
    if not np.isfinite(irradiance.to_numpy(dtype=float)).all():
        raise ValueError("weather irradiance columns must contain finite numeric values")
    if (irradiance < 0).any().any():
        raise ValueError("weather irradiance values must be non-negative")

    temp_air = (
        frame["temp_air"]
        if "temp_air" in frame
        else synthetic_ambient_temperature(times, t_mean=t_mean)
    )
    wind_speed = frame["wind_speed"] if "wind_speed" in frame else pd.Series(1.0, index=times)
    if not np.isfinite(temp_air.to_numpy(dtype=float)).all() or not np.isfinite(
        wind_speed.to_numpy(dtype=float)
    ).all():
        raise ValueError("weather temp_air and wind_speed values must be finite numeric values")
    if (wind_speed < 0).any():
        raise ValueError("weather wind_speed values must be non-negative")

    return (
        times,
        frame["dni"],
        frame["ghi"],
        frame["dhi"],
        temp_air,
        wind_speed,
    )


def simulate_pv_ac(
    latitude: float,
    longitude: float,
    capacity_kw: float,
    tilt: float | None = None,
    azimuth: float = 180.0,
    year: int = 2025,
    tz: str = "Asia/Shanghai",
    clearness: float = 0.75,
    t_mean: float = 17.0,
    weather: pd.DataFrame | None = None,
) -> pd.Series:
    """Simulate AC power (kW) of a fixed-tilt PV array.

    With no ``weather`` frame, uses pvlib's Ineichen clear-sky model scaled by
    ``clearness`` to emulate average cloud cover.  When ``weather`` is
    supplied, its measured or externally simulated irradiance is used
    directly.  Both paths use the isotropic transposition model via
    :func:`pvlib.irradiance.get_total_irradiance`, the PVWatts DC model, and
    the PVWatts inverter model.

    Parameters
    ----------
    latitude, longitude : float
        Site coordinates in degrees.
    capacity_kw : float
        Nameplate DC capacity in kW.
    tilt : float, optional
        Surface tilt in degrees; defaults to ``abs(latitude)``.
    azimuth : float
        Surface azimuth in degrees (180 = south in the northern hemisphere).
    year : int
        Calendar year to simulate when ``weather`` is not supplied (leap years
        handled by pandas).  Ignored when ``weather`` is supplied.
    tz : str
        Timezone of the output index.
    clearness : float
        Multiplicative derate applied to clear-sky irradiance (0-1].
    t_mean : float
        Annual mean ambient temperature in °C when ``weather`` is not
        supplied, or when the supplied frame does not contain ``temp_air``.
    weather : pandas.DataFrame, optional
        User-provided weather indexed by timestamps.  Required columns are
        ``ghi``, ``dni`` and ``dhi`` in W/m².  Optional columns are
        ``temp_air`` in °C and ``wind_speed`` in m/s.  A naive index is
        localised to ``tz``; a timezone-aware index is converted to ``tz``.
        The frame is not resampled, so the output has one row per input row.

    Returns
    -------
    pd.Series
        AC power in kW, indexed by local time.
    """
    if capacity_kw <= 0:
        raise ValueError("capacity_kw must be positive")
    if not 0 < clearness <= 1:
        raise ValueError("clearness must be in (0, 1]")
    if tilt is None:
        tilt = abs(latitude)
    if not 0 <= tilt <= 180:
        raise ValueError("tilt must be in [0, 180] degrees")

    location = pvlib.location.Location(latitude, longitude, tz=tz)
    if weather is None:
        times = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz=tz)[:-1]
        solpos = location.get_solarposition(times)
        cs = location.get_clearsky(times, model="ineichen")
        ghi = (cs["ghi"] * clearness).clip(lower=0.0)
        dni = (cs["dni"] * clearness).clip(lower=0.0)
        dhi = (cs["dhi"] * clearness).clip(lower=0.0)
        temp_air = synthetic_ambient_temperature(times, t_mean=t_mean)
        wind_speed = 1.0
    else:
        times, dni, ghi, dhi, temp_air, wind_speed = _prepare_weather(
            weather, tz=tz, t_mean=t_mean
        )
        solpos = location.get_solarposition(times)

    total = pvlib.irradiance.get_total_irradiance(
        tilt,
        azimuth,
        solpos["apparent_zenith"],
        solpos["azimuth"],
        dni,
        ghi,
        dhi,
    )
    poa = total["poa_global"].fillna(0.0).clip(lower=0.0)

    temp_cell = pvlib.temperature.pvsyst_cell(poa, temp_air, wind_speed=wind_speed)

    dc_w = pvlib.pvsystem.pvwatts_dc(
        poa, temp_cell, pdc0=capacity_kw * 1000.0, gamma_pdc=-0.004
    )
    ac_w = pvlib.inverter.pvwatts(dc_w, pdc0=capacity_kw * 1000.0)

    ac_kw = (ac_w / 1000.0).clip(lower=0.0)
    ac_kw.index = times
    ac_kw.name = "pv_ac_kw"
    return ac_kw
