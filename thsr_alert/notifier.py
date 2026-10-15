"""Email notification via SMTP (Gmail App Password by default)."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(subject: str, body: str, dry_run: bool = False) -> None:
    to_addr = os.environ.get("NOTIFY_EMAIL", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").replace(" ", "").strip()
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))

    if dry_run or not (to_addr and user and password):
        if not dry_run:
            print("[警告] 未設定 NOTIFY_EMAIL / SMTP_USER / SMTP_PASSWORD，改為只印出通知內容。")
        print(f"===== {subject} =====\n{body}\n")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    print(f"[已寄出] {subject} -> {to_addr}")
