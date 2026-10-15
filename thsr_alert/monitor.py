"""Core monitoring logic: sale-open reminders + seat-release (退票) detection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import TPE, Leg, Settings
from .tdx import STATUS_ZH, TrainSeat, has_seat

BOOKING_LINKS = (
    "👉 立即訂票：https://irs.thsrc.com.tw/IMINT/ （或使用「T Express 行動購票」App）"
)


@dataclass
class Report:
    seat_alerts: list[str] = field(default_factory=list)
    reminders: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.seat_alerts or self.reminders or self.info)

    def subject(self) -> str:
        if self.seat_alerts:
            return f"🚄 高鐵有位了！{self.seat_alerts[0].splitlines()[0]}"
        if self.reminders:
            return f"⏰ 高鐵開賣提醒：{self.reminders[0].splitlines()[0]}"
        return "ℹ️ 高鐵空位監控通知"

    def body(self) -> str:
        parts = []
        if self.seat_alerts:
            parts += ["【有座位釋出】", *self.seat_alerts, BOOKING_LINKS, ""]
        if self.reminders:
            parts += ["【開賣提醒】", *self.reminders, ""]
        if self.info:
            parts += ["【監控狀態】", *self.info, ""]
        parts.append("—— THSR Seat Alert（資料來源：交通部 TDX 官方開放資料。請自行至官方管道訂票）")
        return "\n".join(parts)


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(path: str | Path, state: dict) -> None:
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def prune_state(state: dict, today) -> None:
    for k in list(state):
        parts = k.split("|")
        if len(parts) > 1 and parts[1] < today.isoformat():
            del state[k]


def _fmt_td(td: timedelta) -> str:
    secs = int(td.total_seconds())
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    out = (f"{d} 天 " if d else "") + (f"{h} 小時 " if h else "") + (f"{m} 分" if m and not d else "")
    return out.strip() or "不到 1 分鐘"


def _matches(leg: Leg, t: TrainSeat) -> bool:
    if leg.trains and t.train_no not in leg.trains:
        return False
    if t.departure and not (leg.depart_after <= t.departure <= leg.depart_before):
        return False
    return True


def _seat_ok(leg: Leg, t: TrainSeat) -> bool:
    if leg.car == "business":
        return has_seat(t.business)
    if leg.car == "any":
        return has_seat(t.standard) or has_seat(t.business)
    return has_seat(t.standard)


def _train_line(t: TrainSeat) -> str:
    time_part = f"{t.departure}→{t.arrival}" if t.departure else "時間未知"
    return (f"  • {t.train_no} 次 {time_part}｜標準：{STATUS_ZH[t.standard]}"
            f"｜商務：{STATUS_ZH[t.business]}")


def check_reminders(leg: Leg, settings: Settings, state: dict, now: datetime, report: Report) -> None:
    base = f"{leg.travel_date}|{leg.origin_id}|{leg.dest_id}|{leg.trip}|{leg.label}"
    open_at = leg.sale_open
    if now < open_at:
        due = [r for r in leg.reminders
               if open_at - r <= now and f"remind|{base}|{int(r.total_seconds())}" not in state]
        if due:
            report.reminders.append(
                f"{leg.title}\n  將於 {open_at:%Y-%m-%d %H:%M}（台北時間）開放訂票，"
                f"還有 {_fmt_td(open_at - now)}。")
            for r in due:  # mark all overdue reminders as sent so we don't spam
                state[f"remind|{base}|{int(r.total_seconds())}"] = now.isoformat()
    elif settings.notify_when_sale_opens and now < open_at + timedelta(days=1):
        k = f"open|{base}"
        if k not in state:
            state[k] = now.isoformat()
            report.reminders.append(f"{leg.title}\n  已於 {open_at:%m/%d %H:%M} 開放訂票，快去搶！")


def check_seats(leg: Leg, trains: list[TrainSeat], state: dict, now: datetime, report: Report) -> None:
    scanned_key = f"scanned|{leg.key}|{leg.car}|{leg.depart_after}-{leg.depart_before}"
    first_scan = scanned_key not in state
    newly = []
    candidates = [t for t in trains if _matches(leg, t)]
    for t in candidates:
        k = f"seat|{leg.key}|{t.train_no}|{leg.car}"
        cur = "seat" if _seat_ok(leg, t) else "none"
        prev = state.get(k)
        if cur == "seat" and prev != "seat":
            newly.append(t)
        state[k] = cur
    state[scanned_key] = now.isoformat()

    window = f"{leg.depart_after}~{leg.depart_before} 出發"
    car_zh = {"standard": "標準車廂", "business": "商務車廂", "any": "不限車廂"}.get(leg.car, leg.car)
    if newly:
        head = "目前有座位的車次" if first_scan else "有人退票／釋出座位"
        report.seat_alerts.append(
            f"{leg.title}（{window}，{car_zh}）\n  {head}：\n" + "\n".join(_train_line(t) for t in newly))
    elif first_scan:
        if not candidates:
            report.info.append(f"{leg.title}：目前查無符合時段（{window}）的車次資料，會持續監控。")
        else:
            report.info.append(f"{leg.title}：符合條件的 {len(candidates)} 班車目前都已售完，"
                               f"有人退票會立刻通知你。")


def run_once(legs: list[Leg], settings: Settings, client, state: dict, now: datetime | None = None) -> Report:
    now = now or datetime.now(TPE)
    today = now.date()
    report = Report()
    prune_state(state, today)
    cache: dict[str, list[TrainSeat]] = {}
    for leg in legs:
        if leg.travel_date < today:
            continue
        check_reminders(leg, settings, state, now, report)
        if now < leg.sale_open:
            continue
        try:
            if leg.key not in cache:
                cache[leg.key] = client.seats(leg.origin_id, leg.dest_id, leg.travel_date.isoformat())
            check_seats(leg, cache[leg.key], state, now, report)
        except Exception as e:  # keep monitoring other legs
            report.errors.append(f"{leg.title}：查詢失敗 {type(e).__name__}: {e}")
    return report
