import json
import sys
from pathlib import Path

from icewolf.desktop import main


def verify_install(report_path: str) -> int:
    try:
        import google_auth_httplib2
        import keyring.backends.Windows
        import pypdf
        import docx
        import sounddevice
        from icewolf.audio import VoicePipeline
        from icewolf.desktop import create_speaker, default_whisper_path
        from icewolf.vad import SileroDetector

        model = default_whisper_path()
        if not model:
            raise RuntimeError("No cached local Whisper model found.")
        VoicePipeline(Path(model), speak=False)
        SileroDetector()
        create_speaker()
        result = {"ok": True}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    Path(report_path).write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-install":
        raise SystemExit(verify_install(sys.argv[2]))
    raise SystemExit(main())
