"""Validate data/deals.json and bake it into index.html.

usage: python tools/build.py            # validate, drop long-expired deals, write index.html
       python tools/build.py --check    # validate only, exit 1 on problems
"""
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "deals.json"
PAGE = ROOT / "index.html"

TYPES = {"free", "purchase", "discount", "value"}
AREAS = {"Statewide", "Miami-Dade", "Fort Lauderdale", "Palm Beach", "Orlando", "Tampa Bay", "Jacksonville",
         "Gainesville", "Tallahassee", "Sarasota", "Southwest Florida", "Panhandle"}
KINDS = {"Apps & rewards", "Everyday value", "Weekly special", "Happy hour", "Kids eat free", "Sports win",
         "Restaurant week", "Grocery & stores", "Discounts & programs", "Student", "Limited time"}
CATS = {"Burgers", "Chicken", "Mexican", "Sandwiches", "Pizza", "Coffee & sweets", "Healthy", "Sit-down",
        "Grocery & convenience", "Latin & local", "Seafood", "Bar food", "Apps & programs"}
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
KEEP_EXPIRED_DAYS = 7  # the page hides expired deals itself; prune them from the data a week later

# Time windows ("3–6pm", "9pm–close", "after 5pm", "open–7pm", "until 10pm") read from a deal's text.
# Stored as [[start_minute, end_minute], ...] with 1440 meaning close; [] means no set hours (all day).
_T = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
_RANGE = re.compile(_T + r"\s*(?:[–-]|to)\s*" + r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)
_TO_CLOSE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:[–-]|to)\s*close", re.I)
_FROM_OPEN = re.compile(r"\bopen\s*(?:[–-]|to|until)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)
_AFTER = re.compile(r"\b(?:after|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)
_UNTIL = re.compile(r"\buntil\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _mins(h, m, ap):
    h = int(h) % 12 + (12 if ap.lower() == "pm" else 0)
    return h * 60 + int(m or 0)


def derive_hours(text):
    if re.search(r"\ball day\b", text, re.I):   # all day on some days: don't hide it at other times
        return []
    wins, used = [], []
    def add(s, e):
        if e <= s and e != 1440:          # runs past midnight
            wins.extend([[s, 1440], [0, e]])
        else:
            wins.append([s, e])
    for m in _TO_CLOSE.finditer(text):
        add(_mins(m[1], m[2], m[3]), 1440); used.append(m.span())
    for m in _RANGE.finditer(text):
        if any(a <= m.start() < b for a, b in used): continue
        end = _mins(m[4], m[5], m[6])
        start = _mins(m[1], m[2], m[3] or m[6])
        if not m[3] and start >= end and m[6].lower() == "pm": start -= 720   # "11–4pm" means 11am
        add(start, end); used.append(m.span())
    for rx, kind in ((_FROM_OPEN, "open"), (_AFTER, "after"), (_UNTIL, "until")):
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in used): continue
            t = _mins(m[1], m[2], m[3])
            add(0, t) if kind != "after" else add(t, 1440)
    out = []
    for w in sorted(wins):
        if out and w[0] <= out[-1][1]: out[-1][1] = max(out[-1][1], w[1])
        else: out.append(w)
    return out


# Cheapest out-of-pocket cost per person in dollars, or None when there's no fixed price ("50% off", "half-price apps").
_MIN_SPEND = re.compile(r"(?:with|on)\s+(?:a|an|any)?\s*\$(\d+(?:\.\d\d)?)\+?\s*(?:or more\s*)?(?:purchase|order|food|minimum|digital|online|adult)|\$(\d+(?:\.\d\d)?)\+?\s*(?:minimum|min\.?)\b|minimum\s+\$(\d+(?:\.\d\d)?)", re.I)
_DOLLAR = re.compile(r"(?<![\w.])\$(\d+(?:\.\d\d)?)(?!\s*(?:off|back|reward|per month|/mo|mo\b|a month))(?!\d)", re.I)
_N_FOR = re.compile(r"\b(\d+)\s+for\s+\$(\d+(?:\.\d\d)?)", re.I)


_DRINK = re.compile(r"\s*(?:\+\s*)?(?:house\s+|craft\s+|domestic\s+|select\s+|premium\s+|signature\s+|small\s+|medium\s+|large\s+|22\s*oz\s+|16\s*oz\s+)*"
                    r"(?:beers?|wines?|cocktails?|margaritas?|martinis?|drafts?|wells?|mai tais?|pints?|tecates?|mimosas?|spirits|"
                    r"sangrias?|seltzers?|drinks?|liquors?|shots?|pitchers?|long islands?|buckets?)\b", re.I)


def _food_prices(o):
    """Dollar amounts in the offer that are for food, not drinks ("$5 craft beer" doesn't count toward eating cheaply)."""
    out = []
    for m in _DOLLAR.finditer(o):
        rest = re.match(r"\s*[–-]\s*\$\d+(?:\.\d\d)?", o[m.end():])   # "$5–$6 beer" is a drink range
        if _DRINK.match(o, m.end() + (rest.end() if rest else 0)): continue
        before = o[max(0, m.start() - 14):m.start()].lower()
        if re.search(r"(?:beer|wine|drafts?|cocktails?|drinks?)\s*(?:are|at|for)?\s*$", before): continue
        out.append(float(m[1]))
    for m in _N_FOR.finditer(o):          # "2 for $25" is per person; "24 for $23.99" wings is one order
        n, total = int(m[1]), float(m[2])
        if n <= 4 and total in out: out[out.index(total)] = round(total / n, 2)
    return out


def derive_price(d):
    o, text = d["o"], d["o"] + " " + d["c"]
    spend = _MIN_SPEND.search(text)
    if spend: spend = float(next(g for g in spend.groups() if g))
    if d["t"] == "free":
        if spend is not None: return spend
        # "Free taco with any purchase" or "BOGO free" still means buying something first
        return None if re.search(r"with (?:a|any) purchase|with an? (?:adult )?entr|\bBOGO\b|buy (?:one|1)\b", text, re.I) else 0.0
    if d["t"] == "purchase":
        if spend is not None: return spend
        prices = _food_prices(o)
        return min(prices) if prices else None
    prices = _food_prices(o)
    return min(prices) if prices else None


# What you have to do to get it, shown as chips on the card.
_REQ = [
    ("Rewards member", r"\b(?:rewards?|members?|loyalty|e-?club|perks|club \w+|royalty|insiders?)\b|\bjoin(?:ing)?\b|sign(?:ing)?[- ]?up|account"),
    ("App or online", r"\bapp\b|\bonline\b|\bdigital\b|\bin-app\b|\bweb(?:site)?\b|\bmobile\b"),
    ("Dine-in only", r"dine-in only|dine in only|dine-in\b(?!,? (?:or|and|,))"),
    ("Carryout only", r"carryout only|carry-out only|takeout only|to-go only"),
    ("Bar seating", r"\bat the bar\b|bar (?:area|seating|only)|bar and patio|lounge only"),
    ("With adult entrée", r"adult (?:entr[ée]e|meal|food|purchase)"),
    ("Bring ID", r"\bID\b|student ID"),
    ("Participating locations", r"participat"),
    ("Reservations", r"reserv(?:e|ation)"),
]
_CODE = re.compile(r"\b(?:code|promo)\s+([A-Z0-9]{4,})\b")


def derive_req(d):
    text = d["o"] + " " + d["c"]
    req = [label for label, rx in _REQ if re.search(rx, text, re.I)]
    spend = _MIN_SPEND.search(text)
    if spend and d["t"] != "value":
        amt = next(g for g in spend.groups() if g)
        req.insert(0, f"${amt.rstrip('0').rstrip('.') if '.' in amt else amt}+ purchase")
    elif d["t"] == "purchase" and "With adult entrée" not in req:
        req.insert(0, "Purchase required")
    code = _CODE.search(text)
    if code: req.append(f"Code {code[1]}")
    return req


_ONCE = re.compile(r"sign[- ]?up|signing up|\bjoin(?:ing)?\b|new (?:app )?(?:members?|users?|sign-ups?|registrations?|customers?)|first (?:order|visit|purchase|app order)|welcome|birthday|enrol|when you register|registering|one[- ](?:use|time)|once per (?:guest|customer)|per account|receipt", re.I)


def derive_freq(d):
    return "once" if _ONCE.search(d["o"] + " " + d["c"]) or "birthday" in d["o"].lower() else "recurring"


_ADDR = re.compile(r"\b\d{2,5}\s+(?:[NSEW]{1,2}\.?\s+)?[\w.' ]+?\s(?:St|Ave|Blvd|Rd|Dr|Hwy|Pkwy|Place|Way|Ln|Ct|Cir)\b\.?")


def derive_addr(d):
    if d["area"] == "Statewide": return ""
    m = _ADDR.search(d["c"])
    return m[0].rstrip(".") if m else ""


def validate(deals):
    problems, seen = [], set()
    for i, d in enumerate(deals):
        where = f"#{i} {d.get('b', '?')!r}"
        for k in ("b", "o", "c", "t", "cat", "area", "kind", "src"):
            if not str(d.get(k, "")).strip():
                problems.append(f"{where}: missing {k}")
        if d.get("t") not in TYPES: problems.append(f"{where}: t={d.get('t')!r} not in {sorted(TYPES)}")
        if d.get("area") not in AREAS: problems.append(f"{where}: area={d.get('area')!r} not in {sorted(AREAS)}")
        if d.get("kind") not in KINDS: problems.append(f"{where}: kind={d.get('kind')!r} not in {sorted(KINDS)}")
        if d.get("cat") not in CATS: problems.append(f"{where}: cat={d.get('cat')!r} not in {sorted(CATS)}")
        if any(x not in DAYS for x in d.get("days", [])): problems.append(f"{where}: bad day in {d.get('days')}")
        if d.get("until") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["until"]):
            problems.append(f"{where}: until must be YYYY-MM-DD")
        if not str(d.get("src", "")).startswith("http"): problems.append(f"{where}: src must be a URL")
        hrs = d.get("hours", [])
        if not isinstance(hrs, list) or any(not (isinstance(w, list) and len(w) == 2 and 0 <= w[0] < w[1] <= 1440) for w in hrs):
            problems.append(f"{where}: hours must be [[start_min, end_min], ...] with 0 <= start < end <= 1440")
        if "price" in d and d["price"] is not None and not (isinstance(d["price"], (int, float)) and d["price"] >= 0):
            problems.append(f"{where}: price must be a number >= 0 or null")
        if "freq" in d and d["freq"] not in ("once", "recurring"): problems.append(f"{where}: freq must be once or recurring")
        if "req" in d and not (isinstance(d["req"], list) and all(isinstance(x, str) for x in d["req"])):
            problems.append(f"{where}: req must be a list of strings")
        geo = d.get("geo")
        if geo is not None and not (isinstance(geo, list) and len(geo) == 2 and 24.3 < geo[0] < 31.1 and -87.7 < geo[1] < -79.8):
            problems.append(f"{where}: geo must be [lat, lng] inside Florida, or left out")
        if d.get("kind") == "Kids eat free" and re.search(r"\$\d", d.get("o", "")) and "free" not in d.get("o", "").lower():
            problems.append(f"{where}: a priced kids meal isn't 'Kids eat free'; use 'Weekly special' or 'Everyday value'")
        key = (d.get("b", "").lower(), d.get("o", "").lower(), d.get("area"))
        if key in seen: problems.append(f"{where}: duplicate of an earlier deal (same brand, offer, area)")
        seen.add(key)
    return problems


def main():
    deals = json.loads(DATA.read_text(encoding="utf-8"))
    problems = validate(deals)
    if problems:
        print("\n".join(problems)); print(f"{len(problems)} problem(s)"); sys.exit(1)
    if "--check" in sys.argv:
        print(f"ok: {len(deals)} deals"); return

    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_EXPIRED_DAYS)).isoformat()
    kept = [d for d in deals if not d.get("until") or d["until"] >= cutoff]
    for d in kept:
        d["days"] = [x for x in DAYS if x in d.get("days", [])]
        # Anything written explicitly in the data is kept; missing fields are read from the deal's text.
        if "hours" not in d: d["hours"] = derive_hours(d["o"] + " " + d["c"])
        if "price" not in d: d["price"] = derive_price(d)
        if "req" not in d: d["req"] = derive_req(d)
        if "freq" not in d: d["freq"] = derive_freq(d)
        if "addr" not in d: d["addr"] = derive_addr(d)
    DATA.write_text("[\n" + ",\n".join(json.dumps(d, ensure_ascii=False) for d in kept) + "\n]\n", encoding="utf-8")

    page = PAGE.read_text(encoding="utf-8")
    tag = '<script id="dealData" type="application/json">'
    a = page.index(tag) + len(tag)
    b = page.index("</script>", a)
    body = "\n" + ",\n".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in kept).replace("</", "<\\/")
    page = page[:a] + "\n[" + body[1:] + "]\n" + page[b:]
    today = dt.date.today()
    page = re.sub(r"<!--UPDATED-->.*?<!--/UPDATED-->",
                  f"<!--UPDATED-->Last updated {today:%B} {today.day}, {today.year}.<!--/UPDATED-->", page)
    PAGE.write_text(page, encoding="utf-8")
    print(f"built index.html: {len(kept)} deals ({len(deals) - len(kept)} long-expired removed)")


if __name__ == "__main__":
    main()
