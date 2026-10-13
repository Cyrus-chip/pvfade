# Changelog

All notable changes to pvfade are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `simulate_pv_ac()` accepts an optional `weather` DataFrame with measured
  or externally simulated `ghi`/`dni`/`dhi` (plus optional `temp_air` and
  `wind_speed`), with timezone normalisation and input validation.
- `grid_search()` accepts `lifetime_kwargs`, forwarded to
  `simulate_lifetime()` (e.g. `{"initial_soc_frac": 0.8}`).
- "How pvfade compares" table in the README (spreadsheet / pvlib-manual /
  pvfade).

### Fixed
- `self_consumption_dispatch()` now rejects multidimensional, empty, NaN
  and infinite profiles, and non-finite/non-positive `usable_kwh`,
  `initial_soc_frac` and `dt_h`, instead of silently producing misleading
  energy balances.
- `capacity_retention()` rejects negative `k_cycle`/`k_cal`.
- `simulate_pv_ac()` rejects `tilt` outside [0, 180] degrees.
- PyBaMM extra install instructions now use the
  `pip install "pvfade[pybamm] @ git+https://..."` form (the package is not
  on PyPI).
- README: fixed heading levels of the weather-data and input-contract
  sections; updated the weather assumption (measured input is now
  supported); test badge count corrected.

## [0.1.0] - 2026-09-28

### Added
- PV yield chain on pvlib: solar position → Ineichen clear-sky (scaled by a
  clearness factor) → transposition → cell temperature → PVWatts DC/AC.
- Rule-based self-consumption dispatch with hourly energy bookkeeping and a
  year-by-year lifetime loop.
- Degradation feedback: square-root cycle + calendar aging laws mirroring
  SEI-growth physics close the loop between dispatch and usable capacity;
  simulation stops at battery end of life.
- Optional `calibrate_cycle_aging_with_pybamm()` helper fitting the
  cycle-aging coefficient from a short PyBaMM SPM run (`pip install
  pvfade[pybamm]`).
- Techno-economics on the faded energy series: NPV, LCOS, simple payback.
- `grid_search()` sizing over PV kW × battery kWh ranked by NPV.
- Test suite (30 tests), GitHub Actions CI (Python 3.11/3.12), and a
  runnable Shanghai household end-to-end example.
