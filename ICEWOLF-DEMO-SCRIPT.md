# Icewolf v0.2.0: installation and presentation script

Hi, I'm Dennis, also known as Papsi, and I'm an AI enthusiast. I built
Icewolf because I was curious about what it would take to make an AI
assistant that I could talk to on my own computer. So, in this video, I'll
show you what Icewolf can do, explain how I built it, and walk you through
what you need and how you can install it on your own Windows PC. I'll also
show you how you can explore the code and start making the assistant your own.

The idea is to have a local-first voice assistant that can listen, respond,
and speak using models running on my computer, without a paid cloud AI
subscription. Icewolf is still an early project, so I'll be clear about what
works today and what it can't do yet.

Before we install anything, let's talk about the bare essentials. You'll
need a Windows PC compatible with 64-bit x64 software, a microphone, and
speakers or headphones. You'll also need enough free storage and memory for
Icewolf and the models you choose, and an internet connection for the
initial downloads. Icewolf doesn't have a verified minimum RAM or storage
requirement yet; smaller models are a good starting point, but speed and
whether a model fits in memory depend on your PC. A dedicated GPU isn't
required for Icewolf's speech recognition or voice synthesis, though your
local language model's performance will depend on your hardware.

## Step-by-step installation

This recording uses the published Windows installer. The optional source route
below explains how to download a local speech-recognition model and run Icewolf
from the repository.

### Install from the published Windows pre-release

1. Open the [Icewolf v0.2.0 pre-release](https://github.com/DennisLeal/icewolf/releases/tag/v0.2.0).
   Under **Assets**, download **Icewolf-Setup.exe**. The package is unsigned, so
   Windows may show a publisher warning. Verify the source before continuing.
2. Run the installer, follow its steps, choose whether to add a desktop
   shortcut, and launch Icewolf from the Start menu or desktop.
3. Install [Ollama for Windows](https://ollama.com/download/windows) and start
   it. In PowerShell, check for a local model:

~~~~powershell
ollama list
~~~~

4. If the list does not include a local model, download the example model once,
   then check the list again:

~~~~powershell
ollama pull llama3.2:3b
ollama list
~~~~

5. Icewolf also needs a local Faster-Whisper model directory containing
   **model.bin**, **config.json**, and **tokenizer.json**. The installer does
   not include this model. If you already have a compatible local model, keep
   its folder path ready. Otherwise, use the optional source setup below to
   download one.
6. In Icewolf, open **Configuration**. Select your installed Ollama model,
   choose the Whisper model folder with **Browse folder**, and set **Typed
   conversation language** to **English** for voice and integrations. Return
   to **Conversation**, select **Start listening**, and wait for the status
   before saying **"Hey Icewolf."**

### Optional source setup and model download

1. Install Python 3.12 and [Git for Windows](https://git-scm.com/download/win).
   Icewolf supports Python 3.10 through 3.12; these commands use 3.12.
2. Open PowerShell and clone the repository:

~~~~powershell
Set-Location (Join-Path $env:USERPROFILE 'Documents')
git clone https://github.com/DennisLeal/icewolf.git
Set-Location .\icewolf
~~~~

3. Create a virtual environment and install the desktop requirements:

~~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
~~~~

4. Download the English speech-recognition model into the project folder:

~~~~powershell
.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base.en', local_dir='models/faster-whisper-base.en')"
$env:ICEWOLF_WHISPER_MODEL = (Resolve-Path .\models\faster-whisper-base.en).Path
~~~~

5. The source desktop setup also needs the local Kokoro voice files. Download
   them once:

~~~~powershell
New-Item -ItemType Directory -Force .\models\kokoro | Out-Null
$kokoroBase = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1'
curl.exe --fail --location --output .\models\kokoro\kokoro-v1.0.onnx "$kokoroBase/kokoro-v1.0.onnx"
curl.exe --fail --location --output .\models\kokoro\voices-v1.0.bin "$kokoroBase/voices-v1.0.bin"
~~~~

6. Keep Ollama running, then launch the source desktop app:

~~~~powershell
.\.venv\Scripts\python.exe -m icewolf.desktop
~~~~

In Configuration, select the local Ollama model, set **Whisper model folder**
to **models\faster-whisper-base.en**, and choose English. The published
installer already includes Kokoro files; source setup downloads them separately.
For the complete setup details, use the README in the Icewolf repository.

The initial setup needs an internet connection to download the software and
models. After that, the core voice pipeline and a locally configured language
model can run on your computer without a subscription. Local doesn't mean
instant, though: recognition, generating an answer, and creating speech all
take processing time. Gmail and GitHub lookups are optional features that
still need internet access.

Icewolf is built in Python, with a desktop interface made using PyQt. When I
speak, speech activity detection helps identify when I'm talking.
Faster-Whisper turns my voice into text, Ollama runs the language model
locally, and Kokoro generates the spoken response. The dashboard brings those
pieces together, showing the conversation, the current assistant status, and
information about CPU and memory usage. If NVIDIA's monitoring tool is
available, it can also show GPU information.

Now let me show you a conversation. Opening Icewolf doesn't automatically
turn on the microphone, so I'll select Start listening and wait for the
wake-listening status. Then I'll say, "Hey Icewolf."

After Icewolf greets me and shows that it's listening, I can ask, "Suggest an
easy snack." Once he finishes answering and starts listening again, I can
follow up with, "What could I drink with that?"

I only need to say the wake phrase once for this listening session. Icewolf
continues listening for follow-up requests after each reply until I stop the
session. When I am done, I select **Stop listening**.
I can also type a message in Conversation and select **Send**.
**Clear** clears the visible transcript and resets the current in-memory chat history. The microphone closes while he's transcribing, thinking, or
speaking, so he can't hear an interruption during that time. In Configuration,
I can also change how long he waits after I stop speaking. A longer wait gives
me more time to pause, while a shorter wait can feel faster but may interrupt
me if I haven't finished my thought.

Icewolf's interface includes the main Conversation view and a focused Voice
view with a larger animated core. The core responds to microphone and speech
levels, and I can reduce its motion in Configuration. There's also an
avatar-only mode: I can move the small avatar around the desktop, start or
stop listening from it, and return to the full interface with Open HUD. The
avatar stays behind ordinary windows, and the system tray can help me restore
it when available. It isn't a permanent desktop icon, and Windows Show
desktop may minimize it.

I also want to show you the projects behind this demonstration. Icewolf will
display the repository links in his Conversation window. I'll open Conversation, select **Start listening** if needed, say **"Hey Icewolf"**, and then ask him:
"Show project links."

The Conversation window should now show both links:
- Icewolf: https://github.com/DennisLeal/icewolf
- Original Jarvis project: https://github.com/ethanplusai/jarvis

Icewolf is its own local-first implementation. Displaying these links happens
locally; it doesn't contact GitHub.

Another feature I'm excited about is the ability to create a specialist
advisor. I'll open the agent creation wizard, change the prefilled name to
"Marketing Specialist," and describe the kind of marketing advice I want.
Then I'll choose study materials, such as a PDF with selectable text, a Word
document, a text file, or a Markdown file, and save the agent. It's attached
for this session; after restarting Icewolf, I can attach it again from the
Agent roles list. Later, I can add or manage its materials.

For example, after adding a marketing guide, I can ask,
"Ask Marketing Specialist agent to explain our target audience." Icewolf
looks for relevant passages in the documents I've added and provides them to
the local model. When it finds useful material, the conversation can show the
source names and PDF page numbers.

It's important to understand what that means: adding documents does not
retrain the language model. This is a document-backed reference assistant,
and its answers and citations can still be wrong, so I need to check the
source. It can't log into marketing accounts or make changes. The extracted document
text is stored locally without encryption, so I should only add material I'm
allowed to keep on this PC and avoid secrets. Icewolf also has Research,
Coding, and Marketing advisor roles, but those roles offer advice rather than
independently browsing or executing code. For the demo, I can attach Research, ask a question, then point out Coding and Marketing in the Agent roles list.

Icewolf can also help me look at a public GitHub repository. I can select the
GitHub repo button, paste a public repository link, add a question, and ask
Icewolf to check it. This feature goes online to read public repository
information and an excerpt of its README. It does not inspect the project's
source code, run tests, or verify its security, so I should check the original
repository for myself.

There's an optional Gmail connection as well. After setting up a Google OAuth
desktop client and enabling the Gmail API, I can use Connect or reconnect
Gmail in Configuration and review the permission request in my browser. The
credential is stored in Windows Credential Manager. For privacy, I won't show
my sign-in details, client file, or private messages in this recording.

Once connected, I can ask, "Check my Gmail." Icewolf can report up to the
five latest inbox messages, displaying senders, subjects, and short previews
while speaking shortened sender names and subjects. The current authorization
requests Gmail modify access, which is broader than reading, but the
application itself only implements inbox reports today. It cannot yet send
or draft messages, change labels or read status, delete messages, or monitor
the inbox automatically. Gmail access requires an internet connection.

For typed conversations, Icewolf also offers experimental Tagalog, Cebuano,
and Hiligaynon options alongside English. I can stop listening, open
Configuration, choose a typed conversation language, and type a message.
These options ask the local model to respond in the selected language, so
quality depends on the model and Hiligaynon may be unreliable. They do not
currently provide spoken responses or speech recognition in those languages.
I'll switch back to English to use voice and the conversation integrations.

If you want to make Icewolf your own, you can already choose a different
local Ollama model, adjust the speech pause, reduce avatar motion, and create
your own document-backed advisor in the interface. Renaming the assistant or
changing the wake phrase isn't a setting yet. To do that, you'll need the
source code. The README explains where the assistant's prompts, greeting,
wake phrase, and display labels are defined, and how to run and rebuild a
modified copy. Changing the name on the screen alone won't change the phrase
the microphone listens for, so it's important to update the related code and
test it with your own microphone.

So that's Icewolf version 0.2.0: a local-first voice assistant with an
interactive Windows dashboard, a compact avatar, ongoing voice conversation,
document-backed advisors, and optional Gmail and public GitHub features.
It's a work in progress, and features such as autonomous document creation
and sending email haven't been implemented yet.

Thanks for watching. You can find the source, setup instructions, and
pre-release on the [Icewolf GitHub
repository](https://github.com/DennisLeal/icewolf), and the original visual
inspiration at the [Jarvis
repository](https://github.com/ethanplusai/jarvis).
