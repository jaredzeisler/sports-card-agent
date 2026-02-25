"""Notification system for trade alerts and approvals."""

import smtplib
from email.mime.text import MIMEText
from rich.console import Console

from config.settings import get_settings

console = Console()


def notify_deal_found(player: str, price: float, fmv: float, score: float):
    """Alert when a good deal is found."""
    margin = ((fmv - price) / price) * 100 if price > 0 else 0
    msg = (
        f"Deal found: {player} listed at ${price:.2f} "
        f"(FMV ${fmv:.2f}, margin {margin:.1f}%, score {score:.1f})"
    )
    console.print(f"[green bold]{msg}[/]")
    _send_email("Deal Found", msg)


def notify_trade_executed(action: str, player: str, price: float):
    """Alert when a trade is auto-executed."""
    msg = f"Trade executed: {action.upper()} {player} at ${price:.2f}"
    console.print(f"[cyan bold]{msg}[/]")
    _send_email(f"Trade Executed: {action}", msg)


def notify_approval_needed(player: str, price: float, fmv: float):
    """Alert when a trade needs manual approval."""
    msg = (
        f"Approval needed: {player} at ${price:.2f} (FMV ${fmv:.2f}). "
        f"Run: cardagent approvals list"
    )
    console.print(f"[yellow bold]{msg}[/]")
    _send_email("Approval Needed", msg)


def notify_error(context: str, error: str):
    """Alert on errors."""
    msg = f"Error in {context}: {error}"
    console.print(f"[red bold]{msg}[/]")


def _send_email(subject: str, body: str):
    """Send email notification if configured."""
    settings = get_settings()
    if not settings.notification_email or not settings.smtp_host:
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[CardAgent] {subject}"
        msg["From"] = settings.smtp_user
        msg["To"] = settings.notification_email
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception:
        pass  # Don't crash the agent over email failures
