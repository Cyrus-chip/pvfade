import numpy as np
import pandas as pd
import pytest

from pvfade.pv import simulate_pv_ac, synthetic_ambient_temperature


def test_simulate_pv_ac_shape_and_nonnegativity():
    pv = simulate_pv_ac(31.23, 121.47, 5.0, year=2025)
    assert len(pv) == 8760
    assert (pv >= 0).all()
    assert pv.sum() > 0  # Shanghai gets sun


def test_simulate_pv_ac_zero_at_night():
    pv = simulate_pv_ac(31.23, 121.47, 5.0, year=2025)
    midnight = pv.loc["2025-01-15 00:00:00+08:00"]
    assert midnight == 0.0


def test_simulate_pv_ac_peak_below_nameplate():
    pv = simulate_pv_ac(31.23, 121.47, 5.0, year=2025)
    assert pv.max() <= 5.0  # inverter + temperature losses


def test_simulate_pv_ac_scales_with_capacity():
    small = simulate_pv_ac(31.23, 121.47, 2.0, year=2025).sum()
    big = simulate_pv_ac(31.23, 121.47, 4.0, year=2025).sum()
    assert big == pytest.approx(2 * small, rel=1e-6)


def test_simulate_pv_ac_rejects_bad_inputs():
    with pytest.raises(ValueError):
        simulate_pv_ac(31.23, 121.47, 0.0)
    with pytest.raises(ValueError):
        simulate_pv_ac(31.23, 121.47, 5.0, clearness=1.5)


def test_synthetic_ambient_temperature_seasonality():
    times = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="Asia/Shanghai")[:-1]
    temp = synthetic_ambient_temperature(times, t_mean=17.0)
    jan = temp.loc["2025-01"].mean()
    jul = temp.loc["2025-07"].mean()
    assert jul > jan  # northern hemisphere
    assert abs(temp.mean() - 17.0) < 0.5


def _weather_frame(index=None):
    if index is None:
        index = pd.date_range(
            "2025-06-21 10:00", periods=3, freq="h", tz="Asia/Shanghai"
        )
    return pd.DataFrame(
        {
            "ghi": [700.0, 850.0, 600.0],
            "dni": [600.0, 750.0, 500.0],
            "dhi": [100.0, 100.0, 100.0],
            "temp_air": [25.0, 26.0, 27.0],
            "wind_speed": [1.0, 2.0, 1.5],
        },
        index=index,
    )


def test_simulate_pv_ac_accepts_user_weather():
    weather = _weather_frame()
    pv = simulate_pv_ac(31.23, 121.47, 5.0, weather=weather)

    assert pv.index.equals(weather.index)
    assert len(pv) == len(weather)
    assert (pv >= 0).all()
    assert pv.sum() > 0


def test_simulate_pv_ac_localizes_naive_weather_index():
    weather = _weather_frame(
        pd.date_range("2025-06-21 10:00", periods=3, freq="h")
    )
    pv = simulate_pv_ac(31.23, 121.47, 5.0, tz="Asia/Shanghai", weather=weather)

    assert str(pv.index.tz) == "Asia/Shanghai"


def test_simulate_pv_ac_uses_t_mean_when_weather_lacks_temperature():
    weather = _weather_frame().drop(columns=["temp_air", "wind_speed"])
    pv = simulate_pv_ac(31.23, 121.47, 5.0, weather=weather, t_mean=30.0)
    pv_cool = simulate_pv_ac(31.23, 121.47, 5.0, weather=weather, t_mean=10.0)

    assert len(pv) == len(weather)
    assert (pv >= 0).all()
    assert pv.sum() < pv_cool.sum()


def test_simulate_pv_ac_rejects_invalid_weather():
    index = pd.date_range("2025-06-21 10:00", periods=2, freq="h", tz="Asia/Shanghai")
    missing = pd.DataFrame({"ghi": [1.0, 2.0], "dni": [1.0, 2.0]}, index=index)
    with pytest.raises(ValueError, match="missing required columns"):
        simulate_pv_ac(31.23, 121.47, 5.0, weather=missing)

    invalid = _weather_frame()
    invalid.loc[invalid.index[0], "ghi"] = -1.0
    with pytest.raises(ValueError, match="non-negative"):
        simulate_pv_ac(31.23, 121.47, 5.0, weather=invalid)
