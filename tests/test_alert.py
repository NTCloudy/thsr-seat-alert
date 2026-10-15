import tempfile
import textwrap
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from thsr_alert import config as cfg
from thsr_alert.monitor import run_once
from thsr_alert.tdx import AVAILABLE, LIMITED, SOLDOUT, TrainSeat, parse_seats, parse_timetable

TPE = cfg.TPE

CONFIG = """
settings:
  sale_open_days_before: 27
  remind_before_sale: [3d, 1d, 1h]
trips:
  - name: 測試連假
    holiday: H
    legs:
      - label: 去程
        date: start-1
        from: 臺北
        to: 左營
        depart_after: "17:00"
        depart_before: "22:00"
      - label: 回程
        date: end
        from: 左營
        to: 台北
  - name: 關閉的
    enabled: false
    legs: [{from: 台北, to: 台中, date: 2027-01-01}]
"""
HOLIDAYS = """
holidays:
  H: {start: 2027-02-04, end: 2027-02-10}
"""


def load():
    d = Path(tempfile.mkdtemp())
    (d / "c.yaml").write_text(CONFIG, encoding="utf-8")
    (d / "h.yaml").write_text(HOLIDAYS, encoding="utf-8")
    return cfg.load(d / "c.yaml", d / "h.yaml")


class FakeClient:
    def __init__(self, trains):
        self.trains = trains
        self.calls = 0

    def seats(self, o, d, day):
        self.calls += 1
        return self.trains


class ConfigTest(unittest.TestCase):
    def test_resolve(self):
        settings, legs = load()
        self.assertEqual(len(legs), 2)
        out, back = legs
        self.assertEqual(out.travel_date, date(2027, 2, 3))
        self.assertEqual(back.travel_date, date(2027, 2, 10))
        self.assertEqual((out.origin_id, out.dest_id), ("1000", "1070"))
        self.assertEqual(out.sale_open, datetime(2027, 1, 7, 0, 0, tzinfo=TPE))
        self.assertEqual(out.reminders, [timedelta(days=3), timedelta(days=1), timedelta(hours=1)])

    def test_sale_open_override(self):
        hol = {"start": "2027-02-04", "end": "2027-02-10", "sale_open": "2027-01-05 00:00"}
        leg = cfg.Leg("t", "l", "台北", "左營", "1000", "1070", date(2027, 2, 3))
        self.assertEqual(cfg.compute_sale_open(leg, hol, cfg.Settings()),
                         datetime(2027, 1, 5, tzinfo=TPE))

    def test_hhmm_sexagesimal(self):
        self.assertEqual(cfg._hhmm(17 * 60, "x"), "17:00")


class ParseTest(unittest.TestCase):
    def test_stop_stations_layout(self):
        payload = {"AvailableSeats": [{
            "TrainNo": "0123", "DepartureTime": "18:00", "ArrivalTime": "19:35",
            "StopStations": [
                {"StationID": "1040", "StandardSeatStatus": "X", "BusinessSeatStatus": "X"},
                {"StationID": "1070", "StandardSeatStatus": "L", "BusinessSeatStatus": "O"},
            ]}]}
        [t] = parse_seats(payload, "1000", "1070")
        self.assertEqual((t.train_no, t.standard, t.business), ("0123", LIMITED, AVAILABLE))

    def test_flat_layout_and_timetable(self):
        [t] = parse_seats([{"TrainNo": "0809", "StandardSeatStatus": "X"}], "1000", "1070")
        self.assertEqual(t.standard, SOLDOUT)
        tt = parse_timetable([{"DailyTrainInfo": {"TrainNo": "0809"},
                               "OriginStopTime": {"DepartureTime": "18:21"},
                               "DestinationStopTime": {"ArrivalTime": "19:55"}}])
        self.assertEqual(tt["0809"], ("18:21", "19:55"))


class MonitorTest(unittest.TestCase):
    def test_reminders_once_and_no_spam(self):
        settings, legs = load()
        legs = legs[:1]
        state = {}
        client = FakeClient([])
        # 2 days before sale: 3d reminder due
        r = run_once(legs, settings, client, state, datetime(2027, 1, 5, 0, 0, tzinfo=TPE))
        self.assertEqual(len(r.reminders), 1)
        self.assertEqual(client.calls, 0)
        r = run_once(legs, settings, client, state, datetime(2027, 1, 5, 0, 10, tzinfo=TPE))
        self.assertEqual(r.reminders, [])
        # 30 min before: 1d and 1h both overdue -> only one email
        r = run_once(legs, settings, client, state, datetime(2027, 1, 6, 23, 30, tzinfo=TPE))
        self.assertEqual(len(r.reminders), 1)
        r = run_once(legs, settings, client, state, datetime(2027, 1, 6, 23, 40, tzinfo=TPE))
        self.assertEqual(r.reminders, [])

    def test_seat_release_detection(self):
        settings, legs = load()
        legs = legs[:1]
        state = {}
        now = datetime(2027, 1, 7, 0, 5, tzinfo=TPE)
        sold = [TrainSeat("0801", "18:00", "19:35", SOLDOUT, SOLDOUT),
                TrainSeat("0101", "08:00", "09:35", AVAILABLE, AVAILABLE)]  # outside window
        r = run_once(legs, settings, FakeClient(sold), state, now)
        self.assertEqual(r.seat_alerts, [])
        self.assertEqual(len(r.info), 1)       # "all sold out, watching"
        self.assertEqual(len(r.reminders), 1)  # "sale opened"

        r = run_once(legs, settings, FakeClient(sold), state, now + timedelta(minutes=10))
        self.assertTrue(r.empty())

        released = [TrainSeat("0801", "18:00", "19:35", LIMITED, SOLDOUT)]
        r = run_once(legs, settings, FakeClient(released), state, now + timedelta(minutes=20))
        self.assertEqual(len(r.seat_alerts), 1)
        self.assertIn("0801", r.seat_alerts[0])
        self.assertIn("退票", r.seat_alerts[0])

        r = run_once(legs, settings, FakeClient(released), state, now + timedelta(minutes=30))
        self.assertTrue(r.empty())  # no duplicate alert

    def test_errors_do_not_crash(self):
        settings, legs = load()

        class Boom:
            def seats(self, *a):
                raise RuntimeError("down")
        r = run_once(legs, settings, Boom(), {}, datetime(2027, 1, 20, tzinfo=TPE))
        self.assertEqual(len(r.errors), 2)


if __name__ == "__main__":
    unittest.main()
