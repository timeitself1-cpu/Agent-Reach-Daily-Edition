"""Daily podcast: script, SSML, recording with a stand-in speech engine, refresh, CLI and window."""

from __future__ import annotations

import base64
import wave
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from agent_reach.daily import podcast as P
from agent_reach.daily.prefs import DailyPrefs
from agent_reach.daily.store import EditionStore
from tests.daily_fakes import make_edition, make_story

T0 = datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc)


def _edition():
    stories = [
        make_story(headline="Norvale Ferry Strike Halts Island Service", now=T0, url="https://wire-one.test/a",
                   sentences=["Ferry workers began a 48-hour strike over pay.", "Talks resume on Friday."],
                   why="Island residents lose their ferry link while the strike lasts."),
        make_story(headline="Port Calder Quake Damages Roads & Bridges", now=T0, url="https://wire-one.test/b",
                   sentences=["A magnitude 6.8 earthquake struck near Port Calder; 30% of roads closed."]),
        make_story(headline="Riverton Hawks Win Championship Final", category="Sports", now=T0,
                   url="https://wire-one.test/c"),
        make_story(headline="Crypto Exchange Halts Withdrawals", category="Tech", now=T0, url="https://wire-one.test/d"),
    ]
    ed = make_edition(stories, started=T0)
    ed.top_ranks = [1, 2]
    return ed


def _fake_engine(calls: list):
    def synth(ssml: str, text: str, out: Path, voice: str, rate: int) -> None:
        calls.append((ssml, text, voice, rate))
        with wave.open(str(out), "wb") as w:  # one second of silence
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 8000)

    return synth


def test_script_reads_the_edition_and_nothing_else():
    text = P.script_text(P.build_script(_edition(), stories=8, mute=["crypto"], follow=[]))
    assert text.startswith("This is Agent Reach Daily for Thursday, October 1, 2026.")
    assert "Our top story.\nNorvale Ferry Strike Halts Island Service." in text
    assert "Why it matters: Island residents lose their ferry link while the strike lasts." in text
    assert "Reported by Wire One." in text
    assert "Port Calder Quake Damages Roads and Bridges." in text and "30 percent of roads" in text
    assert "In Sports.\nRiverton Hawks Win Championship Final." in text  # quick round of the sections
    assert "Crypto" not in text  # muted
    assert text.rstrip().endswith("Thanks for listening.") and "http" not in text


def test_followed_topics_and_demo_notice():
    ed = _edition()
    text = P.script_text(P.build_script(ed, stories=1, follow=["Hawks"]))
    assert "From the topics you follow.\nRiverton Hawks Win Championship Final." in text
    assert text.count("Riverton Hawks Win Championship Final") == 1  # not repeated in the quick round
    ed.demo = True
    assert "demo edition with made up stories" in P.script_text(P.build_script(ed))


def test_ssml_is_valid_and_escaped():
    segs = [P.Segment("Fish & <chips>", 500), P.Segment("Done.", 0)]
    ssml = P.to_ssml(segs)
    root = ET.fromstring(ssml)
    assert root.tag.endswith("speak") and "Fish &amp; &lt;chips&gt;" in ssml and '<break time="500ms"/>' in ssml
    assert P.speakable("Visit https://x.test now & save 5%") == "Visit now and save 5 percent."


def test_make_podcast_records_audio_and_transcript_and_purges_old(daily_paths):
    old = daily_paths.podcasts_dir / "2026-09-01.wav"
    daily_paths.podcasts_dir.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"x" * 100)
    calls: list = []
    prefs = DailyPrefs(podcast_voice="Microsoft Zira Desktop", podcast_rate=2)
    result = P.make_podcast(daily_paths, _edition(), prefs, synthesizer=_fake_engine(calls))
    assert result.ok and result.audio == daily_paths.podcasts_dir / "2026-10-01.wav"
    assert result.audio.exists() and result.transcript.read_text().startswith("This is Agent Reach Daily")
    assert result.seconds == pytest.approx(1.0) and calls[0][2:] == ("Microsoft Zira Desktop", 2)
    assert calls[0][0].startswith("<speak") and not old.exists()  # older than 7 days: removed
    assert P.existing_podcast(daily_paths, date(2026, 10, 1)) == result.audio
    assert not list(daily_paths.podcasts_dir.glob("*.part.wav"))


def test_failures_are_reported_never_raised(daily_paths, monkeypatch):
    def broken(*a):
        raise P.SynthesisError("voice not installed")

    result = P.make_podcast(daily_paths, _edition(), DailyPrefs(), synthesizer=broken)
    assert not result.ok and "voice not installed" in result.message and result.transcript.exists()
    assert not list(daily_paths.podcasts_dir.glob("*.wav"))
    monkeypatch.setattr(P, "default_synthesizer", lambda: None)
    result = P.make_podcast(daily_paths, _edition(), DailyPrefs())
    assert not result.ok and "No speech engine" in result.message


def test_windows_engine_runs_powershell_with_paths_in_the_environment(monkeypatch, tmp_path):
    seen = {}

    def fake_run(args, env=None, timeout=0):
        seen["args"], seen["env"] = args, env
        seen["ssml"] = Path(env["AR_SSML"]).read_text(encoding="utf-8")
        return ""

    monkeypatch.setattr(P, "_run", fake_run)
    P.windows_synthesizer("<speak>Hi</speak>", "Hi", tmp_path / "x.wav", "", 3)
    args = seen["args"]
    assert args[0] == "powershell.exe" and "-EncodedCommand" in args
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert "SetOutputToWaveFile($env:AR_OUT" in script and "SpeakSsml" in script and script.isascii()
    assert seen["env"]["AR_OUT"] == str(tmp_path / "x.wav") and seen["env"]["AR_RATE"] == "3"
    assert seen["ssml"] == "<speak>Hi</speak>"


def test_refresh_records_the_podcast_and_survives_its_failure(daily_env, monkeypatch):
    from agent_reach.daily import refresh as R
    from tests.daily_fakes import OllamaUp

    calls: list = []
    monkeypatch.setattr(P, "default_synthesizer", lambda: _fake_engine(calls))
    out = R.refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_PUBLISHED and "Podcast ready" in out.message
    assert P.existing_podcast(daily_env.paths, out.edition.edition_date) is not None

    def boom():
        raise RuntimeError("engine crashed")

    monkeypatch.setattr(P, "default_synthesizer", boom)
    out = R.refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_PUBLISHED  # the edition never depends on the podcast


def test_cli_records_a_podcast(daily_paths, monkeypatch, capsys):
    from agent_reach.daily.__main__ import main

    assert main(["--podcast", "--data-dir", str(daily_paths.root)]) == 2  # no edition yet
    EditionStore(daily_paths).publish(_edition())
    monkeypatch.setattr(P, "default_synthesizer", lambda: _fake_engine([]))
    assert main(["--podcast", "--data-dir", str(daily_paths.root)]) == 0
    assert "Podcast ready" in capsys.readouterr().out


def test_openers_vary_and_bare_web_addresses_are_not_read():
    from agent_reach.daily.edition import EvidenceLink

    stories = [make_story(headline=f"Headline Number {n} Happens", now=T0, url=f"https://wire-one.test/{n}")
               for n in ("one", "two", "three", "four", "five", "six", "seven")]
    stories[2].evidence = [EvidenceLink(item_id=1, source="hackernews", source_name="Hacker News", title="x",
                                        url="https://cpr.dk/x", publisher="cpr.dk")]
    ed = make_edition(stories, started=T0)
    text = P.script_text(P.build_script(ed, stories=7))
    openers = [line for line in text.splitlines() if line in P.OPENERS]
    assert openers == ["Our top story.", "Next.", "Also today.", "Meanwhile.", "In other news.", "Also today.",
                       "Meanwhile."]
    assert "cpr.dk" not in text
