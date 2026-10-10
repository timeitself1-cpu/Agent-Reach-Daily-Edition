"""A small gazetteer for the contradiction gate (``daily/gates.py``): places a news story is likely to name, with
what each lies in. No model and no network. A place that is not listed here is simply not checked: the gate
misses a contradiction before it invents one.

Left out on purpose because a news story means something else by them: Washington (the state, the city or the
US government), Georgia, Jordan, Turkey, Chad, Reading, Mobile, Jackson, Lincoln, Orange.
"""
from __future__ import annotations

import re

US = "united states"

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york state": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

#: city -> state (a key of STATES)
US_CITIES = {
    "new york city": "new york state", "brooklyn": "new york state", "manhattan": "new york state",
    "the bronx": "new york state", "queens": "new york state", "staten island": "new york state",
    "buffalo": "new york state", "albany": "new york state", "rochester": "new york state",
    "los angeles": "california", "san francisco": "california", "san diego": "california", "san jose": "california",
    "oakland": "california", "sacramento": "california", "fresno": "california", "bakersfield": "california",
    "long beach": "california", "anaheim": "california", "riverside": "california", "santa ana": "california",
    "chicago": "illinois", "houston": "texas", "dallas": "texas", "austin": "texas", "san antonio": "texas",
    "fort worth": "texas", "el paso": "texas", "uvalde": "texas", "philadelphia": "pennsylvania",
    "pittsburgh": "pennsylvania", "phoenix": "arizona", "tucson": "arizona", "tempe": "arizona",
    "miami": "florida", "orlando": "florida", "tampa": "florida", "jacksonville": "florida",
    "atlanta": "georgia-us", "boston": "massachusetts", "seattle": "washington-state", "spokane": "washington-state",
    "denver": "colorado", "las vegas": "nevada", "reno": "nevada", "detroit": "michigan", "minneapolis": "minnesota",
    "st. paul": "minnesota", "portland": "oregon", "salt lake city": "utah", "nashville": "tennessee",
    "memphis": "tennessee", "new orleans": "louisiana", "baton rouge": "louisiana", "charlotte": "north carolina",
    "raleigh": "north carolina", "baltimore": "maryland", "milwaukee": "wisconsin", "kansas city": "missouri",
    "st. louis": "missouri", "cleveland": "ohio", "columbus": "ohio", "cincinnati": "ohio",
    "indianapolis": "indiana", "louisville": "kentucky", "oklahoma city": "oklahoma", "omaha": "nebraska",
    "albuquerque": "new mexico", "honolulu": "hawaii", "anchorage": "alaska", "newark": "new jersey",
    "jersey city": "new jersey", "richmond": "virginia", "norfolk": "virginia", "arlington": "virginia",
    "birmingham": "alabama", "charleston": "south carolina", "des moines": "iowa", "little rock": "arkansas",
    "boise": "idaho", "providence": "rhode island", "hartford": "connecticut", "minot": "north dakota",
}

#: alias -> the place it names
ALIASES = {"nyc": "new york city", "new york": "new york city", "n.y.c.": "new york city",
           "l.a.": "los angeles", "d.c.": "district of columbia", "washington, d.c.": "district of columbia",
           "u.s.": US, "us": US, "usa": US, "u.s.a.": US, "america": US, "the united states": US,
           "uk": "united kingdom", "u.k.": "united kingdom", "britain": "united kingdom", "england": "united kingdom",
           "uae": "united arab emirates", "south korea": "south korea", "north korea": "north korea"}

#: country -> region used only for "same country" relations; capitals and big cities -> country
COUNTRIES = """afghanistan argentina australia austria bangladesh belgium brazil canada chile china colombia cuba
denmark egypt ethiopia finland france germany ghana greece haiti hungary india indonesia iran iraq ireland israel
italy japan kenya lebanon libya malaysia mexico morocco myanmar nepal netherlands nigeria norway pakistan peru
philippines poland portugal qatar romania russia rwanda somalia spain sudan sweden switzerland syria taiwan
thailand tunisia ukraine venezuela vietnam yemen zimbabwe""".split() + [
    "south korea", "north korea", "saudi arabia", "south africa", "new zealand", "united kingdom",
    "united arab emirates", "sri lanka", "el salvador", "costa rica", "hong kong", "united states", "west bank",
    "gaza", "european union"]

WORLD_CITIES = {
    "london": "united kingdom", "manchester": "united kingdom", "paris": "france", "marseille": "france",
    "berlin": "germany", "munich": "germany", "madrid": "spain", "barcelona": "spain", "rome": "italy",
    "milan": "italy", "moscow": "russia", "kyiv": "ukraine", "kharkiv": "ukraine", "odesa": "ukraine",
    "beijing": "china", "shanghai": "china", "shenzhen": "china", "tokyo": "japan", "osaka": "japan",
    "seoul": "south korea", "pyongyang": "north korea", "delhi": "india", "new delhi": "india", "mumbai": "india",
    "tehran": "iran", "baghdad": "iraq", "damascus": "syria", "beirut": "lebanon", "jerusalem": "israel",
    "tel aviv": "israel", "cairo": "egypt", "khartoum": "sudan", "kabul": "afghanistan",
    "islamabad": "pakistan", "karachi": "pakistan", "dhaka": "bangladesh", "bangkok": "thailand",
    "jakarta": "indonesia", "manila": "philippines", "taipei": "taiwan", "sydney": "australia",
    "melbourne": "australia", "toronto": "canada", "vancouver": "canada", "ottawa": "canada",
    "montreal": "canada", "mexico city": "mexico", "havana": "cuba", "caracas": "venezuela",
    "brasilia": "brazil", "sao paulo": "brazil", "buenos aires": "argentina", "lagos": "nigeria",
    "nairobi": "kenya", "johannesburg": "south africa", "riyadh": "saudi arabia", "doha": "qatar",
    "dubai": "united arab emirates", "abu dhabi": "united arab emirates", "brussels": "belgium",
    "amsterdam": "netherlands", "dublin": "ireland", "warsaw": "poland", "athens": "greece",
}


def _build() -> tuple[dict[str, str | None], dict[str, str]]:
    """(place -> its parent or None, surface form -> place), all lower case."""
    parent: dict[str, str | None] = {}
    surface: dict[str, str] = {}
    for c in COUNTRIES:
        parent[c] = None
        surface[c] = c
    parent[US] = None
    for state in STATES:
        parent[state] = US
        surface[state] = state
    # 'New York' alone means the city in a headline; 'New York state' / 'upstate New York' the state
    surface["new york state"] = "new york state"
    surface["washington state"] = "washington-state"
    parent["washington-state"] = US
    parent["georgia-us"] = US
    surface["georgia (u.s. state)"] = "georgia-us"
    for city, state in US_CITIES.items():
        parent[city] = state
        surface[city] = city
    for city, country in WORLD_CITIES.items():
        parent[city] = country
        surface[city] = city
    for alias, target in ALIASES.items():
        surface[alias] = target
    parent["new york city"] = "new york state"
    for borough in ("brooklyn", "manhattan", "the bronx", "queens", "staten island"):
        parent[borough] = "new york city"
    return parent, surface


PARENT, SURFACE = _build()
# 'Washington' and 'Georgia' alone are ambiguous and not in SURFACE; the entries above are only for the
# cities that name the state.
_PLACE_RX = re.compile(
    r"(?<![\w-])(?<!gulf of )(?<!bay of )(?<!sea of )(?<!strait of )(?<!bank of )(?<!university of )(?<!republic of )(" + "|".join(re.escape(k) for k in sorted(SURFACE, key=len, reverse=True)) + r")(?![\w-])",
    re.IGNORECASE)
#: short forms must be written the way a newsroom writes them
_CASE_SENSITIVE = {"nyc", "us", "uk", "uae", "usa", "u.s.", "u.k.", "d.c.", "l.a.", "u.s.a.", "n.y.c."}


def ancestors(place: str) -> set[str]:
    out, seen = set(), place
    while PARENT.get(seen):
        seen = PARENT[seen]  # type: ignore[assignment]
        out.add(seen)
    return out


def places_in(text: str) -> list[str]:
    """The listed places a text names (canonical lower-case ids), in order of first mention, once each.

    Case: 'Fresno' and 'fresno' both count except for the short forms (NYC, US, UK ...), which must be written
    in capitals so that 'us' and 'uk' in running text are not places. A place written lower case in a sentence
    that is not a title is rare enough in news prose to ignore: only capitalised mentions count."""
    found: list[str] = []
    for m in _PLACE_RX.finditer(text):
        raw = m.group(1)
        surface = raw.lower()
        if surface in _CASE_SENSITIVE:
            if raw.lower() == raw or (surface == "us" and raw != "US"):
                continue
        elif not raw[:1].isupper():
            continue
        place = SURFACE[surface]
        if place not in found:
            found.append(place)
    return found


def related(a: str, b: str) -> bool:
    """Same place, or one lies inside the other (Fresno ~ California ~ United States; not Fresno ~ New York City)."""
    return a == b or a in ancestors(b) or b in ancestors(a)


def label(place: str) -> str:
    return {"washington-state": "Washington state", "georgia-us": "Georgia (US)"}.get(place, place.title())
