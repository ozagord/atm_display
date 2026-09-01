import shutil
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from main import (
    filter_stop_times_file_python,
    get_next_arrivals,
    parse_gtfs_time,
    should_update_gtfs,
)


class TestMainDisplay(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_parse_gtfs_time(self):
        base_date = date(2026, 9, 1)
        # Test standard seconds as integer
        res = parse_gtfs_time(36000, base_date)  # 10:00:00
        self.assertEqual(res, datetime(2026, 9, 1, 10, 0, 0))

        # Test string representation HH:MM:SS
        res = parse_gtfs_time("10:30:00", base_date)
        self.assertEqual(res, datetime(2026, 9, 1, 10, 30, 0))

        # Test time > 24h
        res = parse_gtfs_time(90000, base_date)  # 25:00:00 -> 01:00:00 next day
        self.assertEqual(res, datetime(2026, 9, 2, 1, 0, 0))

        # Test invalid
        self.assertIsNone(parse_gtfs_time("invalid", base_date))

    def test_filter_stop_times_file_python(self):
        # Create a dummy stop_times.txt
        stop_times_content = (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,10:00:00,10:00:00,12422,1\n"
            "T2,10:15:00,10:15:00,99999,2\n"  # not in target stops
            "T3,10:30:00,10:30:00,12423,3\n"
        )
        stop_times_path = self.test_dir / "stop_times.txt"
        with open(stop_times_path, "w", encoding="utf-8") as f:
            f.write(stop_times_content)

        target_stops = [12422, 12423]
        header = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"

        success = filter_stop_times_file_python(stop_times_path, target_stops, header)
        self.assertTrue(success)

        # Read back filtered file
        with open(stop_times_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 3)  # header + 2 filtered lines
        self.assertIn("12422", lines[1])
        self.assertIn("12423", lines[2])
        self.assertNotIn("99999", lines[1])
        self.assertNotIn("99999", lines[2])

    def test_get_next_arrivals(self):
        # Create a mock DataFrame for stop_times_df
        # Partridge loads times as seconds since midnight (float/int)
        fixed_now = datetime(2026, 9, 1, 12, 0, 0)
        now_seconds = fixed_now.hour * 3600 + fixed_now.minute * 60 + fixed_now.second

        stop_times_data = {
            "stop_id": ["12422", "12422", "12422"],
            "arrival_time": [now_seconds + 300, now_seconds + 600, now_seconds + 8000],  # 5 min, 10 min, 133 min (filtered out)
            "stop_headsign": ["Duomo", "Duomo", "Duomo"],
            "trip_headsign": [None, None, None],
            "route_long_name": ["Tram 3", "Tram 3", "Tram 3"],
            "route_short_name": ["3", "3", "3"],
            "route_id": ["R3", "R3", "R3"]
        }
        df = pd.DataFrame(stop_times_data)

        stop_map = {
            "12422": {"stop_id": "12422", "stop_name": "Ferravilla", "direzione": "Piazza Duomo"}
        }

        from unittest.mock import patch
        with patch('main.datetime') as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            mock_datetime.combine = datetime.combine
            mock_datetime.min = datetime.min
            
            arrivals = get_next_arrivals(df, stop_map)
        
        # Should contain two arrivals within 120 minutes
        self.assertEqual(len(arrivals), 2)
        self.assertEqual(arrivals[0]["line"], "3")
        self.assertEqual(arrivals[0]["minutes"], 5)
        self.assertEqual(arrivals[1]["minutes"], 10)

    def test_should_update_gtfs(self):
        # Case 1: Friday after 23:55, not downloaded today
        friday_2358 = datetime(2026, 9, 4, 23, 58, 0)
        from unittest.mock import patch
        with patch('main.datetime') as mock_datetime:
            mock_datetime.now.return_value = friday_2358
            mock_datetime.combine = datetime.combine
            mock_datetime.min = datetime.min
            # Last download date was yesterday (Thursday)
            self.assertTrue(should_update_gtfs(date(2026, 9, 3)))
            
            # Last download date was today (Friday)
            self.assertFalse(should_update_gtfs(date(2026, 9, 4)))

            # Not Friday (e.g. Thursday 23:58)
            thursday_2358 = datetime(2026, 9, 3, 23, 58, 0)
            mock_datetime.now.return_value = thursday_2358
            self.assertFalse(should_update_gtfs(date(2026, 9, 2)))

if __name__ == "__main__":
    unittest.main()
