#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ics_generator.py - turn data/games.json (from scraper.py) into docs/league.ics.

Requirements this satisfies:
  * Permanent per-fixture UID, so a date / time / stadium change UPDATES the
    existing calendar event instead of creating a duplicate:
        UID = ligat-haal-<season_id>-game-<ifa_game_id>@yiznagar.github.io
    The IFA game_id is stable for the life of the fixture.
  * Handles new games, date changes, time changes, stadium changes, and games
    being removed from the schedule.
  * DETERMINISTIC OUTPUT: the file is byte-identical between runs unless a
    fixture actually changed. Each VEVENT stores an X-SIG hash of its
    schedule-relevant fields; on the next run an unchanged event keeps its old
    DTSTAMP / SEQUENCE / LAST-MODIFIED, a changed event gets a fresh DTSTAMP and
    SEQUENCE+1. That means the GitHub Action only commits when something moved.
  * Correct Israel wall-clock: naive local time from the site is converted to
    UTC through the Asia/Jerusalem zone (handles IDT/IST DST), so the file
    carries unambiguous ...Z timestamps and needs no VTIMEZONE.
  * Time not published yet -> all-day event. Date not published yet -> the
    fixture is skipped (nothing to schedule) and logged.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    print("zoneinfo unavailable - use Python 3.9+ (and 'tzdata' on Windows)",
          file=sys.stderr)
    raise

import json

IL_TZ = ZoneInfo("Asia/Jerusalem")
UID_DOMAIN = "yiznagar.github.io"
PRODID = "-//yiznagar//Ligat haAl calendar//HE"
CAL_NAME = "ליגת העל בכדורגל"
MATCH_DURATION = timedelta(hours=2)
ALLDAY_NOTE = "השעה טרם פורסמה"


# --------------------------------------------------------------------------- #
# RFC 5545 helpers
# --------------------------------------------------------------------------- #
def fold_line(line: str) -> str:
    """Fold at 75 octets, never splitting a UTF-8 character."""
    if len(line.encode("utf-8")) <= 75:
        return line
    segments, cur, cur_bytes, limit = [], "", 0, 75
    for ch in line:
        clen = len(ch.encode("utf-8"))
        if cur_bytes + clen > limit:
            segments.append(cur)
            cur, cur_bytes, limit = ch, clen, 74
        else:
            cur += ch
            cur_bytes += clen
    if cur:
        segments.append(cur)
    return ("\r\n ").join(segments)


def esc(text) -> str:
    if text is None:
        return ""
    return (str(text).replace("\\", "\\\\")
                     .replace(";", "\\;")
                     .replace(",", "\\,")
                     .replace("\n", "\\n"))


def parse_date(ddmmyyyy: str) -> datetime:
    d, m, y = (int(x) for x in ddmmyyyy.split("/"))
    return datetime(y, m, d)


def local_to_utc(dt_local_naive: datetime) -> datetime:
    return dt_local_naive.replace(tzinfo=IL_TZ).astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Read the previous league.ics so unchanged events stay byte-identical
# --------------------------------------------------------------------------- #
def load_previous(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        # unfold physical lines first
        text = fh.read().replace("\r\n ", "").replace("\n ", "")
    prev = {}
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        fields = {}
        for ln in block.splitlines():
            if ":" in ln:
                key = ln.split(":", 1)[0].split(";", 1)[0].strip()
                val = ln.split(":", 1)[1].strip()
                fields[key] = val
        uid = fields.get("UID")
        if uid:
            prev[uid] = {
                "sig": fields.get("X-SIG", ""),
                "dtstamp": fields.get("DTSTAMP", ""),
                "sequence": int(fields.get("SEQUENCE", "0") or 0),
            }
    return prev


def content_signature(game: dict) -> str:
    basis = "|".join(str(game.get(k) or "") for k in
                     ("date", "time", "stadium", "home", "away", "round", "box"))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Build one VEVENT
# --------------------------------------------------------------------------- #
def build_event(game: dict, season_id: str, season_label: str,
                prev: dict, now_stamp: str) -> list[str]:
    uid = f"ligat-haal-{season_id}-game-{game['game_id']}@{UID_DOMAIN}"
    sig = content_signature(game)

    old = prev.get(uid)
    if old and old["sig"] == sig and old["dtstamp"]:
        dtstamp = old["dtstamp"]
        sequence = old["sequence"]
    elif old and old["dtstamp"]:
        dtstamp = now_stamp
        sequence = old["sequence"] + 1
    else:
        dtstamp = now_stamp
        sequence = 0

    rnd = game.get("round")
    summary = f"{game['home']} - {game['away']}"
    if rnd:
        summary += f" (מחזור {rnd})"

    desc = [f"ליגת העל {season_label}".strip()]
    if rnd:
        desc.append(f"מחזור {rnd}")
    desc.append(f"עמוד המשחק: {game['game_url']}")
    description = "\\n".join(esc(p) for p in desc if p)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{esc(summary)}",
    ]

    has_time = bool(game.get("date") and game.get("time"))
    if has_time:
        start_local = parse_date(game["date"]).replace(
            hour=int(game["time"][:2]), minute=int(game["time"][3:5]))
        start_utc = local_to_utc(start_local)
        end_utc = local_to_utc(start_local + MATCH_DURATION)
        lines.append(f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}")
        lines.append(f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}")
    elif game.get("date"):
        d = parse_date(game["date"])
        lines.append(f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}")
        description = esc(ALLDAY_NOTE) + "\\n" + description
    else:
        return []  # no date -> nothing to schedule yet

    if game.get("stadium"):
        lines.append(f"LOCATION:{esc(game['stadium'])}")
    lines.append(f"DESCRIPTION:{description}")
    lines.append(f"URL:{game['game_url']}")
    lines.append(f"LAST-MODIFIED:{dtstamp}")
    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:TRANSPARENT")
    lines.append(f"X-SIG:{sig}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(data: dict, prev: dict, now_stamp: str) -> tuple[str, int, int]:
    season_id = str(data.get("season_id", "0"))
    season_label = data.get("season_label", "")

    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(CAL_NAME + ' ' + season_label)}",
        "X-WR-TIMEZONE:Asia/Jerusalem",
        f"X-WR-CALDESC:{esc('יומן משחקי ליגת העל - מתעדכן אוטומטית מאתר ההתאחדות לכדורגל')}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]

    written = skipped = 0
    for game in sorted(data["games"], key=lambda g: g["game_id"]):
        ev = build_event(game, season_id, season_label, prev, now_stamp)
        if not ev:
            skipped += 1
            continue
        out.extend(ev)
        written += 1
    out.append("END:VCALENDAR")
    return "\r\n".join(fold_line(l) for l in out) + "\r\n", written, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", default="data/games.json")
    ap.add_argument("--out", default="docs/league.ics")
    args = ap.parse_args(argv)

    with open(args.infile, encoding="utf-8") as fh:
        data = json.load(fh)
    if not data.get("games"):
        print("[ics] no games in input - aborting", file=sys.stderr)
        return 1

    prev = load_previous(args.out)
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ics, written, skipped = build_calendar(data, prev, now_stamp)

    new_bytes = ics.encode("utf-8")
    old_bytes = None
    if os.path.exists(args.out):
        with open(args.out, "rb") as fh:
            old_bytes = fh.read()
    changed = old_bytes != new_bytes
    with open(args.out, "wb") as fh:
        fh.write(new_bytes)

    print(f"[ics] {written} events, {skipped} skipped (no date). "
          f"{'CHANGED' if changed else 'no change'} -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
