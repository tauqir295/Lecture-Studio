"""Video generation pipeline: TTS -> timing -> per-slide segments -> MP4 + SRT.

Engines:
  * TTS: per-slide narration audio from src/backend/tts (Kokoro-82M by default), generated if missing.
  * Video: ffmpeg (system binary, or the one bundled by `imageio-ffmpeg`).
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.backend.tts import service as tts
from src.backend.video import transitions as tx
from src.backend.video.timing import RenderSettings, TimingPlan, fmt_duration, plan_timing
from src.models.project import Project
from src.utils.logging_config import setup_logger
from src.utils.process_utils import find_tool, no_window_kwargs

logger = setup_logger("video_pipeline")

Progress = Callable[[int, str], None]


class PipelineError(RuntimeError):
    pass


class Cancelled(PipelineError):
    pass


# ------------------------------------------------------------------ tools
def ffmpeg_path() -> Optional[str]:
    """Prefer the ffmpeg bundled with `imageio-ffmpeg` (same recent build on Windows, macOS and Linux;
    distro packages such as Ubuntu 22.04's 4.4 lack filters used by some transitions), else the system one.
    Set LECTURE_STUDIO_FFMPEG to force a specific binary."""
    forced = os.environ.get("LECTURE_STUDIO_FFMPEG")
    if forced and os.path.isfile(forced):
        return forced
    try:
        import imageio_ffmpeg  # bundled static ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path):
            _ensure_executable(path)
            return path
    except Exception:
        pass
    return find_tool("ffmpeg")


def _ensure_executable(path: str) -> None:
    """Some installs unpack the bundled binary without the exec bit (macOS/Linux)."""
    if os.name != "nt" and not os.access(path, os.X_OK):
        try:
            os.chmod(path, os.stat(path).st_mode | 0o111)
        except OSError:
            pass


def missing_tools(project: Optional[Project] = None) -> List[str]:
    """What prevents generation (ffmpeg, and the project's TTS engine)."""
    from src.backend.tts.registry import get_engine
    out = []
    if not ffmpeg_path():
        out.append("ffmpeg not found (install ffmpeg or the 'imageio-ffmpeg' Python package).")
    eng = get_engine(project.settings.tts_engine if project else None)
    ok, why = eng.is_installed()
    if not ok:
        out.append(f"TTS engine '{eng.name}' not available: {why}")
    return out


def _run(cmd: List[str], timeout: int = 600) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **no_window_kwargs())
    if proc.returncode != 0:
        raise PipelineError(f"Command failed ({Path(cmd[0]).name}): {proc.stderr.strip()[-800:]}")


# ------------------------------------------------------------------ render helpers
_SR = 44100
# Identical for every clip so they can be joined with stream copy.
_VENC = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-an"]


def _prep(W: int, H: int) -> str:
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")


def _slide_image(project: Project, slide_id: str, number: int) -> Path:
    slide = project.get_slide_by_id(slide_id)
    img = Path(project.project_dir) / (slide.image_path or "") if slide else None
    if not slide or not slide.image_path or not img.is_file():
        raise PipelineError(f"Rendered image missing for slide {number}.")
    return img


def transition_cmd(ff: str, img_a: Path, img_b: Path, key: str, seconds: float, frames: int,
                   W: int, H: int, fps: float) -> List[str]:
    """ffmpeg command (without output options) for a transition clip between two still slides."""
    graph = (f"[0:v]{_prep(W, H)}[a];[1:v]{_prep(W, H)}[b];"
             + tx.filter_graph(key, frames / fps, frames, W, H))
    return [ff, "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", str(fps), "-i", str(img_a),
            "-loop", "1", "-framerate", str(fps), "-i", str(img_b),
            "-filter_complex", graph, "-map", "[v]", "-frames:v", str(frames), "-r", str(fps)]


def _concat(ff: str, files: List[Path], list_file: Path, out: Path) -> None:
    esc = lambda p: p.resolve().as_posix().replace("'", "'\\''")      # concat-list quoting
    list_file.write_text("".join(f"file '{esc(p)}'\n" for p in files), encoding="utf-8")
    _run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)])


def quantize_plan(plan: TimingPlan, fps: float) -> TimingPlan:
    """Snap transitions and slide bodies to whole frames so video, audio and subtitles agree exactly.

    Narration length is kept; the hold absorbs the rounding (never shortened below the plan).
    """
    out = []
    for st in plan.slides:
        tf = tx.frames_for(st.transition_seconds, fps)
        bf = max(math.ceil((st.narration_seconds + st.hold_seconds) * fps - 1e-6), 1)
        out.append(dataclasses.replace(
            st, transition_seconds=round(tf / fps, 6),
            hold_seconds=round(bf / fps - st.narration_seconds, 6)))
    return dataclasses.replace(plan, slides=out)


def _transition_settings(vcfg) -> Dict:
    return {"default": vcfg.transition, "duration": vcfg.transition_duration,
            "per_slide": dict(vcfg.slide_transitions or {})}


# ------------------------------------------------------------------ transition preview
def transition_preview_frames(project: Project, from_slide_id: str, to_slide_id: str, key: str,
                              seconds: float, width: int = 480, hold: float = 0.6,
                              fps: Optional[float] = None):
    """Small RGB frames showing `from` -> `to` with the given effect, rendered by the same filters
    as the final video. Returns (frames: List[bytes], width, height, fps). Still holds before/after
    reuse the same frame object, so memory stays at roughly (transition frames x frame size).
    """
    ff = ffmpeg_path()
    if not ff:
        raise PipelineError("ffmpeg not found.")
    vc = project.settings
    fps = fps or min(vc.fps, 30)
    w = max(int(width) // 2 * 2, 2)
    h = max(int(round(w * vc.height / vc.width)) // 2 * 2, 2)
    a = _slide_image(project, from_slide_id, 0)
    b = _slide_image(project, to_slide_id, 0)
    hold_n = max(int(round(hold * fps)), 1)

    def raw(cmd: List[str], n: int) -> List[bytes]:
        proc = subprocess.run(cmd + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120,
                              **no_window_kwargs())
        if proc.returncode != 0:
            raise PipelineError(f"Preview failed: {proc.stderr.decode(errors='replace').strip()[-400:]}")
        size = w * h * 3
        data = proc.stdout
        return [data[i:i + size] for i in range(0, min(len(data), n * size), size)]

    def still(img: Path) -> bytes:
        return raw([ff, "-loglevel", "error", "-i", str(img), "-vf", _prep(w, h), "-frames:v", "1"], 1)[0]

    first, last = still(a), still(b)
    n = tx.frames_for(seconds, fps)
    mid: List[bytes] = []
    if key != tx.NONE and n > 0:
        mid = raw(transition_cmd(ff, a, b, key, seconds, n, w, h, fps), n)
    return [first] * hold_n + mid + [last] * hold_n, w, h, fps


# ------------------------------------------------------------------ subtitles
def _chunks(script: str, max_words: int = 14) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", tts.clean_text(script))
    out = []
    for s in sentences:
        w = s.split()
        parts = max(1, -(-len(w) // max_words))      # balanced chunks, no 1-word tails
        size = -(-len(w) // parts) if w else 1
        for i in range(0, len(w), size):
            out.append(" ".join(w[i:i + size]))
    return [c for c in out if c]


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(plan: TimingPlan, scripts: Dict[str, str]) -> str:
    entries, t0, idx = [], 0.0, 1
    for st in plan.slides:
        start = t0 + st.transition_seconds          # narration starts once the slide has fully entered
        chunks = _chunks(scripts.get(st.slide_id, ""))
        total_words = sum(len(c.split()) for c in chunks) or 1
        cur = start
        for c in chunks:
            dur = st.narration_seconds * len(c.split()) / total_words
            entries.append(f"{idx}\n{_ts(cur)} --> {_ts(cur + dur)}\n{c}\n")
            cur += dur
            idx += 1
        t0 += st.display_seconds
    return "\n".join(entries)


# ------------------------------------------------------------------ main entry
def generate_video(
    project: Project,
    cfg: RenderSettings,
    progress: Optional[Progress] = None,
    cancel_check: Callable[[], bool] = lambda: False,
) -> Dict:
    """Render the selected slide range to an MP4. Returns the render report (also saved as JSON)."""
    progress = progress or (lambda p, m: None)
    problems = missing_tools(project)
    if problems:
        raise PipelineError(" ".join(problems))
    ff = ffmpeg_path()
    root = Path(project.project_dir)
    vcfg = project.settings
    W, H, fps = vcfg.width, vcfg.height, vcfg.fps

    scripts = {n.slide_id: n.script for n in project.narrations}
    narr_by_id = {n.slide_id: n for n in project.narrations}
    chosen = [s for s in project.slides if cfg.start <= s.slide_number <= cfg.end]

    # 1. Narration audio per slide: reuse what exists, generate what is missing.
    audio: Dict[str, Path] = {}
    measured: Dict[str, float] = {}
    warnings: List[str] = []
    stale = []
    for i, s in enumerate(chosen, 1):
        if cancel_check():
            raise Cancelled("Video generation cancelled.")
        n = narr_by_id.get(s.slide_id)
        if not n or not n.script.strip():
            measured[s.slide_id] = 0.0
            continue
        state = tts.audio_state(project, n)
        if state in (tts.NONE, tts.MISSING) or (state == tts.OUTDATED and cfg.regenerate_outdated):
            progress(2 + int(38 * i / len(chosen)), f"Generating narration audio for slide {s.slide_number}…")
            tts.generate_slide_audio(project, n)
        elif state == tts.OUTDATED:
            stale.append(s.slide_number)
        audio[s.slide_id] = tts.slide_audio_path(project, n)
        measured[s.slide_id] = tts.wav_seconds(audio[s.slide_id])
        progress(2 + int(38 * i / len(chosen)), f"Narration audio {i}/{len(chosen)} (slide {s.slide_number})")
    if stale:
        warnings.append(f"Used existing (outdated) audio for slides {stale}; regenerate them in Narration Studio "
                        "or tick 'Regenerate outdated audio'.")

    # 2. Timing from real audio lengths; tempo may be adjusted within limits.
    incoming = tx.incoming(vcfg, [s.slide_id for s in chosen])
    plan = plan_timing(project.slides, project.narrations, cfg, measured=measured, transitions=incoming)
    plan = quantize_plan(plan, fps)
    warnings = list(dict.fromkeys(warnings + plan.warnings))
    tempo = plan.speed

    # 3. Per slide: [silent transition clip from the previous slide] + [slide body]; video-only clips
    #    with identical encoding are joined losslessly. Audio is built as one sample-exact PCM track.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = re.sub(r"[^\w-]+", "_", cfg.name.strip()) if cfg.name.strip() else project.project_id
    out_stem = f"{base}_slides_{cfg.start:03d}-{cfg.end:03d}_{stamp}"
    vid_dir = root / "video"
    vid_dir.mkdir(parents=True, exist_ok=True)
    (root / "cache").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="render_", dir=root / "cache"))
    try:
        clips, wavs, prev_img = [], [], None
        for i, st in enumerate(plan.slides, 1):
            if cancel_check():
                raise Cancelled("Video generation cancelled.")
            img = _slide_image(project, st.slide_id, st.slide_number)
            tf = tx.frames_for(st.transition_seconds, fps)
            bf = tx.frames_for(st.narration_seconds + st.hold_seconds, fps)
            if tf > 0 and prev_img is not None:
                clip = work / f"t_{i:04d}.mp4"
                _run(transition_cmd(ff, prev_img, img, st.transition_type, st.transition_seconds, tf, W, H, fps)
                     + _VENC + [str(clip)])
                clips.append(clip)
            clip = work / f"s_{i:04d}.mp4"
            _run([ff, "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(img),
                  "-vf", _prep(W, H), "-frames:v", str(bf)] + _VENC + [str(clip)])
            clips.append(clip)

            wav = work / f"a_{i:04d}.wav"
            total_samples = round((tf + bf) / fps * _SR)
            delay = round(tf / fps * _SR)
            cmd = [ff, "-y", "-loglevel", "error"]
            has_audio = st.slide_id in audio
            cmd += ["-i", str(audio[st.slide_id])] if has_audio else ["-f", "lavfi", "-i", f"anullsrc=r={_SR}:cl=stereo"]
            tempo_f = f"atempo={tempo:.4f}," if has_audio and abs(tempo - 1.0) > 1e-3 else ""
            cmd += ["-af", f"{tempo_f}aresample={_SR},aformat=sample_fmts=s16:channel_layouts=stereo,"
                           f"adelay={delay}S:all=1,apad,atrim=end_sample={total_samples}",
                    "-c:a", "pcm_s16le", str(wav)]
            _run(cmd)
            wavs.append(wav)
            prev_img = img
            progress(40 + int(50 * i / len(plan.slides)), f"Rendering slide {st.slide_number} ({i}/{len(plan.slides)})")

        progress(92, "Joining segments and adding subtitles…")
        joined_v, joined_a = work / "joined.mp4", work / "joined.wav"
        _concat(ff, clips, work / "v.txt", joined_v)
        _concat(ff, wavs, work / "a.txt", joined_a)

        srt = vid_dir / f"{out_stem}.srt"
        srt_text = build_srt(plan, scripts)
        srt.write_text(srt_text, encoding="utf-8")
        mp4 = vid_dir / f"{out_stem}.mp4"
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(joined_v), "-i", str(joined_a)]
        subs = ["-i", str(srt)] if srt_text.strip() else []          # silent ranges have no subtitles
        cmd += subs + ["-map", "0:v", "-map", "1:a"] + (["-map", "2", "-c:s", "mov_text",
                                                          "-metadata:s:s:0", "language=eng"] if subs else [])
        _run(cmd + ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(mp4)])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if cfg.target_seconds and abs(plan.total_seconds - cfg.target_seconds) > max(15, 0.05 * cfg.target_seconds):
        warnings.append(f"Final length {fmt_duration(plan.total_seconds)} differs from target "
                        f"{fmt_duration(cfg.target_seconds)} (real speech length differs from the estimate).")

    report = {
        "video": mp4.name, "subtitles": srt.name, "created": datetime.now().isoformat(timespec="seconds"),
        "settings": cfg.to_dict(), "transitions": _transition_settings(vcfg), "speed_used": plan.speed, "tts_engine": project.settings.tts_engine,
        "total_seconds": round(plan.total_seconds, 2), "narration_seconds": round(plan.narration_seconds, 2),
        "slide_count": len(plan.slides), "warnings": warnings,
        "timeline": [{"slide": t.slide_number, "title": t.title, "narration": t.narration_seconds,
                      "speaker": tts.slide_speaker(project, narr_by_id[t.slide_id]) if t.slide_id in narr_by_id else "",
                      "hold": t.hold_seconds, "transition": t.transition_seconds,
                      "transition_type": t.transition_type,
                      "display": round(t.display_seconds, 3)} for t in plan.slides],
    }
    (vid_dir / f"{out_stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    progress(100, f"Done: {mp4.name} ({fmt_duration(plan.total_seconds)})")
    logger.info(f"Generated {mp4} ({plan.total_seconds:.1f}s, {len(plan.slides)} slides)")
    return report


def list_generated(project: Project) -> List[Dict]:
    """Previously generated videos (newest first), read from their JSON reports."""
    vid_dir = Path(project.project_dir) / "video"
    out = []
    for j in sorted(vid_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (vid_dir / data.get("video", "")).is_file():
            data["path"] = str(vid_dir / data["video"])
            out.append(data)
    return out
