"""Run Icewolf with ``python -m icewolf``."""

import argparse
import os
from pathlib import Path
import sys

from .audio import SAMPLE_RATE, PiperSpeaker, SystemSpeaker, VoicePipeline
from .ollama import OllamaClient
from .openai_local import LocalOpenAIClient


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Icewolf: an offline, push-to-talk assistant")
    parser.add_argument("--model", default="llama3.2:3b", help="Local model ID")
    parser.add_argument("--backend", choices=("ollama", "openai"), default="ollama",
                        help="Local LLM backend (default: ollama)")
    parser.add_argument("--llm-port", type=int, default=1234,
                        help="Loopback port for OpenAI-compatible backend (default: 1234)")
    parser.add_argument(
        "--whisper-model", default=os.environ.get("ICEWOLF_WHISPER_MODEL"),
        help="Path to a local faster-whisper model directory",
    )
    parser.add_argument("--seconds", type=float, default=5, help="Recording length or maximum with --auto-stop (1-30 seconds)")
    parser.add_argument("--auto-stop", action="store_true", help="Stop after speech and a pause")
    parser.add_argument("--vad", choices=("energy", "silero"), default="energy",
                        help="Speech detection for --auto-stop (default: energy)")
    parser.add_argument("--vad-threshold", type=float, default=0.5,
                        help="Silero speech probability threshold (0-1, default 0.5)")
    wake_group = parser.add_mutually_exclusive_group()
    wake_group.add_argument(
        "--wake", dest="wake_model", action="store_const",
        const="icewolf",
        help="Opt into experimental local Hey Icewolf voice recognition",
    )
    wake_group.add_argument("--wake-model", help="Opt into listening with a custom openWakeWord ONNX model")
    parser.add_argument("--wake-threshold", type=float, default=0.5,
                        help="Wake-word confidence threshold (0-1, default 0.5)")
    parser.add_argument(
        "--speech-threshold", type=float, default=0.01,
        help="Audio level for --auto-stop (greater than 0 and at most 1; default 0.01)",
    )
    parser.add_argument("--text", action="store_true", help="Type instead of recording audio")
    parser.add_argument("--no-speech", action="store_true", help="Print replies without speech")
    parser.add_argument("--tts", choices=("piper", "system"), default="piper",
                        help="Speech engine (default: piper)")
    parser.add_argument(
        "--piper-length-scale", type=float, default=1.0,
        help="Piper speech duration scale: higher is slower (0.5-2.0, default 1.0)",
    )
    parser.add_argument(
        "--piper-model",
        default=os.environ.get(
            "ICEWOLF_PIPER_MODEL",
            str(Path(__file__).resolve().parent.parent / "models" / "piper" / "en_US-ryan-medium.onnx"),
        ),
        help="Path to local Piper .onnx voice (requires matching .onnx.json)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 30:
        parser.error("--seconds must be between 1 and 30")
    if not 1 <= args.llm_port <= 65535:
        parser.error("--llm-port must be between 1 and 65535")
    if not 0 < args.speech_threshold <= 1:
        parser.error("--speech-threshold must be greater than 0 and at most 1")
    if not 0 < args.vad_threshold <= 1:
        parser.error("--vad-threshold must be greater than 0 and at most 1")
    if not 0 < args.wake_threshold <= 1:
        parser.error("--wake-threshold must be greater than 0 and at most 1")
    if args.wake_model and args.text:
        parser.error("--wake-model cannot be used with --text")
    if args.vad != "energy" and not args.auto_stop:
        parser.error("--vad silero requires --auto-stop")
    if not 0.5 <= args.piper_length_scale <= 2.0:
        parser.error("--piper-length-scale must be between 0.5 and 2.0")
    if not args.text and not args.whisper_model:
        parser.error("set --whisper-model or ICEWOLF_WHISPER_MODEL for voice input")
    return args


def run(args) -> None:
    client = (LocalOpenAIClient(args.model, port=args.llm_port)
              if args.backend == "openai" else OllamaClient(args.model))
    client.check_model()
    voice = None
    if not args.text:
        print("Loading the local speech model...")
        voice = VoicePipeline(Path(args.whisper_model), speak=False)
    wake = None
    if args.wake_model:
        from .wake import IcewolfPhraseListener, WakeWordListener
        wake = (IcewolfPhraseListener(voice) if args.wake_model == "icewolf"
                else WakeWordListener(Path(args.wake_model), threshold=args.wake_threshold))
    speaker = None
    if not args.no_speech:
        speaker = (PiperSpeaker(Path(args.piper_model), length_scale=args.piper_length_scale)
                   if args.tts == "piper" else SystemSpeaker())
    print("Icewolf ready. Press Ctrl+C or Ctrl+Z then Enter to exit.")
    if args.text:
        print("Type /clear to forget this conversation.")
    while True:
        if args.text:
            text = input("\nYou: ").strip()
        elif wake:
            print("\nWake listening enabled. Say the phrase for your selected model. Ctrl+C exits.", flush=True)
            try:
                with voice.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
                    wake.wait(stream)
                with voice.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
                    print(f"Wake detected. Speak now (up to {args.seconds:g} seconds)...", flush=True)
                    audio = voice._record_until_silence(
                        args.seconds, args.speech_threshold, "silero", args.vad_threshold, stream
                    )
            except (OSError, ValueError, voice.sd.PortAudioError) as exc:
                raise RuntimeError(f"Microphone recording failed: {exc}") from exc
            text = voice.transcribe(audio) if audio is not None else ""
            print(f"You: {text or '[no speech recognized]'}")
        else:
            input("\nPress Enter to record...")
            if args.auto_stop:
                print(f"Listening (up to {args.seconds:g} seconds; stops after a pause)...")
                if args.vad == "silero":
                    text = voice.record_and_transcribe(
                        args.seconds, auto_stop=True, speech_threshold=args.speech_threshold,
                        vad="silero", vad_threshold=args.vad_threshold,
                    )
                else:
                    text = voice.record_and_transcribe(
                        args.seconds, auto_stop=True, speech_threshold=args.speech_threshold
                    )
            else:
                print(f"Listening for {args.seconds:g} seconds...")
                text = voice.record_and_transcribe(args.seconds)
            print(f"You: {text or '[no speech recognized]'}")
        if not text:
            continue
        if args.text and text == "/clear":
            client.clear_history()
            print("Conversation cleared.")
            continue
        print("Thinking...")
        reply = client.reply(text)
        print(f"Icewolf: {reply}")
        if speaker:
            speaker.say(reply)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Icewolf error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
