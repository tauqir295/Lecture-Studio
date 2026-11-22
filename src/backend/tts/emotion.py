"""Narration delivery styles ("emotions"), applied through whatever controls the TTS engine has.

Local models differ a lot:
  * Kokoro-82M and macOS voices have no emotion input. A style changes pace and pauses only
    (plus the choice of voice, which stays with the user).
  * Piper voices also expose expressiveness (VITS noise scales: more or less variation in intonation).
  * An engine with real emotion/style input lists the style keys in `Capabilities.styles`; it then
    receives the style name itself (see TTSEngine.synthesize).

`controls_for(engine)` says which of these apply, so the UI never shows controls a model can't honour.
New styles: call `register(Style(...))`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

NEUTRAL = "neutral"


@dataclass(frozen=True)
class Style:
    key: str
    label: str
    description: str
    speed: float = 1.0            # multiplies the narration speed
    pause: float = 1.0            # multiplies sentence/comma pauses (engines with pause control)
    expressiveness: float = 1.0   # >1 more varied intonation, <1 flatter (engines that support it)
    gain: float = 1.0             # output volume (engine independent), e.g. quieter for whispering


_STYLES: Dict[str, Style] = {}


def register(style: Style) -> None:
    _STYLES[style.key] = style


for _s in (
    Style(NEUTRAL, "Neutral", "The voice's normal delivery."),
    Style("friendly", "Friendly", "Slightly quicker and lighter, a little more varied.", 1.03, 0.9, 1.10),
    Style("enthusiastic", "Enthusiastic", "Faster, short pauses, lively intonation.", 1.10, 0.75, 1.30),
    Style("calm", "Calm", "Slower, longer pauses, even intonation.", 0.90, 1.30, 0.80),
    Style("serious", "Serious", "Measured pace, steady intonation.", 0.95, 1.10, 0.85),
    Style("storytelling", "Storytelling", "Unhurried, with room between sentences.", 0.93, 1.25, 1.15),
    Style("dramatic", "Dramatic", "Slow with long pauses and strong intonation.", 0.88, 1.50, 1.30),
    Style("inspirational", "Inspirational", "Warm, slightly slower, with emphasis through pauses.", 0.96, 1.20, 1.20),
    # Additional tags used by Audio Studio ([happy], [sad], ...). Same honest mapping onto pace/pauses/variation.
    Style("happy", "Happy", "Bright and a little quicker, lively intonation.", 1.05, 0.90, 1.20),
    Style("sad", "Sad", "Slow, long pauses, flat intonation, a little quieter.", 0.86, 1.40, 0.70, 0.85),
    Style("excited", "Excited", "Fast, short pauses, very lively intonation.", 1.14, 0.65, 1.40),
    Style("angry", "Angry", "Quick and clipped with strong intonation, slightly louder.", 1.06, 0.75, 1.40, 1.1),
    Style("fearful", "Fearful", "Hurried with uneven intonation, a little quieter.", 1.08, 0.90, 1.30, 0.9),
    Style("whispering", "Whispering", "Quieter and softer (volume and intonation only; not a true whisper).",
          0.92, 1.10, 0.60, 0.5),
    Style("whispers", "Whispers", "Soft, close-up quiet whisper.", 0.92, 1.10, 0.60, 0.5),
    Style("hopeful", "Hopeful", "Warm and slightly slower with a lift in intonation.", 0.97, 1.10, 1.15),
    Style("satisfied", "Satisfied", "Relaxed and content, steady pace.", 0.96, 1.10, 1.05),
    # Additional exact emotion tags
    Style("amazed", "Amazed", "Wide-eyed astonishment, marvel, and genuine wonder.", 1.05, 1.10, 1.35, 1.05),
    Style("sarcastic", "Sarcastic", "Dry sarcasm, irony, and cynical amusement.", 0.94, 1.15, 1.15, 1.0),
    Style("curious", "Curious", "Inquisitive curiosity with an engaged questioning lilt.", 1.02, 1.05, 1.20, 1.0),
    Style("bored", "Bored", "Flat, unenthusiastic, sluggish, and monotone delivery.", 0.84, 1.30, 0.55, 0.90),
    Style("tired", "Tired", "Weary, exhausted, and low-energy drowsy voice.", 0.82, 1.40, 0.60, 0.85),
    Style("scornful", "Scornful", "Sharp scorn, derisive contempt, and dismissive sneer.", 0.98, 1.10, 1.25, 1.05),
    Style("panicked", "Panicked", "Breathless, hurried anxiety with elevated pitch.", 1.22, 0.60, 1.50, 1.10),
    Style("mischievously", "Mischievously", "Playful, sly, conspiratorial, and teasing tone.", 1.06, 0.90, 1.25, 1.0),
    Style("empathetic", "Empathetic", "Warm empathy, deep compassion, and comforting softness.", 0.92, 1.20, 1.10, 0.95),
    Style("reluctantly", "Reluctantly", "Hesitant, dragging, and resistant delivery.", 0.88, 1.30, 0.80, 0.90),
    Style("crying", "Crying", "Tearful, choking emotion and breaking voice.", 0.80, 1.50, 1.35, 0.85),
    Style("trembling", "Trembling", "Quavering, unsteady, and nervous voice.", 0.92, 1.25, 1.40, 0.90),
    # Delivery styles
    Style("shouting", "Shouting", "Loud, commanding projection.", 1.15, 0.70, 1.50, 1.25),
    Style("deep and loud shouting", "Deep and Loud Shouting", "Booming, deep resonant chest shout.", 1.10, 0.80, 1.50, 1.30),
    Style("asmr", "ASMR", "Intimate, whisper-quiet ASMR delivery.", 0.88, 1.20, 0.50, 0.45),
    Style("very slowly", "Very Slowly", "Extremely slow, deliberate, drawn-out pace.", 0.60, 1.60, 0.90, 1.0),
    Style("very fast", "Very Fast", "Rapid, brisk stream of speech.", 1.60, 0.50, 1.10, 1.0),
    Style("like dracula", "Like Dracula", "Theatrical gothic aristocratic Transylvanian cadence.", 0.82, 1.40, 1.40, 1.05),
    # Nonverbal sounds
    Style("gasp", "Gasp", "Audible sharp intake of breath.", 1.0, 1.20, 1.30, 1.0),
    Style("sighing", "Sighing", "Deep, weary audible exhalation.", 0.90, 1.40, 0.80, 0.90),
    Style("clears throat", "Clears Throat", "Audible throat-clearing sound.", 1.0, 1.10, 1.0, 1.0),
    Style("giggles", "Giggles", "Light, bubbly suppressed giggling.", 1.10, 0.80, 1.35, 1.0),
    Style("laughing", "Laughing", "Hearty, joyful chuckles and laughter.", 1.15, 0.80, 1.40, 1.05),
    Style("cough", "Cough", "Brief dry throat cough.", 1.0, 1.10, 1.0, 1.0),
    Style("snorts", "Snorts", "Brief derisive or amused snort sound.", 1.0, 1.0, 1.10, 1.0),
):
    register(_s)


def styles() -> List[Style]:
    return list(_STYLES.values())


def get(key: str) -> Style:
    return _STYLES.get(key or NEUTRAL) or _STYLES[NEUTRAL]


def controls_for(engine) -> List[str]:
    """Which parts of a style this engine can apply: 'native', 'pace', 'pauses', 'expressiveness'."""
    caps = engine.capabilities
    out = ["pace"]
    if caps.pauses:
        out.append("pauses")
    if caps.expressiveness:
        out.append("expressiveness")
    if caps.styles or getattr(caps, "instructions", False):
        out.insert(0, "native")
    return out


def describe_support(engine) -> str:
    """One line for the UI explaining what a style changes with this engine."""
    ctl = controls_for(engine)
    if "native" in ctl:
        if getattr(engine.capabilities, "instructions", False):
            return f"{engine.name} supports genuine instruction-based emotion, tone, and prosody delivery."
        return f"{engine.name} has built-in delivery styles; they are used directly where available."
    names = {"pace": "pace", "pauses": "pauses", "expressiveness": "intonation variation"}
    parts = [names[c] for c in ctl] + ["volume"]
    return (f"{engine.name} has no emotion input, so a style adjusts its "
            + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + ".")


@dataclass(frozen=True)
class Applied:
    speed: float
    sentence_pause: float
    clause_pause: float
    expressiveness: float
    native_style: str          # passed to engines with native styles, else ""
    gain: float = 1.0          # applied to the audio after synthesis (all engines)


def apply(style_key: str, engine, speed: float, sentence_pause: float, clause_pause: float) -> Applied:
    """Effective synthesis parameters for a style on an engine (unsupported parts are left out)."""
    st = get(style_key)
    caps = engine.capabilities
    native = st.key if st.key in caps.styles else ""
    if native:                                     # the model performs the style itself
        return Applied(speed, sentence_pause, clause_pause, 1.0, native)
    lo, hi = caps.speed_range
    return Applied(round(min(max(speed * st.speed, lo), hi), 3),
                   round(sentence_pause * st.pause, 3) if caps.pauses else 0.0,
                   round(clause_pause * st.pause, 3) if caps.pauses else 0.0,
                   st.expressiveness if caps.expressiveness else 1.0, "", st.gain)
