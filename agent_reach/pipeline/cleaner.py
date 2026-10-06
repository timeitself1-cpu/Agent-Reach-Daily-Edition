"""Pre-LLM heuristic cleaning: normalisation, noise filtering, de-duplication and scoring.

Everything here is deterministic and cheap, so the 8B model only ever sees items that
already look like plausible trend signals.
"""

from __future__ import annotations

import html
import json
import logging
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from agent_reach.config import Settings
from agent_reach.models import CategoryEnum, CleanedTrendItem, RawTrendItem, SourceName

log = logging.getLogger(__name__)

# --------------------------------------------------------------------- lexicons
STOPWORDS: frozenset[str] = frozenset(
    """a an the and or but if of in on at to for from by with without about into over under after before
    is are was were be been being am do does did has have had will would can could should may might must
    this that these those it its it's he she they them their his her our your you we i me my mine us
    what which who whom whose when where why how not no yes so than too very just also more most less
    new news via vs vs. says said say amid after as up out off all any each every other some such only
    own same here there then now today tonight yesterday week year years day days first last next top
    best how-to update live watch video photo photos report reports one two three get gets got make makes
    """.split()
)

CATEGORY_LEXICON: dict[CategoryEnum, tuple[str, ...]] = {
    CategoryEnum.SPORTS: (
        r"nfl", r"nba", r"mlb", r"nhl", r"mls", r"wnba", r"ncaa", r"ufc", r"wwe", r"fifa", r"uefa", r"f1",
        r"formula 1", r"premier league", r"champions league", r"la liga", r"super bowl", r"world series",
        r"playoffs?", r"touchdown", r"quarterback", r"qb", r"tnf", r"snf", r"mnf", r"thursday night football",
        r"sunday night football", r"monday night football", r"packers", r"falcons", r"cowboys", r"eagles",
        r"chiefs", r"bills", r"ravens", r"49ers", r"steelers", r"lions", r"bears", r"vikings", r"giants",
        r"jets", r"patriots", r"dolphins", r"broncos", r"raiders", r"chargers", r"seahawks", r"rams",
        r"cardinals", r"saints", r"buccaneers", r"panthers", r"commanders", r"texans", r"colts", r"jaguars",
        r"titans", r"bengals", r"browns", r"lakers", r"celtics", r"warriors", r"knicks", r"yankees",
        r"dodgers", r"mets", r"red sox", r"cubs", r"astros", r"braves", r"phillies", r"grand slam", r"tennis", r"golf", r"pga", r"ryder cup", r"boxing", r"game \d", r"coach", r"draft",
        r"trade deadline", r"mvp", r"football", r"baseball", r"basketball", r"soccer", r"hockey",
    ),
    CategoryEnum.SCIENCE_AI: (
        r"ai", r"a\.i\.", r"artificial intelligence", r"llm", r"llms", r"gpt[-\s]?\d*", r"chatgpt", r"openai",
        r"anthropic", r"claude", r"gemini", r"llama", r"mistral", r"deepseek", r"qwen", r"transformer",
        r"neural", r"diffusion", r"machine learning", r"deep learning", r"reinforcement learning", r"agents?",
        r"benchmark", r"dataset", r"research", r"study", r"scientists?", r"nasa", r"spacex", r"esa",
        r"telescope", r"asteroid", r"comet", r"mars", r"moon", r"quantum", r"physics", r"biology",
        r"genome", r"vaccine", r"climate", r"fossil", r"species", r"arxiv", r"paper",
    ),
    CategoryEnum.TECH: (
        r"apple", r"iphone", r"ipad", r"macos", r"ios", r"android", r"google", r"microsoft", r"windows",
        r"linux", r"meta", r"amazon", r"aws", r"nvidia", r"amd", r"intel", r"tesla", r"startup", r"software",
        r"hardware", r"chip", r"chips", r"semiconductor", r"app", r"apps", r"api", r"open[-\s]?source",
        r"github", r"rust", r"python", r"javascript", r"typescript", r"golang", r"kubernetes", r"docker",
        r"database", r"sql", r"framework", r"library", r"cli", r"browser", r"security", r"vulnerability",
        r"cve", r"breach", r"hack", r"hacked", r"ransomware", r"outage", r"cloud", r"developer", r"devs?",
        r"programming", r"compiler", r"gpu", r"cpu", r"smartphone", r"laptop", r"gadget", r"crypto",
        r"bitcoin", r"ethereum", r"show hn", r"launch hn", r"saas", r"sdk", r"self-hosted",
    ),
    CategoryEnum.ENTERTAINMENT: (
        r"movie", r"film", r"trailer", r"box office", r"netflix", r"hbo", r"disney", r"marvel", r"star wars", r"season \d+", r"episode", r"album", r"song", r"tour", r"concert",
        r"grammy", r"oscar", r"oscars", r"emmy", r"emmys", r"golden globes", r"actor", r"actress", r"singer",
        r"rapper", r"celebrity", r"premiere", r"sequel", r"anime", r"video game", r"playstation", r"xbox",
        r"nintendo", r"switch 2", r"gta", r"taylor swift", r"beyonce", r"drake", r"kanye", r"spotify",
        r"billboard", r"broadway", r"snl", r"podcast", r"streaming",
    ),
    CategoryEnum.NEWS: (
        r"president", r"senate", r"congress", r"supreme court", r"court", r"judge", r"election",
        r"vote", r"governor", r"mayor", r"minister", r"parliament", r"white house", r"trump", r"biden",
        r"harris", r"government", r"shutdown", r"tariffs?", r"economy", r"inflation", r"fed", r"stocks?",
        r"market", r"war", r"ukraine", r"russia", r"israel", r"gaza", r"china", r"iran", r"hurricane",
        r"storm", r"earthquake", r"wildfire", r"flood", r"shooting", r"police", r"arrested", r"killed",
        r"dies", r"dead", r"death", r"lawsuit", r"strike", r"protest", r"sanctions", r"policy", ),
    CategoryEnum.INTERNET_CULTURE: (
        r"meme", r"viral", r"tiktok", r"trend", r"challenge", r"influencer", r"youtuber", r"streamer",
        r"twitch", r"mrbeast", r"reddit", r"subreddit", r"hashtag", r"fandom", r"discourse",
        r"backlash", r"cancelled", r"drama", r"slang", r"aesthetic",
    ),
}
_CATEGORY_RX: dict[CategoryEnum, re.Pattern[str]] = {
    cat: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE) for cat, words in CATEGORY_LEXICON.items()
}

# --------------------------------------------------------------------- noise rules
CLICKBAIT_STRIP = re.compile(
    r"^\s*(?:breaking(?: news)?|just in|watch|update|updated|exclusive|developing|live|video|photos?|"
    r"must[- ]see|viral|shocking|omg|wow)\s*[:\-|!]+\s*"
    r"|\[(?:oc|video|photo|pic|pics|serious|nsfw|meta|update|removed)\]"
    r"|\((?:video|photos?|watch|pics?|oc)\)"
    r"|\b(?:you won'?t believe|will blow your mind|goes viral|gone viral|jaw[- ]dropping|must[- ]see|"
    r"what happened next|here'?s why|this is why|the internet is losing it|broke the internet|"
    r"can'?t stop watching|mind[- ]blowing|insane|unbelievable)\b[:!.,]*",
    re.IGNORECASE,
)
ANECDOTE_RX = re.compile(
    r"^(?:my|i|i'm|im|i've|ive|i'd|i'll|me|we|we're|we've|our|us|mine|meet my|look at (?:my|this|our)|"
    r"just (?:got|found|finished|made|saw)|finally (?:got|finished|made)|so i|today i|yesterday i|"
    r"this is my|here'?s my|when you|when your|me when|mfw|mrw|tfw|pov:?)\b"
    r"|\bmy (?:cat|dog|wife|husband|son|daughter|boyfriend|girlfriend|bf|gf|mom|mum|dad|grandma|grandpa|"
    r"kid|kids|baby|partner|friend|neighbor|neighbour|boss|coworker|roommate|first|new)\b"
    r"|\b(?:tifu|aita|aitah|wibta|til i|iama|ama)\b",
    re.IGNORECASE,
)
MEME_PHOTO_RX = re.compile(
    r"\b(?:meme|memes|selfie|pic of|photo of|picture of|pics of|took this|i drew|i painted|my (?:drawing|painting|art)|"
    r"fan ?art|wallpaper|cute|adorable|wholesome|caturday|shower thoughts?|unpopular opinion|rate my|roast me|"
    r"any ideas\??|help me|what is this|who is this|does anyone|anyone else|is it just me)\b",
    re.IGNORECASE,
)
PET_RX = re.compile(
    r"\b(?:cats?|kittens?|kitty|dogs?|doggo|puppy|puppies|pupper|pups?|good boy|good girl|hamster|bunny|"
    r"parrot|goldfish|pet|pets|furbaby|fur baby)\b",
    re.IGNORECASE,
)
BOX_SCORE_RX = re.compile(
    r"\b(?:box score|player props?|prop bets?|parlays?|same game parlay|sgp|fantasy (?:football|points|lineup|"
    r"start|sit|team)|start[/ ]sit|waiver wire|injury report|odds|point spread|spread pick|over/under|"
    r"betting lines?|best bets?|picks? (?:and|&) predictions?|prediction[s]?,? odds|final score|live score|"
    r"how to watch|live stream|where to watch|what channel|tv channel|kickoff time|start time)\b"
    r"|\b\d+\s*(?:pts|reb|ast|yds|rec|tds?)\b.*\b\d+\s*(?:pts|reb|ast|yds|rec|tds?)\b",
    re.IGNORECASE,
)
#: Advertising dressed as news ('this $15 E-Degree can help', 'on sale now for just $14.97 (MSRP $159)').
PROMO_RX = re.compile(
    r"\b(?:on sale|for just \$|save \$\d|\d+% off|percent off|promo code|coupon code|lifetime (?:subscription|license|access)|"
    r"e-degree|bundle (?:for|at) \$|deals? of the day|best [\w\s-]{0,40} deals|prime day deals?|black friday deals?|"
    r"cyber monday deals?|price drop|msrp|sponsored|affiliate commission|"
    # shopping-event roundups ('Prime Day Apple Watch deals: Series 12 all-time low, Ultra 4 $100 off')
    r"all[- ]time lows?|\$\d[\d,.]* off|prime (?:day|big deal days?)\b.{0,60}\b(?:deals?|discounts?|sale)|"
    r"(?:deals?|discounts?)\b.{0,60}\bprime (?:day|sale|big deal days?))\b",
    re.IGNORECASE,
)
#: Video clips that are not reports: highlight reels, full replays, live streams, reactions and recaps.
VIDEO_CLIP_RX = re.compile(
    r"\b(?:full game highlights|game highlights|extended highlights|highlights|full game|full match|full episode|"
    r"live ?stream|watch live|press conference live|reaction|recap|podcast|shorts)\b|^live\b",
    re.IGNORECASE,
)
GENERIC_HASHTAGS: frozenset[str] = frozenset(
    """fyp foryou foryoupage fy fypage fypシ viral viralvideo trending trend trend2026 explore explorepage
    tiktok tiktokviral capcut duet stitch fall autumn fallvibes autumnvibes falloutfit fallfashion fallseason
    fallaesthetic pumpkinspice pumpkin cozy cozyseason sweaterweather spookyseason spooky halloweencostume
    summer summervibes winter winteroutfit spring springvibes love fashion ootd grwm makeup skincare beauty
    funny comedy humor cute aesthetic music dance dancechallenge song lyrics motivation inspiration
    goodmorning goodnight morning mood vibes vibe weekend weekendvibes friday fridayvibes fridayfeeling
    monday mondaymotivation tuesday wednesday thursday saturday sunday sundayfunday tbt throwbackthursday
    happy smile life lifestyle family friends couple relationship food foodie recipe cooking fitness gym
    workout travel nature photography art artist fyppppppppppppppppppppppp xyzbca xyzcba greenscreen
    learnontiktok booktok pov relatable""".split()
)
LOW_SIGNAL_SUBREDDITS: frozenset[str] = frozenset(
    """aww cats dogs rarepuppers eyebleach pics mildlyinteresting oddlysatisfying memes me_irl meirl
    2meirl4meirl funny wholesomememes animalsbeingderps animalsbeingbros animalsbeingjerks pets husky
    corgi catsareassholes blackcats tuxedocats standardissuecat selfie amiugly roastme aitah amitheasshole
    tifu relationship_advice askreddit nostupidquestions askmen askwomen showerthoughts unpopularopinion
    confession offmychest trueoffmychest facepalm therewasanattempt mademesmile humansbeingbros
    pic itookapicture earthporn food foodporn gardening houseplants""".split()
)
GENERIC_HASHTAG_RX = re.compile(
    r"(?:happy|good)(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|morning|night)\w*"
    r"|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend)"
    r"(?:vibes|motivation|feeling|funday|mood|mornings?)?"
    r"|\w*(?:vibes|szn|aesthetic|ootd|grwm)"
)
HASHTAG_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[0-9])(?=[A-Za-z])")
URL_RX = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
WS_RX = re.compile(r"\s+")
TOKEN_RX = re.compile(r"[a-z0-9][a-z0-9'+.&-]*[a-z0-9+]|[a-z0-9]")

SOURCE_WEIGHT: dict[SourceName, float] = {
    SourceName.GOOGLE_TRENDS: 1.00,
    SourceName.HACKERNEWS: 0.95,
    SourceName.GOOGLE_NEWS: 0.90,
    SourceName.NEWS_RSS: 0.90,
    SourceName.YOUTUBE: 0.80,
    SourceName.MASTODON: 0.80,
    SourceName.BLUESKY: 0.80,
    SourceName.X_TRENDS24: 0.85,
    SourceName.WIKIPEDIA: 0.80,
    SourceName.REDDIT: 0.80,
    SourceName.GITHUB: 0.75,
    SourceName.PRODUCTHUNT: 0.65,
    SourceName.TIKTOK: 0.60,
    SourceName.ARXIV: 0.55,
}
SOCIAL_SOURCES = frozenset({SourceName.REDDIT, SourceName.X_TRENDS24, SourceName.TIKTOK, SourceName.BLUESKY,
                            SourceName.MASTODON})
ANECDOTE_SOURCES = frozenset({SourceName.REDDIT, SourceName.X_TRENDS24, SourceName.TIKTOK, SourceName.GOOGLE_NEWS,
                              SourceName.YOUTUBE, SourceName.BLUESKY})
#: Sources made of several feeds (publisher feeds, YouTube channels, Google News sections): each feed
#: gets its own floor in the processing budget.
MULTI_FEED_SOURCES = frozenset({SourceName.NEWS_RSS, SourceName.YOUTUBE, SourceName.GOOGLE_NEWS})
#: Fair floors may take at most this share of the processing budget; the rest goes to the best scores.
FLOOR_SHARE = 0.75


# --------------------------------------------------------------------- text utils
#: Letters with no ASCII decomposition are spelled out instead of being dropped.
TRANSLITERATION = str.maketrans({
    "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "ß": "ss", "ẞ": "SS", "œ": "oe", "Œ": "OE", "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ı": "i", "ħ": "h", "Ħ": "H",
})
def normalize_text(text: str) -> str:
    """HTML-unescape, fold to ASCII, drop URLs/control chars, collapse whitespace."""
    if not text:
        return ""
    t = html.unescape(text)
    t = t.translate(TRANSLITERATION)  # letters NFKD cannot decompose: 'hændelse' -> 'haendelse', 'Straße' -> 'Strasse'
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", " - ").replace("…", "...")
    # currency signs have no ASCII form: '$1.9tn (£1.4tn)' must not become '$1.9tn (1.4tn)'
    t = t.replace("£", "GBP ").replace("€", "EUR ").replace("¥", "JPY ")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = URL_RX.sub(" ", t)
    t = "".join(ch if ch.isprintable() else " " for ch in t)
    t = re.sub(r"([!?.])\1{2,}", r"\1", t)  # '!!!!' -> '!'
    t = WS_RX.sub(" ", t).strip(" -|:;,")
    return t.strip()


def split_hashtag(tag: str) -> str:
    """'#JordanLove' -> 'Jordan Love'; '#GBvsATL' -> 'GB vs ATL'; plain text unchanged."""
    body = tag.lstrip("#").strip()
    if not body or " " in body:
        return body
    body = re.sub(r"(?<=[A-Z])vs(?=[A-Z])", " vs ", body)
    body = body.replace("_", " ")
    return WS_RX.sub(" ", HASHTAG_CAMEL.sub(" ", body)).strip()


def dedupe_key(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = WS_RX.sub(" ", t).strip()
    return re.sub(r"^the ", "", t)


def tokens(text: str) -> list[str]:
    return TOKEN_RX.findall(text.lower())


def significant_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) >= 3 and t not in STOPWORDS and not t.isdigit()}


def infer_category(text: str) -> CategoryEnum | None:
    """Keyword vote. Returns None when no lexicon matches."""
    best: CategoryEnum | None = None
    best_hits = 0
    for cat, rx in _CATEGORY_RX.items():
        hits = len(rx.findall(text))
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def category_votes(text: str) -> Counter[CategoryEnum]:
    return Counter({cat: len(rx.findall(text)) for cat, rx in _CATEGORY_RX.items() if rx.search(text)})


# --------------------------------------------------------------------- output sanitisation
SOURCE_DISPLAY: dict[str, str] = {
    "x_trends24": "X",
    "reddit": "Reddit",
    "tiktok": "TikTok",
    "google_trends": "Google Trends",
    "google_news": "Google News",
    "wikipedia": "Wikipedia",
    "arxiv": "arXiv",
    "hackernews": "Hacker News",
    "github": "GitHub",
    "producthunt": "Product Hunt",
    "news_rss": "News feeds",
    "youtube": "YouTube",
    "mastodon": "Mastodon",
    "bluesky": "Bluesky",
}

MD_LINK_RX = re.compile(r"\[([^\]]{1,200})\]\((?:https?://|www\.)[^)]*\)")
BARE_URL_RX = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|org|net|io|ai|dev|app|co)(?:/\S*)?", re.IGNORECASE)
#: Words after which a bare domain is an attribution ('via techcrunch.com'), not the subject of the title.
_ATTRIBUTION_WORDS = frozenset("via from on at by source sources visit see read more".split())
#: A live blog ('Trump claims he's doing great ... - as it happened'): a running page of many updates.
#: ('... - US politics live', 'Ukraine war live: ...', 'Live: ...' are the same running pages.)
LIVE_BLOG_RX = re.compile(r"\bas it happened\b|\blive (?:updates?|blog|coverage)\b|\bthis live blog\b"
                          r"|^\s*(?:[A-Za-z']+\s+){0,3}live\s*[:|]|\s[-–—|]\s*(?:[A-Za-z']+\s+){0,3}live\s*$",
                          re.IGNORECASE)
LIVE_BLOG_SUFFIX_RX = re.compile(r"\s*[-–—|:]\s*(?:as it happened|(?:[A-Za-z']+\s+){0,3}live"
                                 r"(?: updates| blog| coverage)?)\s*$", re.IGNORECASE)


def is_live_blog(text: str | None) -> bool:
    return bool(text and LIVE_BLOG_RX.search(text))


def strip_bare_urls(text: str) -> str:
    """Remove URLs and bare domains, but keep a domain that is the subject ('Example.com just launched ...').

    A bare domain (no scheme, no path) stays when more words follow it in the same sentence and it is
    not an attribution ('via example.com', 'read more at example.com')."""
    def repl(m: re.Match[str]) -> str:
        word = m.group(0)
        if word.lower().startswith(("http", "www.")) or "/" in word:
            return ""
        before = text[:m.start()].split()
        rest = text[m.end():]
        follows = re.match(r"(?:'s)?\s+[A-Za-z]", rest) is not None
        if follows and not (before and before[-1].lower().strip(":,(") in _ATTRIBUTION_WORDS):
            return word
        return ""

    return BARE_URL_RX.sub(repl, text)
TRAILING_URL_RX = re.compile(r"[\s(\[<:-]*(?:(?:https?://|www\.)\S+[\s)\]>.,;]*)+$", re.IGNORECASE)
HANDLE_RX = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{2,30}\b")
JSON_KEY_RX = re.compile(
    r'"?\b(?:headline|summary|category|item_ids|primary_entities|relevance_score|clusters|discarded_item_ids)\b"?\s*:\s*',
    re.IGNORECASE,
)
JSON_JUNK_RX = re.compile(r'\\[nrt"]|[{}\[\]`]|(?<=\s)"\s*,\s*"|^\s*"|"\s*,?\s*$')
SPACE_BEFORE_PUNCT_RX = re.compile(r"\s+([.,;:!?])")
REPEAT_PUNCT_RX = re.compile(r"([.,;:!?])(?:\s*[.,;:])+")
#: Split only where punctuation is followed by space (keeps "2.0"), never after an abbreviation that runs on
#: ('the upcoming U.S. midterm elections' became 'the upcoming U.S.' + 'Midterm elections.').
SENTENCE_RX = re.compile(r"(?<=[.!?])(?<!\bU\.S\.)(?<!\bU\.K\.)(?<!\bU\.N\.)(?<!\bE\.U\.)(?<!\bNo\.)(?<!\bSt\.)"
                         r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<!\bGov\.)(?<!\bSen\.)(?<!\bRep\.)"
                         r"(?<!\bGen\.)(?<!\bJr\.)(?<!\bSr\.)(?<!\bvs\.)(?<!\bLt\.)(?<!\bCol\.)(?<!\bProf\.)\s+")

SMALL_WORDS = frozenset(
    "a an and as at but by for from in into nor of on or over per the to up via vs vs. with".split()
)
CATEGORY_PREFIX_RX = re.compile(
    r"^\s*(?:sports?|entertainment|tech(?:nology)?|news|internet culture|culture|science\s*(?:&|and)\s*ai|"
    r"science|ai|world|business|politics)\s*[:|\-]\s+",
    re.IGNORECASE,
)
GENERIC_HEADLINE_WORDS = frozenset(
    """advances advancements developments development events event news updates update tools tool
    innovations innovation music film films movies global economy economic weather trends trend trending
    industry technology tech science research ai world sports entertainment culture various latest
    highlights roundup recap headlines diplomacy politics business markets market stories story topics
    mixed miscellaneous other others several multiple key major new products product launches
    productivity learning dynamics optimization models""".split()
)


SAFE_URL_RX = re.compile(r"(?:https?://|www\.)[^\s<>\"]*[^\s<>\".,;:!?)\]]", re.IGNORECASE)
JSON_FRAGMENT_RX = re.compile(r'"\s*,\s*"[^"]{0,60}"?|"\s*:\s*"?')
PROPER_WORDS = {
    w.lower(): w
    for w in """Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April June July
    August September October November December""".split()
}


def _json_payload_text(text: str) -> str:
    """If the model leaked a JSON object/array into a text field, pull out the prose value."""
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(data, dict):
        for key in ("summary", "text", "description", "headline"):
            if isinstance(data.get(key), str):
                return data[key]
        vals = [v for v in data.values() if isinstance(v, str)]
        return max(vals, key=len) if vals else ""
    if isinstance(data, list):
        return " ".join(str(v) for v in data if isinstance(v, str))
    return text


def sanitize_summary(text: str, entities: list[str] | None = None) -> str:
    """Strip URLs, @-handle markers and JSON leakage; fix spacing, capitalisation and punctuation.

    ``entities`` restores canonical casing of known names ('packers' -> 'Packers').
    """
    if not text:
        return ""
    t = _json_payload_text(str(text))
    t = MD_LINK_RX.sub(r"\1", t)
    t = SAFE_URL_RX.sub("", t)  # before ASCII folding so trailing sentence punctuation survives
    t = JSON_KEY_RX.sub(" ", t)
    t = JSON_FRAGMENT_RX.sub(" ", t)
    t = normalize_text(t)
    t = TRAILING_URL_RX.sub("", t)
    t = strip_bare_urls(t)
    t = HANDLE_RX.sub(lambda m: m.group(0)[1:], t)  # '@hackernews' -> 'hackernews' keeps the sentence intact
    t = JSON_JUNK_RX.sub(" ", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = WS_RX.sub(" ", t)
    t = SPACE_BEFORE_PUNCT_RX.sub(r"\1", t)
    t = REPEAT_PUNCT_RX.sub(r"\1", t).strip(" ,;:-|\"'")
    if not t:
        return ""
    for low, proper in PROPER_WORDS.items():
        t = re.sub(r"\b" + low + r"\b", proper, t)
    for ent in entities or []:
        ent = ent.strip()
        if len(ent) >= 3 and re.search(r"[A-Z]", ent):
            t = re.sub(r"\b" + re.escape(ent) + r"\b", ent, t, flags=re.IGNORECASE)
    sentences = []
    for raw in SENTENCE_RX.split(t):
        sent = raw.strip(" ,;:-")
        if len(re.sub(r"[^A-Za-z]", "", sent)) < 3:
            continue
        sent = sent[0].upper() + sent[1:]
        if sent[-1] not in ".!?":
            sent += "."
        sentences.append(sent)
    return " ".join(sentences)


def _title_word(word: str, first: bool) -> str:
    core = word.strip("\"'()")
    if not core:
        return word
    # keep acronyms / mixed case / tokens with digits as written: NFL, iPhone, GPT-6, F-Droid
    if re.fullmatch(r"[a-z]{2,4}-\d[\w.]*", core):  # 'gpt-6' -> 'GPT-6', 'f-22' -> 'F-22'
        head, _, tail = core.partition("-")
        return word.replace(core, f"{head.upper()}-{tail}")
    if any(ch.isdigit() for ch in core) or core.isupper() or any(ch.isupper() for ch in core[1:]):
        return word
    if not first and core.lower() in SMALL_WORDS:
        return word.replace(core, core.lower())
    return word.replace(core, core[0].upper() + core[1:])


def sanitize_headline(text: str, max_words: int = 14, stretch_to: int | None = None) -> str:
    """Title Case, <= max_words, no URLs/handles/generic category prefix, no trailing punctuation.

    A title longer than ``max_words`` is cut at its first sentence or last clause break; with no such
    break, a title of at most ``stretch_to`` words is kept whole rather than cut mid-clause."""
    # 'PewDiePie is setting AI free... and OpenAI is furious': an ellipsis joins two clauses
    t = re.sub(r"\s*(?:\.{3}|…)\s+(?=[a-z])", ", ", text or "")
    t = normalize_text(MD_LINK_RX.sub(r"\1", t))
    t = strip_bare_urls(t)
    t = LIVE_BLOG_SUFFIX_RX.sub("", t)
    t = HANDLE_RX.sub("", t)
    # a title that opens with a quotation ('"Your Pay Is Not My Concern": Millionaire ...') keeps its
    # opening quote; JSON leakage would otherwise strip it and leave the closing one alone
    quoted = t.lstrip().startswith('"') and re.search(r'\w[.!?]?"(?=\s|$|[,:;])', t.lstrip()[1:]) is not None
    t = JSON_JUNK_RX.sub(" ", t)
    if quoted:
        t = '"' + t.lstrip()
    t = CATEGORY_PREFIX_RX.sub("", t)
    t = _trim_quotes(WS_RX.sub(" ", t).strip(" .,;:-|")).strip(" .,;:-|")
    words = t.split()
    if len(words) > max_words:
        clause = _sentence_cut(words, max_words) or _clause_cut(words, max_words)
        if clause:
            words = clause
        elif not (stretch_to and len(words) <= stretch_to):  # a few words over: whole, never cut mid-clause
            words = words[:max_words]
            # don't end on a dangling phrase ('... Football in Green'): cut at a late small word
            for k in range(len(words) - 1, max(3, len(words) - 5), -1):
                if words[k].lower().strip(",:;") in SMALL_WORDS:
                    words = words[:k]
                    break
        while words and words[-1].lower().strip(",:;") in DANGLING_WORDS:
            words.pop()
    out = []
    after_colon = True
    for w in words:
        out.append(_title_word(w, after_colon or w[:1] in "\"'("))
        after_colon = w.endswith(":")
    return _close_quotes(" ".join(out).strip(" .,;:-"))


def _trim_quotes(text: str) -> str:
    """Drop an opening or closing quote only when it has no partner ("'We had a threat': Trump..." keeps both)."""
    for q in ("'", '"'):
        if text.startswith(q) and not re.search(r"\w[.!?]?" + q + r"(?=\s|$|[,:;])", text[1:]):
            text = text[1:]
        if text.endswith(q) and not re.search(r"(?:^|\s)" + q + r"\w", text[:-1]):
            text = text[:-1]
    return text


def _close_quotes(text: str) -> str:
    """Restore a closing quote the trimming removed ("... Comments: 'Nazi Bitches" gets its ')."""
    for q in ("'", '"'):
        # an apostrophe before a decade ("the '80s") opens no quotation
        m = re.search(r"(?:^|\s)" + q + r"(?!\d0s\b)\w", text)
        if m and not re.search(r"\w[.!?]?" + q + r"(?=\s|$|[,:;])", text[m.end() - 1:]):
            text += q
    return text


#: Words a headline must not end on ('... Would Warp', '... Shows How iPads Enable' stay whole instead).
DANGLING_WORDS = SMALL_WORDS | frozenset(
    "how why what when where who whom whose which that would could will can may might should must is are was "
    "were be been has have had its their his her our your my this these those amid after before over than "
    "while about against between into onto via he's she's it's they're we're you're i'm that's there's "
    "who's what's he'd she'd they'd".split())


def _sentence_cut(words: list[str], max_words: int) -> list[str] | None:
    """Keep a long title's first full sentence ('Is Bijan Robinson the NFL's best running back?')
    when it fits the limit and has 5+ words, instead of cutting the second one mid-way."""
    for k in range(5, min(len(words), max_words) + 1):
        w = words[k - 1].rstrip("\"'\u2019\u201d")
        if w.endswith(("?", "!")) or (w.endswith(".") and w[:-1].isalpha() and len(w) > 4):
            return words[:k]
    return None


def _clause_cut(words: list[str], max_words: int) -> list[str] | None:
    """Cut a long title at its last clause break (':', ';', ' - ', ',') within the limit, if one leaves 5+ words."""
    for k in range(min(len(words), max_words), 4, -1):
        w = words[k - 1]
        if w.endswith((":", ";", ",")) or (k < len(words) and words[k] in ("-", "|")):
            return [*words[: k - 1], w.rstrip(":;,")]
    return None


#: Verbs and verb forms that make a title a headline rather than a topic label.
HEADLINE_VERBS = frozenset("""
is are was were be been has have had will can could would may might must should says say said
wins win won beats beat defeats tops leads lead loses lose falls fall rises rise drops drop jumps climbs surges
soars plunges slides tumbles gains hits hit cuts cut raises raise sets set signs sign sues sue dies die kills kill
takes take makes make gets get joins join leaves leave quits resigns announces announce confirms confirm denies
deny rejects reject approves approve bans ban blocks block opens open closes close returns return reveals reveal
shows show finds find adds add ends end starts start begins begin strikes strike crashes crash freezes freeze
pauses pause halts halt passes pass fails fail urges urge seeks seek names name picks pick fires fire hires hire
buys buy sells sell acquires acquire expands expand delays delay recalls recall files file charges charge
convicts sentences frees rescues evacuates erupts floods collapses breaks break launches launch unveils unveil
releases release reports report warns warn plans plan faces face calls call arrests arrest accuses accused
expects expect hopes hope wants want needs need gives give keeps keep goes go comes come moves move helps help
claims claim proposes propose backs back slams slam criticizes praises vows vow pledges pledge agrees agree
votes vote elects elect appoints appoint nominates nominate wins clinches advances eliminates trades extends
retires debuts premieres tours introduces introduce updates update fixes fix patches patch bricks orders order
detects detect discovers discover spots spot tests test tries try builds build hosts host holds hold stops stop
even evens ties tie wraps wrap renews renew cancels cancel axes axe drops boosts boost sparks spark triggers
""".split())


def is_label_headline(text: str) -> bool:
    """True for a topic label ('Cornell University Rape Allegations', 'Default Hard Budget Caps'):
    a short title with no verb. Real headlines nearly always say what happened."""
    words = [w.strip(".,:;!?'\"()").lower() for w in (text or "").split()]
    words = [w for w in words if w]
    if not words or len(words) > 6:
        return False
    for k, w in enumerate(words):
        if w.endswith("'s"):
            continue  # possessive: 'Big Tech's ...'
        if w in HEADLINE_VERBS or w.endswith(("ed", "ing")):
            return False
        # a present-tense verb ('Disrupts', 'Calls') sits between subject and object: not first, not last
        if 0 < k < len(words) - 1 and w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
            return False
    return True


def is_generic_headline(text: str) -> bool:
    """True for umbrella titles like 'Entertainment: Music and Film' or 'AI Tools and Innovations'."""
    toks = significant_tokens(CATEGORY_PREFIX_RX.sub("", text or ""))
    if not toks:
        return True
    return all(t in GENERIC_HEADLINE_WORDS for t in toks)


def display_sources(sources: list[str]) -> str:
    names = [SOURCE_DISPLAY.get(s, s) for s in sources]
    if len(names) <= 1:
        return names[0] if names else "one source"
    return ", ".join(names[:-1]) + " and " + names[-1]


# --------------------------------------------------------------------- cleaner
class TrendCleaner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ............................................................ public API
    def clean(self, items: list[RawTrendItem]) -> tuple[list[CleanedTrendItem], dict[str, int]]:
        stats: Counter[str] = Counter()
        survivors: list[tuple[RawTrendItem, str]] = []
        for item in items:
            reason, title = self._evaluate(item)
            if reason:
                stats[reason] += 1
                continue
            survivors.append((item, title))
        merged = self._dedupe(survivors, stats)
        cleaned = self._score(merged)
        stats["kept"] = len(cleaned)
        log.info("cleaner: %d in -> %d kept (%s)", len(items), len(cleaned), dict(stats))
        return cleaned, dict(stats)

    def select_for_llm(self, cleaned: list[CleanedTrendItem]) -> list[CleanedTrendItem]:
        """Top-scored items within the processing budget, with fair floors.

        Every platform gets ``min_items_per_source_for_llm``; inside multi-feed sources every
        publisher feed gets ``min_items_per_feed_for_llm`` and every YouTube channel or Google News
        section gets ``min_items_per_channel_feed_for_llm``, so one prolific source or feed cannot
        crowd out the others. Floors are handed out in rounds (every group's best item, then every
        group's second best, ...) and may use at most ``FLOOR_SHARE`` of the budget, so with many
        feeds each still gets its lead item and the strongest items keep the rest of the budget.
        """
        s = self.settings
        cap = s.max_items_for_llm
        by_group: dict[tuple[SourceName, str], list[CleanedTrendItem]] = defaultdict(list)
        for it in sorted(cleaned, key=lambda x: x.heuristic_score, reverse=True):
            multi = it.source in MULTI_FEED_SOURCES and not it.metadata.get("top_stories")
            feed = str(it.metadata.get("feed") or "") if multi else ""
            by_group[(it.source, feed)].append(it)

        def floor_of(source: SourceName, feed: str) -> int:
            if not feed:
                return s.min_items_per_source_for_llm
            if source is SourceName.NEWS_RSS:
                return s.min_items_per_feed_for_llm
            return s.min_items_per_channel_feed_for_llm

        groups = sorted(by_group.items(), key=lambda kv: kv[1][0].heuristic_score, reverse=True)
        floor_cap = max(1, int(cap * FLOOR_SHARE))
        chosen: dict[int, CleanedTrendItem] = {}
        for r in range(max((floor_of(*key) for key, _ in groups), default=0)):
            for key, lst in groups:
                if len(chosen) >= floor_cap:
                    break
                if r < floor_of(*key) and r < len(lst):
                    chosen[lst[r].item_id] = lst[r]
        for it in sorted(cleaned, key=lambda x: x.heuristic_score, reverse=True):
            if len(chosen) >= cap:
                break
            chosen.setdefault(it.item_id, it)
        return sorted(chosen.values(), key=lambda x: x.heuristic_score, reverse=True)[:cap]

    # ............................................................ stage 1
    def _evaluate(self, item: RawTrendItem) -> tuple[str | None, str]:
        """Return (discard_reason | None, normalized_title)."""
        s = self.settings
        src = item.source
        md = item.metadata

        # --- source-specific engagement thresholds
        if src is SourceName.REDDIT:
            sub = str(md.get("subreddit", "")).lower()
            if sub in LOW_SIGNAL_SUBREDDITS:
                return "reddit_low_signal_subreddit", ""
            if md.get("metrics_verified", False):
                if (item.raw_score or 0) < s.reddit_min_score or (item.comment_count or 0) < s.reddit_min_comments:
                    return "reddit_low_engagement", ""
            elif not s.reddit_allow_unverified_rss:
                # RSS carries no score/comment counts. Items near the top of a subreddit's
                # "top of the day" listing clear the 20-score / 5-comment bar in practice,
                # so they are kept; deeper ranks cannot be verified and are dropped.
                rank = md.get("rank")
                if not isinstance(rank, int) or rank > s.reddit_rss_max_rank:
                    return "reddit_unverified_metrics", ""
        elif src is SourceName.HACKERNEWS:
            if (item.raw_score or 0) < s.hn_min_points:
                return "hn_low_points", ""
        elif src is SourceName.GITHUB:
            if (item.raw_score or 0) < s.github_min_stars_today:
                return "github_low_stars", ""

        raw_title = item.title.strip()

        # --- generic hashtags (check before splitting: '#fallvibes' cannot be camel-split)
        if src in (SourceName.TIKTOK, SourceName.X_TRENDS24, SourceName.BLUESKY):
            bare = normalize_text(raw_title).lstrip("#").lower().replace(" ", "")
            if bare in GENERIC_HASHTAGS or GENERIC_HASHTAG_RX.fullmatch(bare):
                return "generic_hashtag", ""

        title = normalize_text(raw_title)
        if src in (SourceName.TIKTOK, SourceName.X_TRENDS24, SourceName.BLUESKY) and title.startswith("#"):
            title = split_hashtag(title)
        title = CLICKBAIT_STRIP.sub(" ", title)
        title = WS_RX.sub(" ", title).strip(" -|:;,")

        # --- structural checks
        alnum = re.sub(r"[^A-Za-z0-9]", "", title)
        if len(alnum) < max(2, s.min_title_chars - 1) or alnum.isdigit():
            return "too_short_or_non_ascii", ""
        if len(title) > 350:
            title = title[:347].rsplit(" ", 1)[0] + "..."

        # --- content noise
        if src in ANECDOTE_SOURCES and ANECDOTE_RX.search(title):
            return "personal_anecdote", ""
        if src in SOCIAL_SOURCES and MEME_PHOTO_RX.search(title):
            return "meme_or_photo", ""
        if src in SOCIAL_SOURCES and PET_RX.search(title):
            return "pet_post", ""
        if src not in (SourceName.ARXIV, SourceName.GITHUB) and BOX_SCORE_RX.search(title):
            return "box_score_or_betting", ""
        if PROMO_RX.search(f"{title} {(item.description or '')[:300]}"):
            return "promotional", ""
        if src is SourceName.YOUTUBE and VIDEO_CLIP_RX.search(raw_title):
            return "video_clip", ""
        if src in SOCIAL_SOURCES and len(significant_tokens(title)) == 0 and not re.search(r"[A-Z]", title):
            return "no_signal_tokens", ""
        return None, title

    # ............................................................ stage 2
    def _dedupe(
        self, survivors: list[tuple[RawTrendItem, str]], stats: Counter[str]
    ) -> list[tuple[RawTrendItem, str, int, list[str]]]:
        buckets: dict[str, list[tuple[RawTrendItem, str]]] = {}
        for item, title in survivors:
            buckets.setdefault(dedupe_key(title), []).append((item, title))

        groups: list[tuple[str, list[tuple[RawTrendItem, str]]]] = list(buckets.items())
        # near-duplicate pass for longer titles (short names like 'Packers' stay exact-match only)
        merged_into: dict[int, int] = {}
        for i in range(len(groups)):
            if i in merged_into or len(groups[i][0]) < 20:
                continue
            for j in range(i + 1, len(groups)):
                if j in merged_into or len(groups[j][0]) < 20:
                    continue
                a, b = groups[i][0], groups[j][0]
                if abs(len(a) - len(b)) > 0.3 * max(len(a), len(b)):
                    continue
                matcher = SequenceMatcher(None, a, b)  # cheap upper bounds first: O(n^2) pairs on big runs
                if matcher.real_quick_ratio() >= 0.9 and matcher.quick_ratio() >= 0.9 and matcher.ratio() >= 0.9:
                    merged_into[j] = i
        final: dict[int, list[tuple[RawTrendItem, str]]] = {}
        for idx, (_, members) in enumerate(groups):
            root = idx
            while root in merged_into:
                root = merged_into[root]
            final.setdefault(root, []).extend(members)

        out: list[tuple[RawTrendItem, str, int, list[str]]] = []
        for members in final.values():
            members.sort(key=lambda m: (m[0].raw_score or 0.0), reverse=True)
            best_item, best_title = members[0]
            urls: list[str] = []
            for m, _ in members:
                if m.url and m.url not in urls:
                    urls.append(m.url)
            if len(members) > 1:
                stats["duplicates_merged"] += len(members) - 1
                # a same-title item seen on several sources is a strong signal: record them
                srcs = sorted({m.source.value for m, _ in members})
                best_item = best_item.model_copy(
                    update={"metadata": {**best_item.metadata, "duplicate_sources": srcs}}
                )
            best_item = best_item.model_copy(update={"metadata": {**best_item.metadata,
                "observations": [m.model_dump(mode="json") for m, _ in members]}})
            out.append((best_item, best_title, len(members), urls))
        return out

    # ............................................................ stage 3
    def _score(self, merged: list[tuple[RawTrendItem, str, int, list[str]]]) -> list[CleanedTrendItem]:
        # per-source percentile rank of raw_score (robust to wildly different scales)
        by_source: dict[SourceName, list[float]] = defaultdict(list)
        for item, *_ in merged:
            by_source[item.source].append(item.raw_score or 0.0)
        sorted_scores = {k: sorted(v) for k, v in by_source.items()}

        def percentile(src: SourceName, value: float) -> float:
            arr = sorted_scores[src]
            if len(arr) <= 1:
                return 0.75
            below = sum(1 for x in arr if x < value)
            equal = sum(1 for x in arr if x == value)
            return (below + 0.5 * equal) / len(arr)

        # token -> sources, for the cross-source corroboration bonus
        token_sources: dict[str, set[SourceName]] = defaultdict(set)
        token_freq: Counter[str] = Counter()
        item_tokens: list[set[str]] = []
        for item, title, *_ in merged:
            toks = significant_tokens(title)
            item_tokens.append(toks)
            for t in toks:
                token_sources[t].update(SourceName(o["source"]) for o in item.metadata["observations"])
                token_freq[t] += 1
        n_items = max(1, len(merged))
        distinctive_cap = max(3, int(0.08 * n_items))

        cleaned: list[CleanedTrendItem] = []
        for idx, ((item, title, dup_count, urls), toks) in enumerate(zip(merged, item_tokens), start=1):
            pct = percentile(item.source, item.raw_score or 0.0)
            weight = SOURCE_WEIGHT.get(item.source, 0.6)
            other_sources: set[SourceName] = set()
            for t in toks:
                if token_freq[t] <= distinctive_cap:
                    other_sources |= token_sources[t] - {item.source}
            cross_bonus = min(3, len(other_sources)) * 0.10
            source_count = len({o["source"] for o in item.metadata["observations"]})
            dup_bonus = min(0.15, 0.05 * (source_count - 1))
            engagement = 0.0
            if item.comment_count:
                engagement = min(0.10, math.log10(1 + item.comment_count) / 30)
            score = 0.20 + 0.45 * pct * weight + cross_bonus + dup_bonus + engagement
            score = max(0.0, min(1.0, score))
            inferred = infer_category(f"{title} {item.description or ''}")
            cleaned.append(
                CleanedTrendItem(
                    **item.model_dump(exclude={"metadata"}),
                    metadata={k: v for k, v in item.metadata.items() if k != "observations"},
                    observations=item.metadata["observations"],
                    item_id=idx,
                    normalized_title=title,
                    heuristic_score=round(score, 4),
                    duplicate_count=dup_count,
                    merged_urls=urls,
                    inferred_category=inferred,
                )
            )
        return cleaned
