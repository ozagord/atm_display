#!/usr/bin/env python

# -*- coding: utf-8 -*-

"""
Display e-paper per trasporti pubblici Milano - Piazza Ferravilla
Richiede: Raspberry Pi + Waveshare 7.5” e-paper display
"""

import csv
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIGURAZIONE =====

# Coordinate Piazza Ferravilla, Milano

LATITUDE = 45.5016
LONGITUDE = 9.1585
RADIUS = 300  # metri di ricerca fermate

# Aggiorna ogni N secondi

UPDATE_INTERVAL = 120
STOP_ID = "19259"  # stop_id presente in data/stop_times.txt
STOP_TIMES_PATH = Path(__file__).resolve().parent / "data" / "stop_times.txt"

# ===== FUNZIONI API =====

def get_nearby_stops():
    """
    Recupera fermate vicine usando API Muoversi Milano
    Alternativa: usa GTFS statico o API ATM
    """
    # Esempio con coordinate - adatta all’API che userai
    url = "https://giromilano.atm.it/proxy.ashx"


    # Per ora uso dati di esempio - sostituisci con chiamata API reale
    # Fermate comuni a Piazza Ferravilla:
    stops = [
        {"direzione": "Niguarda", "line": ["5"], "stop_id": "12422"},
        {"direzione": "Ortica", "line": ["5"], "stop_id": "12423"},
        {"direzione": "Lodi", "line": ["90"], "stop_id": "12424"},
        {"direzione": "Lotto", "line": ["91"], "stop_id": "12425"},
        {"direzione": "Fake1", "line": ["F1"], "stop_id": "19236"},
        {"direzione": "Fake2", "line": ["F2"], "stop_id": "19279"}
        # "12422";"Via B.Angelico, 1 prima di V.le Romagna";"5";9.22428124893046;45.4709402259963;"(45.4709402259963, 9.22428124893046)"
        # "12423";"P.za Ferravilla, 2 prima di V.le Romagna";"5";9.22336580028576;45.4710498582134;"(45.4710498582134, 9.22336580028576)"
        # "12424";V.le Romagna altezza P.za Ferravilla;"90";9.2236508585372;45.4712426610207;"(45.4712426610207, 9.2236508585372)"
        # "12425";"V.le Romagna, 24 prima di L.go Rio De Janeiro";"91";9.22387370376705;45.4717519434216;"(45.4717519434216, 9.22387370376705)"
    ]
    return stops

def get_arrivals_for_stops(stops):
    """
    Restituisce i prossimi arrivi per tutte le fermate fornite (GTFS statico).
    Per ogni stop_id: massimo 2 arrivi più imminenti, mantenendo "direzione" e "line".
    """
    now = datetime.now()
    stop_map = {str(s.get("stop_id")): s for s in stops}
    arrivals_by_stop = {sid: [] for sid in stop_map}

    try:
        with open(STOP_TIMES_PATH, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("stop_id")
                if sid not in stop_map:
                    continue

                arrival_str = row.get("arrival_time", "")
                try:
                    h, m, s = map(int, arrival_str.split(":"))
                except ValueError:
                    continue

                arrival_dt = datetime.combine(now.date(), datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)
                if arrival_dt < now:
                    arrival_dt += timedelta(days=1)

                minutes = max(0, int((arrival_dt - now).total_seconds() // 60))
                destination = row.get("stop_headsign") or "Destinazione non disponibile"

                stop_info = stop_map[sid]
                line_from_stop = stop_info.get("line") or stop_info.get("lines")
                if isinstance(line_from_stop, list) and line_from_stop:
                    line_label = line_from_stop[0]
                else:
                    line_label = line_from_stop or row.get("trip_id") or "Linea"

                arrivals_by_stop[sid].append({
                    "line": line_label,
                    "direzione": stop_info.get("direzione"),
                    "stop_id": sid,
                    "destination": destination,
                    "minutes": minutes
                })

        results = []
        for sid, items in arrivals_by_stop.items():
            items.sort(key=lambda a: a["minutes"])
            results.extend(items[:2])

        results.sort(key=lambda a: a["minutes"])
        return results

    except FileNotFoundError:
        print(f"File stop_times non trovato: {STOP_TIMES_PATH}")
    except Exception as e:
        print(f"Errore recupero dati: {e}")

    return []

# Retro-compatibilità: alias che usa lo STOP_ID di default

def get_arrivals(stop_id=None, line=None):
    stops = get_nearby_stops()
    # Se viene passato un singolo stop_id, filtra la lista, altrimenti usa tutte le fermate
    if stop_id is not None:
        stops = [s for s in stops if str(s.get("stop_id")) == str(stop_id)] or stops
    return get_arrivals_for_stops(stops)


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

    # Font (usa font di sistema o scarica Roboto/Arial)
    try:
        font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 40)
        font_medium = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 32)
        font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Header
    draw.text((20, 20), "PIAZZA FERRAVILLA", font=font_large, fill=0)

    # Ora corrente
    now = datetime.now().strftime("%H:%M")
    draw.text((width-150, 20), now, font=font_medium, fill=0)

    # Linea separatrice
    draw.line([(20, 80), (width-20, 80)], fill=0, width=3)

    # Raggruppa arrivi per stop/direzione
    y_offset = 110
    line_height = 60
    header_height = 45

    if not arrivals:
        draw.text((20, y_offset), "Nessun dato disponibile", font=font_medium, fill=0)
    else:
        groups = {}
        for arrival in arrivals:
            key = (arrival.get("stop_id"), arrival.get("direzione") or arrival.get("destination"))
            groups.setdefault(key, []).append(arrival)

        # ordina gruppi per arrivo più vicino
        ordered_groups = sorted(groups.items(), key=lambda kv: min(a["minutes"] for a in kv[1]))

        for (stop_id, direzione), items in ordered_groups:
            # Header per stop/direzione
            header_text = f"{direzione or 'Stop'} ({stop_id})"
            draw.text((20, y_offset), header_text, font=font_medium, fill=0)
            y_offset += header_height

            items.sort(key=lambda a: a["minutes"])
            for arrival in items:
                if y_offset > height - 70:
                    break

                # Numero linea (con cerchio)
                circle_x, circle_y = 40, y_offset + 15
                circle_radius = 22
                draw.ellipse([circle_x-circle_radius, circle_y-circle_radius,
                            circle_x+circle_radius, circle_y+circle_radius],
                            outline=0, width=3)

                # Testo linea
                line_text = arrival['line']
                bbox = draw.textbbox((0, 0), line_text, font=font_medium)
                text_width = bbox[2] - bbox[0]
                draw.text((circle_x - text_width//2, circle_y-16),
                        line_text, font=font_medium, fill=0)

                # Destinazione
                draw.text((100, y_offset), arrival['destination'],
                        font=font_medium, fill=0)

                # Tempo arrivo
                minutes = arrival['minutes']
                if minutes == 0:
                    time_text = "In arrivo"
                elif minutes == 1:
                    time_text = "1 min"
                else:
                    time_text = f"{minutes} min"

                draw.text((width-200, y_offset), time_text,
                        font=font_large, fill=0)

                y_offset += line_height

            if y_offset > height - 70:
                break

    # Footer
    draw.line([(20, height-60), (width-20, height-60)], fill=0, width=2)
    draw.text((20, height-45), "Aggiornamento automatico ogni 2 minuti",
            font=font_small, fill=0)

    return image



def update_display(image):
    """
    Aggiorna il display e-paper
    Richiede libreria waveshare_epd installata
    """
    try:
        # Importa driver Waveshare (installa con: pip install waveshare-epd)
        from waveshare_epd import epd7in5_V2

        epd = epd7in5_V2.EPD()
        epd.init()
        epd.Clear()

        # Converti e visualizza immagine
        epd.display(epd.getbuffer(image))

        # Sleep mode per risparmiare energia
        epd.sleep()

        print(f"Display aggiornato: {datetime.now()}")

    except ImportError:
        print("Libreria waveshare_epd non trovata. Salvo immagine per test.")
        image.save('test_display.png')
    except Exception as e:
        print(f"Errore aggiornamento display: {e}")

# ===== MAIN LOOP =====

def main():
    """
    Loop principale
    """
    print("=== Display Trasporti Milano - Piazza Ferravilla ===")
    print(f"Avvio alle {datetime.now()}")


    while True:
        try:
            # Recupera dati arrivi
            print("Recupero dati arrivi...")
            stops = get_nearby_stops()
            arrivals = get_arrivals_for_stops(stops)

            # Crea immagine
            print("Creazione immagine display...")
            image = create_display_image(arrivals)
            
            # Aggiorna display
            print("Aggiornamento display...")
            update_display(image)
            
            # Attendi prima del prossimo aggiornamento
            print(f"Prossimo aggiornamento tra {UPDATE_INTERVAL} secondi\n")
            time.sleep(UPDATE_INTERVAL)
            
        except KeyboardInterrupt:
            print("\nUscita...")
            break
        except Exception as e:
            print(f"Errore nel loop principale: {e}")
            time.sleep(60)  # Riprova tra 1 minuto in caso di errore


if __name__ == "__main__":
    main()
