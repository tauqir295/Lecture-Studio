"""Validated Emotion, Delivery Style, and Nonverbal Sound Tag Registry for Audio Studio and TTS engines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

CATEGORY_EMOTIONS = "Emotions"
CATEGORY_DELIVERY_STYLES = "Delivery Styles"
CATEGORY_NONVERBAL_SOUNDS = "Nonverbal Sounds"


@dataclass(frozen=True)
class TagDefinition:
    tag: str                        # exact canonical spelling, e.g. "sad", "deep and loud shouting"
    category: str                   # CATEGORY_EMOTIONS, CATEGORY_DELIVERY_STYLES, CATEGORY_NONVERBAL_SOUNDS
    label: str                      # Human-readable label
    description: str                # Effect summary
    instruction: str                # Prompt instruction for Qwen3-TTS
    supported_models: Tuple[str, ...] = ()  # empty tuple = all models; or specific engine IDs/families
    speed: float = 1.0              # acoustic multiplier for fallback engines
    pause: float = 1.0
    expressiveness: float = 1.0
    gain: float = 1.0

    @property
    def bracketed(self) -> str:
        return f"[{self.tag}]"

    def is_supported_by(self, engine_id: Optional[str]) -> bool:
        if not self.supported_models:
            return True
        if not engine_id:
            return True
        eid = engine_id.lower()
        for sm in self.supported_models:
            if sm == "qwen3" and "qwen3" in eid:
                return True
            if sm == eid:
                return True
        return False


# ------------------------------------------------------------------ Registry Data
# Exact tags specified by the user:
# Emotions: [sad], [amazed], [angry], [excited], [sarcastic], [curious], [bored], [tired],
#           [scornful], [panicked], [mischievously], [empathetic], [reluctantly], [crying],
#           [serious], [trembling].
# Delivery styles: [shouting], [deep and loud shouting], [whispers], [asmr], [very slowly],
#                  [very fast], [like dracula].
# Nonverbal sounds: [gasp], [sighing], [clears throat], [giggles], [laughing], [cough], [snorts].
# Plus missing standard emotions: [happy], [calm], [neutral], [friendly], [enthusiastic],
#                                  [storytelling], [dramatic], [inspirational], [fearful],
#                                  [hopeful], [satisfied].

_ALL_TAGS: List[TagDefinition] = [
    # ---- 1. EMOTIONS (exact user requested + standard)
    TagDefinition("sad", CATEGORY_EMOTIONS, "Sad", "Sorrowful, solemn, and melancholy tone.",
                  "Speak in a sorrowful, solemn, and melancholy tone with slow, quiet pacing.",
                  speed=0.86, pause=1.40, expressiveness=0.70, gain=0.85),
    TagDefinition("amazed", CATEGORY_EMOTIONS, "Amazed", "Wide-eyed astonishment, marvel, and genuine wonder.",
                  "Speak with wide-eyed amazement, astonishment, and genuine wonder.",
                  speed=1.05, pause=1.10, expressiveness=1.35, gain=1.05),
    TagDefinition("angry", CATEGORY_EMOTIONS, "Angry", "Stern, sharp, intense, and forceful articulation.",
                  "Speak in an angry, intense, sharp, and forceful manner with firm articulation.",
                  speed=1.06, pause=0.75, expressiveness=1.40, gain=1.10),
    TagDefinition("excited", CATEGORY_EMOTIONS, "Excited", "Enthusiastic, lively, high-energy cadence.",
                  "Speak in an enthusiastic, excited, high-energy tone with lively, upbeat cadence.",
                  speed=1.14, pause=0.65, expressiveness=1.40, gain=1.05),
    TagDefinition("sarcastic", CATEGORY_EMOTIONS, "Sarcastic", "Dry sarcasm, irony, and cynical amusement.",
                  "Speak with dry sarcasm, slight irony, and an amused cynical undertone.",
                  speed=0.94, pause=1.15, expressiveness=1.15, gain=1.0),
    TagDefinition("curious", CATEGORY_EMOTIONS, "Curious", "Inquisitive curiosity with an engaged questioning lilt.",
                  "Speak with inquisitive curiosity, an engaged questioning lilt, and bright interest.",
                  speed=1.02, pause=1.05, expressiveness=1.20, gain=1.0),
    TagDefinition("bored", CATEGORY_EMOTIONS, "Bored", "Flat, unenthusiastic, sluggish, and monotone delivery.",
                  "Speak in a flat, unenthusiastic, sluggish, and monotone bored voice.",
                  speed=0.84, pause=1.30, expressiveness=0.55, gain=0.90),
    TagDefinition("tired", CATEGORY_EMOTIONS, "Tired", "Weary, exhausted, and low-energy drowsy voice.",
                  "Speak in a weary, exhausted, low-energy, and drowsy voice.",
                  speed=0.82, pause=1.40, expressiveness=0.60, gain=0.85),
    TagDefinition("scornful", CATEGORY_EMOTIONS, "Scornful", "Sharp scorn, derisive contempt, and dismissive sneer.",
                  "Speak with sharp scorn, derisive contempt, and dismissive sneer.",
                  speed=0.98, pause=1.10, expressiveness=1.25, gain=1.05),
    TagDefinition("panicked", CATEGORY_EMOTIONS, "Panicked", "Breathless, hurried anxiety with elevated pitch.",
                  "Speak in a panicked, breathless, hurried voice with heightened anxiety.",
                  speed=1.22, pause=0.60, expressiveness=1.50, gain=1.10),
    TagDefinition("mischievously", CATEGORY_EMOTIONS, "Mischievously", "Playful, sly, conspiratorial, and teasing tone.",
                  "Speak in a playful, mischievous, sly, and conspiratorial tone.",
                  speed=1.06, pause=0.90, expressiveness=1.25, gain=1.0),
    TagDefinition("empathetic", CATEGORY_EMOTIONS, "Empathetic", "Warm empathy, deep compassion, and comforting softness.",
                  "Speak with warm empathy, deep compassion, and comforting softness.",
                  speed=0.92, pause=1.20, expressiveness=1.10, gain=0.95),
    TagDefinition("reluctantly", CATEGORY_EMOTIONS, "Reluctantly", "Hesitant, dragging, and resistant delivery.",
                  "Speak hesitantly and reluctantly, with slight hesitation and resistance.",
                  speed=0.88, pause=1.30, expressiveness=0.80, gain=0.90),
    TagDefinition("crying", CATEGORY_EMOTIONS, "Crying", "Tearful, choking emotion and breaking voice.",
                  "Speak with tearful, choking emotion and breaking voice as if weeping.",
                  speed=0.80, pause=1.50, expressiveness=1.35, gain=0.85),
    TagDefinition("serious", CATEGORY_EMOTIONS, "Serious", "Measured pace, formal, and authoritative tone.",
                  "Speak in a serious, professional, formal, and authoritative tone.",
                  speed=0.95, pause=1.10, expressiveness=0.85, gain=1.0),
    TagDefinition("trembling", CATEGORY_EMOTIONS, "Trembling", "Quavering, unsteady, and nervous voice.",
                  "Speak with a trembling, quavering, and unsteady voice.",
                  speed=0.92, pause=1.25, expressiveness=1.40, gain=0.90),

    # Missing standard emotions
    TagDefinition("happy", CATEGORY_EMOTIONS, "Happy", "Bright, cheerful, and positive delivery.",
                  "Speak in a bright, cheerful, and happy tone with warm, positive energy.",
                  speed=1.05, pause=0.90, expressiveness=1.20, gain=1.0),
    TagDefinition("calm", CATEGORY_EMOTIONS, "Calm", "Peaceful, soothing, and unhurried pacing.",
                  "Speak in a calm, soothing, peaceful, and relaxed manner with measured, unhurried pacing.",
                  speed=0.90, pause=1.30, expressiveness=0.80, gain=1.0),
    TagDefinition("neutral", CATEGORY_EMOTIONS, "Neutral", "Natural, balanced, standard narration delivery.",
                  "Speak in a natural, balanced, and clear narration style.",
                  speed=1.0, pause=1.0, expressiveness=1.0, gain=1.0),
    TagDefinition("friendly", CATEGORY_EMOTIONS, "Friendly", "Warm, welcoming, and approachable conversational style.",
                  "Speak in a warm, welcoming, friendly, and approachable conversational tone.",
                  speed=1.03, pause=0.90, expressiveness=1.10, gain=1.0),
    TagDefinition("enthusiastic", CATEGORY_EMOTIONS, "Enthusiastic", "Faster, short pauses, vibrant excitement.",
                  "Speak with high enthusiasm, vibrant projection, and spirited excitement.",
                  speed=1.10, pause=0.75, expressiveness=1.30, gain=1.05),
    TagDefinition("storytelling", CATEGORY_EMOTIONS, "Storytelling", "Engaging narrator with deliberate, captivating pauses.",
                  "Speak like an engaging narrator telling a captivating story, with deliberate pauses and expressive cadence.",
                  speed=0.93, pause=1.25, expressiveness=1.15, gain=1.0),
    TagDefinition("dramatic", CATEGORY_EMOTIONS, "Dramatic", "Theatrical pauses, intense emotional emphasis.",
                  "Speak with dramatic intensity, emotional emphasis, and theatrical pauses.",
                  speed=0.88, pause=1.50, expressiveness=1.30, gain=1.05),
    TagDefinition("inspirational", CATEGORY_EMOTIONS, "Inspirational", "Warm, uplifting, and motivating with confident delivery.",
                  "Speak in an uplifting, inspirational, motivating, and confident voice.",
                  speed=0.96, pause=1.20, expressiveness=1.20, gain=1.0),
    TagDefinition("fearful", CATEGORY_EMOTIONS, "Fearful", "Hurried, uneasy intonation, slightly subdued.",
                  "Speak in a trembling, nervous, anxious, and fearful voice.",
                  speed=1.08, pause=0.90, expressiveness=1.30, gain=0.90),
    TagDefinition("hopeful", CATEGORY_EMOTIONS, "Hopeful", "Warm, slightly slower with an optimistic lift.",
                  "Speak with optimism, warm hopefulness, and bright anticipation.",
                  speed=0.97, pause=1.10, expressiveness=1.15, gain=1.0),
    TagDefinition("satisfied", CATEGORY_EMOTIONS, "Satisfied", "Contented, relaxed, and serene delivery.",
                  "Speak in a contented, relaxed, and satisfied tone.",
                  speed=0.96, pause=1.10, expressiveness=1.05, gain=1.0),

    # ---- 2. DELIVERY STYLES
    TagDefinition("shouting", CATEGORY_DELIVERY_STYLES, "Shouting", "Loud, commanding projection.",
                  "Speak in a loud, powerful shout with maximum projection and intensity.",
                  supported_models=("qwen3",), speed=1.15, pause=0.70, expressiveness=1.50, gain=1.25),
    TagDefinition("deep and loud shouting", CATEGORY_DELIVERY_STYLES, "Deep and Loud Shouting", "Booming, deep resonant chest shout.",
                  "Shout with a deep, booming chest voice with commanding loud resonance.",
                  supported_models=("qwen3",), speed=1.10, pause=0.80, expressiveness=1.50, gain=1.30),
    TagDefinition("whispers", CATEGORY_DELIVERY_STYLES, "Whispers", "Soft, close-up quiet whisper.",
                  "Speak in a soft, gentle whisper with quiet breathing and close-mic intimacy.",
                  speed=0.92, pause=1.10, expressiveness=0.60, gain=0.50),
    TagDefinition("asmr", CATEGORY_DELIVERY_STYLES, "ASMR", "Intimate, whisper-quiet ASMR delivery.",
                  "Speak in an intimate, relaxing, whispered ASMR style with soft, gentle close-mic proximity.",
                  supported_models=("qwen3",), speed=0.88, pause=1.20, expressiveness=0.50, gain=0.45),
    TagDefinition("very slowly", CATEGORY_DELIVERY_STYLES, "Very Slowly", "Extremely slow, deliberate, drawn-out pace.",
                  "Speak at a very slow, deliberate, drawn-out pace with prolonged syllables and generous pauses.",
                  speed=0.60, pause=1.60, expressiveness=0.90, gain=1.0),
    TagDefinition("very fast", CATEGORY_DELIVERY_STYLES, "Very Fast", "Rapid, brisk stream of speech.",
                  "Speak rapidly and quickly in a brisk, fast-paced stream of words.",
                  speed=1.60, pause=0.50, expressiveness=1.10, gain=1.0),
    TagDefinition("like dracula", CATEGORY_DELIVERY_STYLES, "Like Dracula", "Theatrical gothic aristocratic Transylvanian cadence.",
                  "Speak with a theatrical, gothic Transylvanian accent like Count Dracula, with elongated aristocratic vowels and dark aristocratic flair.",
                  supported_models=("qwen3",), speed=0.82, pause=1.40, expressiveness=1.40, gain=1.05),

    # ---- 3. NONVERBAL SOUNDS (supported by Qwen3-TTS instruction & acoustic synthesis)
    TagDefinition("gasp", CATEGORY_NONVERBAL_SOUNDS, "Gasp", "Audible sharp intake of breath.",
                  "Take a sudden sharp, audible intake of breath like an astonished gasp before speaking.",
                  supported_models=("qwen3",), speed=1.0, pause=1.2, expressiveness=1.3, gain=1.0),
    TagDefinition("sighing", CATEGORY_NONVERBAL_SOUNDS, "Sighing", "Deep, weary audible exhalation.",
                  "Speak with a deep, weary, audible exhalation of breath like a heavy sigh.",
                  supported_models=("qwen3",), speed=0.90, pause=1.4, expressiveness=0.8, gain=0.9),
    TagDefinition("clears throat", CATEGORY_NONVERBAL_SOUNDS, "Clears Throat", "Audible throat-clearing sound.",
                  "Make an audible throat-clearing sound before speaking.",
                  supported_models=("qwen3",), speed=1.0, pause=1.1, expressiveness=1.0, gain=1.0),
    TagDefinition("giggles", CATEGORY_NONVERBAL_SOUNDS, "Giggles", "Light, bubbly suppressed giggling.",
                  "Speak with light, bubbly, suppressed giggles and mirth.",
                  supported_models=("qwen3",), speed=1.10, pause=0.80, expressiveness=1.35, gain=1.0),
    TagDefinition("laughing", CATEGORY_NONVERBAL_SOUNDS, "Laughing", "Hearty, joyful chuckles and laughter.",
                  "Speak while laughing openly with warm, hearty chuckles and joyful laughter.",
                  supported_models=("qwen3",), speed=1.15, pause=0.80, expressiveness=1.40, gain=1.05),
    TagDefinition("cough", CATEGORY_NONVERBAL_SOUNDS, "Cough", "Brief dry throat cough.",
                  "Cough briefly with a dry throat cough before speaking.",
                  supported_models=("qwen3",), speed=1.0, pause=1.1, expressiveness=1.0, gain=1.0),
    TagDefinition("snorts", CATEGORY_NONVERBAL_SOUNDS, "Snorts", "Brief derisive or amused snort sound.",
                  "Make a brief derisive or amused snort sound before speaking.",
                  supported_models=("qwen3",), speed=1.0, pause=1.0, expressiveness=1.1, gain=1.0),
]

_TAGS_BY_KEY: Dict[str, TagDefinition] = {t.tag.lower(): t for t in _ALL_TAGS}

# Common aliases mapping to canonical exact tags
ALIASES: Dict[str, str] = {
    "whispering": "whispers",
    "whisper": "whispers",
    "joyful": "happy",
    "cheerful": "happy",
    "upbeat": "happy",
    "mad": "angry",
    "upset": "sad",
    "scared": "fearful",
    "afraid": "fearful",
    "giggle": "giggles",
    "chuckle": "laughing",
    "chuckles": "laughing",
    "sigh": "sighing",
    "slow": "very slowly",
    "fast": "very fast",
    "story": "storytelling",
    "narrator": "storytelling",
    "content": "satisfied",
}


# ------------------------------------------------------------------ Query & Lookup Functions
def all_tags() -> List[TagDefinition]:
    return list(_ALL_TAGS)


def get_tag(name: str) -> Optional[TagDefinition]:
    """Retrieve the TagDefinition for a name or alias (case-insensitive, bracket-tolerant)."""
    clean = (name or "").strip().lower().strip("[]").strip()
    clean = ALIASES.get(clean, clean)
    return _TAGS_BY_KEY.get(clean)


def canonical_tag(name: str) -> str:
    """Return canonical exact tag name if valid, else empty string."""
    t = get_tag(name)
    return t.tag if t else ""


def is_valid_tag(name: str) -> bool:
    """Check if the tag name exists in the validated registry."""
    return get_tag(name) is not None


def is_tag_supported_by_model(name: str, model_id: Optional[str]) -> bool:
    """Check if the tag is supported by the specific model."""
    t = get_tag(name)
    if not t:
        return False
    return t.is_supported_by(model_id)


def get_supported_tags(model_id: Optional[str] = None) -> List[TagDefinition]:
    """Return all tags supported by the given model (or all if model_id is None)."""
    return [t for t in _ALL_TAGS if t.is_supported_by(model_id)]


def get_categorized_tags(model_id: Optional[str] = None) -> Dict[str, List[TagDefinition]]:
    """Return tags grouped by category for the tag selector."""
    out: Dict[str, List[TagDefinition]] = {
        CATEGORY_EMOTIONS: [],
        CATEGORY_DELIVERY_STYLES: [],
        CATEGORY_NONVERBAL_SOUNDS: [],
    }
    for t in get_supported_tags(model_id):
        out.setdefault(t.category, []).append(t)
    return out


# ------------------------------------------------------------------ Validation Functions
def validate_tag_in_context(tag_name: str, model_id: Optional[str] = None) -> Tuple[bool, str]:
    """Validate a tag: check whether it exists and is supported by the model."""
    clean = (tag_name or "").strip().lower().strip("[]").strip()
    if clean == "pause":
        return True, ""
    t = get_tag(clean)
    if not t:
        return False, f"Unknown tag [{tag_name}]; not a recognized emotion, delivery style, or sound tag."
    if not t.is_supported_by(model_id):
        engine_hint = model_id or "the selected TTS model"
        return False, f"Tag [{t.tag}] is not supported by {engine_hint} (requires Qwen3-TTS)."
    return True, ""


def find_tags_in_text(text: str) -> List[Tuple[str, int, int]]:
    """Find all potential bracketed tags in text with their start and end character positions."""
    import re
    # Match any bracketed content starting with a letter or slash
    pattern = re.compile(r"\[\s*(/?)\s*([A-Za-z][A-Za-z0-9 _-]*?)(?:\s+([\d.]+\s*s?))?\s*\]")
    matches = []
    for m in pattern.finditer(text or ""):
        name = (m.group(2) or "").strip()
        matches.append((name, m.start(), m.end()))
    return matches
