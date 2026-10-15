"""Minimal client for the TDX (交通部運輸資料流通服務) THSR APIs."""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
BASE_URL = "https://tdx.transportdata.tw/api/basic"

AVAILABLE = "available"
LIMITED = "limited"
SOLDOUT = "soldout"
UNKNOWN = "unknown"

_STATUS_MAP = {
    "O": AVAILABLE, "尚有座位": AVAILABLE, "AVAILABLE": AVAILABLE,
    "L": LIMITED, "座位有限": LIMITED, "LIMITED": LIMITED,
    "X": SOLDOUT, "已售完": SOLDOUT, "SOLDOUT": SOLDOUT, "FULL": SOLDOUT,
}

STATUS_ZH = {AVAILABLE: "尚有座位", LIMITED: "座位有限", SOLDOUT: "已售完", UNKNOWN: "未知"}


def normalize_status(raw) -> str:
    if raw is None:
        return UNKNOWN
    return _STATUS_MAP.get(str(raw).strip().upper(), _STATUS_MAP.get(str(raw).strip(), UNKNOWN))


def has_seat(status: str) -> bool:
    return status in (AVAILABLE, LIMITED)


@dataclass
class TrainSeat:
    train_no: str
    departure: str  # "HH:MM" or ""
    arrival: str
    standard: str
    business: str


def _items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("AvailableSeats", "AvailableSeatStatusList", "Trains", "Data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def parse_seats(payload, origin_id: str, dest_id: str) -> list[TrainSeat]:
    """Parses an AvailableSeatStatus response defensively (field layouts vary by version)."""
    result = []
    for item in _items(payload):
        train_no = str(item.get("TrainNo") or item.get("DailyTrainInfo", {}).get("TrainNo", "")).strip()
        if not train_no:
            continue
        std = item.get("StandardSeatStatus")
        biz = item.get("BusinessSeatStatus")
        if std is None and biz is None:
            stops = item.get("StopStations") or []
            pick = next((s for s in stops if str(s.get("StationID")) == dest_id), None)
            if pick is None:
                pick = next((s for s in stops if str(s.get("StationID")) == origin_id), None)
            if pick is None and stops:
                pick = stops[-1]
            if pick:
                std, biz = pick.get("StandardSeatStatus"), pick.get("BusinessSeatStatus")
        result.append(TrainSeat(
            train_no=train_no,
            departure=str(item.get("DepartureTime") or "")[:5],
            arrival=str(item.get("ArrivalTime") or "")[:5],
            standard=normalize_status(std),
            business=normalize_status(biz),
        ))
    return result


def parse_timetable(payload) -> dict[str, tuple[str, str]]:
    """Returns {train_no: (departure, arrival)} from a DailyTimetable/OD response."""
    out = {}
    for item in _items(payload):
        info = item.get("DailyTrainInfo") or {}
        no = str(info.get("TrainNo") or item.get("TrainNo") or "").strip()
        if not no:
            continue
        dep = (item.get("OriginStopTime") or {}).get("DepartureTime", "")
        arr = (item.get("DestinationStopTime") or {}).get("ArrivalTime", "")
        out[no] = (str(dep)[:5], str(arr)[:5])
    return out


class TDXClient:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._token = None
        self._token_exp = 0.0

    def _auth_header(self) -> dict:
        if not self.client_id:
            return {}  # anonymous access (very low rate limit)
        if not self._token or time.time() > self._token_exp - 60:
            resp = self.session.post(AUTH_URL, data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    def get(self, path: str):
        for attempt in range(3):
            resp = self.session.get(
                BASE_URL + path,
                params={"$format": "JSON"},
                headers={**self._auth_header(), "Accept-Encoding": "gzip"},
                timeout=30,
            )
            if resp.status_code == 429 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        return None

    def seats(self, origin_id: str, dest_id: str, date: str) -> list[TrainSeat]:
        payload = self.get(
            f"/v2/Rail/THSR/AvailableSeatStatus/Train/OD/{origin_id}/to/{dest_id}/TrainDate/{date}")
        trains = parse_seats(payload, origin_id, dest_id)
        if trains and any(not t.departure for t in trains):
            try:
                times = parse_timetable(self.get(
                    f"/v2/Rail/THSR/DailyTimetable/OD/{origin_id}/to/{dest_id}/{date}"))
                for t in trains:
                    if not t.departure and t.train_no in times:
                        t.departure, t.arrival = times[t.train_no]
            except requests.RequestException:
                pass
        return trains
