# MunchMap

A single-page Florida food-deals finder, live at https://munchmap-fl.vercel.app/ (Vercel, auto-deploys from main; the old GitHub Pages URL redirects there). `index.html` is the whole site (no build tooling, no dependencies).
The deal data lives in `data/deals.json` and is baked into `index.html` by `python tools/build.py`.

Never hand-edit the `<script id="dealData">` block in `index.html`; edit `data/deals.json` and rebuild.

## Deal record

One JSON object per line in `data/deals.json`:

| field | meaning |
|---|---|
| `b` | brand or restaurant name |
| `o` | short offer, under ~45 chars, e.g. `"Free 6-pc nuggets"` |
| `c` | one plain sentence of conditions (days/times, app or membership needed, "participating locations", neighborhood for local spots) |
| `t` | `free` \| `purchase` (free with a purchase) \| `discount` \| `value` (a set low price) |
| `cat` | `Burgers` `Chicken` `Mexican` `Sandwiches` `Pizza` `Coffee & sweets` `Healthy` `Sit-down` `Grocery & convenience` `Latin & local` `Seafood` `Bar food` `Apps & programs` |
| `days` | weekday names the deal runs on, `[]` if every day |
| `area` | `Statewide` for chains, else one of `Miami-Dade` `Fort Lauderdale` `Palm Beach` `Orlando` `Tampa Bay` `Jacksonville` `Gainesville` `Tallahassee` `Sarasota` `Southwest Florida` `Panhandle` |
| `kind` | `Apps & rewards` `Everyday value` `Weekly special` `Happy hour` `Kids eat free` `Sports win` `Restaurant week` `Grocery & stores` `Discounts & programs` `Student` `Limited time` |
| `until` | last valid day `YYYY-MM-DD` for limited-time deals, else `""` |
| `hours` | when the deal runs, as minute ranges from midnight: `[[900,1080]]` = 3–6pm, `[[1260,1440]]` = 9pm–close, `[]` = no set hours / all day. Leave the key out and `build.py` reads it from times written in `o`/`c` ("3–6pm", "after 5pm", "9pm–close", "open–7pm"); set it explicitly when the text is ambiguous. Powers the page's Time filter ("Right now", Lunch, Dinner…) |
| `src` | URL where the deal was found |
| `srcName` | publication + month, e.g. `"Hip2Save, Oct 2026"` |

| `price` | cheapest out-of-pocket cost per person in dollars for **food** (free = `0`, "free with a $5 order" = `5`, "2 for $25" = `12.5`), or `null` when there's no fixed price ("50% off", BOGO, drink-only specials). Powers the Under $5/$10/$15 filter, which hides `null` deals |
| `req` | what you must do, shown as chips: e.g. `"$5+ purchase"`, `"Rewards member"`, `"App or online"`, `"Dine-in only"`, `"With adult entrée"`, `"Bring ID"`, `"Participating locations"`, `"Code BOGO50"` |
| `freq` | `"once"` for one-time offers (sign-up gifts, birthday rewards, single-use codes) or `"recurring"` (happy hours, weekly specials, everyday value). One-time cards stamp "Claimed" for good; recurring cards stamp "Used today" and reset the next day |
| `addr` | street address for local spots (e.g. `"207 NE 1st St"`), `""` if unknown or a chain |
| `geo` | `[lat, lng]` of a single local restaurant, `null` if looked up and not found / not one place. Filled by `python tools/geocode.py` |

For `price`, `req`, `freq` and `addr`: leave the key out and `build.py` derives it from `o`/`c`, but check the result; set it
explicitly when the text is ambiguous. If you edit a deal's text, update or remove these keys so they get re-derived.
"Kids eat free" is only for a $0 kids meal; a priced kids meal ("$2.99 kids meals") is a Weekly special (the build rejects it otherwise).

The page hides deals whose `until` has passed; `build.py` deletes them from the data a week later.
`python tools/build.py --check` validates without writing.

## Daily refresh procedure

Goal: keep the deal book accurate and fresh for people in Florida looking for cheap meals.

1. Read `data/deals.json`. Note today's date.
2. Research with web search (prefer recent, dated sources: chain sites and press releases, Brand Eating, EatDrinkDeals,
   Krazy Coupon Lady, Hip2Save, The Freebie Guy, weekly-ad sites for Publix/Winn-Dixie/Aldi, and Florida local press
   such as Miami New Times, Orlando Weekly, Tampa Bay Times, That's So Tampa, I Love the Burg, Jax Today, WOKV,
   Tallahassee Democrat, Gainesville Sun, Palm Beach Post, Sun Sentinel). Look for:
   - new chain app freebies, value menus and limited-time offers valid in Florida
   - food holidays in the coming week (e.g. National Taco Day Tue Oct 6 2026, Halloween, Veterans Day) and their chain deals
   - this week's Publix / Winn-Dixie / Aldi ad highlights (replace last week's ad entries)
   - Florida sports-win freebies for teams in season (Jaguars, Dolphins, Bucs, Heat, Magic, Lightning, Panthers)
   - new kids-eat-free nights, happy hours, weekly specials and restaurant weeks in the Florida metros
3. Edit `data/deals.json`:
   - add new deals you can source; never invent prices, times or dates
   - fix any existing deal your research shows has changed; remove ones confirmed discontinued
   - set `until` whenever a deal has an end date
   - do not add duplicates (same brand + offer + area)
4. Run `python tools/build.py` (derives price/req/freq/addr/hours for new deals), then `python tools/geocode.py` to look up
   coordinates for new local spots (needs network access to nominatim.openstreetmap.org; if it's blocked, say so in your summary),
   then `python tools/build.py` again. It must print `built index.html`. Fix any validation problems it reports.
5. Commit to `main` with a message like `Deals refresh 2026-10-05: +12 new, 4 updated, 9 expired` and push.
   If nothing changed, commit nothing.

Effort bar: a refresh is a real research pass, not a skim. Run at least 25 web searches spread across every bullet in step 2
and every Florida metro, open the most promising results, and aim for roughly 10+ additions or corrections. If a site is blocked
by the network (e.g. hip2save.com), find the same deal on another source such as the chain's own site, a press release or local news.
Before adding, check `data/deals.json` for the same brand + offer at "Statewide" as well as in the area, so you don't duplicate chain deals.

Quality bar: every deal must be current (sourced from the last ~60 days, or a permanent program confirmed still active)
and actually available in Florida. When unsure, leave it out.
