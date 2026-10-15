"""Loads config.yaml / holidays.yaml and resolves them into concrete monitoring legs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .stations import station_id

TPE = ZoneInfo("Asia/Taipei")

_DUR = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.I)
_REL = re.compile(r"^\s*(start|end)\s*([+-]\s*\d+)?\s*$", re.I)


def parse_duration(text) -> timedelta:
    m = _DUR.match(str(text))
    if not m:
        raise ValueError(f"看不懂的時間長度：{text}（例：7d、12h、30m）")
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]


def _to_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def resolve_date(spec, holiday: dict | None) -> date:
    """spec: 2027-02-03 | start | start-1 | end | end+1"""
    if isinstance(spec, date):
        return spec
    m = _REL.match(str(spec))
    if m:
        if not holiday:
            raise ValueError(f"date: {spec} 需要搭配 holiday 使用")
        base = _to_date(holiday["start" if m.group(1).lower() == "start" else "end"])
        offset = int(m.group(2).replace(" ", "")) if m.group(2) else 0
        return base + timedelta(days=offset)
    return _to_date(spec)


def _hhmm(v, default: str) -> str:
    if v is None:
        return default
    if isinstance(v, int):  # YAML may parse 17:00 as sexagesimal int
        return f"{v // 60:02d}:{v % 60:02d}"
    return str(v)[:5]


@dataclass
class Leg:
    trip: str
    label: str
    origin: str
    dest: str
    origin_id: str
    dest_id: str
    travel_date: date
    depart_after: str = "00:00"
    depart_before: str = "23:59"
    car: str = "standard"  # standard | business | any
    trains: list[str] = field(default_factory=list)
    sale_open: datetime | None = None
    reminders: list[timedelta] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.travel_date}|{self.origin_id}|{self.dest_id}"

    @property
    def title(self) -> str:
        return f"{self.trip}・{self.label} {self.travel_date:%m/%d} {self.origin}→{self.dest}"


@dataclass
class Settings:
    sale_open_days_before: int = 27
    sale_open_time: str = "00:00"
    default_reminders: list[timedelta] = field(default_factory=list)
    notify_when_sale_opens: bool = True


def load(config_path: str | Path, holidays_path: str | Path) -> tuple[Settings, list[Leg]]:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    hol_path = Path(holidays_path)
    holidays = (yaml.safe_load(hol_path.read_text(encoding="utf-8")) or {}) if hol_path.exists() else {}
    holidays = holidays.get("holidays", holidays) or {}

    s = cfg.get("settings") or {}
    settings = Settings(
        sale_open_days_before=int(s.get("sale_open_days_before", 27)),
        sale_open_time=_hhmm(s.get("sale_open_time"), "00:00"),
        default_reminders=[parse_duration(x) for x in s.get("remind_before_sale", ["3d", "1d", "1h"])],
        notify_when_sale_opens=bool(s.get("notify_when_sale_opens", True)),
    )

    legs: list[Leg] = []
    for trip in cfg.get("trips") or []:
        if not trip.get("enabled", True):
            continue
        name = trip.get("name", "未命名行程")
        hol = None
        if trip.get("holiday"):
            hol = holidays.get(trip["holiday"])
            if hol is None:
                raise ValueError(f"holidays.yaml 找不到節日：{trip['holiday']}")
        reminders = [parse_duration(x) for x in trip["remind_before_sale"]] \
            if "remind_before_sale" in trip else settings.default_reminders
        done = {str(x).strip() for x in (trip.get("done") or [])}  # legs already booked
        for i, lg in enumerate(trip.get("legs") or []):
            if lg.get("label", f"第{i + 1}段") in done:
                continue
            d = resolve_date(lg.get("date", "start"), hol)
            leg = Leg(
                trip=name,
                label=lg.get("label", f"第{i + 1}段"),
                origin=str(lg["from"]), dest=str(lg["to"]),
                origin_id=station_id(lg["from"]), dest_id=station_id(lg["to"]),
                travel_date=d,
                depart_after=_hhmm(lg.get("depart_after"), "00:00"),
                depart_before=_hhmm(lg.get("depart_before"), "23:59"),
                car=str(lg.get("car", "standard")).lower(),
                trains=[str(t) for t in lg.get("trains") or []],
                reminders=reminders,
            )
            leg.sale_open = compute_sale_open(leg, hol, settings)
            legs.append(leg)
    return settings, legs


def compute_sale_open(leg: Leg, holiday: dict | None, settings: Settings) -> datetime:
    """Holiday-level `sale_open` override wins (e.g. 春節 special sale), else D-N at sale_open_time."""
    if holiday and holiday.get("sale_open"):
        raw = holiday["sale_open"]
        dt = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        return dt.replace(tzinfo=TPE) if dt.tzinfo is None else dt
    h, m = map(int, settings.sale_open_time.split(":"))
    day = leg.travel_date - timedelta(days=settings.sale_open_days_before)
    return datetime.combine(day, time(h, m), tzinfo=TPE)
