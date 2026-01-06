# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repository notes
- No existing README, CLAUDE.md, or Cursor/Copilot rules found.
- Python version: 3.12.8 (from .python-version).

Project structure (big picture)
- main.py: E-paper display loop for Milan transit arrivals. Uses placeholder API data (get_arrivals returns static entries) and Pillow to render an 800x480 monochrome image. If the Waveshare driver is available (`waveshare_epd.epd7in5_V2`), it pushes the buffer to the 7.5" display and then sleeps; otherwise it saves `test_display.png` for local testing. The loop refreshes every 120 seconds; stop/location constants are at the top.
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
- `main.py` currently uses static arrival data; swap `get_arrivals` (and `get_nearby_stops` if needed) with real ATM/Muoversi API calls and keys when available.
- Ensure the target system has fonts at `/usr/share/fonts/truetype/dejavu/`; otherwise Pillow falls back to default fonts.
