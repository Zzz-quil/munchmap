"""Look up map coordinates for local (non-Statewide) deals so the page can show distance.

usage: python tools/geocode.py

Uses OpenStreetMap's Nominatim (free, 1 request/second, needs network access to
nominatim.openstreetmap.org). Only deals without a "geo" key are looked up:
  "geo": [lat, lng]  found
  "geo": null        looked up, not found or not a single place (chains, multi-location, events)
Run `python tools/build.py` afterwards.
"""
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "deals.json"

# Rough center of each area and how far (degrees) a match may sit from it
CENTERS = {
    "Miami-Dade": (25.77, -80.25, 0.6), "Fort Lauderdale": (26.15, -80.20, 0.45), "Palm Beach": (26.80, -80.15, 0.7),
    "Orlando": (28.55, -81.40, 0.8), "Tampa Bay": (27.90, -82.55, 0.8), "Jacksonville": (30.30, -81.55, 0.7),
    "Gainesville": (29.65, -82.33, 0.5), "Tallahassee": (30.45, -84.28, 0.4), "Sarasota": (27.35, -82.50, 0.5),
    "Southwest Florida": (26.40, -81.80, 0.6), "Panhandle": (30.40, -86.80, 1.2),
}
# Not one place you can walk into
_SKIP = re.compile(r"\blocations?\b|\brestaurants\b|several|across|countywide|all \d+|restaurant (?:week|month)|prix fixe menus|"
                   r"\btoo good to go\b|stadium|game day|when the|on a .* win|interceptions", re.I)
UA = "MunchMap/1.0 (https://munchmap-fl.vercel.app; Florida food-deals site)"


FOOD_PLACES = {"restaurant", "bar", "pub", "cafe", "fast_food", "ice_cream", "food_court", "biergarten", "nightclub", "bakery", "deli"}


def lookup(q, area, place_only=False):
    lat, lng, r = CENTERS[area]
    params = {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "us", "bounded": 1,
              "viewbox": f"{lng - r},{lat + r},{lng + r},{lat - r}"}
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        hits = json.load(resp)
    time.sleep(1.1)   # Nominatim usage policy: at most 1 request per second
    if not hits: return None
    if place_only and hits[0].get("type") not in FOOD_PLACES: return None   # a name match must be an actual eatery
    return [round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)]


def main():
    deals = json.loads(DATA.read_text(encoding="utf-8"))
    cache, found, missed = {}, 0, 0
    # A brand that shows up statewide or in several areas has many stores; a name search would pick a random one
    areas_of = {}
    for d in deals: areas_of.setdefault(re.sub(r"\s*\(.*?\)", "", d["b"]).strip().lower(), set()).add(d["area"])
    for d in deals:
        if "geo" in d or d["area"] == "Statewide": continue
        name = re.sub(r"\s*\(.*?\)", "", d["b"]).strip()
        if d["kind"] in ("Sports win", "Restaurant week") or _SKIP.search(d["o"] + " " + d["c"]):
            d["geo"] = None; continue
        addr = d.get("addr") or ""
        key = (name.lower(), addr.lower(), d["area"])
        if key not in cache:
            geo = None
            chain = len(areas_of[name.lower()]) > 1
            # A neighborhood the deal names: "in Brickell", "on Central Ave", "at Pointe Orlando"
            m = re.search(r"\b(?:in|on|at)\s+((?:[A-Z0-9][\w.'&-]*\s?){1,4})", d["c"])
            first = d["c"].split(";")[0].strip().rstrip(".")
            hint = m[1].strip() if m else (first if len(first) <= 30 and not re.search(r"\d", first) else "")
            tries = [(f"{addr}, Florida", False)] if addr else []
            if not chain and not addr:   # name search, pinned to the neighborhood when the deal names one
                tries.append((f"{name}, {hint}, Florida" if hint else f"{name}, Florida", True))
            for q, by_name in tries:
                try:
                    geo = lookup(q, d["area"], place_only=by_name)
                except Exception as e:   # network blocked or rate-limited: leave for the next run
                    print(f"  lookup failed for {q!r}: {e}"); cache[key] = "retry"; break
                if geo: break
            cache.setdefault(key, geo)
        if cache[key] == "retry": continue
        d["geo"] = cache[key]
        found += bool(cache[key]); missed += not cache[key]
        print(("  ok  " if cache[key] else "  --  ") + f"{name} | {addr or d['area']} -> {cache[key]}")
    DATA.write_text("[\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in deals) + "\n]\n", encoding="utf-8")
    print(f"geocoded {found}, not found {missed}")


if __name__ == "__main__":
    main()
