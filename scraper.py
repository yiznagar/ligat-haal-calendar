#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scraper.py - Ligat ha'Al (Israeli Premier League / WINNER) fixtures scraper.

Pulls every game (home team, away team, date, kick-off time, stadium) straight
from the official Israel Football Association site (football.org.il).

How the IFA site actually works (verified against live 2026/27 data, not guessed):

  1. The league page
         https://www.football.org.il/leagues/league/?league_id=40
     is server-rendered. It contains:
       * <select id="season_choose"> ... <option value="28" selected>2026/27</option>
         -> maps a human season label ("2026/27") to the numeric season_id.
       * one or more lazy-load placeholders:
         <section class="... league-game-table" data-table-index="10"
                  data-table-type="games" data-table-round="3"> ...
         data-table-index is the "box" (phase) id used by the games endpoint:
            box 10 = regular season      (rounds 1-26)
            box 30 = lower play-off      (rounds 27-33)   [appears mid-season]
            box 40 = upper play-off      (rounds 27-36)   [appears mid-season]
         We read whatever boxes the page currently exposes, so play-off boxes
         are picked up automatically once the IFA creates them.

  2. Each round is fetched from the ASP.NET web-service the page's own JS calls:
         https://www.football.org.il/Components.asmx/LeagueGamesList
             ?league_id=40&season_id=<sid>&box=<box>&round_id=<n>&componentTitle=x
     It returns XML:  <ResponseData><HtmlData> &lt;div...&gt; </HtmlData>...
     The (HTML-entity-encoded) fragment inside <HtmlData> holds one
     <a class="table_row" href="/leagues/games/game/?game_id=NNNNN"> per game:
         <span class="game-date">22/08/2026</span>
         <span class="team-name-text">מכבי  פ"ת&nbsp;- </span>
         <span class="team-name-text">הפועל ק"ש</span>
         <div class="table_col">...מגרש</span>פתח תקוה אצטדיון שלמה ביטוח</div>
         <div class="table_col">...שעה</span>20:00</div>
     game_id is the IFA's own stable identifier for the fixture and is what we
     use to build a permanent calendar UID.

Output: a JSON file (default data/games.json) consumed by ics_generator.py.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.football.org.il"
LEAGUE_PAGE = BASE + "/leagues/league/?league_id={league_id}"
GAMES_ENDPOINT = BASE + "/Components.asmx/LeagueGamesList"

# Defaults for Ligat ha'Al / WINNER.
DEFAULT_LEAGUE_ID = 40
DEFAULT_SEASON_LABEL = "2026/27"

# Rounds to probe per box. 36 is the real max (26 regular + up to 10 play-off);
# we go a little beyond to be safe. Empty rounds cost one tiny request each.
MAX_ROUND = 40

# "box" ids the LeagueGamesList endpoint uses for this league, confirmed against
# live data: 10 = regular season, 30 = lower play-off, 40 = upper play-off.
# We always probe these even if the league page hasn't rendered the play-off
# placeholders yet, and we additionally pick up any box the page does expose.
KNOWN_GAME_BOXES = (10, 30, 40)

USER_AGENT = (
    "Mozilla/5.0 (compatible; ligat-haal-calendar/1.0; "
    "+https://github.com/yiznagar/ligat-haal-calendar)"
)
REQUEST_TIMEOUT = 30
REQUEST_PAUSE = 0.25  # be polite to the IFA server


class ScrapeError(RuntimeError):
    pass


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Language": "he,en;q=0.8"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read()
            return raw.decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise ScrapeError(f"GET failed after retries: {url} ({last_err})")


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_season_options(page: str):
    sel = re.search(r"<select[^>]*id='season_choose'[^>]*>(.*?)</select>", page, re.S)
    if not sel:
        raise ScrapeError("could not find #season_choose on the league page "
                          "(site layout changed)")
    options = re.findall(
        r"<option value='(\d+)'\s*([^>]*)>\s*([^<]+?)\s*</option>", sel.group(1)
    )
    if not options:
        raise ScrapeError("no <option> entries inside #season_choose")
    return options


def _parse_game_boxes(page: str):
    """box ids of every games-list placeholder rendered on the page."""
    found = {}
    for section in re.findall(
            r"<section[^>]*class='[^']*league-game-table[^']*'[^>]*>", page):
        if "data-table-type='games'" not in section:
            continue
        m_box = re.search(r"data-table-index='(\d+)'", section)
        if not m_box:
            continue
        m_round = re.search(r"data-table-round='(\d+)'", section)
        m_title = re.search(r"data-table-title='([^']*)'", section)
        found[int(m_box.group(1))] = {
            "box": int(m_box.group(1)),
            "current_round": int(m_round.group(1)) if m_round else None,
            "title": m_title.group(1) if m_title else "",
        }
    return found


# --------------------------------------------------------------------------- #
# Step 1: read the league page -> season_id + list of game "boxes" (phases)
# --------------------------------------------------------------------------- #
def resolve_season_and_boxes(league_id: int, season_label: str | None):
    default_page = fetch(LEAGUE_PAGE.format(league_id=league_id))
    options = _parse_season_options(default_page)

    season_id = resolved_label = None
    if season_label:
        for value, _attrs, label in options:
            if label.strip() == season_label.strip():
                season_id, resolved_label = value, label.strip()
                break
        if season_id is None:
            available = ", ".join(l.strip() for _, _, l in options)
            raise ScrapeError(
                f"season {season_label!r} not offered by the site. Available: {available}"
            )
    else:
        for value, attrs, label in options:
            if "selected" in attrs:
                season_id, resolved_label = value, label.strip()
                break
        if season_id is None:
            season_id, resolved_label = options[0][0], options[0][2].strip()

    # Re-fetch the page pinned to the chosen season so we see *that* season's
    # placeholders (a past season's page defaults to its regular-season view;
    # a live season's page also renders play-off placeholders once they exist).
    season_page = fetch(LEAGUE_PAGE.format(league_id=league_id)
                        + f"&season_id={season_id}")
    discovered = _parse_game_boxes(season_page)

    boxes = []
    seen = set()
    for box in list(discovered) + list(KNOWN_GAME_BOXES):
        if box in seen:
            continue
        seen.add(box)
        boxes.append(discovered.get(box) or
                     {"box": box, "current_round": None, "title": f"box {box}"})

    return season_id, resolved_label, boxes


# --------------------------------------------------------------------------- #
# Step 2: fetch + parse one round of one box
# --------------------------------------------------------------------------- #
ROW_RE = re.compile(r"<a\s+(?P<attrs>[^>]*?class=[\"']table_row[^\"']*[\"'][^>]*)>"
                    r"(?P<body>.*?)</a>", re.S)
GAME_ID_RE = re.compile(r"game_id=(\d+)")
DATE_RE = re.compile(r"class=[\"']game-date[\"']\s*>\s*([0-9]{2}/[0-9]{2}/[0-9]{4})")
TEAM_RE = re.compile(r"<span[^>]*class=[\"']team-name-text[\"'][^>]*>(.*?)</span>", re.S)
COL_RE = re.compile(r"<div[^>]*class=[\"']table_col[^\"']*[\"'][^>]*>(.*?)</div>", re.S)
TIME_RE = re.compile(r"\b([0-2]?\d:[0-5]\d)\b")


def parse_round(xml_text: str):
    m = re.search(r"<HtmlData>(.*?)</HtmlData>", xml_text, re.S)
    if not m:
        return []
    inner = html.unescape(m.group(1)).strip()
    if not inner:
        return []

    games = []
    for row in ROW_RE.finditer(inner):
        attrs, body = row.group("attrs"), row.group("body")

        gid_m = GAME_ID_RE.search(attrs)
        if not gid_m:
            continue
        game_id = gid_m.group(1)

        date_m = DATE_RE.search(body)
        game_date = date_m.group(1) if date_m else None  # DD/MM/YYYY or None (TBD)

        teams = [strip_tags(t).rstrip(" -").strip() for t in TEAM_RE.findall(body)]
        teams = [t for t in teams if t]
        if len(teams) < 2:
            continue
        home, away = teams[0], teams[1]

        cols = [strip_tags(c) for c in COL_RE.findall(body)]
        # column order: date | match | stadium | time | result
        stadium = ""
        kickoff = None
        if len(cols) >= 3:
            stadium = re.sub(r"^מגרש\s*", "", cols[2]).strip()
        if len(cols) >= 4:
            t_m = TIME_RE.search(cols[3])
            if t_m:
                kickoff = t_m.group(1)
                if len(kickoff) == 4:  # H:MM -> 0H:MM
                    kickoff = "0" + kickoff

        t1 = re.search(r"data-team1=[\"'](\d+)[\"']", attrs)
        t2 = re.search(r"data-team2=[\"'](\d+)[\"']", attrs)

        games.append({
            "game_id": game_id,
            "home": home,
            "away": away,
            "date": game_date,          # "22/08/2026" or None
            "time": kickoff,            # "20:00" or None
            "stadium": stadium,         # "" if not published yet
            "home_team_id": t1.group(1) if t1 else None,
            "away_team_id": t2.group(1) if t2 else None,
            "game_url": f"{BASE}/leagues/games/game/?game_id={game_id}",
        })
    return games


def scrape(league_id: int, season_label: str | None):
    season_id, resolved_label, boxes = resolve_season_and_boxes(league_id, season_label)
    print(f"[scraper] league_id={league_id}  season='{resolved_label}' (id={season_id})",
          file=sys.stderr)
    print(f"[scraper] game boxes exposed by the site: "
          f"{[(b['box'], b['title']) for b in boxes]}", file=sys.stderr)

    discovered_boxes = {b["box"] for b in boxes if b.get("current_round") is not None}

    by_id: dict[str, dict] = {}
    for b in boxes:
        box = b["box"]
        # Regular list (10) and any box the page actually rendered: scan 1..MAX.
        # Play-off boxes we're only probing speculatively: they never start
        # before round ~27, so scan from 24 and save ~23 requests each.
        first_round = 1 if (box == 10 or box in discovered_boxes) else 24
        found_in_box = 0
        for rnd in range(first_round, MAX_ROUND + 1):
            url = (f"{GAMES_ENDPOINT}?league_id={league_id}&season_id={season_id}"
                   f"&box={box}&round_id={rnd}&componentTitle=cal")
            xml_text = fetch(url)
            rows = parse_round(xml_text)
            for g in rows:
                g["round"] = rnd
                g["box"] = box
                # First box that reports a fixture wins; dedupe on IFA game_id.
                by_id.setdefault(g["game_id"], g)
            found_in_box += len(rows)
            time.sleep(REQUEST_PAUSE)
        print(f"[scraper]   box {box}: {found_in_box} fixture rows", file=sys.stderr)

    games = sorted(
        by_id.values(),
        key=lambda g: (g["date"] is None,
                       _sort_key_date(g["date"]),
                       g["time"] or "99:99",
                       g["game_id"]),
    )

    result = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": LEAGUE_PAGE.format(league_id=league_id),
        "league_id": league_id,
        "season_id": season_id,
        "season_label": resolved_label,
        "game_count": len(games),
        "games": games,
    }
    return result


def _sort_key_date(ddmmyyyy: str | None) -> str:
    if not ddmmyyyy:
        return "9999-99-99"
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m}-{d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league-id", type=int, default=DEFAULT_LEAGUE_ID)
    ap.add_argument("--season", default=DEFAULT_SEASON_LABEL,
                    help="season label as shown on the site, e.g. '2026/27'. "
                         "Pass 'current' to follow whatever the site defaults to.")
    ap.add_argument("--out", default="data/games.json")
    args = ap.parse_args(argv)

    season_label = None if args.season.strip().lower() == "current" else args.season
    data = scrape(args.league_id, season_label)

    if data["game_count"] == 0:
        print("[scraper] WARNING: zero games parsed - refusing to overwrite output",
              file=sys.stderr)
        return 1

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"[scraper] wrote {data['game_count']} games -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
