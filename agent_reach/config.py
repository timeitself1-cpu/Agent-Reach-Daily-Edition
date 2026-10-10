"""Central configuration for Agent Reach.

Every value can be overridden with an environment variable prefixed with
``AGENT_REACH_`` (e.g. ``AGENT_REACH_OLLAMA_HOST=http://10.0.0.5:11434``) or via a
``.env`` file in the working directory. List values accept JSON
(e.g. ``AGENT_REACH_REDDIT_SUBREDDITS='["popular","nfl"]'``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: "Category|CHANNEL_ID|Name": channels whose recent uploads form the YouTube source. YouTube retired its
#: public Trending page in 2025, so "trending" here means the most-watched recent uploads (views per hour)
#: of these news, technology, science, sports and entertainment channels. Every channel posts most days.
DEFAULT_YOUTUBE_CHANNELS: tuple[str, ...] = (
    "News|UC16niRr50-MSBwiO3YDb3RA|BBC News",
    "News|UChqUTb7kYRX8-EiaN3XFrSQ|Reuters",
    "News|UC52X5wxOL_s5yw0dQk7NtgA|Associated Press",
    "News|UCeY0bbntWzzVIaj2z3QigXg|NBC News",
    "News|UCBi2mrWuNuyYy4gbM6fU18Q|ABC News",
    "News|UC8p1vwvWtl6T73JiExfWs1g|CBS News",
    "News|UC6ZFN9Tx6xh-skXCuRHCDpQ|PBS NewsHour",
    "News|UCNye-wNBqNL5ZzHSJj3l8Bg|Al Jazeera English",
    "News|UCoMdktPbSTixAyNGwb-UYkQ|Sky News",
    "News|UCrp_UI8XtuYfpiqluWLD7Lw|CNBC Television",
    "Tech|UCrM7B7SL_g1edFOnmj-SDKg|Bloomberg Technology",
    "Tech|UCOmcA3f_RrH6b9NmcNa4tdg|CNET",
    "Tech|UCddiUEpeqJcYeBxX1IVBKvQ|The Verge",
    "Tech|UCXuqSBlHAE6Xw-yeJA0Tunw|Linus Tech Tips",
    "Tech|UCBJycsmduvYEL83R_U4JriQ|Marques Brownlee",
    "Tech|UCsBjURrPoezykLs9EqgamOA|Fireship",
    "Science & AI|UCLA_DiR1FfKNvjuUpBHmylQ|NASA",
    "Sports|UCiWLfSweyRNmLpgEHekhoAg|ESPN",
    "Sports|UCDVYQ4Zhbm3S2dlz7P1GBDg|NFL",
    "Sports|UCWJ2lWNubArHWmf3FIHbfcQ|NBA",
    "Entertainment|UCKy1dAqELo0zrOtPkf0eTMw|IGN",
    "Entertainment|UCdtXPiqI2cLorKaPrfpKc4g|Entertainment Tonight",
)

#: Google News sections the daily app reads besides the top stories: "Category|TOPIC|Name" for a Google
#: News topic, or "Category|search words|Name" for a search limited to the last day.
DEFAULT_GOOGLE_NEWS_SECTIONS: tuple[str, ...] = (
    "News|WORLD|Google News - World",
    "News|NATION|Google News - U.S.",
    "News|BUSINESS|Google News - Business",
    "News|HEALTH|Google News - Health",
    "Tech|TECHNOLOGY|Google News - Technology",
    "Science & AI|SCIENCE|Google News - Science",
    "Science & AI|artificial intelligence|Google News - AI",
    "Sports|SPORTS|Google News - Sports",
    "Entertainment|ENTERTAINMENT|Google News - Entertainment",
    "Internet Culture|tiktok OR viral OR meme|Google News - Viral & TikTok",
    "News|site:apnews.com|AP News (via Google News)",
    "News|site:reuters.com|Reuters (via Google News)",
    "Science & AI|space OR NASA OR astronomy|Google News - Space",
    "Entertainment|video games|Google News - Games",
)


#: Words a Title Case headline keeps capitalised when it is put in sentence case (``daily/headlines.py``); the
#: story's own key names and any word its reports write capitalised mid-sentence are kept as well.
DEFAULT_HEADLINE_KEEP_WORDS = (
    "AI", "AP", "BBC", "CEO", "CIA", "CNN", "CPU", "DOJ", "EU", "FBI", "FDA", "FCC", "GDP", "GPU", "GOP", "ICE",
    "IMF", "IRS", "NASA", "NATO", "NBA", "NFL", "NHL", "MLB", "NYC", "OpenAI", "SEC", "UK", "UN", "US", "USA",
    "WHO", "iPhone", "iPad", "macOS", "iOS", "YouTube", "GitHub", "Nobel", "Pentagon", "Congress", "Senate",
    "Kremlin", "God", "Covid", "COVID-19", "Wi-Fi", "I",
)
#: Openers a publisher adds to draw a click (matched case-insensitively at the start of a headline, with the
#: punctuation and 'as'/'but'/'and' after them); removed only when at least four words remain.
DEFAULT_HEADLINE_BAIT_OPENERS = (
    r"we might be cooked", r"you (?:won't|will not|wont) (?:even )?believe", r"you'll (?:never|not) believe",
    r"(?:wow|omg|yikes|whoa|woah|oof|yowza)", r"this changes everything", r"what happens next",
    r"(?:you )?(?:need|have) to see this", r"here's why",
)

#: See ``Settings.leak_patterns``. 'Exceptions that require judgment' is the micro1 case of October 10, 2026.
DEFAULT_LEAK_PATTERNS = (
    r"exceptions? that require judg(?:e)?ment",
    r"as an ai(?: language model)?\b",
    r"here(?:'s| is| are) (?:a |the |your )?(?:short |brief |concise |one-sentence )?summary",
    r"i (?:cannot|can't|can not|am unable to|'m unable to)\b",
    r"(?:sure|certainly|okay|ok)[,!.]? (?:here|i)\b",
    # a lead-in that ends in a colon and tells the reader (or the model) what to do: 'Note: ...', 'Summarize the following:'
    r"(?:note|please|ensure|make sure|remember|summari[sz]e|write|provide|use|do not|don't|avoid|include|"
    r"keep|respond|output|return|follow|consider|focus)\b[^.!?]*:\s*$",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_REACH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ LLM
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_s: float = 240.0
    ollama_num_ctx: int = 8192
    ollama_temperature: float = 0.1
    ollama_keep_alive: str = "10m"
    llm_batch_size: int = Field(default=20, ge=5, le=25)  # >25 makes llama3.1:8b emit malformed JSON
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # ------------------------------------------------------ embeddings / density
    # Google DeepMind EmbeddingGemma 2, text-only size (`ollama pull embeddinggemma-2:270m`, ~380 MB, 768 dims).
    # Each exact model tag (and Ollama digest) is its own embedding space: vectors are cached per model.
    embed_model: str = "embeddinggemma-2:270m"
    # tried in order when the model above is missing or fails; then lexical grouping (pipeline/embeddings.py)
    embed_fallback_models: list[str] = Field(default_factory=lambda: ["nomic-embed-text"])
    # "auto" = the model's documented clustering prompt ('task: clustering | query: ' for EmbeddingGemma,
    # 'clustering: ' for nomic-embed-text, none otherwise); any other value is used as given ("" = none)
    embed_prefix: str = "auto"
    embed_dims: int = Field(default=0, ge=0, le=8192)  # 0 = native size; >0 = Matryoshka truncation + re-normalise
    embed_batch_size: int = Field(default=64, ge=1, le=512)
    embed_cache_path: Path | None = None  # None = next to db_path ('<db>.embeddings.sqlite'); '' = no cache
    # "identity" = embedding neighbours + the event-identity gate + cohesive clusters (pipeline/event_identity.py);
    # "density" = the rc11 grouping (HDBSCAN + centroid gate), kept for the benchmark comparison
    cluster_method: str = "identity"
    identity_neighbors: int = Field(default=12, ge=1, le=100)  # candidate neighbours per report
    # a candidate pair needs at least this cosine; it is never enough on its own (the identity gate decides)
    identity_candidate_cosine: float = Field(default=0.45, ge=-1.0, le=1.0)
    # ...and with at least this cosine plus a shared specific word (never a name alone) a pair is accepted
    # without further lexical evidence. Calibrate per model with `python -m tests.embedding_benchmark`.
    identity_strong_cosine: float = Field(default=0.80, ge=-1.0, le=1.0)
    semantic_log_dir: Path | None = None  # developer artifact: every candidate pair and the gate's decision
    hdbscan_min_cluster_size: int = Field(default=2, ge=2, le=20)
    hdbscan_min_samples: int = Field(default=1, ge=1, le=20)
    hdbscan_selection: str = "leaf"  # "leaf" = many small tight clusters (entity isolation); "eom" = larger
    density_member_min_cosine: float = Field(default=0.62, ge=0.0, le=1.0)  # member-to-centroid gate (0.55 was too loose)
    density_fallback_cosine: float = Field(default=0.78, ge=0.0, le=1.0)  # threshold mode when sklearn missing
    outlier_policy: str = "drop"  # "drop" = density outliers are noise; "keep_top" = keep outliers >= singleton_keep_score

    # ------------------------------------------------------------ enrichment
    enrich_enabled: bool = True
    enrich_timeout_s: float = Field(default=6.0, ge=1.0, le=30.0)
    enrich_concurrency: int = Field(default=8, ge=1, le=32)
    enrich_max_bytes: int = Field(default=1_500_000, ge=50_000)
    enrich_max_chars: int = Field(default=600, ge=100, le=4000)  # context kept per item (title+meta+paragraphs)

    # ------------------------------------------------- pre-publish quality gates (daily/gates.py)
    # Regular expressions, matched case-insensitively at the START of a summary's first sentence: text that is
    # the model's instruction or remark about its task, not a summary (October 10: the micro1 story opened with
    # 'Exceptions that require judgment ...'). Override with AGENT_REACH_LEAK_PATTERNS='["...", "..."]'.
    # Developer switch for the offline test world, whose synthetic one-line summaries would all be 'thin'
    # (tests/conftest.py turns it off; the app never does).
    gates_enabled: bool = True
    # Self-check of the gates against tests/golden before each publication (daily/golden.py); a failure keeps the
    # previous edition. Developer switch for tests that deliberately bend a gate setting.
    golden_check_enabled: bool = True
    leak_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_LEAK_PATTERNS))
    min_section_stories: int = Field(default=3, ge=1)
    headline_keep_words: list[str] = Field(default_factory=lambda: list(DEFAULT_HEADLINE_KEEP_WORDS))
    headline_bait_openers: list[str] = Field(default_factory=lambda: list(DEFAULT_HEADLINE_BAIT_OPENERS))
    gate_min_summary_words: int = Field(default=15, ge=1, le=200)
    gate_max_headline_overlap: float = Field(default=0.60, ge=0.0, le=1.0)  # share of the summary's content words

    # -------------------------------------------------------------- storage
    db_path: Path = Path("agent_reach.db")
    retention_days: int = Field(default=30, ge=1)

    # ----------------------------------------------------------------- HTTP
    http_timeout_s: float = 10.0
    http_max_retries: int = Field(default=3, ge=0, le=8)
    http_backoff_base_s: float = 1.0
    http_backoff_max_s: float = 16.0
    http_max_concurrency: int = Field(default=8, ge=1, le=32)
    contact_email: str = "agent-reach@example.invalid"  # Wikimedia/Reddit ask for a contact in the UA

    # -------------------------------------------------------------- sources
    geo: str = "US"
    trends24_region: str = "united-states"
    wikipedia_project: str = "en.wikipedia"
    # also read Wikipedia's curated "In the news" list (featured-content feed) with the most-read articles
    wikipedia_in_the_news: bool = False
    # Mastodon servers whose trending news links are read (public API, no account)
    mastodon_instances: list[str] = Field(default_factory=lambda: ["mastodon.social"])
    reddit_subreddits: list[str] = Field(
        default_factory=lambda: ["popular", "news", "worldnews", "technology", "science", "sports", "movies"]
    )
    arxiv_categories: list[str] = Field(default_factory=lambda: ["cs.AI", "cs.LG", "cs.CL", "cs.CV"])
    # "Category|URL" or "Category|URL|Publisher name" entries for the general-news RSS source (news_rss).
    # Category must be a CategoryEnum value.
    news_rss_feeds: list[str] = Field(
        default_factory=lambda: [
            "News|https://feeds.bbci.co.uk/news/rss.xml",
            "News|https://feeds.npr.org/1001/rss.xml",
            "News|https://www.theguardian.com/us-news/rss",
            "Sports|https://www.espn.com/espn/rss/news",
            "Entertainment|https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
            "Science & AI|https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        ]
    )
    news_rss_items_per_feed: int = Field(default=10, ge=1, le=50)
    # news_rss may contribute items_per_feed x feeds, up to this total (a per-feed allowance, not one
    # shared 40-item pool), so adding publishers does not starve the existing ones.
    news_rss_max_total_items: int = Field(default=300, ge=10, le=2000)
    max_items_per_source: int = Field(default=40, ge=5, le=200)
    youtube_channels: list[str] = Field(default_factory=lambda: list(DEFAULT_YOUTUBE_CHANNELS))
    youtube_items_per_channel: int = Field(default=4, ge=1, le=15)  # most-watched recent uploads per channel
    youtube_max_age_hours: float = Field(default=72.0, gt=0.0, le=720.0)  # older uploads are not today's trend
    youtube_max_total_items: int = Field(default=120, ge=5, le=1000)
    # extra Google News sections (see DEFAULT_GOOGLE_NEWS_SECTIONS); empty = top stories only
    google_news_sections: list[str] = Field(default_factory=list)
    google_news_items_per_section: int = Field(default=20, ge=1, le=100)
    # Turning a news.google.com link into the publisher's address (ingestion/google_urls.py): bounded on every side
    google_news_resolve_timeout_s: float = Field(default=10.0, ge=1.0, le=60.0)  # per attempt
    google_news_resolve_retries: int = Field(default=2, ge=0, le=5)  # extra attempts after a transient failure
    google_news_resolve_concurrency: int = Field(default=4, ge=1, le=16)
    google_news_resolve_budget_s: float = Field(default=90.0, ge=5.0, le=600.0)  # whole run; the rest stay unresolved
    enabled_sources: list[str] = Field(
        default_factory=lambda: [
            "x_trends24",
            "reddit",
            "tiktok",
            "google_trends",
            "google_news",
            "wikipedia",
            "arxiv",
            "hackernews",
            "github",
            "producthunt",
        ]
    )

    # ------------------------------------------------------ noise thresholds
    reddit_min_score: int = 20
    reddit_min_comments: int = 5
    reddit_allow_unverified_rss: bool = False  # keep ALL RSS items regardless of rank
    reddit_rss_max_rank: int = Field(default=10, ge=0, le=100)  # RSS "top of day" ranks kept without metrics
    reddit_timeout_s: float = 5.0  # per-request timeout
    reddit_request_spacing_s: float = Field(default=2.0, ge=0.0, le=10.0)  # min gap between ANY two Reddit requests
    reddit_max_retries: int = Field(default=2, ge=0, le=5)  # backoff retries on 403/429/5xx/timeouts
    reddit_budget_s: float = Field(default=30.0, ge=5.0)  # stop starting new subreddits after this long
    tiktok_timeout_s: float = 5.0
    tiktok_request_spacing_s: float = Field(default=2.0, ge=0.0, le=10.0)
    tiktok_max_retries: int = Field(default=2, ge=0, le=5)
    social_timeout_s: float = Field(default=8.0, ge=1.0, le=30.0)  # Mastodon and Bluesky public APIs
    hn_min_points: int = 10
    github_min_stars_today: int = 20
    min_title_chars: int = 3
    max_items_for_llm: int = Field(default=150, ge=10, le=600)
    min_items_per_source_for_llm: int = Field(default=6, ge=0)
    # per-publisher-feed floor inside news_rss, so one prolific feed cannot crowd out the others
    min_items_per_feed_for_llm: int = Field(default=3, ge=0)
    # the same floor for each YouTube channel and each Google News section
    min_items_per_channel_feed_for_llm: int = Field(default=1, ge=0)

    # ----------------------------------------------------------- clustering
    min_cluster_items: int = Field(default=2, ge=1)
    singleton_keep_score: float = Field(default=0.80, ge=0.0, le=1.0)
    singleton_keep_relevance: int = Field(default=7, ge=1, le=10)
    min_cluster_relevance: int = Field(default=4, ge=1, le=10)  # LLM relevance below this is dropped

    # -------------------------------------------------------------- scoring
    velocity_max_coverage_change: float = Field(default=0.25, ge=0.0, le=1.0)
    event_max_age_hours: float = Field(default=72.0, gt=0.0)
    enrich_max_redirects: int = Field(default=5, ge=0, le=10)
    velocity_windows_hours: list[float] = Field(default_factory=lambda: [1.0, 6.0, 24.0])
    velocity_window_weights: list[float] = Field(default_factory=lambda: [0.5, 0.3, 0.2])
    # A reference run for window w must have started within w * (1 +/- tolerance) of now.
    velocity_window_tolerance: float = Field(default=0.5, gt=0.0, lt=1.0)
    rank_relevance_weight: float = Field(default=0.6, ge=0.0, le=1.0)

    # --------------------------------------------------------------- report
    report_top_n: int = Field(default=15, ge=1, le=100)
    report_width: int = Field(default=100, ge=70, le=200)

    @field_validator("velocity_window_weights")
    @classmethod
    def _weights_positive(cls, v: list[float]) -> list[float]:
        if any(w < 0 for w in v):
            raise ValueError("velocity_window_weights must be non-negative")
        return v

    @field_validator("news_rss_feeds")
    @classmethod
    def _feeds(cls, v: list[str]) -> list[str]:
        from agent_reach.models import CategoryEnum

        for entry in v:
            category, sep, rest = entry.partition("|")
            url = rest.split("|", 1)[0]
            if not sep or category.strip() not in CategoryEnum.values() or not url.strip().startswith(("http://", "https://")):
                raise ValueError(f"news_rss_feeds entry must be 'Category|http(s)://url[|Name]' with a valid category: {entry!r}")
        return v

    @field_validator("youtube_channels")
    @classmethod
    def _channels(cls, v: list[str]) -> list[str]:
        import re

        from agent_reach.models import CategoryEnum

        for entry in v:
            category, _, rest = entry.partition("|")
            channel = rest.split("|", 1)[0].strip()
            if category.strip() not in CategoryEnum.values() or not re.fullmatch(r"UC[\w-]{22}", channel):
                raise ValueError(f"youtube_channels entry must be 'Category|UC<22 characters>[|Name]': {entry!r}")
        return v

    @field_validator("google_news_sections")
    @classmethod
    def _sections(cls, v: list[str]) -> list[str]:
        from agent_reach.models import CategoryEnum

        for entry in v:
            category, sep, rest = entry.partition("|")
            if not sep or category.strip() not in CategoryEnum.values() or not rest.split("|", 1)[0].strip():
                raise ValueError(f"google_news_sections entry must be 'Category|TOPIC or search words[|Name]': {entry!r}")
        return v

    @field_validator("mastodon_instances")
    @classmethod
    def _instances(cls, v: list[str]) -> list[str]:
        import re

        out = []
        for host in v:
            host = host.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
            if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
                raise ValueError(f"mastodon_instances entries must be host names like mastodon.social: {host!r}")
            out.append(host)
        return out

    @field_validator("hdbscan_selection")
    @classmethod
    def _selection(cls, v: str) -> str:
        if v not in ("leaf", "eom"):
            raise ValueError("hdbscan_selection must be 'leaf' or 'eom'")
        return v

    @field_validator("cluster_method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ("identity", "density"):
            raise ValueError("cluster_method must be 'identity' or 'density'")
        return v

    @field_validator("outlier_policy")
    @classmethod
    def _outliers(cls, v: str) -> str:
        if v not in ("drop", "keep_top"):
            raise ValueError("outlier_policy must be 'drop' or 'keep_top'")
        return v

    @field_validator("ollama_host")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
