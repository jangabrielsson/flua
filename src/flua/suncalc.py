"""Sunrise/sunset computation, ported from the HC3 algorithm (dev/suncalc.lua).

The sim's HC3 device (id 1) serves ``sunriseHour``/``sunsetHour`` computed for
the virtual clock's current date at the configured location — the HC3
computes them the same way, so QAs reading fibaro.getValue(1, "sunsetHour")
get controller-compatible values even when the virtual clock disagrees with
the wall clock (online mode included).

Times use the host's local timezone, like flua's os.date — including the
Lua algorithm's extra DST hour (ported exactly, quirk for quirk).
"""

from __future__ import annotations

import math
from datetime import datetime

# sunset/sunrise 90°50′; civil twilight 96°0′
ZENITH = 90.83
ZENITH_TWILIGHT = 96.0


def _fit_into_range(value: float, low: float, high: float) -> float:
    span = high - low
    if value < low:
        return value + (math.floor((low - value) / span) + 1) * span
    if value >= high:
        return value - (math.floor((value - high) / span) + 1) * span
    return value


def _sun_turn_time(
    dt: datetime,
    rising: bool,
    latitude: float,
    longitude: float,
    zenith: float,
    utc_offset: float,
) -> int | None:
    """Local seconds-of-day for the sun event, or None when the sun never
    rises/sets at this location on this date."""
    n1 = math.floor(275 * dt.month / 9)
    n2 = math.floor((dt.month + 9) / 12)
    n3 = 1 + math.floor((dt.year - 4 * math.floor(dt.year / 4) + 2) / 3)
    day_of_year = n1 - n2 * n3 + dt.day - 30
    lng_hour = longitude / 15.0
    if rising:
        t = day_of_year + (6 - lng_hour) / 24
    else:
        t = day_of_year + (18 - lng_hour) / 24
    # mean anomaly
    m = 0.9856 * t - 3.289
    # true longitude
    lng = _fit_into_range(
        m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634,
        0.0,
        360.0,
    )
    # right ascension, in the same quadrant as the true longitude, in hours
    ra = _fit_into_range(math.degrees(math.atan(0.91764 * math.tan(math.radians(lng)))), 0.0, 360.0)
    l_quadrant = math.floor(lng / 90) * 90
    ra_quadrant = math.floor(ra / 90) * 90
    ra = (ra + l_quadrant - ra_quadrant) / 15
    # declination + local hour angle
    sin_dec = 0.39782 * math.sin(math.radians(lng))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(latitude))) / (
        cos_dec * math.cos(math.radians(latitude))
    )
    if cos_h > 1 or cos_h < -1:
        return None
    if rising:
        h = (360 - math.degrees(math.acos(cos_h))) / 15
    else:
        h = math.degrees(math.acos(cos_h)) / 15
    # local mean time -> UTC -> local
    t_local = h + ra - 0.06571 * t - 6.622
    ut = _fit_into_range(t_local - lng_hour, 0.0, 24.0)
    lt = math.fmod(ut + utc_offset, 24.0)
    hour = math.floor(lt)
    minute = math.floor(math.modf(lt)[0] * 60)  # the Lua code takes the integer part
    return hour * 3600 + minute * 60


def _format(seconds_of_day: int | None) -> str:
    if seconds_of_day is None:
        return "00:00"
    return f"{seconds_of_day // 3600:02d}:{(seconds_of_day % 3600) // 60:02d}"


def sunrise_sunset(
    latitude: float, longitude: float, timestamp: float
) -> tuple[str, str, str, str]:
    """(sunrise, sunset, sunrise_twilight, sunset_twilight) as HH:MM strings
    for the given epoch timestamp (the engine's virtual clock) at the
    location."""
    dt = datetime.fromtimestamp(timestamp).astimezone()  # attach local tzinfo
    utc_offset = dt.utcoffset().total_seconds() / 3600.0 if dt.utcoffset() else 0.0
    if dt.dst() and dt.dst().total_seconds() != 0:
        utc_offset += 1  # the original Lua algorithm adds an extra hour on DST
    rise = _sun_turn_time(dt, True, latitude, longitude, ZENITH, utc_offset)
    set_ = _sun_turn_time(dt, False, latitude, longitude, ZENITH, utc_offset)
    rise_twilight = _sun_turn_time(dt, True, latitude, longitude, ZENITH_TWILIGHT, utc_offset)
    set_twilight = _sun_turn_time(dt, False, latitude, longitude, ZENITH_TWILIGHT, utc_offset)
    return _format(rise), _format(set_), _format(rise_twilight), _format(set_twilight)
