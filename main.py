#!/usr/bin/env python

# -*- coding: utf-8 -*-

"""
Display e-paper per trasporti pubblici Milano - Piazza Ferravilla
Richiede: Raspberry Pi + Waveshare 7.5” e-paper display
"""

import io
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import re

import requests
import partridge as ptg
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIGURAZIONE =====

UPDATE_INTERVAL = 120  # Aggiorna ogni N secondi
GTFS_URL = "https://dati.comune.milano.it/gtfs.zip"
GTFS_PATH = Path(__file__).resolve().parent / "data" / "gtfs"
LOG_PATH = Path(__file__).resolve().parent / "atm_display.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 3
TARGET_STOPS = [12422, 12423, 12424, 12425, 12170]

handler = RotatingFileHandler(LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
console_handler = logging.StreamHandler()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[handler, console_handler],
)
logger = logging.getLogger(__name__)

# Stato display Waveshare
_epd_device = None
_update_counter = 0

# Font (usa font di sistema o scarica Roboto/Arial)
try:
    font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
    font_medium = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
    font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
except:
    font_large = ImageFont.truetype('/System/Library/Fonts/Supplemental/Tahoma Bold.ttf', 24)
    font_medium = ImageFont.truetype('/System/Library/Fonts/Supplemental/Tahoma.ttf', 20)
    font_small = ImageFont.truetype('/System/Library/Fonts/Supplemental/Tahoma.ttf', 16)
    # font_large = ImageFont.load_default()
    # font_medium = ImageFont.load_default()
    # font_small = ImageFont.load_default()

def download_gtfs_data():
    """
    Scarica e estrae i dati GTFS dal portale open data di Milano.
    """
    logger.info("Download dati GTFS da %s...", GTFS_URL)

    response = requests.get(GTFS_URL, timeout=60)
    response.raise_for_status()

    # Rimuovi directory esistente e ricrea
    if GTFS_PATH.exists():
        shutil.rmtree(GTFS_PATH)
    GTFS_PATH.mkdir(parents=True, exist_ok=True)

    # Estrai il contenuto dello zip
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        zf.extractall(GTFS_PATH)

    logger.info("Dati GTFS estratti in %s", GTFS_PATH)


def filter_stop_times_file(stop_times_path: Path, target_stops):
    """
    Usa grep per ridurre stop_times.txt alle sole righe per le fermate target.
    Restituisce il path (eventualmente filtrato) da usare nel feed.
    """
    if not stop_times_path.exists():
        logger.warning("stop_times.txt non trovato in %s", stop_times_path.parent)
        return stop_times_path

    target_ids = [str(s) for s in target_stops]
    if not target_ids:
        logger.info("Nessuna fermata target: nessun filtro applicato")
        return stop_times_path

    header = ""
    try:
        with stop_times_path.open("r", encoding="utf-8") as src:
            header = src.readline()
    except Exception:
        logger.exception("Impossibile leggere stop_times.txt per estrarre l'header")
        return stop_times_path

    filtered_path = stop_times_path.with_name("stop_times.filtered.txt")
    pattern = rf"\b({'|'.join(map(re.escape, target_ids))})\b"

    try:
        match_count = None
        count_cmd = ["grep", "-E", "-c", pattern, str(stop_times_path)]
        logger.info("Comando grep (conteggio): %s", " ".join(count_cmd))
        count_result = subprocess.run(
            count_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if count_result.returncode in (0, 1):
            try:
                match_count = int(count_result.stdout.strip() or 0)
            except ValueError:
                logger.warning("Impossibile parsare il conteggio delle righe grep: %r", count_result.stdout.strip())
        else:
            logger.warning("Conteggio grep su stop_times.txt fallito (code %s): %s", count_result.returncode, count_result.stderr.strip())

        if match_count == 0:
            logger.warning("grep su stop_times.txt ha trovato 0 righe: file lasciato intatto")
            return stop_times_path

        # Scrive prima l'header, poi appende le righe filtrate
        if header:
            with filtered_path.open("w", encoding="utf-8") as dest:
                dest.write(header)
        grep_cmd = ["grep", "-E", pattern, str(stop_times_path)]
        logger.info("Comando grep (estrazione): %s", " ".join(grep_cmd))
        with filtered_path.open("a", encoding="utf-8") as dest:
            result = subprocess.run(
                grep_cmd,
                stdout=dest,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

        if result.returncode not in (0, 1):
            logger.warning("grep su stop_times.txt fallito (code %s): %s", result.returncode, result.stderr.strip())
            filtered_path.unlink(missing_ok=True)
            return stop_times_path

        if match_count is not None:
            logger.info("stop_times.txt: %d righe corrispondono alle fermate target", match_count)

        shutil.move(filtered_path, stop_times_path)
        logger.info("stop_times.txt filtrato con grep per %d fermate target", len(target_ids))
        return stop_times_path

    except Exception:
        logger.exception("Errore durante il filtraggio di stop_times.txt")
        filtered_path.unlink(missing_ok=True)
        return stop_times_path


# ===== FUNZIONI API =====

def get_nearby_stops(feed, target_stops=None):
    """
    Recupera fermate dal feed GTFS già caricato in memoria.
    Restituisce solo le fermate elencate in target_stops.
    """
    if target_stops is None:
        target_stops = TARGET_STOPS

    target_stop_ids = [str(s) for s in target_stops]

    try:
        stops_df = feed.stops[feed.stops["stop_id"].isin(target_stop_ids)]

        stops = []
        for _, row in stops_df.iterrows():
            stops.append({
                "stop_id": row["stop_id"],
                "stop_name": row.get("stop_name", ""),
                "direzione": row.get("stop_name", ""),
                "line": [],
            })
        return stops

    except Exception:
        logger.exception("Errore recupero fermate")
        return []


def parse_gtfs_time(time_value, base_date):
    """
    Parses GTFS time (seconds since midnight as float) to datetime.
    Handles times > 24h (next day service).
    """
    try:
        if isinstance(time_value, (int, float)):
            total_seconds = int(time_value)
        else:
            # Fallback for string format "HH:MM:SS"
            h, m, s = map(int, str(time_value).split(":"))
            total_seconds = h * 3600 + m * 60 + s
    except (ValueError, TypeError):
        return None

    days_offset, remaining_seconds = divmod(total_seconds, 86400)
    return datetime.combine(base_date, datetime.min.time()) + timedelta(days=days_offset, seconds=remaining_seconds)

def filter_stop_times(feed, stops, service_ids_by_date):
    """
    Filtra i dati GTFS per le fermate specificate e li prepara per le query.
    Eseguito una sola volta all'avvio per ridurre il dataset in memoria.

    Restituisce un DataFrame con stop_times già uniti a trips e routes.
    """
    import pandas as pd

    stop_map = {str(s.get("stop_id")): s for s in stops}
    stop_ids = list(stop_map.keys())

    if not stop_ids:
        return pd.DataFrame(), stop_map

    try:
        # Filter by today's service patterns
        today = datetime.now().date()
        if service_ids_by_date and today in service_ids_by_date:
            service_ids = list(service_ids_by_date[today])
            active_trips = feed.trips[feed.trips["service_id"].isin(service_ids)]
            active_trip_ids = set(active_trips["trip_id"])
            stop_times = feed.stop_times[
                (feed.stop_times["stop_id"].isin(stop_ids)) &
                (feed.stop_times["trip_id"].isin(active_trip_ids))
            ]
        else:
            stop_times = feed.stop_times[feed.stop_times["stop_id"].isin(stop_ids)]

        if stop_times.empty:
            return pd.DataFrame(), stop_map

        # Pre-merge con trips e routes (fatto una sola volta)
        trips = feed.trips[["trip_id", "route_id", "trip_headsign", "direction_id"]]
        routes = feed.routes[["route_id", "route_short_name", "route_long_name"]]

        merged = stop_times.merge(trips, on="trip_id", how="left").merge(routes, on="route_id", how="left")

        logger.info("Dataset filtrato: %d righe per %d fermate", len(merged), len(stop_ids))
        return merged, stop_map

    except Exception:
        logger.exception("Errore filtraggio dati")
        return pd.DataFrame(), stop_map


def get_next_arrivals(stop_times_df, stop_map):
    """
    Interroga i dati pre-filtrati per trovare i prossimi 2 arrivi per linea/destinazione.
    Eseguito ad ogni ciclo di aggiornamento.
    """
    import pandas as pd

    if stop_times_df.empty:
        return []

    now = datetime.now()

    arrivals_by_line = {}

    for _, row in stop_times_df.iterrows():
        sid = row["stop_id"]
        arrival_dt = parse_gtfs_time(row.get("arrival_time", ""), now.date())
        if not arrival_dt:
            continue
        if arrival_dt < now:
            continue  # Skip past arrivals

        minutes = int((arrival_dt - now).total_seconds() // 60)
        if minutes > 120:
            continue  # Don't list arrivals that far ahead

        def get_str(val, default=""):
            if pd.isna(val):
                return default
            return str(val) if val else default

        destination = get_str(row.get("stop_headsign")) or get_str(row.get("trip_headsign")) or get_str(row.get("route_long_name")) or "Destinazione non disponibile"
        line_label = get_str(row.get("route_short_name")) or get_str(row.get("route_id")) or "Linea"

        stop_info = stop_map.get(sid, {})

        arrival_entry = {
            "line": line_label,
            "direzione": stop_info.get("direzione", destination),
            "stop_id": sid,
            "destination": destination,
            "minutes": minutes
        }

        # Group by line + destination
        group_key = (line_label, destination)
        if group_key not in arrivals_by_line:
            arrivals_by_line[group_key] = []
        arrivals_by_line[group_key].append(arrival_entry)

    # Limit to next 2 arrivals per line+destination
    results = []
    for group_key, items in arrivals_by_line.items():
        items.sort(key=lambda a: a["minutes"])
        results.extend(items[:2])

    results.sort(key=lambda a: a["minutes"])
    return results
# Retro-compatibilità: alias per uso semplificato

def get_arrivals(feed, service_ids_by_date, stop_id=None):
    stops = get_nearby_stops(feed)
    # Se viene passato un singolo stop_id, filtra la lista, altrimenti usa tutte le fermate
    if stop_id is not None:
        stops = [s for s in stops if str(s.get("stop_id")) == str(stop_id)] or stops
    stop_times_df, stop_map = filter_stop_times(feed, stops, service_ids_by_date)
    return get_next_arrivals(stop_times_df, stop_map)


# ===== FUNZIONI DISPLAY =====

def create_display_image(arrivals):
    """
    Crea immagine per display e-paper 7.5” (800x480)
    """
    # Dimensioni display Waveshare 7.5”
    width, height = 800, 480

    # Crea immagine bianca
    image = Image.new('1', (width, height), 255)  # '1' = monocromatico
    draw = ImageDraw.Draw(image)

    # Header
    draw.text((20, 10), "PROSSIME PARTENZE", font=font_large, fill=0)

    # Ora corrente
    now = datetime.now().strftime("%H:%M")
    draw.text((width-150, 10), now, font=font_medium, fill=0)

    # Linea separatrice
    draw.line([(20, 60), (width-20, 60)], fill=0, width=3)

    # Raggruppa arrivi per line/destination
    y_offset = 95
    line_height = 60

    if not arrivals:
        draw.text((20, y_offset), "Nessun dato disponibile", font=font_medium, fill=0)
    else:
        # Group arrivals by (line, destination)
        groups = {}
        for arrival in arrivals:
            key = (arrival.get("line"), arrival.get("destination"))
            groups.setdefault(key, []).append(arrival)

        # Sort groups by soonest arrival
        ordered_groups = sorted(groups.items(), key=lambda kv: min(a["minutes"] for a in kv[1]))

        for (line, destination), items in ordered_groups:
            if y_offset > height - 70:
                break

            items.sort(key=lambda a: a["minutes"])

            # Line number (with circle)
            circle_x, circle_y = 40, y_offset + 15
            circle_radius = 22
            draw.ellipse([circle_x-circle_radius, circle_y-circle_radius,
                        circle_x+circle_radius, circle_y+circle_radius],
                        outline=0, width=3)

            # Line text
            line_text = str(line)
            bbox = draw.textbbox((0, 0), line_text, font=font_medium)
            text_width = bbox[2] - bbox[0]
            draw.text((circle_x - text_width//2, circle_y-16),
                    line_text, font=font_medium, fill=0)

            # Destination
            draw.text((100, y_offset), destination, font=font_medium, fill=0)

            # Arrival times (up to 2 in columns)
            def format_minutes(minutes):
                if minutes == 0:
                    return "In arrivo"
                elif minutes == 1:
                    return "1 min"
                else:
                    return f"{minutes} min"

            time1 = format_minutes(items[0]["minutes"])
            draw.text((width-280, y_offset), time1, font=font_medium, fill=0)

            if len(items) > 1:
                time2 = format_minutes(items[1]["minutes"])
                draw.text((width-130, y_offset), time2, font=font_medium, fill=0)

            y_offset += line_height

    # Footer
    draw.line([(20, height-60), (width-20, height-60)], fill=0, width=2)
    draw.text((20, height-45), "Aggiornamento automatico ogni 2 minuti",
            font=font_small, fill=0)

    return image



def _get_epd():
    """Inizializza e restituisce l'istanza EPD (singleton)."""
    import sys
    sys.path.append("/home/utah/Downloads/e-Paper/RaspberryPi_JetsonNano/python/lib")

    global _epd_device
    if _epd_device is None:
        from waveshare_epd import epd7in5_V2
        _epd_device = epd7in5_V2.EPD()
        _epd_device.init()
        logger.info("Display EPD inizializzato")
    return _epd_device


def update_display(image):
    """
    Aggiorna il display e-paper.
    Init eseguito una sola volta; Clear ogni 10 aggiornamenti.
    """
    global _update_counter
    try:
        epd = _get_epd()
        epd.init_part()
    
        # Pulizia ogni 10 aggiornamenti (incluso il primo)
        if _update_counter % 10 == 0:
            epd.init()
            epd.Clear()

        epd.display(epd.getbuffer(image))
        epd.sleep()

        _update_counter += 1
        logger.info("Display aggiornato (%d)", _update_counter)

    except ImportError:
        logger.warning("Libreria waveshare_epd non trovata. Salvo immagine per test.")
        image.save('test_display.png')
    except Exception:
        logger.exception("Errore aggiornamento display")

# ===== MAIN LOOP =====

def load_gtfs_data():
    """
    Carica il feed GTFS e prepara i dati filtrati per le fermate.
    Restituisce (feed, service_ids_by_date, stops, stop_times_df, stop_map).
    """
    logger.info("Caricamento feed GTFS...")
    filter_stop_times_file(GTFS_PATH / "stop_times.txt", TARGET_STOPS)
    feed = ptg.load_feed(str(GTFS_PATH))
    service_ids_by_date = ptg.read_service_ids_by_date(str(GTFS_PATH))
    logger.info("Feed GTFS caricato: %d fermate, %d stop_times", len(feed.stops), len(feed.stop_times))

    stops = get_nearby_stops(feed)
    logger.info("Fermate monitorate: %d", len(stops))

    logger.info("Filtraggio dati per fermate selezionate...")
    stop_times_df, stop_map = filter_stop_times(feed, stops, service_ids_by_date)

    return feed, service_ids_by_date, stops, stop_times_df, stop_map



def should_update_gtfs(last_download_date):
    """
    Controlla se è il momento di aggiornare i dati GTFS.
    Aggiorna ogni venerdì dopo le 23:55, una sola volta.
    """
    now = datetime.now()
    is_friday = now.weekday() == 4
    is_after_2355 = now.hour == 23 and now.minute >= 55
    not_downloaded_today = last_download_date != now.date()

    return is_friday and is_after_2355 and not_downloaded_today


def main():
    """
    Loop principale
    """
    logger.info("=== Display Trasporti Milano - Piazza Ferravilla ===")
    logger.info("Avvio alle %s", datetime.now())

    # Scarica dati GTFS se non esistono
    if not GTFS_PATH.exists() or not any(GTFS_PATH.iterdir()):
        download_gtfs_data()
        last_download_date = datetime.now().date()
    else:
        logger.info("Dati GTFS esistenti trovati in %s", GTFS_PATH)
        last_download_date = None  # Non sappiamo quando sono stati scaricati

    # Carica feed GTFS in memoria
    feed, service_ids_by_date, stops, stop_times_df, stop_map = load_gtfs_data()
    global _update_counter
    while True:
        try:
            # Controlla se è ora di aggiornare i dati GTFS (venerdì dopo 23:55)
            if should_update_gtfs(last_download_date):
                logger.info("=== Aggiornamento settimanale GTFS ===")
                download_gtfs_data()
                _update_counter = 0
                last_download_date = datetime.now().date()
                feed, service_ids_by_date, stops, stop_times_df, stop_map = load_gtfs_data()

            # Interroga i dati pre-filtrati (operazione leggera)
            logger.info("Recupero dati arrivi...")
            arrivals = get_next_arrivals(stop_times_df, stop_map)

            # Stampa arrivi
            logger.info("Arrivi alle %s:", datetime.now().strftime('%H:%M'))
            for a in arrivals:
                logger.info("  Linea %3s → %-40s %3s min", a['line'], a['destination'], a['minutes'])

            # Crea immagine
            logger.info("Creazione immagine display...")
            image = create_display_image(arrivals)

            # Aggiorna display
            logger.info("Aggiornamento display...")
            update_display(image)

            # Attendi prima del prossimo aggiornamento
            logger.info("Prossimo aggiornamento tra %s secondi", UPDATE_INTERVAL)
            time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Uscita... pulisco il display")
            epd = _get_epd()
            epd.init()
            epd.Clear() # Pulisce prima di uscire
            epd.sleep()
            break
        except Exception:
            logger.exception("Errore nel loop principale")
            time.sleep(60)  # Riprova tra 1 minuto in caso di errore

if __name__ == "__main__":
    main()
