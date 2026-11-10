# Icewolf

**Current version: 0.2.0** — a local-first Windows voice assistant with an
experimental desktop HUD.

Icewolf is an offline-first, local voice assistant for Windows. This first
milestone includes a **command-line prototype and an initial desktop HUD**,
with push-to-talk and opt-in wake-word listening. It records from your microphone, transcribes with a
local faster-whisper model, asks a locally running Ollama model, and speaks using
local Kokoro in the desktop or Piper Ryan in the CLI by default. Conversations are kept only in the
running process.

There are no subscriptions or paid APIs. Installing dependencies and obtaining
models requires an internet connection once; normal operation can then be
offline. Models use disk space and inference takes time: local does not mean
zero latency. Voice quality and speed depend on your PC and installed voice.
Gmail, YouTube video searches, and public GitHub repository lookups are optional
online integrations.

Ask "Who are you?" or "What can you do?" in an English desktop conversation
for an explanation of Icewolf's capabilities and limitations. The explanation
describes the development source, not a check that each optional service is
connected or working. Voice responses are spoken in sections and can be stopped.

### Play YouTube videos

In the development desktop, say or type "search classical piano music and play
it for me" or "search recent videos about TenZ". Icewolf searches YouTube and
asks your default browser to open a matching video in a new window. The link
also appears in Conversation. The browser or YouTube may open a tab instead,
block autoplay, show ads or a consent prompt, or require sign-in for a
particular video. If playback does not start, use the browser's play button.
Icewolf stops its microphone session before the video plays; start listening
again when ready.

The search is sent to YouTube over the internet and is not private or offline.
No subscription or API key is required. Icewolf chooses the first matching
video; for "recent" it chooses the newest result with a recognizable age on the
first search page, not necessarily the newest video on YouTube. Search results
may be inaccurate and YouTube can change its public page, breaking this feature.
This feature is not in the published v0.2.0 installer.

## Project repositories

- Icewolf source repository: [github.com/DennisLeal/icewolf](https://github.com/DennisLeal/icewolf)
- Jarvis project referenced for inspiration: [github.com/ethanplusai/jarvis](https://github.com/ethanplusai/jarvis)

In an English desktop conversation, say or type "show project links" to display
both URLs in the Conversation window. This local command does not contact GitHub.
The public GitHub README lookup is a separate online feature.

In the current development source, English desktop conversations also support
temporary, centered link displays. Say or type one of: "show icewolf release
link", "show ollama download link", "show git download link", "show icewolf
clone link", "show kokoro download link", "show icewolf repository link", or
"show jarvis repository link". Each appears for 15 seconds and is also retained
in the Conversation window. "Show project links" displays both repository
links together. These commands do not fetch or open URLs. The Kokoro URL is the
base used by the source-setup download commands, not a standalone download
page. This display feature is not included in the published v0.2.0 installer.

### What's in 0.2.0

- Per-user Windows installer, dashboard, Voice view, and desktop avatar mode.
- Local wake phrase, continuous conversation, offline speech and local Ollama.
- Local document-backed advisor agents, including the NICE IEX wizard.
- Optional Gmail inbox reports and public GitHub README overviews.
- Show the Icewolf and Jarvis project links directly in the Conversation window.
- Experimental typed replies in Tagalog, Cebuano and Hiligaynon. Voice remains
  English-only, and model quality varies by language.

The development source includes conversational Gmail actions described below;
the published v0.2.0 installer still provides inbox reports only.

## Architecture and roadmap

1. **Foundation (implemented):** Python, `sounddevice` for microphone input,
   `faster-whisper` / CTranslate2 for offline STT, and Piper for offline TTS.
   Windows SAPI (`comtypes`) remains available as a fallback; `pyttsx3` is the
   system fallback on other platforms. Press Enter to record a fixed-length
   clip, or opt into stopping after a pause. The microphone is not open while
   Icewolf is thinking or speaking. Optional Silero VAD detects speech when
   using push-to-talk auto-stop; energy-based detection remains the default.
2. **Local LLM (implemented):** Ollama on `127.0.0.1:11434`, with a short
   in-memory conversation. The desktop defaults to `qwen2.5:7b` if available,
   with an editable selector for installed Ollama models. The CLI retains
   `llama3.2:3b` as its default and accepts `--model`.
3. **Wake word and VAD:** Silero and Whisper support opt-in experimental
   "Hey Icewolf" phrase recognition; openWakeWord supports an optional trained
   "Hey Jarvis" model. VAD detects speech, not a wake phrase.
4. **Dashboard (in progress):** A PyQt6 desktop HUD shows status, conversation
   and errors, and provides text, push-to-talk, and wake-listening controls.
   Device selection and a full settings interface are not included yet.
5. **Tools and memory (in progress):** Document-backed custom agent profiles
   are stored locally in the desktop. Planned opt-in, allowlisted tools include
   `psutil` system information and Python's built-in `sqlite3`. Require clear
   confirmation for changes or script execution; never run arbitrary
   LLM-generated commands. Persistent memory should be explicit and local.
6. **Voice quality and performance (in progress):** Kokoro Adam is used in
   the desktop; measure end-to-end delay, evaluate other licensed voices, and
   consider streaming responses before attempting GPU tuning.

## Setup on Windows

### Get the source

The v0.2.0 repository provides source code; a locally built installer is not
automatically a GitHub Release. Install Git for Windows, then clone the project
into your Documents folder:

~~~~powershell
Set-Location (Join-Path $env:USERPROFILE 'Documents')
git clone https://github.com/DennisLeal/icewolf.git
Set-Location .\icewolf
~~~~

Continue with the setup commands below from the cloned project folder.

Prerequisites: Python 3.10-3.12, an audio input/output device, Ollama with a
**local** model, and a complete local CTranslate2 faster-whisper model directory.
The first setup downloads free software or models if you do not already have
them; no payment or account is required for the recommended public models.

From PowerShell in this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama list
```

If `llama3.2:3b` is not listed, you can download it once with
`ollama pull llama3.2:3b`. Only use an ordinary, locally stored Ollama model:
do not use cloud models or remote Ollama endpoints. Icewolf connects directly
to loopback, rejects cloud-style model names and checks Ollama's reported
remote-model metadata. Those checks cannot control a separately configured or
modified Ollama service; for a strong offline guarantee, disable network access
for Ollama and Icewolf after setup.

For STT, obtain a CTranslate2-format model such as
`Systran/faster-whisper-base.en` once, or use one already in the Hugging Face
cache. Specify the **snapshot directory** containing `model.bin`, `config.json`,
and `tokenizer.json`. For example, if it is not already cached, with internet
access you can download it to the ignored `models` directory:

```powershell
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base.en', local_dir='models/faster-whisper-base.en')"
$env:ICEWOLF_WHISPER_MODEL = (Resolve-Path .\models\faster-whisper-base.en).Path
```

Alternatively, set `ICEWOLF_WHISPER_MODEL` to an existing cached snapshot
directory, or pass `--whisper-model "C:\path\to\snapshot"`. The environment
variable applies to the current PowerShell session. The English model is a
small starting point; choose a multilingual model if needed. Icewolf only
loads an existing directory and requests local-only model loading; it will not
download a speech model on startup.

On the original development PC, a compatible model was already found in the
cache. To use it without downloading a second copy, run:

```powershell
$env:ICEWOLF_WHISPER_MODEL = "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-base.en\snapshots\3d3d5dee26484f91867d81cb899cfcf72b96be6c"
```

### Local voices

The desktop uses **Kokoro Adam** without a voice selection menu. Kokoro runs locally on the CPU,
without sending speech or email content to an online voice service. On a new
machine install `requirements-gui.txt` and download the Kokoro files once:

```powershell
New-Item -ItemType Directory -Force .\models\kokoro | Out-Null
$base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1'
curl.exe --fail --location --output .\models\kokoro\kokoro-v1.0.onnx "$base/kokoro-v1.0.onnx"
curl.exe --fail --location --output .\models\kokoro\voices-v1.0.bin "$base/voices-v1.0.bin"
```

The command-line interface continues to use Piper by default; Piper support and
its model files have not been removed. If Kokoro files are missing, the desktop
reports an error rather than silently switching voices. Kokoro synthesis may
need to finish before a stop request takes effect.

Piper needs both `models\piper\en_US-ryan-medium.onnx` and
`models\piper\en_US-ryan-medium.onnx.json`. They were downloaded on the
original development PC. On a new setup, download both files once:

```powershell
New-Item -ItemType Directory -Force .\models\piper | Out-Null
$base = 'https://huggingface.co/rhasspy/piper-voices/resolve/2f8dbe0bb0dde986411632bf014a13cdbe6596e7/en/en_US/ryan/medium'
curl.exe --fail --location --output .\models\piper\en_US-ryan-medium.onnx "$base/en_US-ryan-medium.onnx"
curl.exe --fail --location --output .\models\piper\en_US-ryan-medium.onnx.json "$base/en_US-ryan-medium.onnx.json"
```

Icewolf loads these files locally; it does not download voices automatically.
Use `--piper-model "C:\path\voice.onnx"` (with a matching
`voice.onnx.json` beside it) or set `ICEWOLF_PIPER_MODEL` to use another
voice. The `models` directory is ignored by Git. Select `--tts system` to
use the previous system voice; missing Piper files cause an explicit error
rather than a silent fallback. `--no-speech` skips speech setup entirely.

Piper defaults to its normal speaking pace (`--piper-length-scale 1.0`).
Increase the value to slow it further, for example `--piper-length-scale 1.7`,
or decrease it to speed it up. The accepted range is 0.5-2.0;
this option only affects Piper. If audio is still distorted rather than merely
fast, compare `--tts system` and check the Windows output device and its audio
settings. The LLM's printed reply helps distinguish unclear text from playback
problems.
Piper plays each reply through one audio stream with a brief silent lead-in to
help prevent an output device from clipping the start of speech.

The maintained `piper-tts` package is GPL-3.0-or-later. The
[Ryan model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ryan/medium/MODEL_CARD)
identifies its training dataset as CC BY-NC-SA 4.0. Review the applicable
licenses before distribution or commercial use; don't assume all Piper voices
have the same terms.

## Run

Start Ollama, then:

```powershell
.\.venv\Scripts\python.exe -m icewolf
```

Press Enter, speak during the five-second recording, and wait for the response.
Use `--seconds 8` to change the recording duration (1-30 seconds).
Press Ctrl+C to exit. If no audio is recognized, check your default Windows
microphone and permissions. If speech output fails, check your Windows voices
and default output device. Restart Icewolf after updating its files so the
running process loads the latest version.

For an experimental pause-based ending to each push-to-talk recording:

```powershell
.\.venv\Scripts\python.exe -m icewolf --auto-stop --seconds 15
```

Press Enter and start speaking. After speech crosses the volume threshold, a
1.2-second quiet pause ends the recording; otherwise it stops at the `--seconds`
maximum, including time spent waiting for speech. This energy-based detector
can mistake background noise for speech or cut off quiet speech. Try
`--speech-threshold 0.005` for a quiet microphone or a higher value in a noisy
room. Omit `--auto-stop` to use the original fixed-length recording.

For speech-aware detection using the Silero model bundled with Faster-Whisper,
instead of the energy threshold:

```powershell
.\.venv\Scripts\python.exe -m icewolf --auto-stop --vad silero --seconds 15
```

This still requires pressing Enter; it is not always-on or a wake word.
`--vad-threshold 0.5` controls the speech probability threshold. Background
noise, echo and quiet speech can still cause mistakes; adjust the threshold
after testing your microphone. The bundled model runs on the CPU locally.

### Optional wake-word mode

Wake listening is **off by default**. With the local Whisper model already set,
start the experimental "Hey Icewolf" detector with:

```powershell
.\.venv\Scripts\python.exe -m icewolf --wake --seconds 15
```

This uses Silero VAD and Faster-Whisper on the CPU to recognize the phrase
locally. It is **not** a trained openWakeWord model: it uses more compute,
recognition can miss or falsely activate, and microphone performance must be
tested in your room. The microphone pauses while each utterance is being
transcribed. It only accepts the phrase by itself; wait for "Wake detected.
Speak now" before giving a request. Adjusting `--wake-threshold` does not affect
this detector. In a synthetic-audio test, "Hey ice wall" was misrecognized as
"Hey Icewolf" and activated it, so do not treat it as an authentication or
security control.

The optional trained "Hey Jarvis" alternative needs a one-time download
of the optional package and the official openWakeWord feature models:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-wake.txt
New-Item -ItemType Directory -Force .\models\openwakeword | Out-Null
$base = 'https://github.com/dscripka/openWakeWord/releases/download/v0.5.1'
curl.exe --fail --location --output .\models\openwakeword\melspectrogram.onnx "$base/melspectrogram.onnx"
curl.exe --fail --location --output .\models\openwakeword\embedding_model.onnx "$base/embedding_model.onnx"
```

Download the "Hey Jarvis" model:

```powershell
curl.exe --fail --location --output .\models\openwakeword\hey_jarvis_v0.1.onnx "$base/hey_jarvis_v0.1.onnx"
.\.venv\Scripts\python.exe -m icewolf --wake-model .\models\openwakeword\hey_jarvis_v0.1.onnx --seconds 15
```

The microphone listens continuously for that model's phrase only while this
mode is active. After "Wake detected. Speak now" appears, pause briefly, then
give your request; Silero stops recording after a quiet pause or the maximum
duration. Words spoken during the wake phrase may not be captured. The
microphone closes while the assistant transcribes, thinks, and speaks, then
reopens for the next wake phrase. Barge-in is not implemented. Press Ctrl+C to
stop. Wake detection can miss phrases or activate falsely; tune the trained
openWakeWord model using `--wake-threshold` (0-1, default 0.5). No audio is sent to a cloud
service by this mode.

For a different trained phrase, use `--wake-model` with a compatible
single-output openWakeWord ONNX model. Normal push-to-talk and the experimental
Hey Icewolf detector do not require openWakeWord. The model
and feature assets were downloaded on the original development PC. Review
openWakeWord and model licenses before distributing them.

### Desktop HUD

Install the optional desktop dependencies once, then launch:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe -m icewolf.desktop
```

After setup, you can also double-click **Start-Icewolf.cmd** in the project
folder to launch the HUD without a console window. Ollama must be running with
the configured local model available. Opening Icewolf does not automatically
enable the microphone.

### Windows installer

The published v0.2.0 Windows pre-release is available at [GitHub Releases](https://github.com/DennisLeal/icewolf/releases/tag/v0.2.0);
download the **Icewolf-Setup.exe** asset from its **Assets** list.

The per-user installer is built as `dist\Icewolf-Setup.exe`. Close any running
Icewolf instance before installing. The installer places the application in
`%LOCALAPPDATA%\Programs\Icewolf`, creates a Start menu shortcut, and offers an
optional desktop shortcut. It includes the local Kokoro voice files. It does
not install Ollama or an Ollama language model; both must be available
separately. Whisper uses the existing local cache or a folder selected in
Configuration.
The installer and included documentation identify this version as 0.2.0.
Building the installer locally does not create a GitHub Release.

The optional migration task copies the existing project settings and agent
database to `%LOCALAPPDATA%\Icewolf\UserData` only when the corresponding
destination file does not already exist. It never removes the originals.
Gmail authorization remains in Windows Credential Manager. If the agent
database is in use, migration stops and asks you to close Icewolf. Uninstall
does not remove the user data or voice models; delete those separately only
if you no longer want them. The installer is unsigned and Windows may show a
publisher warning.

To rebuild on this PC, install the GUI and build requirements in `.venv`,
install the Inno Setup compiler at `.tools\InnoSetup`, and run
`.\packaging\build-installer.ps1` in PowerShell. The build requires the two
Kokoro model files in `models\kokoro`. Generated build output is ignored by
Git. The migration source is the project folder on the build PC, so on another
PC this optional migration only works if its original data is at that same
path. No personal settings, study materials, or credentials are bundled in
the installer.

The **Typed conversation language** selector in Configuration offers English,
Tagalog, Cebuano (Bisaya), and Hiligaynon. The three additional choices are
experimental: they ask the selected local LLM to respond in that language, and
the quality depends on the model. They support typed conversation only and do
not speak responses. Voice recognition, voice output, and conversation-driven
integrations and agent commands still require English. Select English again to
use those features. This setting does not install language models.

The HUD selects the cached `base.en` Whisper model if available; otherwise
choose its local model folder under **Configuration**. Whisper converts your
speech into text; Kokoro turns Icewolf's replies into speech. `base.en` is a
small English model, not a verified best choice for your hardware. Type a
message or click **Start listening** once to enable wake listening. Say
**Hey Icewolf** once and wait for Icewolf's greeting. Then speak whenever
**Conversation listening — speak now** appears. Icewolf waits through silence
and listens again after each reply without another wake phrase. The microphone
remains active while waiting for conversation until you stop the session.
Icewolf waits for 3 seconds of detected silence after you speak before responding.
Under **Configuration**, adjust **Wait after you stop speaking** from 1.5 to
8 seconds between sessions; 3 seconds is the default, but an existing saved
setting may differ. A longer setting accommodates longer pauses but delays replies.
Speech detection can still mistake a quiet voice or background noise for silence.
Individual recordings can retain up to 5 minutes, including pre-roll and the final pause. If
that limit is exceeded, Icewolf waits for you to finish, reports that the request
was not sent, and keeps listening; repeat the request in shorter parts.
Click **Stop listening** or **Stop / cancel** to end the session and interrupt audio
playback; synthesis, recording,
and inference may still need time to finish. Closing the window also waits for
the current operation. No barge-in is available. The HUD uses the Windows
default audio devices and local Ollama. Choose the Ollama model under
**Configuration**; the model selection is saved. Device selection and other
desktop backends remain future work. The centered, animated particle sphere
is drawn at 20% opacity (80% transparent) over the HUD background;
the window, status text, and controls remain opaque. The core animates continuously;
its size and waveform respond to microphone levels while recording and to Kokoro
playback levels while speaking. Its idle movement is decorative, and it does
not capture all system audio or monitor the microphone during replies.
Choose **Voice view** in the sidebar for a larger core and a focused
listening control; **Conversation** returns to the dashboard. Both views
control the same voice session.

Select **Avatar-only mode** in the sidebar to replace the HUD with a small,
movable desktop avatar. Drag the avatar to reposition it. Its **Start
listening** / **Stop** button controls the same opt-in voice session, and
**Open HUD** returns to the full interface without restarting that session.
The avatar reflects voice status and audio levels, and respects **Reduce
avatar motion**. It stays behind ordinary windows rather than covering other
apps; it is a small window, not a desktop icon. Windows **Show desktop** can
minimize it as well. If the Windows system tray is available, click the Icewolf
tray icon or use its menu to restore the HUD or avatar; otherwise restore the
avatar from its taskbar entry. Closing the full HUD or choosing **Exit
Icewolf** in the tray ends the application and its voice session. Minimize
or use avatar mode to keep it running. Icewolf does not start automatically
with Windows.

### Customizing the assistant

Configuration lets you choose the local Ollama model, Whisper folder,
conversation pause, typed conversation language and avatar motion. The agent
wizard lets you define your own advisor and attach local documents.

The assistant's name and wake phrase are not configurable in the UI. To
customize them, obtain the source, make a backup, and use the Windows setup
instructions above to create a development environment. The installed
executable does not automatically pick up changes to source files.

1. Edit `SYSTEM_PROMPT` and the role-specific prompts in `icewolf\ollama.py`
   to change the assistant's identity and how it addresses the user.
2. Update the transcription prompt in `icewolf\audio.py` and the fixed greeting,
   window labels, status messages, and command handling in
   `icewolf\desktop.py`. Search for both `Icewolf` and `Dennis`; changing the
   prompt alone does not change all displayed or spoken names.
3. For a different wake phrase, update `is_icewolf_phrase`, the inline-request
   matcher, and the transcription prompt in `icewolf\wake.py`. Also update the
   wake handoff, greeting and labels in `icewolf\desktop.py`; review the CLI
   in `icewolf\__main__.py` if you use it. The detector is experimental, so
   recognition of a new phrase is not guaranteed.
4. Update the related tests in `tests\test_wake.py` and
   `tests\test_desktop.py`; run the suite as described below, then try the new
   phrase with your own microphone. Run the desktop from source using
   `.\.venv\Scripts\python.exe -m icewolf.desktop`.
5. To install your modified version, follow the installer rebuild instructions
   above. Changing the installer name, shortcuts, user-data location or Gmail
   credential name also requires separate changes to packaging or application
   code; plan data migration carefully before doing so.

Never commit personal settings, OAuth client files, tokens, or private study
materials. Review model and dependency licenses before distributing your copy.

### Create a local document-backed agent

The desktop's **Create agent** button opens a wizard prefilled for a
**NICE IEX Administrator**; you can change the name and role description for
another specialty. Select study materials in the wizard, or add them later:

1. Select **Create agent**, review the name and responsibilities, and select
   **Select study materials**. Choose PDFs with selectable text, Word `.docx`,
   UTF-8 `.txt`, or Markdown `.md` files, then select **Save**.
2. The new agent is attached for the current session. After restarting Icewolf,
   select it under **Agent roles** and choose **Attach agent**.
3. Type or say, for example, **"Ask NICE IEX Administrator agent to explain
   forecast settings"**. After waking Icewolf, wait for conversation listening
   before speaking. The answer appears in the conversation with the excerpts'
   source names and PDF page numbers when available.
4. To update the knowledge base, select the agent and use **Add study
   materials**. Use **Manage study materials** to list or remove a document
   from that agent. Removal does not delete your original file.

Icewolf extracts document text into `data\agents.sqlite3` on this PC and keeps
agent profiles there between restarts; it does not upload documents or change
the local model's weights. The database is **not encrypted** and is excluded
from Git, but anyone with access to the PC or its backups may be able to read
it. Removing a document is not a secure erase from disk or backups. Add only
materials you are authorized to use; avoid passwords or other secrets. Original files are not watched for changes:
remove and re-add a document to refresh it. Each file is limited to 10 MB,
one million extracted characters and, for PDFs, 500 pages; up to 100 documents
can be added per agent. Encrypted PDFs and scanned PDFs without extractable
text are not supported. The wizard reports import errors instead of silently
skipping files.

Reference lookup uses basic local keyword matching, not full-text understanding;
use specific words from your material. If no matching passage is found, the
agent says so. Relevant passages and your question are sent only to the
configured local Ollama endpoint, subject to the offline caveat above. The
model can still misunderstand documents, follow misleading text, cite the
wrong passage, or make mistakes; check the listed sources and verify any
administrative steps before applying them. Agents provide advice only; they
cannot access NICE IEX or execute changes. Online agent catalogs, external
downloads, OCR, and model fine-tuning are not included.

**Configuration → Reduce avatar motion** stops the decorative animation while
retaining audio-level updates. The setting is saved; on first use, it follows
the Windows animation preference when available. The system monitor
shows CPU and memory via psutil, and NVIDIA GPU/VRAM when `nvidia-smi` is
available; other GPU vendors are not currently monitored. The LLM indicator
reflects the last model check, not continuous availability. The pipeline panel
describes configured components rather than reporting their health. The
conversation is kept only in memory.

The sidebar can attach Research, Coding, and Marketing roles for this session.
Say or type, for example, **"ask research agent to explain caching"**.
These roles are local LLM advisors, not autonomous agents: they cannot browse,
access files, execute code, or perform tasks on your behalf. Green means a role
is processing a request; red means attached but idle; black means no roles are
attached. Attachments are not saved between sessions. Social integrations and
quick-command integrations are not implemented.

### Check a public GitHub repository

This optional feature contacts **GitHub over the internet**, without a login or
token. Icewolf's model still runs locally. It reads public repository metadata
and up to the first 16,000 characters of the default README; it does **not**
inspect source files, test the project, verify claims, or perform a security
review.

- Select **GitHub repo** in Conversation or Voice view, paste a repository-root
  URL such as `https://github.com/owner/repository`, optionally type a question,
  and select **Check repository**.
- Alternatively, paste the link in a conversation message with your question,
  for example: `What does this project do? https://github.com/owner/repository`.
  Sending a message containing a GitHub URL initiates an online lookup.
- If you open the dialog during a wake session, Icewolf pauses the microphone.
  After the answer (or if you cancel), it resumes listening without requiring
  another wake phrase. Press **Stop / cancel** to stop instead.

The conversation reports which source was consulted and if the README was
truncated or absent. Private repositories, URLs to files or subdirectories,
and GitHub sign-in are not supported. GitHub may impose unauthenticated rate
limits. Repository content is untrusted; answers can be incomplete or
incorrect, so check the source. Repository contents are not saved as agent
study materials or included in subsequent unrelated questions. As with all
local-model requests, the existing Ollama offline caveat applies.

In an English conversation, say or type **"show project links"** to display
the Icewolf repository and the Jarvis inspiration repository in the
conversation. This command displays the links locally; it does not fetch them.

### Gmail: optional online connection

Gmail access contacts Google over the internet. The development source uses
conversational Gmail actions rather than a separate Gmail tools window. Ask in
English by voice or text, for example "find email from person@example.com",
"read the first email", "reply to that and say thank you", or "mark all
inbox messages read". Icewolf uses the selected local Ollama model to interpret
requests, so it can misinterpret instructions or produce incorrect text.

**Sending, saving drafts, labeling, archiving, marking read/unread and starring
happen without an additional confirmation when requested.** Review the
conversation and be aware that voice transcription or the model may be wrong.
Icewolf asks you to identify ambiguous messages or supply missing details. The
first five matching results are shown and numbered; read a numbered result to
select it for follow-up requests. Recipient addresses must be given explicitly,
except "to me" uses the connected address and replies use the original sender.
Only existing user labels are supported. Attachments and document creation are
not supported in this conversational workflow.

Deletion is limited to moving messages to Gmail Trash, never permanent deletion.
Icewolf first lists the targets and requires a separate "yes" or "confirm";
"no" or "cancel" cancels, and the request expires after two minutes. Trash
may be emptied by Gmail according to its retention policy. Email content is
untrusted and is not supplied as an instruction to the Gmail request interpreter.
There is no background monitoring or work/family alert feature. The app must be
running and online; this is not available in the published v0.2.0 installer.

To connect, enable the Gmail API in your Google Cloud project, configure OAuth
consent, and add your account as a test user if the app is external and in
Testing. Create a Desktop app OAuth client, keep its downloaded JSON private,
then select **Connect or reconnect Gmail** in Icewolf's Configuration and grant
`https://www.googleapis.com/auth/gmail.modify`. Credentials are stored in
Windows Credential Manager. This restricted scope allows broad mailbox access;
Google may require verification for distribution. Do not commit credentials.

If Icewolf reports insufficient permission, or you connected before the
scope changed from `gmail.readonly`, open **Configuration**, select **Connect
or reconnect Gmail**, choose the same OAuth desktop client JSON, and approve
the requested access. Consent is requested only when you choose to connect or
reconnect. The existing credential is not deleted automatically. If Google
does not return a refresh token, Icewolf reuses the saved token only if the
OAuth client and Gmail account match and a refresh confirms modify access.
Otherwise it preserves the old credential and asks you to reconnect again.

For manual recovery only, you can remove the `Icewolf Gmail` entry in Windows
Credential Manager and reconnect after reviewing the impact: this removes the
local saved authorization, not Google's account grant, and requires a fresh
successful authorization. Do not remove it automatically. Google Cloud must
have the Gmail API enabled, the modify scope configured, and the correct test
user included for an external app in testing. Restricted scopes may require
Google verification for broader distribution.

Consult Google's [Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python)
and [scope documentation](https://developers.google.com/workspace/gmail/api/auth/scopes)
for current requirements. Facebook and TikTok require their own developer
registration and permissions; they are not connected in this release.

To try the local LLM without installing audio packages or a Whisper model:

```powershell
py -3.12 -m icewolf --text --no-speech
```

To type and hear responses, omit `--no-speech` after installing the dependencies.
In text mode, type `/clear` to discard the current in-memory conversation.
Console output includes conversation text, so protect terminal logs and
screenshots if they contain private information. Ctrl+C or Ctrl+Z then Enter
exits and clears Icewolf's in-memory conversation; Ollama and the OS may have
their own logging or caching settings.

## Improving the local brain

The default remains `llama3.2:3b` for a lighter baseline. Your PC already
has `qwen2.5:7b`, a larger alternative to compare without a download:

```powershell
.\.venv\Scripts\python.exe -m icewolf --auto-stop --seconds 15 --model qwen2.5:7b
```

Model size alone doesn't guarantee better answers. Compare the same practical
prompts for accuracy and response time; loading a different model can be much
slower than a warm response, and available GPU memory varies with other apps.
Use `--model llama3.2:3b` to switch back. Icewolf asks the model to acknowledge
uncertainty and not claim to use tools it doesn't have; these are instructions,
not a guarantee. The CLI has no live web access, persistent conversation
memory, or tool execution. Useful next steps are a repeatable local prompt
benchmark, measured end-to-end latency, speech-aware VAD, and opt-in
allowlisted tools with confirmation for changes.

An OpenAI-compatible local server such as LM Studio can be used instead of
Ollama. Start its local server, load a model, and pass the exact ID exposed by
its `/v1/models` endpoint:

```powershell
.\.venv\Scripts\python.exe -m icewolf --text --backend openai --llm-port 1234 --model "your-loaded-model-id"
```

The client always connects to `127.0.0.1`; it does not support remote endpoints
or credentials. The server itself must also use a local model and must not
forward requests to a cloud provider. Loopback alone does not guarantee that.
This backend has not yet been tested against LM Studio on this machine.

Streaming replies, barge-in, and live device selection are not implemented yet.
Kokoro and Piper are offline voices; Edge-TTS is not included because it needs an
online service. The goal is to preserve push-to-talk as a fallback.

## Tests

The tests use fakes and need no microphone, models, downloads, or Ollama.
Install `requirements-gui.txt` first; the suite imports the optional desktop
and wake-word dependencies as well as NumPy:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

They do not replace an end-to-end microphone and speaker test on your machine.
