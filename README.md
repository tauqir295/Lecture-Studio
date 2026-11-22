# Lecture Studio — Universal Offline Tutorial Video Studio

Lecture Studio is a desktop application that turns documents and teaching material into **narrated tutorial videos**.
You import a PDF, PowerPoint, Word file, Markdown, plain text or source code. Lecture Studio turns it into readable
16:9 slides and drafts a narration script for each slide. It then speaks the scripts with a **local** text-to-speech
model and renders an MP4 with subtitles and slideshow-style transitions.

- **Offline-first.** Narration, slide rendering and video encoding all run on your computer. The network is needed only to install packages and to download the TTS model once (see [Privacy](#privacy)).
- **Topic-agnostic.** It works for SAP, Android/AOSP, Linux, programming, AI/ML, cloud/DevOps, engineering, science, business and any other subject. Topic profiles are optional data files; the core has no topic-specific code, and a test (`tests/test_content_agnostic.py`) enforces this.
- **Cross-platform.** Python + Qt (PySide6) + ffmpeg. It is designed for Windows, Linux and macOS. See [Supported operating systems](#supported-operating-systems) for what has actually been verified.
- **Reusable workflow.** Import → review slides → edit narration → generate audio → render video. Every project is a self-contained folder.

---

## Features

**Dashboard**
- Recent Projects lists each project's name, slide count, stage and last-modified date.
  - Open a project with **Open** or by double-clicking it. Projects opened from outside `Projects/` are remembered.
- **Delete…** offers two choices:
  - **Remove from Recent Projects** hides the entry and keeps all files. Opening the project again brings it back.
  - **Delete Project and All Files** permanently deletes the project folder after a second confirmation.
    - It only deletes a real project folder (one containing `project.json`).
    - It refuses links, the workspace, `Projects/` itself, your home folder and drive roots, and it never follows links inside the project.
    - The currently open project can't be deleted.

**Content**
- Import PDF, PPTX, DOCX, Markdown, plain text and code files (`.py .java .kt .js .ts .go .rs .c .cpp .cs .sh .sql .yaml` …).
- Analysis report on import: structure, slide count, text, images, warnings.
- Non-PDF sources become video-friendly slides: at most 6 bullets, ~60 words of prose, 14 code lines or 7 table rows per slide. Long content continues on further slides and **no source text is dropped**; it goes on a slide or into the narration.
- PPTX is converted through LibreOffice when installed (faithful). Otherwise it is rebuilt from text, tables and pictures. Speaker notes become narration.
- Optional topic profiles (General, SAP, Android, Linux, AI/ML, Programming & Web) seed things like pronunciations. You can add your own JSON profiles in `<workspace>/profiles/`.
- Companion packages (a `<pdf-name>.json` manifest next to the PDF) import ready-made narration and related files.

**Slide Studio**
- Thumbnail navigator, zoomable preview, extracted text, notes, review status (approve / reject / edited). Approval is optional and blocks nothing.

**Narration Studio**
- Per-slide script editing with word count and duration estimate.
- **TTS model selection.** Kokoro-82M is the default; macOS system voices are a macOS-only fallback.
- **Custom local TTS models.** **Manage Models…** imports models you have downloaded from a file or folder.
  - Supported: **Piper voices** (`.onnx` + `.onnx.json`) and **Kokoro-compatible ONNX** builds (`.onnx` + voices `.bin`).
  - The format and missing dependencies are detected automatically. Unsupported models (PyTorch, Hugging Face, sherpa-onnx, GGUF) get an explanation of what to do instead.
  - You can name, rename and remove models, and choose to copy them into the model library or use them where they are.
  - Imported models and their voices work everywhere the default does: global or per-slide speakers, samples, previews and video rendering. They run fully offline.
- **Speaker selection** with language, gender and style labels, plus **▶ Play Sample**.
- **▶ Preview Narration** reads the actual slide text, including unsaved edits.
- **One speaker for the whole presentation, or a different speaker per slide** (Speaker Assignment tab).
- Generate or regenerate audio per slide, for selected slides, for missing/outdated slides, or for all slides. Audio is marked *outdated* when the text or voice changes.
- Speed, sentence/comma pauses (Kokoro) and a pronunciation dictionary.

**Video Studio**
- **Slide range:** From/To, with validation.
- **Target duration:** natural length, 10/20/30/45 min or custom, with a reachable range shown. Narration is never cut. Hold time is adjusted first, then narration speed within your limits.
- Estimated duration and a timeline (start time, how each slide enters, narration, hold, time on screen). You can step through the slide sequence in the preview.
- **Slide transitions:**
  - Effects: None/Cut, Fade (through black), Crossfade, Dissolve, Slide Left/Right/Up/Down, Wipe Left/Right/Up/Down, Zoom In, Zoom Out.
  - Durations: 0.25, 0.5, 0.75, 1, 1.5 or 2 s.
  - Set a default for all slides, set per-slide overrides for selected slides, or pick "No transition" for specific slides.
  - "Vary" assigns a varied sequence. "Apply to all" with *Override per-slide settings* resets every slide to the default.
  - **▶ Preview transition** plays the previous slide changing into the selected one, using the same ffmpeg filters as the final render.
  - Transition settings are saved in the project (`project.json`).
- **MP4 rendering:** H.264 video and AAC audio with an embedded subtitle track, plus a separate `.srt` and a `.json` render report. You can render as many videos per project as you like and reuse previous settings.

---

## What you need to make a video

You select **one source file** in **Create New Project**. The app builds everything else from it: slide images, narration scripts, audio, subtitles and the MP4.

### Which file to select

| You have… | Select this file | What you get |
|---|---|---|
| Finished slides (any tool) | **`.pdf`** (recommended) | Each page becomes one slide, exactly as designed. |
| PowerPoint slides | **`.pptx`** (or export to PDF first) | Speaker notes become narration. Install LibreOffice for faithful slides; without it, slides are rebuilt from the text, tables and pictures. |
| PDF + ready-made narration | **the `.pdf`**, not its `.json` manifest | The manifest next to it is found automatically (see [below](#preparing-files-for-a-pdf-project)). |
| A Word document | **`.docx`** | Headings become sections; text, lists, tables, code and images become slides. |
| Notes or docs in Markdown | **`.md`** / `.markdown` / `.mdown` | Headings, lists, code blocks, tables and linked images become slides. |
| Plain text | **`.txt`** / `.text` / `.rst` / `.adoc` | Headings are guessed (ALL CAPS, numbered or underlined lines). |
| Source code for a walkthrough | the code file, e.g. **`.py` `.java` `.kt` `.js` `.ts` `.go` `.rs` `.c` `.cpp` `.cs` `.sh` `.sql` `.yaml`** | Slides of at most 14 lines; comments seed the narration. |

Sample files to try: `docs/pdfs/*.pdf`, `docs/samples/` (Markdown, Kotlin, text), and `output/day1_video_lecture/` (a PDF with a companion manifest). The New Project dialog lists them.

**Common mistakes**
- **Don't select the `.json` manifest itself.** `.json` is accepted as a *code* file, so you would get slides of JSON. Select the PDF; the manifest is picked up automatically.
- **Old formats aren't supported:** `.ppt`, `.doc` and Keynote `.key`. Save them as `.pptx`, `.docx` or PDF first.
- **One file per project.** Other files in the same folder (images, diagrams, code) are not added. Put that content in the file you select, or create a separate project from it.

### What else the video needs

| Needed | Where it comes from | What you do |
|---|---|---|
| Slide images | Rendered from your file during import | Nothing |
| Narration text | Your speaker notes, a companion manifest, or drafted from the slide text | Review and edit it in Narration Studio |
| Narration voice | Kokoro-82M (default) or a model you imported | One-time **Download model** in Narration Studio (see [TTS models](#tts-models)) |
| ffmpeg (video encoding) | Installed with `requirements.txt` (`imageio-ffmpeg`) | Nothing |
| LibreOffice | Optional, PPTX import only | Install it if you want PowerPoint slides reproduced exactly |

Then render in **Video Studio**. The video, subtitles and render report are saved in `Projects/<project>/video/`, named `<name>_slides_<from>-<to>_<date-time>.mp4` (see [Video rendering](#video-rendering)).

---

## Preparing files for a PDF project

### Mandatory and optional files

| File | Required? | What it does |
|------|-----------|--------------|
| `<name>.pdf` | **Yes** | The slides. Each page becomes one video slide. This is the only file you select in the New Project dialog. |
| `<name>.json` (companion manifest) | Optional | Gives ready-made narration scripts and slide titles/metadata, and lists related files to copy into the project. |
| Files listed in the manifest's `files` section | Optional | Any files (Markdown notes, CSV, HTML, …). They are **copied into the project for reference only**. They are not read or shown in the video. |

Only the PDF and the manifest are read. The app does not pick up other files just because they are in the same folder. Loose images, diagrams, code or config files next to a PDF are ignored. To put that content into a video, put it in the PDF itself. Or import the Markdown, text, code, DOCX or PPTX file as its own project (see [Features](#features)). Images that a Markdown file links with a relative path (`![Diagram](images/flow.png)`) are placed on the slides when that Markdown file is imported.

### How the companion manifest is found

You don't attach the manifest by hand. When you pick a PDF, the app looks in **the same folder**:

1. First for `<pdf-name-without-.pdf>.json`. For example, `intro.pdf` → `intro.json`.
2. Then for any other `*.json` whose `"pdf"` field names this PDF exactly (for example `"pdf": "intro.pdf"`).

Other `.json` files in the folder (configs, data) are ignored, because only files containing the `"format"` value below are treated as manifests.

A manifest is used only if it is valid JSON and has `"format": "ppt-lecture-studio/companion@1"`. Otherwise it is skipped, and a warning is logged if the JSON can't be read. When a manifest is found, the New Project dialog shows **✔ Companion lecture package found** with the number of scripts and related files.

### Manifest format

```json
{
  "format": "ppt-lecture-studio/companion@1",
  "deck_title": "Intro to Networking",
  "pdf": "intro.pdf",
  "words_per_minute": 145,
  "files": {
    "narration": "narration.md",
    "technical_review": "notes/review.md",
    "slide_mapping_csv": "slide_mapping.csv"
  },
  "slides": [
    { "slide_number": 1, "title": "Welcome", "section": "Intro",
      "narration": "Welcome to this lesson on networking basics..." },
    { "slide_number": 2, "title": "The OSI model",
      "narration": "Networks are easiest to understand in layers..." }
  ]
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `format` | Yes | Must be exactly `ppt-lecture-studio/companion@1`. |
| `pdf` | Only if the manifest isn't named after the PDF | The PDF file name, without a folder path. |
| `deck_title` | No | Shown in the project. Defaults to the manifest file name. |
| `words_per_minute` | No | Used for duration estimates. Default: 140. |
| `files` | No | `role → path relative to the manifest`. You choose the role names. A file with the role `narration` is copied to the project's `narration/` folder. All other files go to `companion/`. |
| `slides[].slide_number` | Yes, per entry | A whole number starting at 1. It matches PDF page *N*. Entries without one are ignored. |
| `slides[].narration` | No | The narration script for that slide. |
| `slides[].title`, `section`, `source_page`, `slide_key` | No | Slide title and metadata. |

Use UTF-8 for the manifest. Narration imported from a manifest starts as **Draft**, so you still review and approve it in Narration Studio.

### What happens when optional files are missing

- **No manifest:** the project imports normally. A draft narration is written for every slide from its extracted text. You can edit it in Narration Studio.
- **No entry for a slide:** that slide gets the same auto-drafted narration.
- **An entry with no `narration` text:** the slide's script is empty. It's flagged as empty in Narration Studio until you write one.
- **The slide count differs from the PDF page count:** a warning is logged and entries are matched by `slide_number`. Extra entries are ignored.
- **A file listed in `files` doesn't exist:** a warning is logged and that file is skipped. The import continues.

### Example project folder

```
my-course/
└── networking-intro/
    ├── intro.pdf               ← required: select this in New Project
    ├── intro.json              ← optional: found automatically (same base name)
    ├── narration.md            ← optional: listed in "files", copied to <project>/narration/
    ├── slide_mapping.csv       ← optional: listed in "files", copied to <project>/companion/
    └── notes/
        └── review.md           ← optional: listed in "files" as "notes/review.md"
```

After the import, the project is self-contained. The PDF, the manifest and the listed files are copied into it, so you can move or delete the original folder.

---

## Supported operating systems

| OS | Status |
|---|---|
| **macOS** | **Verified** on macOS 26.7, Intel (x86_64), Python 3.13: full test suite (131 tests) passes and the app starts. Apple Silicon is expected to work (all dependencies ship arm64 wheels) but has **not** been tested. |
| **Windows 10/11** | **Not yet verified.** The code has been audited for Windows: paths use `pathlib`, there are no shell commands, child processes start without console windows, and LibreOffice/ffmpeg are looked up in Program Files. All dependencies publish Windows wheels. Please report results. |
| **Ubuntu / Linux** | **Not yet verified.** Same audit. Qt needs a few system libraries (see the install steps). |

Known platform differences:
- The `macos-say` TTS engine exists only on macOS. Kokoro-82M is the cross-platform engine.
- Video encoding uses the ffmpeg binary bundled with `imageio-ffmpeg`, so it is the same recent build everywhere. Distro ffmpeg 4.x (e.g. Ubuntu 22.04) lacks a filter that Zoom Out uses. Set `LECTURE_STUDIO_FFMPEG=/path/to/ffmpeg` to force a particular binary.

---

## Installation

Requirements on every OS: **Python 3.12 or newer** (tested with 3.13), about 2 GB of disk space for packages, and about 360 MB for the Kokoro model.
Internet is needed only during installation and the one-time model download.

### Windows 10/11
1. Install Python 3.12+ from python.org. Tick *Add python.exe to PATH*.
2. In PowerShell, from the project folder:
   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   pip install -r requirements.txt
   python main.py
   ```
3. Optional: install LibreOffice for faithful PPTX import.

### Ubuntu / Debian Linux
```bash
sudo apt install python3 python3-venv python3-pip libxcb-cursor0 libegl1 libxkbcommon-x11-0
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```
- `libxcb-cursor0` is required by Qt 6.5+ on X11.
- Optional: `sudo apt install libreoffice` for faithful PPTX import.
- On other distributions, install the equivalent Qt/xcb runtime libraries.

### macOS (Intel or Apple Silicon)
```bash
python3 -m venv .venv            # Python 3.12+ from python.org, Homebrew or uv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```
Optional: install LibreOffice (`brew install --cask libreoffice`) for faithful PPTX import.

### First run: install the TTS model
Open **Narration Studio → TTS Model → Download model**. This is a one-time ~350 MB download, verified with SHA-256.
You can also place the files manually; see [docs/TTS.md](docs/TTS.md). After that, everything works offline.

---

## Development setup

```bash
git clone <your-repo-url> Lecture-Studio && cd Lecture-Studio
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt                          # or: uv pip install -r requirements.txt
python main.py                                           # run the app from source
```

**Tests** run headless with Qt's offscreen platform:
```bash
QT_QPA_PLATFORM=offscreen python -m pytest               # macOS/Linux
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest       # Windows PowerShell
```
- Render tests need ffmpeg, which `imageio-ffmpeg` provides.
- Tests that synthesize speech are skipped when the TTS model isn't installed.

**Building / packaging:** the project does not yet have a packaging setup (installer, PyInstaller spec, etc.). It currently runs from source. See [Roadmap](#roadmap).

**App icon:** the master icon is `assets/icon.png`. `python tools/make_icons.py` regenerates `assets/icons/`:
- `lecture-studio.ico` (Windows)
- `lecture-studio.icns` (macOS)
- `hicolor/<size>/apps/lecture-studio.png` (Linux)

The running app uses these for its window and taskbar icon on every OS.
On Linux, you can add a launcher entry:
```bash
cp -r assets/icons/hicolor ~/.local/share/icons/
sed "s#/path/to/Lecture-Studio#$PWD#g" packaging/linux/lecture-studio.desktop > ~/.local/share/applications/lecture-studio.desktop
```

**Adding a transition effect:** call `register(key, label, builder)` in `src/backend/video/transitions.py`. The builder returns an ffmpeg filter chain from `[a]` (previous slide) and `[b]` (next slide) to `[v]`. The UI, preview and renderer pick it up automatically.

**Adding a TTS engine:** subclass `TTSEngine` (`src/backend/tts/base.py`) and register it in `src/backend/tts/registry.py`.

---

## TTS models

| Engine | Default | Platforms | Offline | Licence |
|---|---|---|---|---|
| Kokoro-82M (`kokoro-82m`), ONNX on CPU | ✅ | Windows, Linux, macOS | ✅ after the one-time download | Apache-2.0 weights; MIT wrapper |
| macOS System Voices (`macos-say`) | – | macOS only | ✅ | Apple macOS licence (see the commercial-use caution in docs/TTS.md) |
| Imported **Piper** voices | – | Windows, Linux, macOS | ✅ | per voice (see its model card) |
| Imported **Kokoro-compatible** ONNX builds | – | Windows, Linux, macOS | ✅ | per model |

- **Custom models:** use Narration Studio → TTS Model → **Manage Models…** → *Import File…* or *Import Folder…*.
  - The library is stored in `<models folder>/tts/custom/` (`models.json`, plus copies if you choose to copy). Set `LECTURE_STUDIO_CUSTOM_MODELS` to put it elsewhere.
  - Piper voices run through ONNX Runtime and the same espeak-ng front-end Kokoro uses, so no extra package is needed.
  - New formats plug in through `src/backend/tts/custom/formats.py` (`register(ModelFormat(...))`).

- **Model storage:** the model goes in `models/tts/kokoro-82m/` inside the app folder by default.
  - If that folder isn't writable, the app uses the per-user data folder:
    - Windows: `%LOCALAPPDATA%\LectureStudio\models`
    - macOS: `~/Library/Application Support/LectureStudio/models`
    - Linux: `$XDG_DATA_HOME/lecture-studio/models` (default `~/.local/share/lecture-studio/models`)
  - To use any other folder, set `LECTURE_STUDIO_MODELS=/path/to/models`.
- **Voices:** Kokoro has 54 speakers, 28 of them English. Choose a voice in Narration Studio, or per slide in the Speaker Assignment tab.
- More detail, performance figures and licensing: [docs/TTS.md](docs/TTS.md).

---

## Video rendering

The renderer is `src/backend/video/pipeline.py`. It uses **ffmpeg** through `imageio-ffmpeg`, or a system ffmpeg as a fallback.

1. **Narration audio.** Existing per-slide WAVs are reused, and missing ones are synthesized.
2. **Timing plan.** `src/backend/video/timing.py` computes the time on screen for each slide:
   - `incoming transition + narration + hold`.
   - The hold is adjusted to meet a target duration; narration speed changes only within your limits.
   - Every duration is rounded to whole frames.
3. **Clips.** Each slide becomes a still-image clip, and each transition becomes a short clip between two stills.
   - Clips are encoded identically and joined without re-encoding.
   - Each ffmpeg call handles at most two images, so memory use stays flat regardless of slide count.
4. **Audio.** One continuous, sample-exact PCM track is built: silence during transitions, then narration, then the hold. It is encoded to AAC once, so narration cannot drift across many slides.
5. **Subtitles.** Each slide's subtitles start when its narration starts, after the transition, and are written as `.srt` and embedded in the MP4.

Transitions are **added** time: they are silent and play before the next slide's narration, so they never overlap speech or subtitles.
The first slide of a rendered range has no incoming transition, and the last slide simply ends.
Output goes to `Projects/<project>/video/<name>_slides_AAA-BBB_<timestamp>.mp4`, plus `.srt` and `.json`.

---

## Privacy

All processing is local. The application makes **no** network requests while you import, edit, narrate or render, and sends no telemetry.
Network access happens only in these cases:
- `pip install -r requirements.txt` downloads packages from PyPI.
- **Download model** in Narration Studio fetches the Kokoro files from GitHub (`github.com/thewh1teagle/kokoro-onnx` releases). It runs only when you click it.
- Optional tools you install yourself (LibreOffice, Homebrew, apt) use their own channels.

---

## Project structure

```
main.py                     App entry point (PySide6)
requirements.txt            Python dependencies
src/
  frontend/                 Qt UI: dashboard, project wizard, Slide/Narration/Video Studio, settings, widgets/
  backend/
    content/                Importers (PDF, PPTX, DOCX, MD, text, code), slide builder, deck renderer, topic profiles/
    slides/                 PDF parsing, slide image rendering, validation
    narration/              Narration management and script checks
    tts/                    TTS engines (Kokoro, Piper, macOS say), registry, audio service;
                            custom/ = imported-model format detection + library
    video/                  timing.py (planning), transitions.py (effects), pipeline.py (render + preview)
    workers/                Background QThread workers (import, render, TTS, video, preview)
    project_manager.py      Project folders and atomic JSON persistence
  models/                   Dataclasses: Project, Slide, SlideNarration, VideoConfig
  utils/                    Paths, logging, cross-platform process/tool helpers
assets/                     icon.png (master icon) and icons/ (generated .ico, .icns, Linux PNG sizes)
packaging/linux/            Desktop entry template
tools/make_icons.py         Regenerates platform icons from assets/icon.png
tests/                      pytest suite (backend, UI offscreen, rendering, transitions)
docs/                       TTS.md, architecture notes, sample PDFs and sources
models/                     Downloaded TTS models (not in git)
Projects/                   Your projects (not in git): source/, slides/, narration/, audio/, video/, project.json;
                            .recent.json stores hidden / external Recent Projects entries
output/day1_video_lecture/  Example companion lecture package and its build scripts
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the virtual environment, then run `pip install -r requirements.txt`. |
| "ffmpeg not found" | Run `pip install imageio-ffmpeg` (in requirements), or install ffmpeg and set `LECTURE_STUDIO_FFMPEG`. |
| Transition render fails with a filter error | You are using an old system ffmpeg. Unset `LECTURE_STUDIO_FFMPEG` to use the bundled build. |
| Imported model shows "cannot run" / "files missing" | Open **Manage Models…** and select it: the detail line explains why. Restore the moved files, or remove the model and import it again (tick *Copy files into the model library* to make it independent of the originals). |
| "Model Not Supported" on import | The dialog lists the supported formats. Piper voices need the `.onnx.json` next to the `.onnx`, and Kokoro models need their voices `.bin`. |
| TTS "not installed" | Use Narration Studio → **Download model**, or copy the files into the model folder (see [TTS models](#tts-models)). |
| Model loading fails | Delete the files in `models/tts/kokoro-82m/` and download again; the checksums are verified. Check that `onnxruntime` installed for your CPU and Python version. |
| Audio generation fails | Check the log output. Very long scripts or special characters can be split or cleaned in Narration Studio. Try **Play Sample** to isolate the problem. |
| Rendering fails / "Rendered image missing" | Re-import or re-render the slides. Check free disk space; temporary files go in `Projects/<p>/cache/`. |
| Permission errors | Keep the app in a writable folder, or set `LECTURE_STUDIO_MODELS` to a writable path. On macOS/Linux the bundled ffmpeg is made executable automatically. |
| Linux: "Could not load the Qt platform plugin xcb" | `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1` |
| Windows: script activation blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| macOS: `macos-say` missing on Windows/Linux | Expected; use Kokoro-82M. |

---

## Roadmap (not yet implemented)
- Verified test runs on Windows 10/11 and Ubuntu, plus CI on all three OSes.
- Packaged installers (PyInstaller or similar) and per-user project workspace outside the app folder.
- More imported-model formats (e.g. sherpa-onnx), Piper clause-pause control.
- More transition effects and an optional fade-in/out at the start and end of a video.
- Burned-in (hard) subtitles option in the UI.

---

## License

The project's own code is released under **MIT No Attribution (MIT-0)**. See [LICENSE](LICENSE).

- You may use, copy, modify, merge, publish, distribute, sublicense and sell it, for personal, educational or commercial purposes, including in commercial products.
- **No attribution or credit is required.** Unlike the classic MIT licence, MIT-0 does not require you to keep the copyright notice.
- The software is provided "as is", without warranty.

The licence covers only this project's code. Dependencies, the bundled ffmpeg binary, the Kokoro model and voices, and system voices keep their own licences. Some are GPL or LGPL, which matters if you **redistribute** a bundled build. See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

> The copyright line in `LICENSE` still contains placeholders (`[YEAR] [COPYRIGHT HOLDER]`) for the owner to fill in.

## Contributions

Contributions are welcome:
1. Fork the repository and create a branch.
2. Keep the core topic-agnostic.
3. Add tests for new behaviour and run the suite headless.
4. Open a pull request that describes what you changed and which OS you tested on.

Contributions are accepted under the project licence (MIT-0).
