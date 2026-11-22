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

LOCALES = {"en_US": "English (US)", "en_GB": "English (UK)", "en_AU": "English (AU)", "en_IN": "English (IN)",
           "en_IE": "English (IE)", "en_ZA": "English (ZA)", "en_SC": "English (Scotland)"}


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
                if m and m.group(2).startswith("en_"):
                    out.append(Speaker(m.group(1).strip(), m.group(1).strip(),
                                       LOCALES.get(m.group(2), f"English ({m.group(2)[-2:]})"), "", m.group(3)[:60],
                                       m.group(1).strip() in ("Samantha", "Daniel", "Alex")))
            self._speakers = sorted(out, key=lambda s: (not s.recommended, s.id))
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
