from __future__ import annotations

from datetime import date, datetime, timedelta


def parse_date_input(text: str) -> date:
    """Parse flexible date input into a date object.

    Accepts: YYYY-MM-DD, YYYYMMDD, MM-DD (current year), "today", "yesterday".
    """
    text = text.strip().lower()

    if text == "today":
        return date.today()
    if text == "yesterday":
        return date.today() - timedelta(days=1)

    # YYYY-MM-DD
    if len(text) == 10 and text[4] == "-":
        return datetime.strptime(text, "%Y-%m-%d").date()

    # YYYYMMDD
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()

    # MM-DD (assume current year)
    if len(text) <= 5 and "-" in text:
        parsed = datetime.strptime(text, "%m-%d").date()
        return parsed.replace(year=date.today().year)

    raise ValueError(
        f"Cannot parse date '{text}'. "
        "Use YYYY-MM-DD, YYYYMMDD, MM-DD, 'today', or 'yesterday'."
    )


def format_date_for_title(d: date) -> str:
    """Format date as YYYYMMDD for video title."""
    return d.strftime("%Y%m%d")
