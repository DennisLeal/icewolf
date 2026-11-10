"""Local PyQt desktop interface: ``python -m icewolf.desktop``."""

import os
import math
import re
import logging
import queue
from pathlib import Path
import sqlite3
import sys
import threading

import psutil
from PyQt6.QtCore import QDateTime, QPointF, QProcess, QRectF, QSettings, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QDoubleSpinBox, QMainWindow,
    QMenu, QPlainTextEdit, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .agents import AgentStore, BUILTIN_ROLES
from .audio import SAMPLE_RATE, KokoroSpeaker, SpeechTooLong, VoicePipeline
from . import gmail
from . import github_repo
from .ollama import OllamaClient, RESPONSE_LANGUAGES
from .wake import IcewolfPhraseListener

ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    if getattr(sys, "frozen", False):
        if not os.environ.get("LOCALAPPDATA"):
            raise RuntimeError("LOCALAPPDATA is required for the installed Icewolf application.")
        return Path(os.environ["LOCALAPPDATA"]) / "Icewolf" / "UserData"
    return ROOT


KOKORO_MODEL = data_root() / "models" / "kokoro" / "kokoro-v1.0.onnx"
KOKORO_VOICES = data_root() / "models" / "kokoro" / "voices-v1.0.bin"
CONVERSATION_SILENCE_SECONDS = 3.0
CONVERSATION_MAX_SECONDS = 300
PROJECT_LINKS = (
    "Icewolf repository: https://github.com/DennisLeal/icewolf\n"
    "Jarvis inspiration: https://github.com/ethanplusai/jarvis"
)
PRESENTATION_LINKS = {
    "show icewolf release link": ("Icewolf release", "https://github.com/DennisLeal/icewolf/releases/tag/v0.2.0"),
    "show ollama download link": ("Ollama for Windows", "https://ollama.com/download/windows"),
    "show git download link": ("Git for Windows", "https://git-scm.com/download/win"),
    "show icewolf clone link": ("Icewolf clone URL", "https://github.com/DennisLeal/icewolf.git"),
    "show kokoro download link": (
        "Kokoro download base URL",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1",
    ),
    "show icewolf repository link": ("Icewolf repository", "https://github.com/DennisLeal/icewolf"),
    "show jarvis repository link": ("Jarvis repository", "https://github.com/ethanplusai/jarvis"),
}
LINK_DISPLAY_MS = 15000
PRESENTATION_CUES = (
    ("icewolf release page", "show icewolf release link"),
    ("ollama for windows", "show ollama download link"),
    ("git for windows", "show git download link"),
    ("icewolf clone address", "show icewolf clone link"),
    ("kokoro download address", "show kokoro download link"),
    ("icewolf repository", "show icewolf repository link"),
    ("original jarvis repository", "show jarvis repository link"),
)


def system_reduced_motion() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    enabled = wintypes.BOOL()
    if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
        logging.warning("Could not read Windows animation preference; use Configuration to reduce motion.")
        return False
    return not bool(enabled.value)


def create_speaker():
    return KokoroSpeaker(KOKORO_MODEL, KOKORO_VOICES, "am_adam")


def default_whisper_path() -> str:
    configured = os.environ.get("ICEWOLF_WHISPER_MODEL")
    if configured:
        return configured
    snapshots = (
        Path.home() / ".cache" / "huggingface" / "hub" /
        "models--Systran--faster-whisper-base.en" / "snapshots"
    )
    if snapshots.is_dir():
        candidates = sorted(p for p in snapshots.iterdir() if (p / "model.bin").is_file())
        if candidates:
            return str(candidates[-1])
    return ""


def is_inbox_report_request(text: str) -> bool:
    request = text.lower().replace("e-mail", "email").replace("’", "'")
    request = re.sub(r"[,.?!]", " ", request)
    request = " ".join(request.split())
    request = re.sub(r"^(?:(?:hey )?ice\s*wolf\s+)?", "", request)
    request = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", request)
    request = re.sub(r"(?:\s+(?:for me|please|right now|now))+$", "", request)
    mailbox = r"(?:gmail|emails?|mail|inbox|(?:connected )?email account)"
    messages = r"(?:(?:new|latest|recent) )?(?:emails?|mail)"
    five = r"(?:(?:the|my) )?(?:first|latest|last|most recent) (?:five|5)"
    return bool(re.fullmatch(
        rf"(?:(?:check|read|show|show me|look at) (?:my |the )?"
        rf"(?:(?:new|latest|recent) )?{mailbox}"
        r"|(?:gmail|email|inbox) report"
        r"|report my gmail"
        r"|give me (?:an? |my |the )?(?:gmail|email|inbox) report"
        r"|what(?:'s|s| is) (?:going on in |in )(?:my |the )?(?:gmail|inbox)"
        rf"|(?:check if|see if) i have (?:any )?{messages}"
        rf"|do i have (?:any )?{messages}"
        rf"|are there (?:any )?(?:(?:new|latest|recent) )?messages in (?:my |the )?inbox"
        rf"|what {messages} do i have)",
        request,
    ) or re.fullmatch(
        rf"(?:read(?: me| out loud| out| aloud)?|check|show(?: me)?|report|tell me) "
        rf"{five} (?:emails?|messages)(?: (?:in|from|of) (?:my |the )?(?:inbox|gmail))?"
        rf"(?: (?:aloud|out loud|to me))?",
        request,
    ))


def gmail_tools_action(text: str) -> str | None:
    normalized = text.lower().replace("’", "'").replace("e-mail", "email")
    if re.search(r"\b(?:do not|don't|never|delete|trash|outlook|yahoo)\b", normalized):
        return None
    mailbox = re.search(r"\b(?:gmail|emails?|mail|inbox|messages?)\b", normalized) or re.search(
        r"\b(?:reply to|mark|archive|star|unstar|flag|unflag)\s+(?:that|this|it)\b", normalized
    )
    if not mailbox:
        return None
    if (re.search(r"\b(?:all|every)\b", normalized)
            and re.search(r"\b(?:mark|set)\b", normalized)
            and re.search(r"\bread\b", normalized)
            and re.search(r"\binbox\b", normalized)):
        return "bulk_read"
    if re.search(r"\breply\b", normalized):
        return "reply"
    if re.search(r"\b(?:mark|archive|star|unstar|flag|unflag|remove label)\b", normalized) or (
        re.search(r"\blabel\b", normalized) and re.search(r"\b(?:that|this|it|selected)\b", normalized)
    ):
        return "modify"
    if re.search(r"\bunread\b", normalized) and re.search(
        r"\b(?:review|check|read|report|summarize|summarise|show)\b", normalized
    ):
        return "review"
    if re.search(r"\b(?:organize|organise|sort|categorize|categorise|label)\b", normalized):
        return "organize"
    if re.search(r"\b(?:draft|compose|write|send)\b", normalized) or re.search(
        r"(?:^|\b(?:please|can you|could you)\s+)email\s+(?:me|[\w.+-]+@|[a-z]+)", normalized
    ):
        return "compose"
    if re.search(r"\b(?:find|search|read|show|look for|open)\b", normalized):
        return "find"
    return None


def is_pdf_email_request(text: str) -> bool:
    normalized = text.lower().replace("’", "'")
    return bool(
        re.search(r"\bpdf\b", normalized)
        and re.search(r"\b(?:send|email|mail)\b", normalized)
        and not re.search(r"\b(?:do not|don't|never|delete|trash)\b", normalized)
    )


class CoreDisplay(QWidget):
    """Animated core with audio level driven by the current input or output."""

    AVATAR_OPACITY = 0.2

    def __init__(self):
        super().__init__()
        self.state = "STANDBY"
        self.level = 0.0
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(50)
        self.setMinimumHeight(140)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Icewolf assistant status")

    def set_state(self, state: str):
        self.state = state
        if state not in ("LISTENING", "WAKE LISTENING", "SPEAKING"):
            self.level = 0.0
        self.setAccessibleDescription(state)
        self.update()

    def set_level(self, value):
        self.level = max(0.0, min(1.0, value))
        self.update()

    def animate(self):
        self.phase += 0.08
        self.level *= 0.93
        self.update()

    def set_reduced_motion(self, reduced: bool):
        if reduced:
            self.timer.stop()
            self.phase = 0.0
        else:
            self.timer.start(50)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        center = QPointF(width / 2, height / 2 - 12)
        radius = min(width * 0.34, height * 0.34)
        radius *= 1 + self.level * 0.07
        painter.save()
        painter.setOpacity(self.AVATAR_OPACITY)
        glow = QRadialGradient(center, radius * 1.4)
        glow.setColorAt(0, QColor(7, 45, 80, 110))
        glow.setColorAt(0.7, QColor(8, 70, 110, 75))
        glow.setColorAt(1, QColor(4, 17, 34, 0))
        painter.fillRect(self.rect(), glow)
        rings, columns = 15, 32
        points = []
        for row in range(rings):
            ring = []
            for col in range(columns):
                latitude = math.pi * (row + 0.5 + 0.27 * math.sin(col * 2.3 + row)) / rings
                longitude = (2 * math.pi * (col + 0.32 * math.sin(row * 2.5 + col))
                             / columns + self.phase * 0.12)
                wobble = 1 + 0.035 * math.sin(row * 2.1 + col * 1.7 + self.phase)
                x = math.sin(latitude) * math.cos(longitude) * wobble
                y = math.cos(latitude) * wobble
                z = math.sin(latitude) * math.sin(longitude)
                ring.append((QPointF(center.x() + x * radius, center.y() + y * radius), z))
            points.append(ring)
        for row, ring in enumerate(points):
            for col, (point, depth) in enumerate(ring):
                neighbor, _ = ring[(col + 1) % columns]
                brightness = int(75 + 100 * (depth + 1) / 2)
                painter.setPen(QPen(QColor(47, 166, 225, brightness), 0.7))
                painter.drawLine(point, neighbor)
                if row + 1 < rings:
                    next_point, _ = points[row + 1][(col + row % 2) % columns]
                    painter.drawLine(point, next_point)
                painter.setPen(QPen(QColor(175, 239, 255, min(255, brightness + 70)), 2))
                painter.drawPoint(point)
        painter.restore()
        painter.setPen(QPen(QColor("#69edff"), 2))
        wave = QPolygonF()
        for i in range(81):
            x = center.x() - radius + 2 * radius * i / 80
            envelope = math.sin(math.pi * i / 80)
            y = center.y() + radius * 1.12 + math.sin(i * 0.6 + self.phase * 4) * envelope * (2 + self.level * 10)
            wave.append(QPointF(x, y))
        painter.drawPolyline(wave)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#5bdcf7"))
        painter.drawText(QRectF(0, center.y() + radius * 1.17, width, 22),
                         Qt.AlignmentFlag.AlignCenter, self.state)


class AvatarWindow(QWidget):
    """Compact desktop window; it shares the main window's voice session."""

    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnBottomHint)
        self.owner = owner
        self.drag_offset = None
        self.placed = False
        self.setWindowTitle("Icewolf avatar")
        self.setAccessibleName("Icewolf avatar")
        self.setFixedSize(220, 220)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        self.core = CoreDisplay()
        self.core.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.core.setToolTip("Drag to move Icewolf on your desktop.")
        layout.addWidget(self.core, 1)
        buttons = QHBoxLayout()
        self.listen_button = QPushButton("Start listening")
        self.listen_button.setAccessibleName("Start or stop the voice session")
        self.listen_button.clicked.connect(owner.toggle_wake)
        buttons.addWidget(self.listen_button)
        self.hud_button = QPushButton("Open HUD")
        self.hud_button.clicked.connect(owner.restore_hud)
        buttons.addWidget(self.hud_button)
        layout.addLayout(buttons)
        self.setToolTip("Drag the avatar to move it. Use Open HUD to return to Icewolf.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.owner.restore_hud()


def create_tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#0c2938"))
    painter.setPen(QPen(QColor("#71e9ee"), 2))
    painter.drawEllipse(2, 2, 27, 27)
    painter.setPen(QPen(QColor("#b2f6ff"), 2))
    painter.drawPolyline(QPolygonF([
        QPointF(7, 17), QPointF(11, 17), QPointF(14, 10),
        QPointF(18, 22), QPointF(21, 15), QPointF(25, 15),
    ]))
    painter.end()
    return QIcon(pixmap)


class AssistantWorker(QThread):
    status_changed = pyqtSignal(str)
    message = pyqtSignal(str, str)
    failed = pyqtSignal(str)
    model_checked = pyqtSignal()
    audio_level = pyqtSignal(float)
    connect_requested = pyqtSignal()
    gmail_tools_requested = pyqtSignal(str)
    gmail_request_details = pyqtSignal(str)
    pdf_email_requested = pyqtSignal(str)
    agent_state = pyqtSignal(str, bool)
    link_requested = pyqtSignal(str, str)

    def __init__(self, client, mode: str, whisper_path: str, text: str = "", agents=(),
                 end_silence_seconds: float = CONVERSATION_SILENCE_SECONDS,
                 custom_agents=(), agent_store=None, language="English"):
        super().__init__()
        self.client = client
        self.mode = mode
        self.whisper_path = whisper_path
        self.text = text
        self.agents = tuple(agents)
        self.end_silence_seconds = end_silence_seconds
        self.custom_agents = {agent.name: agent for agent in custom_agents}
        self.agent_store = agent_store
        self.language = language
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            if self.mode == "presentation":
                self.run_presentation()
                return
            if self.mode == "connect_gmail":
                self.status_changed.emit("Waiting for Google authorization")
                gmail.connect(self.text)
                self.message.emit(
                    "System", "Gmail connected with modify permission. Open Gmail tools to "
                    "review mail, prepare messages, and approve changes."
                )
                return
            if self.mode == "gmail":
                self.status_changed.emit("Reading Gmail inbox")
                report = gmail.inbox_report()
                self.message.emit("Icewolf", report.display)
                if not self.stop_event.is_set():
                    self.status_changed.emit("Speaking")
                    speaker = create_speaker()
                    speaker.level_callback = self.audio_level.emit
                    speaker.say(report.speech, stop_event=self.stop_event)
                return
            gmail_text = (self.mode == "text" and (
                is_inbox_report_request(self.text) or gmail_tools_action(self.text)
                or re.search(r"\b(?:gmail|e-?mails?|inbox)\b", self.text, re.I)
            ))
            if not gmail_text:
                self.status_changed.emit("Connecting to local model")
                self.client.check_model()
                self.model_checked.emit()
            if self.stop_event.is_set():
                return
            if (self.mode == "text" and self.language != "English"
                    and not (gmail_tools_action(self.text) or is_inbox_report_request(self.text)
                             or re.search(r"\b(?:gmail|e-?mails?|inbox)\b", self.text, re.I))):
                self.status_changed.emit("Thinking")
                response = self.client.reply(self.text, language=self.language)
                if not self.stop_event.is_set():
                    self.message.emit("Icewolf", response)
                return
            self.status_changed.emit("Loading local voice")
            speaker = create_speaker()
            speaker.level_callback = self.audio_level.emit
            if self.stop_event.is_set():
                return
            if self.mode == "text":
                self.respond(self.text, speaker)
                return
            self.status_changed.emit("Loading speech recognition")
            voice = VoicePipeline(Path(self.whisper_path), speak=False)
            voice.level_callback = self.audio_level.emit
            if self.stop_event.is_set():
                return
            if self.mode == "push":
                self.status_changed.emit("Listening — speak now")
                text = voice.record_and_transcribe(15, auto_stop=True, vad="silero")
                if not self.stop_event.is_set():
                    self.handle_transcript(text, speaker)
                return
            if self.mode != "resume_wake":
                self.status_changed.emit("Preparing wake phrase detection")
                wake = IcewolfPhraseListener(
                    voice, inline_request_matcher=lambda text: (
                        is_inbox_report_request(text) or is_pdf_email_request(text)
                        or gmail_tools_action(text) is not None
                    ),
                    end_silence_seconds=self.end_silence_seconds,
                )
                try:
                    self.status_changed.emit("Wake listening — say Hey Icewolf")
                    with voice.sd.InputStream(
                        samplerate=SAMPLE_RATE, channels=1, dtype="float32"
                    ) as stream:
                        if not wake.wait(stream, self.stop_event):
                            return
                except (OSError, ValueError, voice.sd.PortAudioError) as exc:
                    raise RuntimeError(f"Microphone recording failed: {exc}") from exc
                if self.stop_event.is_set():
                    return
                inline_request = wake.inline_request
                if isinstance(inline_request, str) and inline_request:
                    self.handle_transcript(inline_request, speaker)
                else:
                    self.respond("hey icewolf", speaker)
            while not self.stop_event.is_set():
                try:
                    with voice.sd.InputStream(
                        samplerate=SAMPLE_RATE, channels=1, dtype="float32"
                    ) as stream:
                        self.status_changed.emit("Conversation listening — speak now")
                        audio = voice._record_until_silence(
                            CONVERSATION_MAX_SECONDS, 0.01, "silero", 0.5, stream,
                            self.stop_event, wait_for_speech=True,
                            end_silence_seconds=self.end_silence_seconds, fail_on_limit=True,
                        )
                except SpeechTooLong:
                    if not self.stop_event.is_set():
                        self.message.emit(
                            "System", "Your request exceeded the 5-minute recording limit and was "
                            "not sent. Please repeat it in shorter parts."
                        )
                    continue
                except (OSError, ValueError, voice.sd.PortAudioError) as exc:
                    raise RuntimeError(f"Microphone recording failed: {exc}") from exc
                if self.stop_event.is_set():
                    return
                self.status_changed.emit("Transcribing")
                text = voice.transcribe(audio) if audio is not None else ""
                self.handle_transcript(text, speaker)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def run_presentation(self):
        import numpy as np

        self.status_changed.emit("Loading speech recognition for recording")
        voice = VoicePipeline(Path(self.whisper_path), speak=False)
        self.client.check_model()
        self.model_checked.emit()
        speaker = create_speaker()
        speaker.level_callback = self.audio_level.emit
        audio_queue = queue.Queue(maxsize=30)
        overflow = threading.Event()
        self.presentation_conversation = False
        self.presentation_seen = set()
        previous = None

        def capture(indata, frames, time_info, status):
            if status:
                overflow.set()
            try:
                audio_queue.put_nowait(indata.copy())
            except queue.Full:
                overflow.set()

        try:
            while not self.stop_event.is_set():
                if self.presentation_conversation:
                    self.status_changed.emit("Recording mode — conversation demo")
                    with voice.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
                        audio = voice._record_until_silence(
                            CONVERSATION_MAX_SECONDS, 0.01, "silero", 0.5, stream,
                            self.stop_event, wait_for_speech=True,
                            end_silence_seconds=self.end_silence_seconds, fail_on_limit=True,
                        )
                    if audio is not None and not self.stop_event.is_set():
                        self.handle_presentation_transcript(voice.transcribe(audio), speaker)
                    continue
                while not audio_queue.empty():
                    audio_queue.get_nowait()
                previous = None
                self.status_changed.emit("Recording mode — listening for narration")
                with voice.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                          blocksize=SAMPLE_RATE * 3, callback=capture):
                    while not self.stop_event.is_set() and not self.presentation_conversation:
                        if overflow.is_set():
                            raise RuntimeError(
                                "Recording audio could not be processed fast enough. "
                                "Stop and retry with a smaller speech model."
                            )
                        try:
                            chunk = audio_queue.get(timeout=0.2)
                        except queue.Empty:
                            continue
                        audio = np.concatenate((previous[-SAMPLE_RATE:], chunk)) if previous is not None else chunk
                        previous = chunk
                        text = voice.transcribe(audio)
                        if text and not self.stop_event.is_set():
                            self.handle_presentation_transcript(text, speaker)
        except SpeechTooLong as exc:
            raise RuntimeError("Conversation request was too long; recording mode stopped.") from exc
        except (OSError, ValueError, voice.sd.PortAudioError) as exc:
            raise RuntimeError(f"Microphone recording failed: {exc}") from exc

    def handle_presentation_transcript(self, text: str, speaker):
        normalized = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("'", "").replace("’", "")).strip()
        if "now lets have a conversation" in normalized:
            self.presentation_conversation = True
            self.status_changed.emit("Recording mode — conversation demo")
            return
        if "that was our conversation demo" in normalized:
            self.presentation_conversation = False
            self.status_changed.emit("Recording mode — listening for narration")
            return
        if self.presentation_conversation:
            self.handle_transcript(text, speaker)
            return
        for cue, command in PRESENTATION_CUES:
            if cue in normalized and cue not in self.presentation_seen:
                self.presentation_seen.add(cue)
                title, url = PRESENTATION_LINKS[command]
                self.message.emit("Icewolf", f"{title}: {url}")
                self.link_requested.emit(title, url)

    def handle_transcript(self, text: str, speaker):
        if not text:
            self.message.emit("System", "No speech recognized.")
            return
        self.message.emit("You", text)
        self.respond(text, speaker)

    def respond(self, text: str, speaker):
        if self.stop_event.is_set():
            return
        normalized = " ".join(text.lower().strip(" .?!").split())
        if normalized in ("show project links", "show the project links"):
            self.message.emit("Icewolf", PROJECT_LINKS)
            self.link_requested.emit("Project repositories", PROJECT_LINKS)
            self.status_changed.emit("Speaking")
            speaker.say(
                "I have displayed the Icewolf and Jarvis repository links in the conversation.",
                stop_event=self.stop_event,
            )
            return
        if normalized in PRESENTATION_LINKS:
            title, url = PRESENTATION_LINKS[normalized]
            self.message.emit("Icewolf", f"{title}: {url}")
            self.link_requested.emit(title, url)
            self.status_changed.emit("Speaking")
            speaker.say(f"I have displayed the {title} link.", stop_event=self.stop_event)
            return
        repo_request = github_repo.extract_repository_request(text)
        if repo_request:
            if re.search(r"\b(?:do not|don't|never)\s+(?:check|fetch|open|access|inspect|read)\b",
                         normalized):
                self.message.emit("Icewolf", "I will not access that repository.")
                self.status_changed.emit("Speaking")
                speaker.say("I will not access that repository.", stop_event=self.stop_event)
                return
            url, question = repo_request
            self.status_changed.emit("Fetching public GitHub repository overview")
            overview = github_repo.fetch_overview(url)
            if self.stop_event.is_set():
                return
            self.message.emit(
                "Sources consulted",
                f"{overview.url} — public metadata and "
                + ("README excerpt" if overview.readme else "no README found")
                + (" (truncated)" if overview.readme_truncated else "")
                + "; source code not inspected.",
            )
            self.status_changed.emit("Thinking")
            response = self.client.repository_reply(overview, question)
            if self.stop_event.is_set():
                return
            self.message.emit("Icewolf", response)
            self.status_changed.emit("Speaking")
            speaker.say(response, stop_event=self.stop_event)
            return
        if re.search(r"\bgithub\b", normalized) and re.search(
            r"\b(?:repo|repository|project)\b", normalized
        ):
            response = (
                "To check a public GitHub repository, use the GitHub repo button to paste "
                "its link, or paste the link in a conversation message. "
                "I can read the public overview and README, not the source code."
            )
            self.message.emit("Icewolf", response)
            self.status_changed.emit("Speaking")
            speaker.say(response, stop_event=self.stop_event)
            return
        if normalized in ("connect gmail", "connect my gmail"):
            self.message.emit("Icewolf", "Select your Google client file to connect Gmail.")
            self.connect_requested.emit()
            self.stop_event.set()
            return
        roles = sorted((*BUILTIN_ROLES, *self.custom_agents), key=len, reverse=True)
        role_pattern = "|".join(re.escape(role) for role in roles)
        match = re.match(
            rf"^(?:ask|assign|use) ({role_pattern})(?: agent)?(?: to)?[,: ]+(.+)$",
            text.strip(), re.IGNORECASE,
        )
        if match:
            role = next(role for role in roles if role.casefold() == match.group(1).casefold())
            task = match.group(2).strip()
            if role not in self.agents:
                response = f"{role} agent is not attached. Attach it in the agent selector first."
            else:
                self.agent_state.emit(role, True)
                try:
                    self.status_changed.emit(f"{role} agent working")
                    if role in self.custom_agents:
                        if self.agent_store is None:
                            raise RuntimeError("The local agent store is unavailable.")
                        passages = self.agent_store.search(role, task)
                        if passages:
                            response = self.client.document_agent_reply(
                                role, self.custom_agents[role].instructions, task, passages
                            )
                            sources = "\n".join(
                                f"[{index}] {part.source}"
                                for index, part in enumerate(passages, 1)
                            )
                            self.message.emit("Sources consulted", sources)
                        else:
                            response = (
                                "I could not find matching information in this agent's local "
                                "documents. Try more specific terms or add relevant materials."
                            )
                    else:
                        response = self.client.agent_reply(role, task)
                finally:
                    self.agent_state.emit(role, False)
            self.message.emit("Icewolf", response)
            if not self.stop_event.is_set():
                self.status_changed.emit("Speaking")
                speaker.say(response, stop_event=self.stop_event)
            return
        if normalized in ("hey icewolf", "hey ice wolf", "hey eswulf"):
            response = "Hello, Dennis. How can I help?"
            self.message.emit("Icewolf", response)
            self.status_changed.emit("Speaking")
            speaker.say(response, stop_event=self.stop_event)
            return
        if is_pdf_email_request(text):
            self.message.emit("Icewolf", "Opening a PDF and email preview. Nothing will be sent without your approval.")
            self.pdf_email_requested.emit(text)
            self.stop_event.set()
            return
        if is_inbox_report_request(text):
            self.status_changed.emit("Reading Gmail inbox")
            report = gmail.inbox_report()
            self.message.emit("Icewolf", report.display)
            if not self.stop_event.is_set():
                self.status_changed.emit("Speaking")
                speaker.say(report.speech, stop_event=self.stop_event)
            return
        action = gmail_tools_action(text)
        if action is not None:
            response = ("I'll open Gmail tools so you can select the message to reply to."
                        if action == "reply" else
                        "I'll open Gmail tools for you to review and approve the next steps.")
            self.message.emit("Icewolf", response)
            self.status_changed.emit("Speaking")
            speaker.say(response, stop_event=self.stop_event)
            if self.stop_event.is_set():
                return
            self.gmail_request_details.emit(text)
            self.gmail_tools_requested.emit(action)
            self.stop_event.set()
            return
        if re.search(r"\b(?:gmail|e-?mails?|mail|inbox)\b", normalized) or re.search(
            r"\b(?:delete|trash)\s+(?:that|it|this|the message)\b", normalized
        ):
            response = ("That specific email request is not available. "
                        "I can report recent messages or open Gmail tools to review, draft, "
                        "send, and organize with your approval.")
            self.message.emit("Icewolf", response)
            speaker.say(response, stop_event=self.stop_event)
            return
        self.status_changed.emit("Thinking")
        response = self.client.reply(text)
        self.message.emit("Icewolf", response)
        if self.stop_event.is_set():
            return
        self.status_changed.emit("Speaking")
        speaker.say(response, stop_event=self.stop_event)


class LinkDisplay(QWidget):
    def __init__(self):
        super().__init__(flags=Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "QWidget { background: #0a1825; color: #eff8fc; }"
            "QLabel { color: #71e9ee; font: bold 22px 'Segoe UI'; }"
            "QPlainTextEdit { background: #0a1825; color: white; border: 0;"
            " font: 20px 'Segoe UI'; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        self.heading = QLabel()
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.heading)
        self.links = QPlainTextEdit()
        self.links.setReadOnly(True)
        self.links.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.links.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.links.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.links)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_links(self, title: str, links: str, screen):
        self.heading.setText(title)
        self.links.setPlainText(links)
        area = screen.availableGeometry()
        self.resize(min(1100, area.width() - 40), min(250, area.height() - 40))
        self.move(area.center() - self.rect().center())
        self.show()
        self.raise_()
        self.timer.start(LINK_DISPLAY_MS)


class IcewolfWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.client = None
        self.client_model = None
        self.closing = False
        self.pending_connect = False
        self.pending_gmail_tools = None
        self.pending_gmail_request = ""
        self.current_gmail_message = None
        self.pending_pdf_email = None
        self.pending_repo = False
        self.resume_after_repo = False
        self.link_display = LinkDisplay()
        self.agents = set()
        self.agent_store = AgentStore(data_root() / "data" / "agents.sqlite3")
        self.custom_agents = []
        self.agent_load_error = None
        try:
            self.custom_agents = self.agent_store.list_agents()
        except (OSError, sqlite3.Error) as exc:
            self.agent_load_error = str(exc)
        data_root().mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(data_root() / "icewolf-settings.ini"), QSettings.Format.IniFormat)
        self.setWindowTitle("Icewolf")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 680)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 20, 16, 16)
        title = QLabel("ICEWOLF")
        title.setObjectName("brand")
        subtitle = QLabel("PERSONAL AI  /  LOCAL FIRST")
        subtitle.setObjectName("eyebrow")
        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(18)
        navigation = QLabel("NAVIGATION")
        navigation.setObjectName("section")
        side.addWidget(navigation)
        self.nav_conversation = QPushButton("Conversation")
        self.nav_conversation.setObjectName("navActive")
        self.nav_voice = QPushButton("Voice view")
        self.nav_settings = QPushButton("Configuration")
        self.avatar_button = QPushButton("Avatar-only mode")
        side.addWidget(self.nav_conversation)
        side.addWidget(self.nav_voice)
        side.addWidget(self.nav_settings)
        side.addWidget(self.avatar_button)
        side.addSpacing(12)
        section = QLabel("AGENT ROLES")
        section.setObjectName("section")
        side.addWidget(section)
        self.agent_select = QComboBox()
        self.agent_select.addItems([*BUILTIN_ROLES, *(agent.name for agent in self.custom_agents)])
        self.agent_select.currentTextChanged.connect(self.update_attach_button)
        side.addWidget(self.agent_select)
        self.attach_button = QPushButton("Attach agent")
        self.attach_button.clicked.connect(self.toggle_agent)
        side.addWidget(self.attach_button)
        self.create_agent_button = QPushButton("Create agent")
        self.create_agent_button.clicked.connect(self.open_agent_wizard)
        side.addWidget(self.create_agent_button)
        self.add_material_button = QPushButton("Add study materials")
        self.add_material_button.clicked.connect(self.add_agent_materials)
        side.addWidget(self.add_material_button)
        self.manage_material_button = QPushButton("Manage study materials")
        self.manage_material_button.clicked.connect(self.manage_agent_materials)
        side.addWidget(self.manage_material_button)
        agent_note = QLabel("Local advice and reference documents. No browsing or code execution.")
        agent_note.setWordWrap(True)
        agent_note.setObjectName("muted")
        side.addWidget(agent_note)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Icewolf Configuration")
        self.settings_dialog.setMinimumWidth(420)
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(24, 24, 24, 24)
        settings_layout.setSpacing(12)
        settings_title = QLabel("Configuration")
        settings_title.setObjectName("heading")
        settings_layout.addWidget(settings_title)
        settings_layout.addWidget(QLabel("Ollama model"))
        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItem(str(self.settings.value("model", "qwen2.5:7b")))
        self.model_input.activated.connect(
            lambda: self.settings.setValue("model", self.model_input.currentText())
        )
        self.model_input.lineEdit().editingFinished.connect(
            lambda: self.settings.setValue("model", self.model_input.currentText().strip())
        )
        settings_layout.addWidget(self.model_input)
        settings_layout.addWidget(QLabel("Typed conversation language"))
        self.language_input = QComboBox()
        self.language_input.addItems(RESPONSE_LANGUAGES)
        saved_language = self.settings.value("response_language", "English", type=str)
        self.language_input.setCurrentText(
            saved_language if saved_language in RESPONSE_LANGUAGES else "English"
        )
        self.language_input.currentTextChanged.connect(
            lambda value: self.settings.setValue("response_language", value)
        )
        settings_layout.addWidget(self.language_input)
        language_note = QLabel(
            "Tagalog, Cebuano and Hiligaynon are experimental typed conversation only. "
            "Voice and integrations currently require English."
        )
        language_note.setWordWrap(True)
        language_note.setObjectName("muted")
        settings_layout.addWidget(language_note)
        settings_layout.addWidget(QLabel("Whisper model folder (speech recognition)"))
        self.whisper_input = QLineEdit(default_whisper_path())
        self.whisper_input.setPlaceholderText("Select local model folder")
        settings_layout.addWidget(self.whisper_input)
        self.browse_button = QPushButton("Browse folder")
        self.browse_button.clicked.connect(self.browse_model)
        settings_layout.addWidget(self.browse_button)
        settings_layout.addWidget(QLabel("Wait after you stop speaking"))
        self.speech_pause = QDoubleSpinBox()
        self.speech_pause.setRange(1.5, 8.0)
        self.speech_pause.setSingleStep(0.5)
        self.speech_pause.setDecimals(1)
        self.speech_pause.setSuffix(" seconds")
        self.speech_pause.setValue(self.settings.value(
            "conversation_silence_seconds", CONVERSATION_SILENCE_SECONDS, type=float
        ))
        self.speech_pause.setToolTip(
            "Icewolf waits this long after speech before replying. Longer waits allow longer pauses."
        )
        self.speech_pause.valueChanged.connect(
            lambda value: self.settings.setValue("conversation_silence_seconds", value)
        )
        settings_layout.addWidget(self.speech_pause)
        pause_note = QLabel("Longer pauses give you more time to think, but delay replies.")
        pause_note.setWordWrap(True)
        pause_note.setObjectName("muted")
        settings_layout.addWidget(pause_note)
        self.connect_gmail_button = QPushButton("Connect or reconnect Gmail")
        self.connect_gmail_button.clicked.connect(self.connect_gmail)
        settings_layout.addWidget(self.connect_gmail_button)
        settings_note = QLabel(
            "Gmail requests modify permission online; sending and organizing require approval. "
            "Speech uses local Kokoro Adam."
        )
        settings_note.setWordWrap(True)
        settings_layout.addWidget(settings_note)
        self.reduce_motion = QCheckBox("Reduce avatar motion")
        self.reduce_motion.setChecked(
            self.settings.value("reduce_motion", system_reduced_motion(), type=bool)
        )
        self.reduce_motion.setToolTip("Stop decorative animation; audio levels still update.")
        settings_layout.addWidget(self.reduce_motion)
        side.addStretch()
        privacy = QLabel("MICROPHONE CONTROL")
        privacy.setObjectName("section")
        side.addWidget(privacy)
        self.wake_button = QPushButton("Enable Hey Icewolf")
        self.wake_button.setObjectName("secondary")
        self.wake_button.clicked.connect(self.start_wake)
        side.addWidget(self.wake_button)
        self.presentation_button = QPushButton("Start recording mode")
        self.presentation_button.setToolTip(
            "Listen locally for script phrases and display their links. Stop with Stop / cancel."
        )
        self.presentation_button.clicked.connect(lambda: self.start_worker("presentation"))
        side.addWidget(self.presentation_button)
        self.stop_button = QPushButton("Stop / cancel")
        self.stop_button.clicked.connect(self.stop_worker)
        self.stop_button.setEnabled(False)
        side.addWidget(self.stop_button)
        note = QLabel("Wake listening is opt-in. The microphone closes during replies.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        side.addWidget(note)
        layout.addWidget(sidebar)

        main = QVBoxLayout()
        main.setSpacing(12)
        header = QHBoxLayout()
        heading = QLabel("Your command center")
        heading.setObjectName("heading")
        header.addWidget(heading)
        header_subtitle = QLabel("  /  ICEWOLF")
        header_subtitle.setObjectName("eyebrow")
        header.addWidget(header_subtitle)
        header.addStretch()
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        header.addWidget(self.clock)
        main.addLayout(header)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()

        top = QHBoxLayout()
        top.setSpacing(10)
        core_panel, core_layout = self.make_panel("ASSISTANT CORE")
        core_panel.setObjectName("corePanel")
        self.status = QLabel("Ready — microphone off")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        core_layout.addWidget(self.status)
        self.llm_status = QLabel("LLM: not checked")
        self.llm_status.setObjectName("muted")
        core_layout.addWidget(self.llm_status)
        self.model_input.currentTextChanged.connect(lambda: self.llm_status.setText("LLM: not checked"))
        self.core = CoreDisplay()
        self.core.set_reduced_motion(self.reduce_motion.isChecked())
        self.reduce_motion.toggled.connect(self.set_reduced_motion)
        core_layout.addWidget(self.core, 1)
        pipeline, pipeline_layout = self.make_panel("VOICE PIPELINE")
        pipeline.setMinimumWidth(190)
        for name, description in (
            ("WAKE WORD", "Hey Icewolf · opt-in"),
            ("TRANSCRIPTION", "Faster-Whisper · local"),
            ("REASONING", "Ollama · local endpoint"),
            ("VOICE", "Kokoro Adam · local"),
        ):
            item = QFrame()
            item.setObjectName("pipelineItem")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(10, 7, 10, 7)
            item_layout.setSpacing(1)
            item_name = QLabel(name)
            item_name.setObjectName("itemTitle")
            item_value = QLabel(description)
            item_value.setObjectName("muted")
            item_layout.addWidget(item_name)
            item_layout.addWidget(item_value)
            pipeline_layout.addWidget(item)
        pipeline_layout.addStretch()
        top.addWidget(pipeline, 2)
        top.addWidget(core_panel, 5)

        monitor, monitor_layout = self.make_panel("SYSTEM MONITOR")
        monitor.setMaximumWidth(210)
        self.cpu_status = QLabel("CPU: sampling")
        self.memory_status = QLabel("MEMORY: sampling")
        self.gpu_status = QLabel("GPU: not yet sampled")
        self.gpu_status.setWordWrap(True)
        self.gpu_status.setMinimumHeight(40)
        for label in (self.cpu_status, self.memory_status, self.gpu_status):
            label.setObjectName("itemTitle")
            monitor_layout.addWidget(label)
        monitor_layout.addSpacing(12)
        feed_heading = QLabel("LIVE INTELLIGENCE FEED")
        feed_heading.setObjectName("section")
        monitor_layout.addWidget(feed_heading)
        self.feed = QPlainTextEdit()
        self.feed.setMinimumWidth(0)
        self.feed.setMinimumHeight(36)
        self.feed.setReadOnly(True)
        self.feed.document().setMaximumBlockCount(30)
        self.feed.setPlaceholderText("Status updates appear here.")
        self.feed.setAccessibleName("Live status feed")
        monitor_layout.addWidget(self.feed, 1)
        agent_status = QLabel("SOCIAL: not connected")
        agent_status.setObjectName("muted")
        agent_status.setWordWrap(True)
        monitor_layout.addWidget(agent_status)
        top.addWidget(monitor, 2)
        main.addLayout(top, 8)

        conversation, conversation_layout = self.make_panel("CONVERSATION")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Your conversation will appear here.\nStart listening or type a message below.")
        self.log.setAccessibleName("Conversation history")
        conversation_layout.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a message to Icewolf...")
        self.text_input.setAccessibleName("Message to Icewolf")
        self.text_input.returnPressed.connect(self.send_text)
        row.addWidget(self.text_input, 1)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send_text)
        row.addWidget(self.send_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_conversation)
        row.addWidget(self.clear_button)
        self.repo_button = QPushButton("GitHub repo")
        self.repo_button.setToolTip("Paste a public GitHub repository link and question.")
        self.repo_button.clicked.connect(self.open_repo_dialog)
        row.addWidget(self.repo_button)
        self.gmail_tools_button = QPushButton("Gmail tools")
        self.gmail_tools_button.setToolTip(
            "Stop listening and open Gmail tools. Restart listening when finished."
        )
        self.gmail_tools_button.clicked.connect(lambda: self.open_gmail_tools())
        row.addWidget(self.gmail_tools_button)
        conversation_layout.addLayout(row)
        main.addWidget(conversation, 2)
        agent_panel, agent_layout = self.make_panel("ATTACHED AGENTS")
        self.agent_status = QLabel('<span style="color:#000000; background-color:#b9c9d0">●</span>  No agents attached / assigned')
        self.agent_status.setStyleSheet("color: #8797a0;")
        self.agent_status.setWordWrap(True)
        agent_layout.addWidget(self.agent_status)
        main.addWidget(agent_panel)
        self.nav_settings.clicked.connect(self.settings_dialog.show)
        self.push_button = QPushButton("START LISTENING  /  SAY HEY ICEWOLF")
        self.push_button.setObjectName("talk")
        self.push_button.clicked.connect(self.toggle_wake)
        main.addWidget(self.push_button)
        tip = QLabel("SAY HEY ICEWOLF ONCE  /  Then speak after each reply.")
        tip.setObjectName("footer")
        main.addWidget(tip)
        footer = QLabel("LOCAL SESSION  •  Conversation stays in memory  •  Wake word: Hey Icewolf")
        footer.setObjectName("footer")
        main.addWidget(footer)
        dashboard = QWidget()
        dashboard.setLayout(main)
        self.views = QStackedWidget()
        self.views.addWidget(dashboard)

        voice_page = QWidget()
        voice_layout = QVBoxLayout(voice_page)
        voice_layout.setContentsMargins(12, 12, 12, 12)
        voice_header = QLabel("ICEWOLF  /  VOICE")
        voice_header.setObjectName("eyebrow")
        voice_layout.addWidget(voice_header)
        self.voice_core = CoreDisplay()
        self.voice_core.set_reduced_motion(self.reduce_motion.isChecked())
        voice_layout.addWidget(self.voice_core, 1)
        self.voice_status = QLabel(self.status.text())
        self.voice_status.setObjectName("status")
        self.voice_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.voice_status.setWordWrap(True)
        voice_layout.addWidget(self.voice_status)
        self.voice_button = QPushButton(self.push_button.text())
        self.voice_button.setObjectName("talk")
        self.voice_button.clicked.connect(self.toggle_wake)
        voice_layout.addWidget(self.voice_button)
        self.voice_repo_button = QPushButton("GitHub repo")
        self.voice_repo_button.setToolTip(
            "Pause the listening session to paste a public GitHub repository link."
        )
        self.voice_repo_button.clicked.connect(self.open_repo_dialog)
        voice_layout.addWidget(self.voice_repo_button)
        voice_note = QLabel("Say Hey Icewolf once. After waking, the microphone stays on between replies.")
        voice_note.setObjectName("footer")
        voice_note.setWordWrap(True)
        voice_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        voice_layout.addWidget(voice_note)
        self.views.addWidget(voice_page)
        self.nav_conversation.clicked.connect(self.show_conversation)
        self.nav_voice.clicked.connect(self.show_voice)
        layout.addWidget(self.views, 1)
        self.setStyleSheet(STYLE)
        self.avatar_window = AvatarWindow(self)
        self.avatar_window.core.set_reduced_motion(self.reduce_motion.isChecked())
        self.avatar_window.core.set_state(self.core.state)
        self.avatar_button.clicked.connect(self.show_avatar)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(create_tray_icon(), self)
            self.tray.setToolTip("Icewolf — open HUD")
            menu = QMenu(self)
            menu.addAction("Open HUD", self.restore_hud)
            menu.addAction("Show avatar", self.show_avatar)
            menu.addSeparator()
            menu.addAction("Exit Icewolf", self.close)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()
        if self.agent_load_error:
            QTimer.singleShot(0, lambda: self.show_error(
                f"Could not load local agents: {self.agent_load_error}"
            ))
        self.model_process = QProcess(self)
        self.model_process.finished.connect(self.models_loaded)
        self.model_process.errorOccurred.connect(self.model_list_error)
        self.model_process.start("ollama", ["list"])
        self.gpu_process = QProcess(self)
        self.gpu_process.finished.connect(self.gpu_finished)
        self.gpu_process.errorOccurred.connect(self.gpu_error)
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.update_system)
        self.monitor_timer.start(3000)
        psutil.cpu_percent()
        self.update_system()

    @staticmethod
    def make_panel(title):
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        heading = QLabel(title)
        heading.setObjectName("section")
        layout.addWidget(heading)
        return panel, layout

    def update_clock(self):
        self.clock.setText(QDateTime.currentDateTime().toString("ddd, dd MMM yyyy   HH:mm:ss"))

    def set_reduced_motion(self, reduced: bool):
        self.core.set_reduced_motion(reduced)
        self.voice_core.set_reduced_motion(reduced)
        self.avatar_window.core.set_reduced_motion(reduced)
        self.settings.setValue("reduce_motion", reduced)

    def show_avatar(self):
        if self.closing:
            return
        self.settings_dialog.hide()
        if not self.avatar_window.placed:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.avatar_window.move(area.right() - self.avatar_window.width() - 15,
                                        area.bottom() - self.avatar_window.height() - 15)
            self.avatar_window.placed = True
        self.avatar_window.showNormal()
        self.avatar_window.lower()
        self.hide()

    def restore_hud(self):
        if self.closing:
            return
        self.avatar_window.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_hud()

    def show_conversation(self):
        self.views.setCurrentIndex(0)
        self.set_active_navigation(self.nav_conversation)
        self.text_input.setFocus()

    def show_voice(self):
        self.views.setCurrentIndex(1)
        self.set_active_navigation(self.nav_voice)
        self.voice_button.setFocus()

    def set_active_navigation(self, active):
        for button in (self.nav_conversation, self.nav_voice):
            button.setObjectName("navActive" if button is active else "")
            button.style().unpolish(button)
            button.style().polish(button)

    def set_audio_level(self, value: float):
        self.core.set_level(value)
        self.voice_core.set_level(value)
        self.avatar_window.core.set_level(value)

    def models_loaded(self, exit_code, exit_status):
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self.feed.appendPlainText("Could not list local models; enter a model name manually.")
            return
        output = bytes(self.model_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        models = [line.split()[0] for line in output.splitlines()[1:] if line.split()]
        selected = self.model_input.currentText()
        for model in models:
            if self.model_input.findText(model) < 0 and "cloud" not in model.lower():
                self.model_input.addItem(model)
        if not self.settings.contains("model") and selected not in models and models:
            self.model_input.setCurrentText(models[0])

    def model_list_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.feed.appendPlainText("Ollama not found; enter a local model name manually.")

    def update_system(self):
        memory = psutil.virtual_memory()
        self.cpu_status.setText(f"CPU: {psutil.cpu_percent():.0f}%")
        self.memory_status.setText(f"MEMORY: {memory.percent:.0f}%")
        if self.gpu_process.state() == QProcess.ProcessState.NotRunning:
            self.gpu_process.start("nvidia-smi", [
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ])
            QTimer.singleShot(2000, self.gpu_timeout)

    def gpu_timeout(self):
        if self.gpu_process.state() != QProcess.ProcessState.NotRunning:
            self.gpu_process.kill()
            self.gpu_status.setText("GPU: query timed out")

    def gpu_finished(self, exit_code, exit_status):
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            if self.gpu_status.text() != "GPU: query timed out":
                self.gpu_status.setText("GPU: unavailable")
            return
        try:
            values = bytes(self.gpu_process.readAllStandardOutput()).decode("utf-8").splitlines()[0].split(",")
            usage, used, total = (int(value.strip()) for value in values)
        except (ValueError, IndexError, UnicodeDecodeError):
            self.gpu_status.setText("GPU: invalid response")
            return
        self.gpu_status.setText(f"GPU: {usage}%  /  VRAM: {used}/{total} MiB")

    def gpu_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.gpu_status.setText("GPU: nvidia-smi unavailable")

    def set_status(self, text: str):
        self.status.setText(text)
        self.voice_status.setText(text)
        self.feed.appendPlainText(f"{QDateTime.currentDateTime().toString('HH:mm:ss')}  {text}")
        lowered = text.lower()
        if "connecting to local model" in lowered:
            self.llm_status.setText("LLM: checking")
        if "error" in lowered:
            state = "ERROR"
        elif "wake listening" in lowered:
            state = "WAKE LISTENING"
        elif "listening" in lowered or "speak now" in lowered:
            state = "LISTENING"
        elif "speaking" in lowered:
            state = "SPEAKING"
        elif "thinking" in lowered or "transcribing" in lowered:
            state = "PROCESSING"
        elif "ready" in lowered:
            state = "STANDBY"
        else:
            state = "WORKING"
        for label in (self.status, self.voice_status):
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
        self.core.set_state(state)
        self.voice_core.set_state(state)
        self.avatar_window.core.set_state(state)
        self.avatar_window.setToolTip(text)
        if self.tray is not None:
            self.tray.setToolTip(f"Icewolf — {text}")

    def browse_model(self):
        path = QFileDialog.getExistingDirectory(self, "Select local Whisper model folder")
        if path:
            self.whisper_input.setText(path)

    def open_agent_wizard(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create local agent")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Create a local advice role. Your selected documents are copied as searchable "
            "text on this PC without encryption; the model is not retrained. "
            "Only add materials you are authorized to use."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel("Agent name"))
        name = QLineEdit("NICE IEX Administrator")
        layout.addWidget(name)
        layout.addWidget(QLabel("Role and responsibilities"))
        instructions = QPlainTextEdit(
            "Help Dennis troubleshoot and administer NICE IEX using the provided documentation. "
            "Explain risks, prerequisites, and verification steps; do not claim to make changes."
        )
        instructions.setMaximumHeight(110)
        layout.addWidget(instructions)
        files = []
        file_label = QLabel("No documents selected. You can add them later.")
        file_label.setWordWrap(True)
        choose = QPushButton("Select study materials")
        def choose_files():
            selected, _ = QFileDialog.getOpenFileNames(
                dialog, "Select local study materials", "",
                "Documents (*.pdf *.docx *.txt *.md)"
            )
            if selected:
                files[:] = [Path(path) for path in selected]
                file_label.setText("\n".join(path.name for path in files))
        choose.clicked.connect(choose_files)
        layout.addWidget(choose)
        layout.addWidget(file_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        def save():
            try:
                self.agent_store.create_agent(name.text(), instructions.toPlainText(), files)
                self.custom_agents = self.agent_store.list_agents()
            except (OSError, UnicodeError, ValueError, sqlite3.Error) as exc:
                QMessageBox.warning(dialog, "Could not create agent", str(exc))
                return
            self.agent_select.addItem(name.text().strip())
            self.agent_select.setCurrentText(name.text().strip())
            self.agents.add(name.text().strip())
            self.update_agents()
            self.update_attach_button()
            dialog.accept()
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def add_agent_materials(self):
        role = self.agent_select.currentText()
        if role not in {agent.name for agent in self.custom_agents}:
            QMessageBox.information(self, "Study materials", "Select a custom agent first.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Add study materials for {role}", "",
            "Documents (*.pdf *.docx *.txt *.md)"
        )
        if not files:
            return
        try:
            self.agent_store.add_documents(role, [Path(path) for path in files])
        except (OSError, UnicodeError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Could not add study materials", str(exc))
            return
        self.append_message("System", f"Added {len(files)} document(s) to {role}.")

    def manage_agent_materials(self):
        role = self.agent_select.currentText()
        if role not in {agent.name for agent in self.custom_agents}:
            QMessageBox.information(self, "Study materials", "Select a custom agent first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Study materials - {role}")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        note = QLabel("Removing a document deletes its stored text, not the original file.")
        note.setWordWrap(True)
        layout.addWidget(note)
        documents = QListWidget()
        layout.addWidget(documents)
        try:
            documents.addItems(self.agent_store.list_documents(role))
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Could not load study materials", str(exc))
            return
        remove = QPushButton("Remove selected document")
        def remove_selected():
            item = documents.currentItem()
            if item is None:
                QMessageBox.information(dialog, "Study materials", "Select a document to remove.")
                return
            answer = QMessageBox.question(
                dialog, "Remove study material",
                f"Remove the stored text for {item.text()} from this agent? "
                "The original file will not be deleted."
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                self.agent_store.remove_document(role, item.text())
            except (OSError, ValueError, sqlite3.Error) as exc:
                QMessageBox.warning(dialog, "Could not remove study material", str(exc))
                return
            documents.takeItem(documents.row(item))
        remove.clicked.connect(remove_selected)
        layout.addWidget(remove)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def append_message(self, role: str, text: str):
        self.log.appendPlainText(f"{role}: {text}\n")

    def show_presentation_link(self, title: str, links: str):
        window = self.avatar_window if self.avatar_window.isVisible() else self
        screen = QApplication.screenAt(window.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            self.append_message("Error", "Unable to display the link: no screen is available.")
            return
        self.link_display.show_links(title, links, screen)

    def open_repo_dialog(self):
        if self.language_input.currentText() != "English":
            self.set_status("Error — repository access currently requires English; change it in Configuration")
            return
        if self.worker is not None:
            if self.worker.mode in ("wake", "resume_wake"):
                self.pending_repo = True
                self.resume_after_repo = True
                self.stop_worker()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Check a public GitHub repository")
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "This contacts GitHub online without signing in. Icewolf reads public "
            "repository metadata and the README only; it does not inspect source code."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Public repository URL"))
        url = QLineEdit()
        url.setPlaceholderText("https://github.com/owner/repository")
        layout.addWidget(url)
        layout.addWidget(QLabel("Question (optional)"))
        question = QLineEdit()
        question.setPlaceholderText("Summarize this repository")
        layout.addWidget(question)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Check repository")
        def submit():
            try:
                github_repo.parse_repository_url(url.text().strip())
            except ValueError as exc:
                QMessageBox.warning(dialog, "Invalid repository link", str(exc))
                return
            text = f"{question.text().strip()} {url.text().strip()}".strip()
            dialog.accept()
            self.start_worker("text", text)
            if self.worker is not None:
                self.append_message("You", text)
        buttons.accepted.connect(submit)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        if self.resume_after_repo and self.worker is None:
            self.resume_after_repo = False
            self.start_worker("resume_wake")

    def toggle_agent(self):
        role = self.agent_select.currentText()
        if role in self.agents:
            self.agents.remove(role)
        else:
            self.agents.add(role)
        self.update_agents()
        self.update_attach_button()

    def update_attach_button(self):
        action = "Detach agent" if self.agent_select.currentText() in self.agents else "Attach agent"
        self.attach_button.setText(action)

    def update_agents(self, active_role=None, active=False):
        if not self.agents:
            self.agent_status.setText('<span style="color:#000000; background-color:#b9c9d0">●</span>  No agents attached / assigned')
            return
        parts = []
        for role in sorted(self.agents):
            running = active and role == active_role
            color = "#35df86" if running else "#ff6565"
            status = "active" if running else "idle"
            parts.append(f'<span style="color:{color}">●</span> {role}: {status}')
        self.agent_status.setText("   |   ".join(parts))

    def request_connect(self):
        self.pending_connect = True

    def set_busy(self, busy: bool):
        for control in (self.model_input, self.language_input, self.whisper_input, self.browse_button, self.speech_pause,
                        self.wake_button, self.presentation_button, self.send_button,
                        self.text_input, self.clear_button, self.connect_gmail_button, self.gmail_tools_button,
                        self.agent_select, self.attach_button, self.create_agent_button,
                        self.add_material_button, self.manage_material_button):
            control.setEnabled(not busy)
        listening = busy and self.worker is not None and self.worker.mode in ("wake", "resume_wake")
        gmail_listening = busy and self.worker is not None and self.worker.mode in (
            "wake", "resume_wake", "presentation"
        )
        self.gmail_tools_button.setEnabled(not busy or gmail_listening)
        self.avatar_window.listen_button.setEnabled(not busy or listening)
        self.avatar_window.listen_button.setText("Stop" if listening else "Start listening")
        self.repo_button.setEnabled(not busy or listening)
        self.voice_repo_button.setEnabled(not busy or listening)
        for button in (self.push_button, self.voice_button):
            button.setEnabled(not busy or listening)
            button.setText(
                "STOP LISTENING  /  END SESSION" if listening
                else "START LISTENING  /  SAY HEY ICEWOLF"
            )
            button.setProperty("listening", listening)
            button.style().unpolish(button)
            button.style().polish(button)
        self.stop_button.setEnabled(busy)

    def start_worker(self, mode: str, text: str = ""):
        if self.worker is not None:
            return
        language = self.language_input.currentText()
        if language != "English":
            if mode == "gmail":
                self.set_status("Error — Gmail reports currently require English; change it in Configuration")
                return
            if mode not in ("text", "connect_gmail"):
                self.set_status("Error — voice currently requires English; change it in Configuration")
                return
        model = self.model_input.currentText().strip()
        if mode in ("connect_gmail", "gmail"):
            self.worker = AssistantWorker(None, mode, "", text, self.agents)
            self.worker.status_changed.connect(self.set_status)
            self.worker.message.connect(self.append_message)
            self.worker.failed.connect(self.show_error)
            self.worker.finished.connect(self.worker_finished)
            self.worker.audio_level.connect(self.set_audio_level)
            self.set_busy(True)
            self.worker.start()
            return
        if not model:
            self.set_status("Error — enter a local Ollama model")
            return
        if mode != "text" and not self.whisper_input.text().strip():
            self.set_status("Error — select a local Whisper model folder")
            return
        try:
            if self.client is None or self.client_model != model:
                self.client = OllamaClient(model)
                self.client_model = model
        except ValueError as exc:
            self.set_status(f"Error — {exc}")
            return
        self.worker = AssistantWorker(self.client, mode, self.whisper_input.text(), text,
                                      self.agents, self.speech_pause.value(),
                                      self.custom_agents, self.agent_store, language)
        self.worker.status_changed.connect(self.set_status)
        self.worker.model_checked.connect(
            lambda: self.llm_status.setText(f"LLM: {model} checked")
        )
        self.worker.message.connect(self.append_message)
        self.worker.link_requested.connect(self.show_presentation_link)
        self.worker.failed.connect(self.show_error)
        self.worker.audio_level.connect(self.set_audio_level)
        self.worker.connect_requested.connect(self.request_connect)
        self.worker.gmail_tools_requested.connect(self.request_gmail_tools)
        self.worker.gmail_request_details.connect(self.request_gmail_details)
        self.worker.pdf_email_requested.connect(self.request_pdf_email)
        self.worker.agent_state.connect(self.update_agents)
        self.worker.finished.connect(self.worker_finished)
        self.set_busy(True)
        self.worker.start()

    def show_error(self, message: str):
        if self.llm_status.text() == "LLM: checking":
            self.llm_status.setText("LLM: check failed")
        self.set_status("Error — microphone off")
        self.voice_status.setText(f"Error — {message}")
        self.append_message("Error", message)

    def worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.set_busy(False)
        if not self.status.text().startswith("Error"):
            self.set_status("Ready — microphone off")
        if self.closing:
            self.close()
        elif self.pending_connect:
            self.pending_connect = False
            self.connect_gmail()
        elif self.pending_pdf_email is not None:
            request = self.pending_pdf_email
            self.pending_pdf_email = None
            self.open_gmail_tools(pdf_request=request)
        elif self.pending_gmail_tools is not None:
            action = self.pending_gmail_tools
            self.pending_gmail_tools = None
            request = self.pending_gmail_request
            self.pending_gmail_request = ""
            self.open_gmail_tools(action, request=request)
        elif self.pending_repo:
            self.pending_repo = False
            self.open_repo_dialog()
        elif self.resume_after_repo:
            self.resume_after_repo = False
            self.start_worker("resume_wake")

    def start_wake(self):
        self.start_worker("wake")

    def toggle_wake(self):
        if self.worker is None:
            self.start_wake()
        elif self.worker.mode in ("wake", "resume_wake"):
            self.stop_worker()

    def start_push(self):
        self.start_worker("push")

    def connect_gmail(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Google OAuth desktop client JSON", "", "JSON files (*.json)"
        )
        if path:
            self.current_gmail_message = None
            self.start_worker("connect_gmail", path)

    def check_gmail(self):
        self.start_worker("gmail")

    def request_gmail_tools(self, action):
        self.pending_gmail_tools = action

    def request_gmail_details(self, request):
        self.pending_gmail_request = request

    def request_pdf_email(self, request):
        self.pending_pdf_email = request

    def open_gmail_tools(self, action="", pdf_request=None, request=""):
        if self.worker is not None:
            if self.worker.mode in ("wake", "resume_wake", "presentation"):
                self.pending_gmail_tools = action
                self.gmail_tools_button.setEnabled(False)
                self.stop_worker()
            return
        model = self.model_input.currentText().strip()
        try:
            client = OllamaClient(model)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        from .gmail_ui import GmailTools
        dialog = GmailTools(client, self, selected_message=self.current_gmail_message)
        dialog.message_selected.connect(self.remember_gmail_message)
        if pdf_request is not None:
            QTimer.singleShot(0, lambda: dialog.compose(None, pdf_request))
        elif action == "review":
            QTimer.singleShot(0, dialog.load_unread)
        elif action in ("reply", "modify"):
            QTimer.singleShot(0, lambda: dialog.start_request(action, request))
        elif action in ("find", "bulk_read"):
            QTimer.singleShot(0, lambda: dialog.start_request(action, request))
        elif action == "organize":
            QTimer.singleShot(0, lambda: dialog.load(False))
        elif action == "compose":
            QTimer.singleShot(0, lambda: dialog.compose(None, request=request))
        dialog.exec()

    def remember_gmail_message(self, message):
        self.current_gmail_message = message

    def send_text(self):
        text = self.text_input.text().strip()
        if not text or self.worker is not None:
            return
        self.start_worker("text", text)
        if self.worker is not None:
            self.append_message("You", text)
            self.text_input.clear()

    def stop_worker(self):
        if self.worker is not None:
            if not self.pending_repo:
                self.resume_after_repo = False
            self.worker.stop()
            self.stop_button.setEnabled(False)
            self.push_button.setEnabled(False)
            self.voice_button.setEnabled(False)
            self.avatar_window.listen_button.setEnabled(False)
            self.set_status("Stopping — speech stops shortly; other operations may need to finish")

    def clear_conversation(self):
        if self.client is not None:
            self.client.clear_history()
        self.log.clear()

    def closeEvent(self, event):
        if self.worker is not None:
            self.closing = True
            self.stop_worker()
            event.ignore()
        else:
            self.monitor_timer.stop()
            self.link_display.timer.stop()
            self.link_display.close()
            self.avatar_window.hide()
            self.avatar_window.core.timer.stop()
            if self.tray is not None:
                self.tray.hide()
            if self.model_process.state() != QProcess.ProcessState.NotRunning:
                self.model_process.kill()
                self.model_process.waitForFinished(1000)
            if self.gpu_process.state() != QProcess.ProcessState.NotRunning:
                self.gpu_process.kill()
                self.gpu_process.waitForFinished(1000)
            event.accept()


STYLE = """
QWidget { background: #07111c; color: #d6e5ec; font-family: Segoe UI; font-size: 13px; }
QFrame#sidebar { background: #0a1825; border: 1px solid #20384a; border-radius: 8px; }
QFrame#panel { background: #0c1a28; border: 1px solid #203748; border-radius: 6px; }
QFrame#corePanel { background: #0b1d2c; border: 1px solid #31566a; border-radius: 6px; }
QFrame#sidebar QLabel, QFrame#panel QLabel, QFrame#corePanel QLabel { background: transparent; border: none; }
QFrame#pipelineItem { background: transparent; border: 0px; border-left: 2px solid #315568; border-radius: 0px; }
QLabel#brand { color: #f0fbff; font-size: 25px; font-weight: 700; letter-spacing: 4px; }
QLabel#eyebrow, QLabel#section { color: #8db9c9; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel#heading { font-size: 20px; font-weight: 700; color: #eff8fc; }
QLabel#clock { color: #a4c5d2; font-size: 12px; }
QLabel#status { color: #b9dbe5; font-size: 13px; font-weight: 600; padding: 2px; }
QLabel#status[state="LISTENING"], QLabel#status[state="WAKE LISTENING"],
QLabel#status[state="SPEAKING"] { color: #71e9ee; }
QLabel#status[state="ERROR"] { color: #ff9a94; }
QLabel#muted { color: #a4bac6; font-size: 12px; }
QLabel#itemTitle { color: #d7ecf2; font-size: 11px; font-weight: 600; }
QLabel#footer { color: #a0bac6; font-size: 11px; padding: 2px; }
QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox { background: #091522; border: 1px solid #2a4658;
    border-radius: 4px; padding: 8px; selection-background-color: #285d6e; }
QPlainTextEdit { font-size: 13px; }
QPushButton { background: #13293a; border: 1px solid #365568; border-radius: 4px;
    min-height: 22px; padding: 8px 10px; color: #e0eff5; font-weight: 600; }
QPushButton#navActive { text-align: left; background: #142e3e; border-left: 3px solid #6bdce8; }
QPushButton#primary { background: #147387; border-color: #58cbd6; color: white; }
QPushButton#talk { background: #13788a; border: 1px solid #72dce3; color: white;
    font-size: 14px; font-weight: 700; padding: 12px; letter-spacing: 1px; }
QPushButton#talk[listening="true"] { background: #542f35; border-color: #e8958d; }
QPushButton:hover { background: #244b5d; border-color: #78cbd8; }
QPushButton#primary:hover, QPushButton#talk:hover { background: #198ea0; }
QPushButton#talk[listening="true"]:hover { background: #704249; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QCheckBox:focus {
    border: 2px solid #91f3ff; }
QPushButton:disabled { color: #8ba1ac; background: #152430; border-color: #304450; }
QComboBox::drop-down { border: 0px; width: 24px; }
QCheckBox { spacing: 8px; color: #d6e5ec; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #8db9c9; background: #091522; }
QCheckBox::indicator:checked { background: #20a7b3; border: 1px solid #b8f8ff; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    window = IcewolfWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
