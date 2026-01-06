# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repository notes
- No existing README, CLAUDE.md, or Cursor/Copilot rules found.
- Python version: 3.12.8 (from .python-version).

Project structure (big picture)
- main.py: E-paper display loop for Milan transit arrivals. Arrivals now come from GTFS static `data/stop_times.txt` via `get_arrivals_for_stops`, grouped by stop/direzione with two next arrivals per stop. Pillow renders an 800x480 mono image; with `waveshare_epd.epd7in5_V2` it drives the 7.5" panel, otherwise it saves `test_display.png`. Loop refresh every 120s; stop/location constants at the top.
- requirements.in / requirements.txt: Requests + Pillow; the display driver `waveshare-epd` is required at runtime on the device but is not pinned here.

Common commands
- Create virtual environment with uv `uv venv`
- Activate with: `source .venv/bin/activate`
- Compile requirements
```
    uv pip compile requirements.in \
    --universal \
    --output-file requirements.txt
```
- Install dependencies: `uv pip sync requirements.txt` (add `pip install waveshare-epd` on the device that drives the panel)
- Run display loop (blocking refresh every 120s): `python main.py`

Operational notes
- Arrivals: uses GTFS static `data/stop_times.txt`; `get_arrivals_for_stops` pulls all stops from `get_nearby_stops` and takes the two soonest per stop. Update GTFS data if schedules change.
- Ensure the target system has fonts at `/usr/share/fonts/truetype/dejavu/`; otherwise Pillow falls back to default fonts.
- `test_display.png` can be generated via `python - <<'PY' ... create_display_image ... PY` for local preview; file is gitignored.
- `.gitignore` excludes venv, pycache, pyc, `test_display.png`, `data/`, `requirements.txt`.
- If you switch to live APIs, replace GTFS reads in `get_arrivals_for_stops` and adapt grouping if needed.
