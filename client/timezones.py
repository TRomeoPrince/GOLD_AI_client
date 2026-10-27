from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CHOICES=("UTC","Africa/Kampala","Europe/London","America/New_York","Asia/Dubai","Asia/Kolkata","Asia/Tokyo","Australia/Sydney")
ALIASES={"EAT":"Africa/Kampala","Africa-Kampala":"Africa/Kampala","London":"Europe/London","New York":"America/New_York"}

def valid_zone(value):
    value=ALIASES.get(str(value).strip(),str(value).strip())
    ZoneInfo(value)
    return value

def display_time(value, zone="UTC"):
    if value in (None,""): return "—"
    try:
        if isinstance(value,(int,float)): date=datetime.fromtimestamp(value,timezone.utc)
        else: date=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
        return date.astimezone(ZoneInfo(valid_zone(zone))).strftime("%d %b %Y  %H:%M %Z")
    except (ValueError,TypeError,KeyError): return "—"

def remaining_text(expires):
    if not expires: return "No expiry configured"
    try:
        date=datetime.fromisoformat(str(expires).replace("Z","+00:00"))
        if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
        seconds=(date-datetime.now(timezone.utc)).total_seconds()
        if seconds<=0: return "Expired"
        days,hours=divmod(int(seconds)//3600,24)
        minutes=int(seconds)//60%60
        return f"{days}d {hours}h {minutes}m remaining"
    except ValueError: return "Expiry unavailable"
