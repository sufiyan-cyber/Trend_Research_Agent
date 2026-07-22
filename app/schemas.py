"""Request/response models and report schemas.

Versioning: CampaignReport (v0, seven core fields) is preserved as the
composed core of CampaignReportV1. The composer LLM emits only the core;
specialist detail + programmatic palette are assembled in code.
CampaignReportV2 (Phase 3) adds the trend verdict + audience fit.
CampaignReportV3 (Phase 6) adds the critique + scorecard. Every added field is
optional, so records stored under an earlier version still validate as v3.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class CampaignReport(BaseModel):
    """Marketing deconstruction core, schema v0 — also the composed core of v1."""

    campaign_idea: str = Field(
        description=(
            "The core idea behind the campaign in 2-4 sentences: what marketing "
            "play it runs (FOMO, social proof, UGC, launch, newsjack, ...) and "
            "the insight it is built on."
        )
    )
    how_it_was_run: str = Field(
        description=(
            "Execution reconstruction: channel(s) the format implies, timing "
            "logic (why now), targeting (who it speaks to and how you can tell), "
            "and the CTA structure. Mark inferences as inferences."
        )
    )
    hook: str = Field(
        description=(
            "The scroll-stopper: quote the actual headline/first line when "
            "present, then name the hook mechanic (curiosity gap, bold claim, "
            "specificity, self-selection callout, pattern interrupt, ...)."
        )
    )
    emotional_trigger: str = Field(
        description=(
            "The single dominant emotion doing the work (FOMO, aspiration, "
            "belonging, insecurity, pride, ...) and the exact element in the "
            "material that fires it."
        )
    )
    visual_notes: str = Field(
        description=(
            "Visuals read as strategy: layout hierarchy, thumbnail energy, "
            "production quality as a signal, text density; palette only if it "
            "does marketing work. One signal among many, not the headline."
        )
    )
    why_it_worked: str = Field(
        description=(
            "Causal chain connecting play x hook x emotion x channel fit x "
            "timing: 'because X audience saw Y at moment Z and felt W, they did "
            "V'. No vague praise; every claim traces to the material."
        )
    )
    takeaway_for_us: str = Field(
        description=(
            "One concrete, stealable move adapted to our brand (see the brand "
            "context in the prompt), naming which audience bucket it targets."
        )
    )
    seen_before: str = Field(
        default="",
        description=(
            "Phase 2 memory section: if similar past campaigns were provided, "
            "'this resembles <id> analyzed on <date>; the new twist is ...'. "
            "If none were provided, 'First of its kind in our memory.'"
        ),
    )


# --- Phase 1: specialist outputs -------------------------------------------


class StrategyAnalysis(BaseModel):
    """Campaign Strategy specialist output."""

    primary_play: str = Field(description="Primary play from the campaign-play taxonomy, named plainly.")
    secondary_play: str | None = Field(default=None, description="Secondary play if clearly present, else null.")
    campaign_idea: str = Field(description="The insight the campaign is built on, 2-3 repeatable sentences.")
    channel_inference: str = Field(description="Channel(s) the format implies and the fingerprint evidence; marked as inference.")
    timing_logic: str = Field(description="Why this ran now (moment/season/trend/product), or 'evergreen' if no timing device is visible.")
    targeting: str = Field(description="Who this speaks to and the exact evidence: vocabulary, references, callouts, imagery.")
    cta_structure: str = Field(description="CTA type (hard/soft/engagement bait/lead magnet/absent) and why it fits the funnel stage.")


class HookAnalysis(BaseModel):
    """Hook & Copy specialist output."""

    hook_quote: str = Field(description="The actual hook text, quoted exactly (transcribed from images if needed).")
    mechanics: list[str] = Field(description="Hook mechanics from the taxonomy, e.g. 'curiosity gap', 'specificity'.")
    stakes: str = Field(description="What the reader gains by stopping or loses by scrolling past.")
    dominant_emotion: str = Field(description="Exactly one emotion from the emotion map.")
    trigger_element: str = Field(description="The exact word/image that fires the dominant emotion.")
    credibility_devices: list[str] = Field(description="Receipts shown (screenshots, numbers, names, logos); empty if none.")
    copy_structure: str = Field(description="Line-1-to-line-2 handoff, reading gravity, voice, jargon budget.")


class VisualAnalysis(BaseModel):
    """Visual specialist output (LLM part; extracted palette is attached in code)."""

    production_signal: str = Field(description="Raw / template / polished — and the marketing work that choice does.")
    layout_hierarchy: str = Field(description="First fixation point, text density, faces/gaze, thumbnail energy at feed size.")
    format_read: str = Field(description="Aspect ratio to intended placement; carousel/swipe devices if applicable.")
    palette_interpretation: str = Field(description="What the extracted palette does: category convention, contrast, brand recall, temperature.")
    notes: str = Field(description="Anything else visually strategic; 'no image evidence' when analyzing text alone.")


class PaletteColor(BaseModel):
    """One programmatically extracted color."""

    hex: str
    coverage_pct: float


class Neighbor(BaseModel):
    """A similar past analysis surfaced from memory (mechanical data)."""

    report_id: str
    analyzed_at: str
    similarity: float
    primary_play: str = ""
    summary: str = ""


class CampaignReportV1(BaseModel):
    """Full Phase 1 report: composed core + specialist detail + palette.

    Phase 2 adds `neighbors` (similar past analyses) — additive, still v1.
    """

    schema_version: str = "v1"
    core: CampaignReport
    strategy: StrategyAnalysis
    hook_copy: HookAnalysis
    visual: VisualAnalysis
    palette: list[PaletteColor] = Field(default_factory=list)
    neighbors: list[Neighbor] = Field(default_factory=list)


# --- Phase 3: trend verdict + audience fit ----------------------------------


class Citation(BaseModel):
    """A grounded-search source (attached in code, never LLM-invented)."""

    title: str = ""
    url: str


class TrendDraft(BaseModel):
    """LLM-structured part of the trend verdict (citations excluded on purpose)."""

    verdict: Literal["new", "rising", "peaked", "fading"] = Field(
        description=(
            "new: barely present in memory and market chatter is early/experimental. "
            "rising: increasing frequency in memory and/or growing market discussion. "
            "peaked: everywhere right now, saturation signals. "
            "fading: declining usage, market has moved on."
        )
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="How strong the combined evidence is (thin memory + vague search = low)."
    )
    reasoning: str = Field(
        description="2-4 sentences combining the memory frequency data and the market signal into the verdict."
    )
    memory_frequency: str = Field(
        description="Plain-language restatement of what our own memory shows (counts and timing provided)."
    )
    market_signal: str = Field(
        description="What the live market search shows: who is talking about it, examples, saturation cues."
    )


class TrendVerdict(TrendDraft):
    """Trend verdict with search citations attached."""

    citations: list[Citation] = Field(default_factory=list)


class AudienceBucket(BaseModel):
    """One audience segment in the editable registry."""

    id: str
    name: str
    description: str
    pains: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


class BucketRegistry(BaseModel):
    buckets: list[AudienceBucket]


class AudienceFit(BaseModel):
    """Which of our audience buckets this trend/play can carry a message to."""

    bucket_id: str = Field(description="id of the best-fit bucket from the provided registry — must be one of the given ids.")
    bucket_name: str = Field(description="name of that bucket, copied from the registry.")
    angle: str = Field(description="The angle that carries this campaign's mechanics to that bucket, in one crisp sentence.")
    fit_reasoning: str = Field(description="Why this bucket over the others — tie to their pains and channels.")
    content_suggestion: str = Field(description="What we should actually make: format + channel + working hook, briefable tomorrow.")
    secondary_bucket_id: str | None = Field(default=None, description="Optional second-best bucket id, else null.")


class TriggerPlay(BaseModel):
    """How to pull this campaign's emotional trigger in ONE of our buckets.

    One entry per registry bucket, honestly rated — `avoid` is a legitimate
    answer and the schema forces the strategist to say it per bucket instead
    of silently matching everything to everything.
    """

    bucket_id: str = Field(description="id from the provided registry, copied exactly.")
    bucket_name: str = Field(description="name of that bucket, copied from the registry.")
    fit: Literal["strong", "stretch", "avoid"] = Field(
        description=(
            "strong: the trigger maps directly onto this bucket's pains. "
            "stretch: workable with reframing — say what reframing. "
            "avoid: firing this trigger at this bucket would misfire or harm."
        )
    )
    how_to_fire: str = Field(
        description=(
            "How the SAME trigger fires for this bucket: which of their pains it "
            "hooks into and through which of their channels. For 'avoid', why it "
            "misfires here instead."
        )
    )
    example_hook: str = Field(
        description="A working one-line hook for this bucket firing this trigger; empty string for 'avoid'."
    )
    caution: str = Field(
        default="",
        description=(
            "Ethical/brand-safety line for using this trigger on this bucket — "
            "mandatory when the emotion is negative-valence (anxiety, shame, "
            "fear...) aimed at stressed students; empty if genuinely none."
        ),
    )


class AudienceDraft(BaseModel):
    """Audience node output: best-fit bucket + the per-bucket trigger playbook."""

    fit: AudienceFit
    trigger_playbook: list[TriggerPlay] = Field(
        min_length=1,
        max_length=6,
        description="One entry per bucket in the provided registry — cover every bucket, no skipping.",
    )


class EmotionProfile(BaseModel):
    """Normalized emotion read, built in code from the hook specialist's output.

    `raw` preserves what the specialist actually wrote; `primary`/`valence`
    are what analytics and memory aggregate on (see app/emotions.py).
    """

    primary: str
    valence: Literal["positive", "negative", "desire", "unclassified"]
    raw: str = ""
    trigger_element: str = ""


class CampaignReportV2(CampaignReportV1):
    """Phase 3 report: deconstruction + trend verdict + audience fit = campaign brief."""

    schema_version: str = "v2"
    trend: TrendVerdict | None = None
    audience: AudienceFit | None = None


# --- Phase 6: critique (the negative section) + scorecard --------------------
#
# Models default to praise. Three mechanisms fight that here, in order of how
# hard they are to talk around:
#   1. schema  — `weaknesses` has min_length=2, so "nothing negative" cannot be
#                emitted at all; the structured-output call fails instead.
#   2. persona — a separate adversarial node (see prompts/critique_v1.md) that
#                never wrote the praise it is attacking.
#   3. rubric  — forced enums + calibration anchors, so scores can't all be 90.


class Weakness(BaseModel):
    """One concrete thing wrong with the campaign. Evidence-bound, not a vibe."""

    issue: str = Field(
        description=(
            "The specific weakness in one sentence, stated as a flaw and not "
            "hedged into a compliment. Name what fails, not what 'could be "
            "strengthened'."
        )
    )
    severity: Literal["low", "medium", "high"] = Field(
        description=(
            "high: would likely sink the campaign or damage the brand. "
            "medium: meaningfully caps the result. low: real but survivable."
        )
    )
    evidence: str = Field(
        description=(
            "The exact element in the material (or its absence) that shows this. "
            "If it is an inference rather than something visible, say so."
        )
    )
    mitigation: str = Field(
        description="What we would have to do differently to avoid it. Concrete, not 'test more'."
    )


class Critique(BaseModel):
    """Adversarial read of the campaign. The section that is allowed to say no."""

    weaknesses: list[Weakness] = Field(
        min_length=2,
        max_length=6,
        description=(
            "At least two real weaknesses, strongest first. Every campaign has "
            "them — a campaign you cannot fault is a campaign you have not "
            "examined. Do not pad to the maximum."
        ),
    )
    why_it_might_not_work: str = Field(
        description=(
            "The strongest honest case that this campaign underperformed or was "
            "not the cause of whatever result it is credited with. Argue it "
            "properly, do not straw-man it."
        )
    )
    risk_if_we_copy_it: str = Field(
        description=(
            "What specifically goes wrong if OUR brand runs this play: audience "
            "mismatch, budget/production reality, channel fit, timing miss."
        )
    )
    brand_safety_flag: str = Field(
        description=(
            "Reputational, legal, cultural or accessibility exposure. Write "
            "'None identified' only if you genuinely find none — and then say "
            "what you checked for."
        )
    )
    survivorship_check: str = Field(
        description=(
            "Are we only seeing this because it worked? What would the same play "
            "look like from the brands where it flopped and never got posted?"
        )
    )
    what_we_could_not_verify: str = Field(
        description=(
            "The claims in this report resting on inference rather than visible "
            "evidence — spend, reach, results, attribution, audience response. "
            "Name them plainly."
        )
    )
    confidence_in_positive_read: Literal["low", "medium", "high"] = Field(
        description=(
            "How much the optimistic half of this report should be trusted. "
            "'high' requires visible outcome evidence (numbers, receipts), not "
            "just a well-crafted creative."
        )
    )


class ScoreDimension(BaseModel):
    """One judged 0-100 dimension with its reasoning and provenance."""

    key: str
    label: str
    score: int = Field(ge=0, le=100)
    rationale: str = ""
    computed: bool = False  # True when derived in code, not judged by the model


class JudgedScores(BaseModel):
    """The LLM-judged half of the scorecard. Emitted by the critic, not the composer.

    Anchors live in the prompt: 50 is a competent average campaign, 80+ needs
    exceptional evidence. Asking the skeptic for the numbers is deliberate —
    the node that just listed the flaws is the one least likely to inflate them.
    """

    craft: int = Field(ge=0, le=100, description="Execution quality of the creative itself.")
    originality: int = Field(ge=0, le=100, description="How much this differs from the standard version of this play.")
    hook_strength: int = Field(ge=0, le=100, description="Does the opening actually stop a scroll?")
    brand_fit: int = Field(ge=0, le=100, description="Fit with OUR brand voice and positioning (see brand context).")
    replicability: int = Field(ge=0, le=100, description="Could we realistically produce this with our resources?")
    evidence_strength: int = Field(
        ge=0, le=100, description="How much of this analysis rests on visible evidence vs inference. Low is common and honest."
    )
    scoring_note: str = Field(description="One sentence on what dragged the scores down. Not a summary of strengths.")


class CritiqueDraft(BaseModel):
    """What the critic node returns: the case against, plus the judged numbers.

    One call, not two — the scores are more honest coming from the node that
    just enumerated the flaws, and it keeps the added cost to a single Flash call.
    """

    critique: Critique
    scores: JudgedScores


class Scorecard(BaseModel):
    """Quantified read of the campaign — what the charts render.

    Half the dimensions are computed in code (`computed: true`) from the bucket
    registry, the trend verdict and memory similarity, so the headline number
    is not purely a model's opinion.
    """

    relevance_to_us: int = Field(ge=0, le=100, description="Headline: how relevant this campaign is to our brand.")
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    risk_index: int = Field(ge=0, le=100, default=0, description="Weighted severity of the critique's weaknesses.")
    scoring_note: str = ""


class CampaignReportV3(CampaignReportV2):
    """Phase 6 report: the brief, plus the case against it and the numbers."""

    schema_version: str = "v3"
    critique: Critique | None = None
    scorecard: Scorecard | None = None
    # Phase 7 (additive, still v3): normalized emotion + per-bucket trigger playbook.
    emotion: EmotionProfile | None = None
    trigger_playbook: list[TriggerPlay] = Field(default_factory=list)


# --- Phase 4: Trend Radar ----------------------------------------------------


class Source(BaseModel):
    """One entry in the editable source registry (config/sources.json)."""

    id: str
    type: Literal["rss", "gdelt"]
    name: str
    url: str | None = None  # rss
    query: str | None = None  # gdelt
    timespan: str = "3d"  # gdelt
    max_records: int = 25  # gdelt


class SourceRegistry(BaseModel):
    sources: list[Source]


class Player(BaseModel):
    """One tracked market player (config/players.json)."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class PlayerRegistry(BaseModel):
    players: list[Player]


class ScanItem(BaseModel):
    """One normalized item fetched from a source during a radar scan."""

    url_hash: str
    source_id: str
    source_name: str
    title: str
    url: str
    published: str = ""
    summary: str = ""


class TriageDecision(BaseModel):
    """Verdict on one scanned item, by index into the presented batch."""

    index: int = Field(description="0-based index of the item in the presented list.")
    notable: bool = Field(description="True only if this signals a marketing trend/campaign worth deep analysis.")
    reason: str = Field(description="One sentence: why it is or isn't radar-worthy.")


class TriageBatch(BaseModel):
    decisions: list[TriageDecision]


class ScanStats(BaseModel):
    """Outcome of one radar scan run (also the cost-guardrail evidence)."""

    run_at: str
    sources_ok: int = 0
    sources_failed: int = 0
    fetched: int = 0
    new: int = 0
    notable: int = 0
    analyzed: int = 0
    failed: int = 0
    filter_rate: float = 0.0  # share of new items that never hit the deep model


class TrendLine(BaseModel):
    """One trend called out in the weekly digest."""

    pattern: str = Field(description="The marketing pattern/play, named plainly.")
    evidence: str = Field(description="What in this week's data supports it (counts, examples, verdicts).")
    recommended_bucket: str = Field(description="Which of our audience buckets it can carry a message to.")
    suggested_move: str = Field(description="Concrete move we could run: format + channel + hook direction.")


class NotableCampaign(BaseModel):
    title: str = Field(description="Short name for the campaign/analysis.")
    why_notable: str = Field(description="One-two sentences on why it matters.")
    reference: str = Field(default="", description="report_id or source name it came from, copied from the data.")


class DigestModel(BaseModel):
    """Weekly trend digest (LLM-composed from memory; rendered to markdown)."""

    headline: str = Field(description="One-line headline for the week.")
    week_summary: str = Field(description="3-5 sentence overview of what moved this week.")
    rising: list[TrendLine] = Field(description="Patterns rising this week; empty if none.")
    watch: list[TrendLine] = Field(description="Peaked/fading patterns to be cautious with; empty if none.")
    notable_campaigns: list[NotableCampaign] = Field(description="Standout campaigns from this week's analyses.")


class Alert(BaseModel):
    """A rising-trend alert. Early is the entire point."""

    alert_id: str
    created_at: str
    report_id: str
    play: str
    verdict: str
    message: str


class PlayerProfileText(BaseModel):
    """LLM-written profile for one tracked player, grounded in our analyses."""

    player_id: str = Field(description="id of the player, copied from the provided data.")
    profile: str = Field(description="2-4 sentences: how this player markets, based only on the provided analyses.")
    tone: str = Field(description="Their voice/tone in one line.")
    visual_identity: str = Field(description="Their visual signature in one line (from palette families/production signals).")
    counter_move: str = Field(description="One way we could differentiate against them.")


class MarketMapModel(BaseModel):
    profiles: list[PlayerProfileText]


# --- Phase 5: outcomes, lifecycles, ask-the-agent ----------------------------


class OutcomeRequest(BaseModel):
    """Manually entered result of a recommendation that became a campaign."""

    became_campaign: bool = Field(description="Did this recommendation actually ship as a campaign?")
    performance: Literal["strong", "moderate", "weak"] | None = Field(
        default=None, description="Honest overall rating once results are in."
    )
    open_rate: float | None = None
    ctr: float | None = None
    engagement: float | None = None
    notes: str = ""


class TrendEvent(BaseModel):
    """One observation of a play's trend verdict at a point in time."""

    at: str
    play: str
    verdict: str
    report_id: str


class TrendTimeline(BaseModel):
    """Lifecycle of one play: first seen -> rising -> peak -> fade."""

    play: str
    current_verdict: str
    first_seen: str
    last_seen: str
    observations: int
    first_rising_at: str | None = None
    first_peaked_at: str | None = None
    early_call_days: int | None = None  # rising flagged N days before peak — the provable claim
    events: list[TrendEvent] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=3)


class AskAnswer(BaseModel):
    """Grounded answer over memory + market map + lifecycles."""

    answer: str = Field(description="Direct answer to the question, grounded ONLY in the provided context.")
    sources: list[str] = Field(
        description="report_ids / player names / digest dates from the context that support the answer; empty if none."
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="low when the context barely covers the question — say so in the answer too."
    )


# --- API request/response ---------------------------------------------------


class ImagePayload(BaseModel):
    """One input image, base64-encoded."""

    data: str = Field(description="Base64-encoded image bytes (no data: prefix needed).")
    mime_type: str = Field(default="image/png", description="e.g. image/png, image/jpeg, image/webp")


class AnalyzeRequest(BaseModel):
    """JSON body for POST /analyze."""

    text: str = Field(default="", description="Campaign copy, caption, or context from the submitter.")
    images: list[ImagePayload] = Field(default_factory=list, max_length=10)


class Usage(BaseModel):
    """Token accounting for one model call."""

    model: str
    node: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AnalyzeResponse(BaseModel):
    """Envelope returned by POST /analyze."""

    report_id: str
    report: CampaignReportV3
    markdown: str
    usages: list[Usage]
    deduped: bool = False  # true when memory short-circuited to an existing report


class ReviewRequest(BaseModel):
    """Human review of a stored report."""

    decision: Literal["approved", "rejected"]
    comment: str = ""


class ReportSummary(BaseModel):
    """List-view projection of a stored report."""

    report_id: str
    created_at: datetime
    status: str
    primary_play: str | None = None
    trend_verdict: str | None = None
    audience_bucket: str | None = None
    takeaway: str | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
