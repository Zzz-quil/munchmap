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
    if re.search(r"all day", text, re.I):   # all day on some days: don't hide it at other times
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
        if "hours" not in d:   # an explicit "hours" (even []) is kept as written
            d["hours"] = derive_hours(d["o"] + " " + d["c"])
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
