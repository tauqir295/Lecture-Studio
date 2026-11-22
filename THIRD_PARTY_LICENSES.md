# Third-party components and their licences

This project's own source code is licensed under **MIT No Attribution (MIT-0)**; see [LICENSE](LICENSE).
**That licence covers only this project's own code.** The dependencies, binaries, models and voices
below are separate works under their own licences, which still apply to them. They are **not**
in this repository (they are installed by `pip` or downloaded at runtime) unless noted.

Licences were taken from package metadata and upstream pages on 22 Nov 2026. This is not legal advice;
re-check before redistributing a bundled build.

| Component | Used for | Licence | Redistribution notes |
|---|---|---|---|
| PySide6 / Qt 6 | desktop UI | LGPL-3.0 (or GPL / commercial Qt licence) | When shipping a bundled app, follow LGPL terms (dynamic linking, allow relinking/replacement, provide licence text). |
| pypdf | PDF reading | BSD-3-Clause | Keep copyright + licence notice. |
| python-pptx | PowerPoint import | MIT | Keep notice. |
| Pillow | images | MIT-CMU (HPND) | Keep notice. |
| defusedxml | safe XML parsing | PSF-2.0 | Keep notice. |
| numpy | audio arrays | BSD-3-Clause | Keep notice. |
| soundfile / libsndfile | WAV I/O | BSD-3-Clause / LGPL-2.1 | LGPL terms for libsndfile. |
| imageio-ffmpeg | locates/bundles ffmpeg | BSD-2-Clause (wrapper) | Keep notice. |
| ffmpeg binary bundled by imageio-ffmpeg | video encoding | **GPL** build (includes libx264) | Redistributing it requires GPL compliance (source offer). Videos you produce are not covered. |
| kokoro-onnx | Kokoro TTS wrapper | MIT | Keep notice. |
| onnxruntime | model inference | MIT | Keep notice. |
| eSpeak NG (`espeakng-loader`) | pronunciation front-end | **GPL-3.0-or-later** | Redistributing requires GPL-3.0 compliance. |
| phonemizer | pronunciation front-end | **GPL-3.0** | As above. |
| Kokoro-82M weights `kokoro-v1.0.onnx` | TTS model (downloaded, ~325 MB) | Apache-2.0 | Keep licence + NOTICE if redistributing the weights. Not tracked in git. |
| Kokoro voices `voices-v1.0.bin` | speaker voices (downloaded, ~28 MB) | Apache-2.0 per the model card (not verified voice by voice) | As above. Not tracked in git. |
| Piper voices / custom models you import | your own narration models | **varies per voice/model** (many Piper voices are MIT or CC-BY, some are non-commercial) | Not shipped with this project. Check each model card before commercial use; add a licence note when importing. |
| macOS `say` system voices | optional TTS (macOS only) | Apple macOS licence | Not redistributable; Apple's terms may restrict commercial use of output. |
| LibreOffice (optional, external) | faithful PPTX → PDF | MPL-2.0 | Not bundled. |
| pytest | tests only | MIT | Not shipped. |

## Generated media
Narration audio, subtitles and MP4 files you create are your content. The GPL covers distributing the
*software*, not its output. Kokoro's Apache-2.0 weights put no licence obligation on generated audio.
See [docs/TTS.md](docs/TTS.md#4-licensing-checked-22-nov-2026-not-legal-advice) for details, including YouTube notes.

## Sample content
Sample decks in `docs/pdfs/`, `docs/samples/` and `output/day1_video_lecture/` are part of this repository
and are covered by the project licence unless a file states otherwise.
