"""Canonical emotion taxonomy + normalizer.

The specialists write emotions as free text ("insecurity", "fear of missing
out", "FOMO"), which fragments every count downstream — three spellings of the
same trigger read as three trends. This module is the single place that
resolves free text to a canonical emotion and its valence, so memory payloads,
analytics and the UI all aggregate on the same vocabulary.

The taxonomy is deliberately code, not config: the LLM is *steered* toward it
via the emotion-map skill pack (app/skill_packs/hook/emotion_map_v1.md), but
whatever it writes is normalized here — a model drifting off-list degrades to
"unclassified" instead of silently polluting the counts.

Valence groups:
  positive — feel-good states a campaign leaves the viewer in
  negative — discomfort states campaigns weaponize (use with care; the
             critique node treats these as brand-safety-relevant)
  desire   — marketing/consumer drives (FOMO, status, aspiration...): not
             raw feelings but the wanting-states that convert
"""

POSITIVE = [
    "joy", "excitement", "delight", "amusement", "love", "trust", "hope",
    "optimism", "inspiration", "gratitude", "relief", "pride", "confidence",
    "comfort", "satisfaction", "curiosity", "surprise", "belonging",
]

NEGATIVE = [
    "fear", "anxiety", "stress", "anger", "frustration", "sadness",
    "disappointment", "disgust", "shame", "guilt", "loneliness", "confusion",
    "boredom", "jealousy", "envy", "regret", "panic", "doubt",
]

DESIRE = [
    "fomo", "urgency", "scarcity", "exclusivity", "luxury", "status",
    "achievement", "empowerment", "security", "safety", "convenience",
    "freedom", "adventure", "nostalgia", "anticipation", "desire",
    "aspiration", "reward", "self-improvement", "control", "escape",
    "family", "romance", "health", "social approval", "value seeking",
    "prestige", "recognition",
]

VALENCE: dict[str, str] = (
    {e: "positive" for e in POSITIVE}
    | {e: "negative" for e in NEGATIVE}
    | {e: "desire" for e in DESIRE}
)

# Common off-list spellings the specialists actually produce, mapped to canon.
SYNONYMS: dict[str, str] = {
    "happiness": "joy",
    "affection": "love",
    "insecurity": "anxiety",
    "outrage": "anger",
    "wonder": "surprise",
    "fear of missing out": "fomo",
    "greed": "value seeking",
    "greed (value seeking)": "value seeking",
    "self improvement": "self-improvement",
    "ambition": "aspiration",
    "aspirational": "aspiration",
    "exclusiveness": "exclusivity",
}


def normalize(raw: str) -> tuple[str, str]:
    """Resolve free text to (canonical_emotion, valence).

    Resolution order: exact hit -> synonym -> canonical term contained in the
    text (longest first, so "fear of missing out" doesn't stop at "fear").
    Unresolvable text is kept lowercase with valence "unclassified" — visible
    in analytics as a drift signal rather than dropped.
    """
    text = raw.strip().lower()
    if not text:
        return "", "unclassified"
    if text in VALENCE:
        return text, VALENCE[text]
    if text in SYNONYMS:
        canon = SYNONYMS[text]
        return canon, VALENCE[canon]
    for phrase, canon in SYNONYMS.items():
        if phrase in text:
            return canon, VALENCE[canon]
    for canon in sorted(VALENCE, key=len, reverse=True):
        if canon in text:
            return canon, VALENCE[canon]
    return text, "unclassified"


def emotion_map_lines() -> str:
    """The taxonomy as prompt-ready text (used by the audience briefing)."""
    return (
        f"positive: {', '.join(POSITIVE)}\n"
        f"negative: {', '.join(NEGATIVE)}\n"
        f"consumer-desire: {', '.join(DESIRE)}"
    )
