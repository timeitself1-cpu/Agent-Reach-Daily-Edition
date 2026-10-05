"""Daily podcast: a spoken version of the edition, made on this PC.

The script is built deterministically from the edition's validated text (headlines, summaries,
grounded "why it matters" notes and the publishers that reported each story). The model writes
nothing new for it, so the podcast says exactly what the reader sees. It is spoken by the speech
engine built into Windows (System.Speech, the voices under Settings > Time & language > Speech),
run through Windows PowerShell; no download, account or cloud service is involved. Elsewhere
``espeak-ng`` is used when installed.

Output (data folder, never the repository): ``podcasts/YYYY-MM-DD.wav`` plus a transcript
``YYYY-MM-DD.txt``. Making a podcast never affects the edition: a failure is only reported.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from agent_reach.daily.edition import DailyEdition, Story, category_sections, top_stories
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.strength import strength_of
from agent_reach.daily.timeutil import format_long_date

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
SYNTH_TIMEOUT_S = 900
QUICK_HITS_PER_SECTION = 2
OPENERS = ("Our top story.", "Next.", "Also today.", "Meanwhile.", "In other news.")


@dataclass
class Segment:
    text: str
    pause_ms: int = 500  # silence after this segment


@dataclass
class PodcastResult:
    ok: bool
    message: str
    audio: Path | None = None
    transcript: Path | None = None
    seconds: float = 0.0


class SynthesisError(Exception):
    pass


#: (ssml, plain text, output .wav, voice name or "", rate -5..5) -> writes the file or raises
Synthesizer = Callable[[str, str, Path, str, int], None]


# ====================================================================== script
_URL_RX = re.compile(r"https?://\S+|www\.\S+")
_HOST_RX = re.compile(r"\.[a-z]{2,}$", re.IGNORECASE)


def speakable(text: str) -> str:
    """Text a speech engine reads naturally: no links, symbols spelled out, no ellipses."""
    t = _URL_RX.sub("", text or "")
    t = t.replace("&", " and ").replace("%", " percent").replace("...", ".").replace("…", ".")
    t = re.sub(r"\bvs\.?(?=\s)", "versus", t, flags=re.IGNORECASE)
    t = re.sub(r"[\[\]{}<>|#*_~^]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if not t or t[-1] in ".!?" else t + "."


def _names(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def build_script(edition: DailyEdition, *, stories: int = 8, mute: list[str] | None = None,
                 follow: list[str] | None = None) -> list[Segment]:
    """Intro, the top stories in full, quick headlines from each section, stories you follow, outro."""
    from agent_reach.daily.reading import followed, without_muted

    day = f"{edition.edition_date:%A}, {format_long_date(edition.edition_date)}"
    segs = [Segment(f"This is Agent Reach Daily for {day}.", 400)]
    if edition.demo:
        segs.append(Segment("This is a demo edition with made up stories, not real news.", 600))
    top, _ = without_muted(top_stories(edition), mute or [])
    top = top[:stories]
    segs.append(Segment(f"Here are today's top {len(top)} stories." if len(top) > 1 else "Here is today's top story.",
                        900))
    told: set[int] = set()
    for i, s in enumerate(top):
        opener = OPENERS[i] if i < len(OPENERS) else OPENERS[2 + (i - len(OPENERS)) % (len(OPENERS) - 2)]
        segs.extend(_story_segments(s, edition, opener))
        told.add(s.rank)
    mine = [s for s in without_muted(followed(edition.stories, follow or []), mute or [])[0] if s.rank not in told]
    if mine:
        segs.append(Segment("From the topics you follow.", 500))
        for s in mine[:4]:
            segs.append(Segment(speakable(s.headline), 300))
            told.add(s.rank)
    hits: list[Segment] = []
    for category, items in category_sections(edition):
        rest = [s for s in without_muted(items, mute or [])[0] if s.rank not in told][:QUICK_HITS_PER_SECTION]
        if rest:
            hits.append(Segment(f"In {category.replace('&', 'and')}.", 250))
            hits.extend(Segment(speakable(s.headline), 350) for s in rest)
    if hits:
        segs.append(Segment("Now, a quick look around the sections.", 600))
        segs.extend(hits)
    segs.append(Segment(f"That's Agent Reach Daily for {day}. Every summary comes from the reports cited in the "
                        "app, where you can open the sources. Thanks for listening.", 0))
    return segs


def _story_segments(story: Story, edition: DailyEdition, opener: str) -> list[Segment]:
    out = [Segment(opener, 250), Segment(speakable(story.headline), 450),
           Segment(" ".join(speakable(x) for x in story.sentences), 350)]
    if story.why_it_matters:
        out.append(Segment("Why it matters: " + speakable(story.why_it_matters), 350))
    # named publishers only: a bare web address ('cpr.dk') sounds like noise when spoken
    publishers = [p for p in strength_of(story, edition.generation_completed_utc).publishers if not _HOST_RX.search(p)]
    if publishers:
        more = len(publishers) - 3
        names = _names(publishers[:3]) + (f", and {more} more" if more > 0 else "")
        out.append(Segment(f"Reported by {names}.", 900))
    else:
        out[-1].pause_ms = 900
    return out


def script_text(segments: list[Segment]) -> str:
    """The transcript: one paragraph per story block."""
    lines: list[str] = []
    for seg in segments:
        lines.append(seg.text)
        if seg.pause_ms >= 800:
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def to_ssml(segments: list[Segment]) -> str:
    body = "".join(f"{escape(s.text)}" + (f'<break time="{s.pause_ms}ms"/>' if s.pause_ms else " ")
                   for s in segments)
    return ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f"{body}</speak>")


# ====================================================================== speech engines
_WINDOWS_SCRIPT = r"""
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:AR_VOICE) { try { $s.SelectVoice($env:AR_VOICE) } catch { } }
$s.Rate = [int]$env:AR_RATE
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:AR_OUT, $fmt)
$ssml = [System.IO.File]::ReadAllText($env:AR_SSML, [System.Text.Encoding]::UTF8)
$ssml = $ssml.Replace('xml:lang="en-US"', 'xml:lang="' + $s.Voice.Culture.Name + '"')
$s.SpeakSsml($ssml)
$s.Dispose()
"""

_WINDOWS_VOICES = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }
$s.Dispose()
"""


def powershell_args(script: str) -> list[str]:
    """Windows PowerShell 5.1 with the script passed as -EncodedCommand (no quoting pitfalls)."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", encoded]


def _run(args: list[str], env: dict[str, str] | None = None, timeout: float = SYNTH_TIMEOUT_S) -> str:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, creationflags=flags,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SynthesisError(f"{type(exc).__name__}: {exc}") from exc
    if done.returncode != 0:
        raise SynthesisError((done.stderr or done.stdout or f"exit code {done.returncode}").strip()[:300])
    return done.stdout


def windows_synthesizer(ssml: str, text: str, out: Path, voice: str, rate: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ssml_path = Path(tmp) / "script.xml"
        ssml_path.write_text(ssml, encoding="utf-8")
        env = {**os.environ, "AR_SSML": str(ssml_path), "AR_OUT": str(out), "AR_VOICE": voice or "",
               "AR_RATE": str(max(-10, min(10, rate)))}
        _run(powershell_args(_WINDOWS_SCRIPT), env=env)


def espeak_synthesizer(ssml: str, text: str, out: Path, voice: str, rate: int) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise SynthesisError("espeak-ng is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "script.txt"
        src.write_text(text, encoding="utf-8")
        args = [exe, "-w", str(out), "-s", str(165 + 15 * rate), "-f", str(src)]
        if voice:
            args[1:1] = ["-v", voice]
        _run(args)


def default_synthesizer() -> Synthesizer | None:
    if sys.platform == "win32":
        return windows_synthesizer
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return espeak_synthesizer
    return None


def list_voices() -> list[str]:
    """Installed voices (Windows); empty when they cannot be listed. Never raises."""
    if sys.platform != "win32":
        return []
    try:
        return [v.strip() for v in _run(powershell_args(_WINDOWS_VOICES), timeout=60).splitlines() if v.strip()]
    except SynthesisError:
        return []


# ====================================================================== files
def podcast_paths(paths: DataPaths, day: date) -> tuple[Path, Path]:
    base = paths.podcasts_dir / day.isoformat()
    return base.with_suffix(".wav"), base.with_suffix(".txt")


def existing_podcast(paths: DataPaths, day: date) -> Path | None:
    audio, _ = podcast_paths(paths, day)
    return audio if audio.exists() and audio.stat().st_size > 44 else None


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (OSError, wave.Error, EOFError):
        return 0.0


def purge_podcasts(paths: DataPaths, keep_days: int, today: date) -> int:
    """Delete podcasts older than ``keep_days`` (by the date in their file name)."""
    removed = 0
    if not paths.podcasts_dir.is_dir():
        return 0
    cutoff = today - timedelta(days=keep_days - 1)
    for p in paths.podcasts_dir.iterdir():
        try:
            day = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if day < cutoff and p.suffix in (".wav", ".txt"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def make_podcast(paths: DataPaths, edition: DailyEdition, prefs, *, synthesizer: Synthesizer | None = None,
                 today: date | None = None) -> PodcastResult:
    """Write the transcript and record the audio for ``edition``. Never raises."""
    segments = build_script(edition, stories=prefs.podcast_stories, mute=prefs.mute_topics,
                            follow=prefs.follow_topics)
    audio, transcript = podcast_paths(paths, edition.edition_date)
    paths.podcasts_dir.mkdir(parents=True, exist_ok=True)
    text = script_text(segments)
    try:
        transcript.write_text(text, encoding="utf-8")
    except OSError as exc:
        return PodcastResult(False, f"Could not save the podcast transcript: {exc}")
    synth = synthesizer or default_synthesizer()
    if synth is None:
        return PodcastResult(False, "No speech engine was found. Podcasts use the speech voices built into "
                                    "Windows (or espeak-ng elsewhere).", transcript=transcript)
    partial = audio.with_name(audio.stem + ".part.wav")
    try:
        synth(to_ssml(segments), text, partial, prefs.podcast_voice, prefs.podcast_rate)
        if not partial.exists() or partial.stat().st_size <= 44:
            raise SynthesisError("the speech engine produced no audio")
        os.replace(partial, audio)
    except (SynthesisError, OSError) as exc:
        try:
            partial.unlink()
        except OSError:
            pass
        log.warning("podcast not recorded: %s", exc)
        return PodcastResult(False, f"The podcast could not be recorded: {str(exc)[:200]}", transcript=transcript)
    purge_podcasts(paths, prefs.podcast_keep_days, today or edition.edition_date)
    seconds = wav_seconds(audio)
    log.info("podcast recorded: %s (%.0f s)", audio.name, seconds)
    minutes = max(1, round(seconds / 60)) if seconds else 0
    return PodcastResult(True, f"Podcast ready{f' ({minutes} min)' if minutes else ''}.", audio, transcript, seconds)
