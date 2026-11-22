"""macOS `say` engine (built into macOS, offline). Secondary / fallback engine."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

import numpy as np

from src.backend.tts.base import Capabilities, Speaker, TTSEngine
from src.utils.process_utils import find_tool

LOCALES = {
    # English
    "en_US": "English (US)", "en_GB": "English (UK)", "en_AU": "English (AU)", "en_IN": "English (IN)",
    "en_IE": "English (IE)", "en_ZA": "English (ZA)", "en_SC": "English (Scotland)",
    # Spanish
    "es_ES": "Spanish (Spain)", "es_MX": "Spanish (Mexico)", "es_AR": "Spanish (Argentina)",
    "es_CO": "Spanish (Colombia)", "es_US": "Spanish (US)", "es_CL": "Spanish (Chile)",
    # French
    "fr_FR": "French (France)", "fr_CA": "French (Canada)", "fr_BE": "French (Belgium)", "fr_CH": "French (Switzerland)",
    # German
    "de_DE": "German (Germany)", "de_AT": "German (Austria)", "de_CH": "German (Switzerland)",
    # Italian
    "it_IT": "Italian (Italy)",
    # Portuguese
    "pt_BR": "Portuguese (Brazil)", "pt_PT": "Portuguese (Portugal)",
    # Chinese
    "zh_CN": "Chinese (China)", "zh_TW": "Chinese (Taiwan)", "zh_HK": "Chinese (Hong Kong)",
    # Japanese & Korean
    "ja_JP": "Japanese (Japan)", "ko_KR": "Korean (South Korea)",
    # Scandinavian & Nordic
    "sv_SE": "Swedish (Sweden)", "nb_NO": "Norwegian (Norway)", "da_DK": "Danish (Denmark)", "fi_FI": "Finnish (Finland)",
    # Other European
    "nl_NL": "Dutch (Netherlands)", "nl_BE": "Dutch (Belgium)", "ru_RU": "Russian (Russia)",
    "pl_PL": "Polish (Poland)", "tr_TR": "Turkish (Turkey)", "el_GR": "Greek (Greece)",
    "cs_CZ": "Czech (Czechia)", "hu_HU": "Hungarian (Hungary)", "ro_RO": "Romanian (Romania)",
    "sk_SK": "Slovak (Slovakia)", "uk_UA": "Ukrainian (Ukraine)", "ca_ES": "Catalan (Spain)", "hr_HR": "Croatian (Croatia)",
    # Middle Eastern, South & Southeast Asian
    "ar_SA": "Arabic (Saudi Arabia)", "he_IL": "Hebrew (Israel)", "hi_IN": "Hindi (India)", "kn_IN": "Kannada (India)",
    "bn_IN": "Bengali (India)", "ta_IN": "Tamil (India)", "te_IN": "Telugu (India)", "mr_IN": "Marathi (India)",
    "gu_IN": "Gujarati (India)", "pa_IN": "Punjabi (India)", "ml_IN": "Malayalam (India)", "ur_PK": "Urdu (Pakistan)",
    "id_ID": "Indonesian (Indonesia)", "ms_MY": "Malay (Malaysia)", "th_TH": "Thai (Thailand)",
    "vi_VN": "Vietnamese (Vietnam)", "bg_BG": "Bulgarian (Bulgaria)", "sl_SI": "Slovenian (Slovenia)",
}


def _format_locale(loc: str) -> str:
    if loc in LOCALES:
        return LOCALES[loc]
    p = loc.split("_")
    if len(p) == 2:
        return f"{p[0].upper()} ({p[1].upper()})"
    return loc


class SayEngine(TTSEngine):
    id = "macos-say"
    name = "macOS System Voices (say)"
    description = "Apple's built-in voices. Robotic but fast; useful as a fallback."
    license_summary = ("Part of macOS; Apple's software licence governs use of system voices. "
                       "Check Apple's terms before commercial publication.")
    capabilities = Capabilities(speed_range=(0.5, 2.0), pauses=False, pronunciation=True, emphasis=False)
    sample_rate = 22050
    BASE_WPM = 175

    def __init__(self) -> None:
        super().__init__()
        self._speakers = None

    def is_installed(self) -> Tuple[bool, str]:
        return (True, "") if find_tool("say", ["/usr/bin/say"]) else (False, "'say' is only available on macOS.")

    def speakers(self) -> List[Speaker]:
        if self._speakers is None:
            out = []
            try:
                txt = subprocess.run([find_tool("say", ["/usr/bin/say"]) or "say", "-v", "?"],
                                     capture_output=True, text=True, timeout=20).stdout
            except Exception:
                txt = ""
            for line in txt.splitlines():
                m = re.match(r"^(.+?)\s{2,}(\w\w_\w\w)\s+#\s*(.*)$", line)
                if m:
                    loc = m.group(2)
                    lang = _format_locale(loc)
                    out.append(Speaker(m.group(1).strip(), m.group(1).strip(),
                                       lang, "", m.group(3)[:60],
                                       m.group(1).strip() in ("Samantha", "Daniel", "Alex")))
            self._speakers = sorted(out, key=lambda s: (not s.is_english, not s.recommended, s.id))
        return self._speakers

    def default_speaker(self) -> str:
        ids = [s.id for s in self.speakers()]
        return "Samantha" if "Samantha" in ids else (ids[0] if ids else "")

    def _synthesize(self, text, speaker, speed, sentence_pause, clause_pause):
        import soundfile as sf
        with tempfile.TemporaryDirectory() as d:
            txt, wav = Path(d) / "t.txt", Path(d) / "o.wav"
            txt.write_text(text, encoding="utf-8")
            cmd = [find_tool("say", ["/usr/bin/say"]), "-r", str(int(self.BASE_WPM * speed)),
                   "-o", str(wav), f"--data-format=LEI16@{self.sample_rate}", "-f", str(txt)]
            if speaker:
                cmd[1:1] = ["-v", speaker]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "say failed")
            audio, sr = sf.read(str(wav), dtype="float32")
        return np.asarray(audio, dtype=np.float32), int(sr)
