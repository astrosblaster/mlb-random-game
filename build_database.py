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
            data = raw.read().decode("utf-8-sig", "replace")
        return io.StringIO(data)

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
    # Retrosheet's published team-code table. Keeping this small static copy
    # makes the build independent of how the source HTML is wrapped.
    data = """id,league,start,end,city,nick
ALT,UA,1884,1884,Altoona,Mountain Cities
ARI,NL,1998,9999,Arizona,Diamondbacks
BFN,NL,1879,1885,Buffalo,Bisons
BFP,PL,1890,1890,Buffalo,Bisons
BL1,NA,1872,1874,Baltimore,Canaries
BL2,AA,1882,1891,Baltimore,Orioles
BLN,NL,1892,1899,Baltimore,Orioles
BL4,NA,1873,1873,Baltimore,Marylands
BLA,AL,1901,1902,Baltimore,Orioles
NYA,AL,1903,9999,New York,Yankees
BLF,FL,1914,1915,Baltimore,Terrapins
BLU,UA,1884,1884,Baltimore,Unions
BOS,AL,1901,9999,Boston,Red Sox
BR1,NA,1872,1872,Brooklyn,Eckfords
BR2,NA,1872,1875,Brooklyn,Atlantics
BR3,AA,1884,1889,Brooklyn,Dodgers
BRO,NL,1890,1957,Brooklyn,Dodgers
LAN,NL,1958,9999,Los Angeles,Dodgers
BR4,AA,1890,1890,Brooklyn,Gladiators
BRF,FL,1914,1915,Brooklyn,Tip-Tops
BRP,PL,1890,1890,Brooklyn,Wonders
BS1,NA,1871,1875,Boston,Braves
BSN,NL,1876,1952,Boston,Braves
MLN,NL,1953,1965,Milwaukee,Braves
ATL,NL,1966,9999,Atlanta,Braves
BSP,PL,1890,1890,Boston,Reds
BS2,AA,1891,1891,Boston,Reds
BSU,UA,1884,1884,Boston,Reds
BUF,FL,1914,1915,Buffalo,Feds
CH1,NA,1871,1871,Chicago,White Stockings
CH2,NA,1874,1875,Chicago,White Stockings
CHN,NL,1876,9999,Chicago,Cubs
CHA,AL,1901,9999,Chicago,White Sox
CHF,FL,1914,1915,Chicago,Whales
CHP,PL,1890,1890,Chicago,Pirates
CHU,UA,1884,1884,Chicago,Unions
CL1,NA,1871,1872,Cleveland,Forest Cities
CL2,NL,1879,1884,Cleveland,Spiders
CL3,AA,1887,1888,Cleveland,Spiders
CL4,NL,1889,1899,Cleveland,Spiders
CL5,AA,1883,1884,Columbus,Colts
CL6,AA,1889,1891,Columbus,Colts
CLE,AL,1901,9999,Cleveland,Indians
CLP,PL,1890,1890,Cleveland,Infants
CN1,NL,1876,1880,Cincinnati,Reds
CN2,AA,1882,1889,Cincinnati,Reds
CIN,NL,1890,9999,Cincinnati,Reds
CN3,AA,1891,1891,Cincinnati,Porkers
CNU,UA,1884,1884,Cincinnati,Outlaw Reds
COL,NL,1993,9999,Colorado,Rockies
DET,AL,1901,9999,Detroit,Tigers
DTN,NL,1881,1888,Detroit,Wolverines
ELI,NA,1873,1873,Elizabeth,Resolutes
FLO,NL,1993,2011,Florida,Marlins
FW1,NA,1871,1871,Ft. Wayne,Kekiongas
HOU,NL,1962,9999,Houston,Astros
HR1,NA,1874,1875,Hartford,Dark Blues
HAR,NL,1876,1877,Hartford,Dark Blues
IN1,NL,1878,1878,Indianapolis,Blues
IN2,AA,1884,1884,Indianapolis,Blues
IN3,NL,1887,1889,Indianapolis,Hoosiers
IND,FL,1914,1914,Indianapolis,Hoosier-Feds
NEW,FL,1915,1915,Newark,Peppers
KC2,AA,1888,1889,Kansas City,Blues
KCA,AL,1969,9999,Kansas City,Royals
KCF,FL,1914,1915,Kansas City,Packers
KCN,NL,1886,1886,Kansas City,Cowboys
KCU,UA,1884,1884,Kansas City,Unions
KEO,NA,1875,1875,Keokuk,Westerns
LAA,AL,1961,1964,Los Angeles,Angels
CAL,AL,1965,1996,California,Angels
ANA,AL,1997,9999,Anaheim,Angels
LS1,NL,1876,1877,Louisville,Grays
LS2,AA,1882,1891,Louisville,Colonels
LS3,NL,1892,1899,Louisville,Colonels
MID,NA,1872,1872,Middletown,Mansfields
ML2,NL,1878,1878,Milwaukee,Cream Citys
ML3,AA,1891,1891,Milwaukee,Brewers
MLA,AL,1901,1901,Milwaukee,Brewers
SLA,AL,1902,1953,St. Louis,Browns
BAL,AL,1954,9999,Baltimore,Orioles
MLU,UA,1884,1884,Milwaukee,Grays
MON,NL,1969,2004,Montreal,Expos
WAS,NL,2005,9999,Washington,Nationals
NH1,NA,1875,1875,New Haven,Elm Cities
NY2,NA,1871,1875,New York,Mutuals
NY3,NL,1876,1876,New York,Mutuals
NY4,AA,1883,1887,New York,Metropolitans
NYN,NL,1962,9999,New York,Mets
NYP,PL,1890,1890,New York,Giants
PH1,NA,1871,1875,Philadelphia,Athletics
PHN,NL,1876,1876,Philadelphia,Athletics
PH2,NA,1873,1875,Philadelphia,White Stockings
PH3,NA,1875,1875,Philadelphia,Centennials
PH4,AA,1882,1891,Philadelphia,Athletics
PHI,NL,1883,9999,Philadelphia,Phillies
PHA,AL,1901,1954,Philadelphia,Athletics
KC1,AL,1955,1967,Kansas City,Athletics
OAK,AL,1968,9999,Oakland,Athletics
PHP,PL,1890,1890,Philadelphia,Quakers
PHU,UA,1884,1884,Philadelphia,Keystones
PRO,NL,1878,1885,Providence,Grays
PT1,AA,1882,1886,Pittsburgh,Pirates
PIT,NL,1887,9999,Pittsburgh,Pirates
PTF,FL,1914,1915,Pittsburgh,Rebels
PTP,PL,1890,1890,Pittsburgh,Burghers
PTU,UA,1884,1884,Pittsburgh,Unions
RC1,NA,1871,1871,Rockford,Forest Citys
RC2,AA,1890,1890,Rochester,Hop Bitters
RIC,AA,1884,1884,Richmond,Virginias
SDN,NL,1969,9999,San Diego,Padres
SE1,AL,1969,1969,Seattle,Pilots
MIL,NL,1998,9999,Milwaukee,Brewers
MIL,AL,1970,1997,Milwaukee,Brewers
SEA,AL,1977,9999,Seattle,Mariners
SL1,NA,1875,1875,St. Louis,Red Stockings
SL2,NA,1875,1875,St. Louis,Brown Stockings
SL3,NL,1876,1877,St. Louis,Brown Stockings
SL4,AA,1882,1891,St. Louis,Cardinals
SLN,NL,1892,9999,St. Louis,Cardinals
SLF,FL,1914,1915,St. Louis,Terriers
SLU,UA,1884,1884,St. Louis,Maroons
SL5,NL,1885,1886,St. Louis,Maroons
SPU,UA,1884,1884,St. Paul,Saints
SR1,NL,1879,1879,Syracuse,Stars
SR2,AA,1890,1890,Syracuse,Stars
TBA,AL,1998,9999,Tampa Bay,Devil Rays
TL1,AA,1884,1884,Toledo,Blue Stockings
TL2,AA,1890,1890,Toledo,Maumees
TOR,AL,1977,9999,Toronto,Blue Jays
TRN,NL,1879,1882,Troy,Trojans
NY1,NL,1883,1957,New York,Giants
SFN,NL,1958,9999,San Francisco,Giants
TRO,NA,1871,1872,Troy,Haymakers
WIL,UA,1884,1884,Wilmington,Quicksteps
WOR,NL,1880,1882,Worcester,Ruby Legs
WS1,AL,1901,1960,Washington,Senators
MIN,AL,1961,9999,Minnesota,Twins
WS2,AL,1961,1971,Washington,Senators
TEX,AL,1972,9999,Texas,Rangers
WS3,NA,1871,1872,Washington,Olympics
WS4,NA,1872,1872,Washington,Nationals
WS5,NA,1873,1873,Washington,Nationals
WS6,NA,1875,1875,Washington,Nationals
WS7,AA,1884,1884,Washington,Nationals
WS8,NL,1886,1889,Washington,Senators
WS9,AA,1891,1891,Washington,Senators
WSN,NL,1892,1899,Washington,Senators
WSU,UA,1884,1884,Washington,Nationals"""
    rows = []
    for r in csv.DictReader(io.StringIO(data)):
        rows.append({"id":r["id"],"league":r["league"],"start":int(r["start"]),"end":int(r["end"]),"city":r["city"],"nick":r["nick"]})
    def lookup(code, year):
        candidates=[x for x in rows if x["id"]==code and x["start"]<=year<=x["end"]]
        if candidates:
            return (candidates[0]["city"]+" "+candidates[0]["nick"]).strip()
        return code
    def major(code, year):
        candidates=[x for x in rows if x["id"]==code and x["start"]<=year<=x["end"]]
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
