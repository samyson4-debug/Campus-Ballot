"""
Campus Ballot — Election Service
Computes election state on demand, handles status changes and result declaration.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings
from ..database import DATE_FORMAT

# Election states (computed, not stored)
STATE_OPEN = "OPEN"
STATE_CLOSED = "CLOSED"
STATE_NOT_STARTED = "NOT_STARTED"
STATE_INVALID = "INVALID"


def get_election_state(start_time: str, end_time: str, status: str) -> str:
    """
    Compute the current election state from its stored fields.

    Rules:
    - status != 'ON' → CLOSED (admin turned it off or it was never turned on)
    - Otherwise compare current time with start/end:
        - now < start → NOT_STARTED
        - start <= now <= end → OPEN
        - now > end → CLOSED
    - Malformed dates → INVALID
    """
    if status != "ON":
        return STATE_CLOSED

    try:
        tz = ZoneInfo(settings.APP_TIMEZONE)
        now = datetime.now(tz)
        start = datetime.strptime(start_time, DATE_FORMAT).replace(tzinfo=tz)
        end = datetime.strptime(end_time, DATE_FORMAT).replace(tzinfo=tz)
    except (ValueError, TypeError):
        return STATE_INVALID

    if now < start:
        return STATE_NOT_STARTED
    elif now > end:
        return STATE_CLOSED
    else:
        return STATE_OPEN
