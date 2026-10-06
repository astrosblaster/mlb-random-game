#!/usr/bin/env python3
import csv
import io
import json
import os
import re
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
DATA = SITE / "data"
DATA.mkdir(parents=True, exist_ok=True)

URL_GAMEINFO = "https://www.retrosheet.org/downloads/gameinfo.zip"
URL_TEAMSTATS = "https://www.retrosheet.org/downloads/teamstats.zip"
URL_BIODATA = "https://www.retrosheet.org/downloads/biodata.zip"
URL_OLD_LOGS = "https://www.retrosheet.org/gamelogs/gl1871_99.zip"
URL_TEAM_CODES = "https://www.retrosheet.org/team_codes.html"

def download(url, path):
    if path.exists() and path.stat().st_size > 0:
        return
    print("Downloading", url)
    req = urllib.request.Request(url, headers={"User-Agent": "MLB-Random-Game/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

def read_zip_csv(zip_path, filename):
    with zipfile.ZipFile(zip_path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("/" + filename.lower()) or n.lower() == filename.lower()), None)
        if not name:
            raise FileNotFoundError(filename)
        with z.open(name) as raw:
            return io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.text = []
    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = []
    def handle_endtag(self, tag):
        if tag == "td" and self.row is not None and self.cell is not None:
            self.row.append("".join(self.text).strip())
            self.text = []
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
    def handle_data(self, data):
        if self.row is not None and self.cell is not None:
            self.text.append(data)

def team_names():
    req = urllib.request.Request(URL_TEAM_CODES, headers={"User-Agent": "MLB-Random-Game/1.0"})
    html = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    p = TableParser()
    p.feed(html)
    rows = []
    for r in p.rows:
        if len(r) >= 8 and re.fullmatch(r"[A-Z0-9]{3}", r[0]) and re.fullmatch(r"\d{4}", r[2]):
            try:
                rows.append({
                    "id": r[0], "league": r[1], "start": int(r[2]), "end": int(r[3] or 9999),
                    "city": r[4], "nick": r[5], "franchise": r[6]
                })
            except ValueError:
                pass
    def lookup(code, year):
        candidates = [x for x in rows if x["id"] == code and x["start"] <= year <= x["end"]]
        if candidates:
            x = candidates[0]
            return (x["city"] + " " + x["nick"]).strip()
        return code
    def major(code, year):
        candidates = [x for x in rows if x["id"] == code and x["start"] <= year <= x["end"]]
        return bool(candidates and candidates[0]["league"] in {"NA","NL","AL","AA","UA","PL","FL"})
    return lookup, major

def park_names():
    p = {}
    path = ROOT / ".cache_biodata.zip"
    download(URL_BIODATA, path)
    try:
        f = read_zip_csv(path, "ballparks0.csv")
        for row in csv.DictReader(f):
            pid = (row.get("id") or row.get("park_id") or "").strip()
            name = (row.get("name") or row.get("park_name") or "").strip()
            city = (row.get("city") or "").strip()
            state = (row.get("state") or "").strip()
            if pid:
                p[pid] = name or ", ".join(x for x in [city, state] if x)
    except Exception:
        pass
    return p

def bref_team(code, year):
    # Baseball-Reference consolidates several early franchise/team codes.
    aliases = {
        "CL1":"CLE","CL2":"CLE","CL3":"CLE","CL4":"CLE",
        "BS1":"BSN","CH1":"CHN","CH2":"CHN",
        "NY2":"NYG","NY3":"NYG","NY4":"NYG","NY1":"NYG",
        "BR1":"BRO","BR2":"BRO","BR3":"BRO","BR4":"BRO",
        "PH1":"PHA","PHN":"PHA","PH2":"PHA","PH3":"PHA","PH4":"PHA",
        "SL1":"SLN","SL2":"SLN","SL3":"SLN","SL4":"SLN",
        "WS3":"WSN","WS4":"WSN","WS5":"WSN","WS6":"WSN","WS7":"WSN","WS8":"WSN","WS9":"WSN",
        "CN1":"CIN","CN2":"CIN","CN3":"CIN",
        "BL1":"BLN","BL2":"BLN",
        "LS1":"LS3","LS2":"LS3",
    }
    return aliases.get(code, code)

def bref_url(home, date, number):
    h = bref_team(home, int(date[:4]))
    return f"https://www.baseball-reference.com/boxes/{h}/{h}{date}{number}.shtml"

def normalize_type(raw):
    s = (raw or "").lower().replace("_", "-").replace(" ", "")
    if "world" in s:
        return "world"
    if "all-star" in s or "allstar" in s:
        return "allstar"
    if any(x in s for x in ("lcs", "division", "wildcard", "postseason", "post-season")):
        return "postseason"
    if s == "playoff":
        return "regular"
    if "regular" in s:
        return "regular"
    if not s:
        return "regular"
    return "other"

def make_record(gid, date, number, vis, home, site, vruns, hruns, innings, gametype, parks, names):
    date = str(date).replace("/", "").replace("-", "")
    year = int(date[:4])
    vruns, hruns = int(vruns), int(hruns)
    innings = max(1, int(innings or 9))
    vname = names(vis, year)
    hname = names(home, year)
    raw_type = gametype or "regular-season"
    typ = normalize_type(raw_type)
    rec = {
        "i": gid or f"{home}{date}{number}",
        "d": date,
        "n": int(number or 0),
        "v": vis,
        "h": home,
        "vn": vname,
        "hn": hname,
        "vs": vruns,
        "hs": hruns,
        "p": parks.get(site, site or ""),
        "inn": innings,
        "t": typ,
        "rt": raw_type,
        "one": abs(vruns - hruns) == 1,
        "extra": innings > 9,
        "high": vruns + hruns >= 10,
        "b": bref_url(home, date, str(number or 0)),
    }
    return rec

def parse_old_logs(path, names, major, parks):
    out = []
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            m = re.search(r"GL(18\d\d)\.TXT$", member, re.I)
            if not m:
                continue
            year = int(m.group(1))
            if year >= 1897:
                continue
            with z.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
                for line in text:
                    if not line.strip() or line.startswith("#"):
                        continue
                    try:
                        row = next(csv.reader([line]))
                    except Exception:
                        continue
                    if len(row) < 21 or not re.fullmatch(r"\d{8}", row[0].strip('"')):
                        continue
                    date = row[0].strip('"')
                    num = row[1] or "0"
                    vis, home = row[3], row[6]
                    vr, hr = row[9], row[10]
                    if not (str(vr).strip("-").isdigit() and str(hr).strip("-").isdigit()):
                        continue
                    outs = row[11]
                    innings = int(outs) / 3 if str(outs).isdigit() else 9
                    # Round up because a completed game can end after a partial inning.
                    actual_innings = max(1, int((int(outs) + 2) // 3)) if str(outs).isdigit() else 9
                    park = row[16] if len(row) > 16 else ""
                    if not (major(vis, year) and major(home, year)):
                        continue
                    rec = make_record(
                        f"{home}{date}{num}", date, num, vis, home, park, vr, hr,
                        actual_innings, "regular-season", parks, names
                    )
                    out.append(rec)
    return out

def parse_modern(gameinfo_zip, teamstats_zip, parks, names, major):
    # First collect game-level information.
    games = {}
    f = read_zip_csv(gameinfo_zip, "gameinfo.csv")
    for r in csv.DictReader(f):
        gid = r.get("gid", "")
        if not gid:
            continue
        date = (r.get("date") or "").replace("/", "").replace("-", "")
        if len(date) != 8:
            continue
        year = int(date[:4])
        if not (major(r.get("visteam") or "", year) and major(r.get("hometeam") or "", year)):
            continue
        games[gid] = {
            "gid": gid,
            "date": date,
            "number": r.get("number") or "0",
            "vis": r.get("visteam") or "",
            "home": r.get("hometeam") or "",
            "site": r.get("site") or "",
            "vruns": r.get("vruns") or "0",
            "hruns": r.get("hruns") or "0",
            "innings": r.get("innings") or "9",
            "gametype": r.get("gametype") or "regular-season",
        }

    # Teamstats supplies the actual final inning, which is important for extra-inning filters.
    actual = {}
    f = read_zip_csv(teamstats_zip, "teamstats.csv")
    for r in csv.DictReader(f):
        gid = r.get("gid", "")
        if gid not in games:
            continue
        mx = 0
        for n in range(1, 29):
            val = (r.get(f"inn{n}") or "").strip()
            if val != "":
                mx = n
        if mx:
            actual[gid] = max(actual.get(gid, 0), mx)

    out = []
    for gid, g in games.items():
        innings = actual.get(gid, 0)
        if not innings:
            try:
                innings = int(g["innings"])
            except Exception:
                innings = 9
        out.append(make_record(
            gid, g["date"], g["number"], g["vis"], g["home"], g["site"],
            g["vruns"], g["hruns"], innings, g["gametype"], parks, names
        ))
    return out

def write_decades(games):
    buckets = defaultdict(list)
    for g in games:
        decade = (int(g["d"][:3]) * 10)
        buckets[decade].append(g)
    manifest = {"version": 1, "sourceUpdated": "Retrosheet", "decades": [], "teams": {}}
    for decade in sorted(buckets):
        arr = sorted(buckets[decade], key=lambda x: (x["d"], x["n"], x["i"]))
        name = f"games-{decade}s.json"
        (DATA / name).write_text(json.dumps(arr, separators=(",", ":")), encoding="utf-8")
        years = sorted({int(x["d"][:4]) for x in arr})
        for g in arr:
            manifest["teams"][g["v"]] = g["vn"]
            manifest["teams"][g["h"]] = g["hn"]
        manifest["decades"].append({"file": name, "from": years[0], "to": years[-1], "count": len(arr)})
    (DATA / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    total = sum(x["count"] for x in manifest["decades"])
    print(f"Built {total:,} games across {len(manifest['decades'])} decade files.")

def main():
    SITE.mkdir(parents=True, exist_ok=True)
    for old in ROOT.glob(".cache_*"):
        old.unlink(missing_ok=True)

    gameinfo_zip = ROOT / ".cache_gameinfo.zip"
    teamstats_zip = ROOT / ".cache_teamstats.zip"
    biodata_zip = ROOT / ".cache_biodata.zip"
    old_zip = ROOT / ".cache_oldlogs.zip"

    download(URL_GAMEINFO, gameinfo_zip)
    download(URL_TEAMSTATS, teamstats_zip)
    download(URL_BIODATA, biodata_zip)
    download(URL_OLD_LOGS, old_zip)

    names, major = team_names()
    parks = park_names()
    games = parse_modern(gameinfo_zip, teamstats_zip, parks, names, major)
    old = parse_old_logs(old_zip, names, major, parks)

    # Keep the 1871-1896 portion from the game logs and the 1897+ portion from gameinfo.
    games.extend(old)
    # Deduplicate defensively by game ID.
    unique = {}
    for g in games:
        unique[g["i"]] = g
    write_decades(list(unique.values()))

    for p in (gameinfo_zip, teamstats_zip, biodata_zip, old_zip):
        p.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
