"""CLI entry: python -m thsr_alert {run,plan,test-email}"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from . import config as cfg
from .monitor import _fmt_td, load_state, run_once, save_state
from .notifier import send_email
from .tdx import TDXClient


def cmd_plan(args) -> int:
    settings, legs = cfg.load(args.config, args.holidays)
    now = datetime.now(cfg.TPE)
    if not legs:
        print("config.yaml 裡沒有啟用的行程（enabled: true）。")
    for leg in legs:
        status = "監控中" if now >= leg.sale_open else f"尚未開賣（還有 {_fmt_td(leg.sale_open - now)}）"
        print(f"- {leg.title}")
        print(f"    時段 {leg.depart_after}~{leg.depart_before}｜車廂 {leg.car}"
              + (f"｜指定車次 {','.join(leg.trains)}" if leg.trains else ""))
        print(f"    開賣時間 {leg.sale_open:%Y-%m-%d %H:%M}｜{status}")
        for r in leg.reminders:
            print(f"    提醒 {leg.sale_open - r:%Y-%m-%d %H:%M}（開賣前 {_fmt_td(r)}）")
    return 0


def cmd_run(args) -> int:
    settings, legs = cfg.load(args.config, args.holidays)
    client = TDXClient(os.environ.get("TDX_CLIENT_ID", ""), os.environ.get("TDX_CLIENT_SECRET", ""))
    while True:
        state = load_state(args.state)
        report = run_once(legs, settings, client, state)
        for e in report.errors:
            print("[錯誤]", e, file=sys.stderr)
        if not report.empty():
            send_email(report.subject(), report.body(), dry_run=args.dry_run)
        else:
            print(f"[{datetime.now(cfg.TPE):%Y-%m-%d %H:%M}] 檢查完成，沒有新通知。")
        save_state(args.state, state)
        if not args.loop:
            return 1 if report.errors and len(report.errors) == len(legs) else 0
        time.sleep(args.loop)


def cmd_seats(args) -> int:
    """Debug: raw TDX seat data for one route/date (no email)."""
    import json
    from .stations import station_id
    o, d = station_id(args.frm), station_id(args.to)
    client = TDXClient(os.environ.get("TDX_CLIENT_ID", ""), os.environ.get("TDX_CLIENT_SECRET", ""))
    path = f"/v2/Rail/THSR/AvailableSeatStatus/Train/OD/{o}/to/{d}/TrainDate/{args.date}"
    raw = client.get(path)
    print(path)
    items = raw if isinstance(raw, list) else raw
    print(json.dumps(items, ensure_ascii=False)[:6000])
    for t in client.seats(o, d, args.date):
        print(f"{t.train_no} {t.departure}->{t.arrival} 標準={t.standard} 商務={t.business}")
    return 0


def cmd_test_email(args) -> int:
    send_email("✅ 高鐵空位監控：測試信", "收到這封信代表 Email 通知設定成功！", dry_run=args.dry_run)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="thsr_alert", description="高鐵空位監控與開賣提醒（官方 TDX 資料）")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--holidays", default="holidays.yaml")
    p.add_argument("--state", default="state.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="檢查一次（或 --loop 秒數 持續監控）並寄出通知")
    r.add_argument("--loop", type=int, default=0, help="每隔幾秒檢查一次（本機持續執行用）")
    r.add_argument("--dry-run", action="store_true", help="只印出通知，不寄信")
    sub.add_parser("plan", help="列出目前設定會監控哪些日期、何時開賣、何時提醒")
    sp = sub.add_parser("seats", help="（除錯）印出某天某路線的 TDX 原始座位資料")
    sp.add_argument("--from", dest="frm", default="台北")
    sp.add_argument("--to", default="台中")
    sp.add_argument("--date", required=True)
    t = sub.add_parser("test-email", help="寄一封測試信")
    t.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return {"run": cmd_run, "plan": cmd_plan, "test-email": cmd_test_email, "seats": cmd_seats}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
