"""Shared fixtures: fake LLM + fake embeddings (no API key / network) and
isolated tmp storage + tmp Qdrant for every test."""

import base64
import io
import math

import pytest
from PIL import Image

from app.memory import MemoryIndex
from app.schemas import (
    AskAnswer,
    AudienceFit,
    CampaignReport,
    CampaignReportV3,
    Citation,
    Critique,
    CritiqueDraft,
    DigestModel,
    HookAnalysis,
    JudgedScores,
    MarketMapModel,
    NotableCampaign,
    PaletteColor,
    PlayerProfileText,
    StrategyAnalysis,
    TrendDraft,
    TrendLine,
    TriageBatch,
    TriageDecision,
    Usage,
    VisualAnalysis,
    Weakness,
)
from app.storage import LocalJsonStore

FIXTURE_CORE = CampaignReport(
    campaign_idea="A FOMO play built on a 24-hour-only offer.",
    how_it_was_run="Story-format 9:16 suggests Instagram; timed to results week (inference).",
    hook='"Your seniors already know this" — self-selection callout.',
    emotional_trigger="Insecurity: the fear of falling behind peers.",
    visual_notes="Lo-fi screenshot aesthetic signals authenticity; palette does no special work here.",
    why_it_worked="Because final-years saw a peer-shaped warning during placement season, urgency converted.",
    takeaway_for_us="Run a placement-season countdown for final-year students on WhatsApp.",
    seen_before="First of its kind in our memory.",
)

FIXTURE_STRATEGY = StrategyAnalysis(
    primary_play="FOMO / Scarcity",
    secondary_play="Social proof",
    campaign_idea="Peers-know-something-you-don't during placement season.",
    channel_inference="9:16 with burned-in captions suggests Reels (inference).",
    timing_logic="Timed to campus placement season.",
    targeting="Final-year students — 'placement', campus vocabulary.",
    cta_structure="Hard CTA with deadline; fits bottom-of-funnel.",
)

FIXTURE_HOOK = HookAnalysis(
    hook_quote="Your seniors already know this",
    mechanics=["self-selection callout", "curiosity gap"],
    stakes="Miss it and stay behind your batch.",
    dominant_emotion="insecurity",
    trigger_element="'already know' implies you are late",
    credibility_devices=["screenshot receipts"],
    copy_structure="Line 1 forces line 2; short mobile-paced lines; second-person voice.",
)

FIXTURE_VISUAL = VisualAnalysis(
    production_signal="Raw screenshot aesthetic — authenticity play, dodges ad-blindness.",
    layout_hierarchy="Big number is the first fixation point; low text density.",
    format_read="9:16 built for Stories/Reels with caption-safe zones respected.",
    palette_interpretation="High-contrast yellow on dark — attention contrast against app chrome.",
    notes="Nothing else notable.",
)

FIXTURE_TREND = TrendDraft(
    verdict="rising",
    confidence="medium",
    reasoning="Memory shows repeat sightings and the market signal reports growing adoption.",
    memory_frequency="Seen 2 times in the last 30 days, 1 before that.",
    market_signal="Multiple brands running the play this month; discussion growing.",
)

FIXTURE_AUDIENCE = AudienceFit(
    bucket_id="final-years",
    bucket_name="Final-year students facing placements",
    angle="Your batchmates' offer letters are the new FOMO — show the skill gap closing in 30 days.",
    fit_reasoning="Placement pressure and peer comparison map directly onto the insecurity trigger.",
    content_suggestion="9:16 Reel with screenshot-style receipts, WhatsApp community CTA; rising trend so ship fast.",
    secondary_bucket_id=None,
)

FIXTURE_CITATIONS = [Citation(title="Marketing Dive", url="https://example.com/a")]

FIXTURE_CRITIQUE = CritiqueDraft(
    critique=Critique(
        weaknesses=[
            Weakness(
                issue="The offer is never stated — the creative sells urgency with nothing to be urgent about.",
                severity="high",
                evidence="No price, deadline date, or deliverable appears anywhere in the frame.",
                mitigation="Put the actual deadline and what they get on the first card.",
            ),
            Weakness(
                issue="Peer-shaming hook risks alienating the students who most need the product.",
                severity="medium",
                evidence="'Your seniors already know this' positions the reader as behind.",
                mitigation="Reframe to the gap being closable rather than already lost.",
            ),
        ],
        why_it_might_not_work=(
            "Placement-season posts are dense; the engagement may be peers commiserating "
            "rather than buyers converting."
        ),
        risk_if_we_copy_it="We would be the tenth brand running placement FOMO that week.",
        brand_safety_flag="Anxiety-led messaging to a stressed student audience — reputationally live.",
        survivorship_check="We only see this because it circulated; identical posts that flopped were never sent to us.",
        what_we_could_not_verify="Spend, reach, conversion and whether the post caused any enrolment at all.",
        confidence_in_positive_read="low",
    ),
    scores=JudgedScores(
        craft=62,
        originality=38,
        hook_strength=71,
        brand_fit=55,
        replicability=80,
        evidence_strength=30,
        scoring_note="Originality is low — this is the standard version of the play, and no results data is visible.",
    ),
)

FIXTURE_TRIAGE = TriageBatch(
    decisions=[
        TriageDecision(index=0, notable=True, reason="Named brand running a nameable play."),
        TriageDecision(index=1, notable=False, reason="Generic listicle, no creative signal."),
    ]
)

FIXTURE_DIGEST = DigestModel(
    headline="Self-selection callouts are surging with final-years.",
    week_summary="Two FOMO-driven campaigns landed this week; both leaned on peer-comparison hooks.",
    rising=[
        TrendLine(
            pattern="FOMO / Scarcity",
            evidence="Seen twice this week with rising verdicts.",
            recommended_bucket="Final-year students facing placements",
            suggested_move="9:16 Reel with countdown + WhatsApp CTA.",
        )
    ],
    watch=[],
    notable_campaigns=[NotableCampaign(title="Placement-week reel", why_notable="Textbook peer-pressure hook.", reference="seed-1")],
)

FIXTURE_MARKET_MAP = MarketMapModel(
    profiles=[
        PlayerProfileText(
            player_id="blinkit",
            profile="Rides live moments with quick-turnaround topical creatives.",
            tone="Cheeky, hyper-timely.",
            visual_identity="Flat yellow, bold type, app-screenshot energy.",
            counter_move="Own the 'career moment' the way they own the cricket moment.",
        )
    ]
)

FIXTURE_ASK = AskAnswer(
    answer="Self-selection callouts on FOMO plays are working; see report 20260615-cccc.",
    sources=["20260615-cccc"],
    confidence="medium",
)

_FIXTURES = {
    StrategyAnalysis: FIXTURE_STRATEGY,
    HookAnalysis: FIXTURE_HOOK,
    VisualAnalysis: FIXTURE_VISUAL,
    CampaignReport: FIXTURE_CORE,
    TrendDraft: FIXTURE_TREND,
    AudienceFit: FIXTURE_AUDIENCE,
    CritiqueDraft: FIXTURE_CRITIQUE,
    TriageBatch: FIXTURE_TRIAGE,
    DigestModel: FIXTURE_DIGEST,
    MarketMapModel: FIXTURE_MARKET_MAP,
    AskAnswer: FIXTURE_ASK,
}


def make_v1_report() -> CampaignReportV3:
    return CampaignReportV3(
        core=FIXTURE_CORE,
        strategy=FIXTURE_STRATEGY,
        hook_copy=FIXTURE_HOOK,
        visual=FIXTURE_VISUAL,
        palette=[PaletteColor(hex="#ffcc00", coverage_pct=61.0)],
    )


class FakeLLM:
    """Captures every structured call; returns schema-matched fixtures."""

    def __init__(self):
        self.nodes: list[str] = []
        self.messages: dict[str, list] = {}
        self.market_topics: list[str] = []

    async def __call__(self, schema, messages, *, node, model="fake-flash", temperature=0.4):
        self.nodes.append(node)
        self.messages[node] = messages
        return _FIXTURES[schema], Usage(model=model, node=node, input_tokens=100, output_tokens=50, total_tokens=150)

    async def market_signal(self, topic: str):
        self.market_topics.append(topic)
        return (
            "Search summary: several brands adopted this play recently; volume growing.",
            list(FIXTURE_CITATIONS),
            Usage(model="fake-flash", node="trend_search", input_tokens=80, output_tokens=40, total_tokens=120),
        )


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("app.graph.call_structured", fake)
    monkeypatch.setattr("app.graph.market_signal", fake.market_signal)
    monkeypatch.setattr("app.radar.triage.call_structured", fake)
    monkeypatch.setattr("app.radar.digest.call_structured", fake)
    monkeypatch.setattr("app.radar.market_map.call_structured", fake)
    monkeypatch.setattr("app.ask.call_structured", fake)
    return fake


@pytest.fixture(autouse=True)
def tmp_radar(monkeypatch, tmp_path):
    """Route every radar artifact (alerts, seen urls, stats, digests, map) into tmp."""
    root = tmp_path / "radar"
    monkeypatch.setattr("app.radar.alerts.ALERTS_PATH", root / "alerts.json")
    monkeypatch.setattr("app.radar.scan.SEEN_PATH", root / "seen_urls.json")
    monkeypatch.setattr("app.radar.scan.STATS_PATH", root / "scan_stats.json")
    monkeypatch.setattr("app.radar.digest.DIGESTS_DIR", root / "digests")
    monkeypatch.setattr("app.radar.market_map.MARKET_MAP_PATH", root / "market_map.json")
    monkeypatch.setattr("app.lifecycle.TRENDS_PATH", tmp_path / "trends.json")

    async def _no_crawl(url):  # no real browser in tests; specific tests override
        return None

    monkeypatch.setattr("app.radar.crawler.crawl_page", _no_crawl)
    return root


def fake_vec(text: str, dim: int = 768) -> list[float]:
    """Deterministic trigram embedding — real text overlap => real cosine similarity."""
    v = [0.0] * dim
    t = " ".join(text.lower().split())
    for i in range(len(t) - 2):
        v[hash(t[i : i + 3]) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [fake_vec(t) for t in texts]


@pytest.fixture(autouse=True)
def tmp_memory(monkeypatch, tmp_path):
    """Every test gets a fresh embedded Qdrant in tmp + fake embeddings."""
    monkeypatch.setattr("app.memory.embed_texts", fake_embed_texts)
    mem = MemoryIndex(path=str(tmp_path / "qdrant"))
    monkeypatch.setattr("app.memory._memory", mem)
    yield mem
    mem.close()


@pytest.fixture
def tmp_store(monkeypatch, tmp_path):
    """Route persistence (reports + blobs) into a per-test tmp dir."""
    store = LocalJsonStore(root=tmp_path / "reports")
    monkeypatch.setattr("app.storage._store", store)
    monkeypatch.setattr("app.storage.BLOBS_DIR", tmp_path / "blobs")
    return store


def png_b64(color: tuple[int, int, int] = (255, 0, 0), size: int = 32) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
