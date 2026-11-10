# Icewolf presentation script

Hi, I'm Dennis, also known as Papsi, and I'm an AI enthusiast. I built Icewolf
because I was curious about what it would take to make an AI assistant that I
could talk to on my own computer. In this video, I'll explain how Icewolf
works, show you its features, walk you through installing it on your Windows
PC, and share how you can make it your own.

Icewolf is a local-first voice assistant. Its core speech recognition,
language model, and voice synthesis run on your computer, without a paid AI
subscription. It's an early project, not a fully autonomous assistant, so
I'll also explain its current limitations.

Let's start with what you need. You'll need a Windows PC compatible with
64-bit x64 software, a microphone, speakers or headphones, enough memory and
storage for the app and your chosen models, and an internet connection for
the initial downloads. Icewolf doesn't have verified minimum memory or
storage requirements yet, and its speed depends on your hardware and model
choice. A dedicated GPU isn't required for its speech recognition or voice
synthesis.

To install Icewolf, visit the Icewolf release page. The link is appearing in
the Conversation panel and on screen, so you can pause the video and copy it
into your browser's address bar. Open the version 0.2.0 pre-release, find
Assets, and download Icewolf-Setup.exe. The installer is unsigned, so Windows
may show a publisher warning; verify the source before deciding to proceed.
Run the installer, follow the prompts, choose whether to create a desktop
shortcut, and launch Icewolf.

Next, you'll need Ollama for Windows. Download and install it, then make sure
it's running. Ollama runs the local language model that generates Icewolf's
answers. In PowerShell, use the command "ollama list" to see your installed
models. If you don't have one, the README shows how to download a small
starting model, Llama three point two, three B, with the command "ollama pull
llama three point two, colon three b." Copy the exact command from the README.

Icewolf also needs a local Faster-Whisper model for speech recognition. The
installer includes the Kokoro voice, but not Ollama, an Ollama language model,
or a Whisper model. If you already have a compatible Faster-Whisper model,
you can use its folder. Otherwise, follow the README's Windows setup and
model-download instructions. The documented download method uses Python and
project dependencies; the packaged app itself doesn't require Python or Git.

If you're setting up from source, you'll also need Git for Windows. After
installing Git and Python, you can clone the project using the Icewolf clone
address. The README provides the exact PowerShell commands to clone the
repository, create a Python environment, install dependencies, and download the
Whisper model. Source setup also requires the Kokoro voice files. The Kokoro
download address shown on screen is the base address used by the README's
commands; those commands add the individual filenames.

Once your models are ready, open Icewolf's Configuration. Choose your
installed local Ollama model and use Browse folder to select the Whisper
model folder containing model dot bin, config dot JSON, and tokenizer dot
JSON. Select English for voice and integrated commands. Once everything has
been downloaded and configured, the core voice pipeline can work offline.
Optional Gmail and GitHub features still need an internet connection, and
local processing can take time.

Icewolf is built in Python with a PyQt desktop interface. Speech activity
detection helps identify when I'm talking. Faster-Whisper transcribes my
voice, Ollama runs the language model locally, and Kokoro produces the spoken
reply. The dashboard shows the conversation, assistant status, and CPU and
memory information. If NVIDIA's monitoring tool is available, it can also
show GPU information.

Now let's have a conversation.

Hey Icewolf.

Suggest an easy snack.

What could I drink with that?

That was our conversation demo.

In normal use, the microphone is off until I choose to start listening. After
the wake phrase, Icewolf can listen for follow-up requests until I stop the
session. The microphone closes while it transcribes, thinks, or speaks, so it
can't hear interruptions then. In Configuration I can adjust how long Icewolf
waits after I stop speaking. A shorter pause feels faster but can cut me off;
a longer pause gives me more time to finish.

I can also type a message in Conversation. Clear removes the visible
conversation and resets the current in-memory chat history. The Voice view
shows a larger animated core, and I can reduce its motion in Configuration.
There's also an avatar-only mode that I can move around the desktop, with
controls to start or stop listening and return to the full interface. The
avatar stays behind ordinary windows, and Windows Show desktop can minimize
it. The system tray can help restore it when available.

The Icewolf repository contains the source code, setup instructions, and
release information. The original Jarvis repository is the project that
inspired the visual direction. Their links appear in the Conversation panel,
and you can pause the video to copy them. Displaying these links is local and
doesn't contact GitHub.

Another feature is the ability to create a specialist advisor. In the agent
creation wizard, I can change the prefilled name and description to create a
Marketing Specialist, then add a PDF with selectable text, a Word document,
a text file, or a Markdown file. The agent is attached for the current
session, and I can attach it again after restarting Icewolf. I can also add
or manage study materials later.

With a marketing guide attached, I can ask the Marketing Specialist to
explain the target audience. Icewolf searches the documents for relevant
passages and provides them to the local model. When useful material is found,
the conversation can show source names and PDF page numbers. This doesn't
retrain the model, and answers and citations can be wrong, so always check
the original source. Extracted document text is stored locally without
encryption, so only add material you're allowed to keep on your PC and avoid
secrets. The built-in Research, Coding, and Marketing roles offer advice;
they don't independently browse, execute code, or perform tasks.

Icewolf can also look up a public GitHub repository through the GitHub repo
button. This optional online feature reads public metadata and an excerpt of
the README. It does not inspect source code, run tests, or verify security.

There's an optional Gmail connection too. After setting up a Google OAuth
desktop client and enabling the Gmail API, I can use Connect or reconnect
Gmail in Configuration and review the permission request in my browser. The
credential is stored in Windows Credential Manager. I won't show private
messages or sign-in details during the recording.

Once connected, the published version can report up to five recent inbox
messages, showing senders, subjects, and short previews. In the development
version shown here, Gmail tools also offer an on-demand review of unread mail,
full message and thread viewing, drafting and replies, and a preview of proposed
inbox labels. I select the message before replying or changing it, and can ask
Icewolf to reply to that selected message. An inbox-wide mark-read request
shows the affected messages for approval. Sending,
reply drafts and organizing require my confirmation. Unreported messages stay unread, and
Icewolf does not delete mail. Classification uses message previews and can
make mistakes, so I can check the messages it initially hides. Gmail features
need an internet connection and are not an automatic background monitor.
Work and family alerts are not implemented.

For typed conversations, Icewolf also offers experimental Tagalog, Cebuano,
and Hiligaynon alongside English. The local model's ability varies, and
Hiligaynon may be unreliable. Voice recognition and spoken replies in those
languages aren't implemented yet; use English for voice and integrations.

You can make Icewolf your own by choosing another local model, adjusting the
speech pause, changing avatar motion, or creating a document-backed advisor.
Renaming the assistant and changing the wake phrase require source-code
changes; they aren't settings in the interface yet. The README explains
where to look and how to rebuild your modified copy. Updating a display
name alone doesn't change the wake phrase.

That's Icewolf version 0.2.0: an early local-first voice assistant with a
Windows dashboard, voice conversations, a desktop avatar, document-backed
advisors, and optional Gmail and public GitHub features. In the development
version, Icewolf can also prepare a locally generated PDF as an email
attachment for me to review. It can't carry out arbitrary tasks, and the newer
Gmail tools require my approval before sending or organizing messages.

Thanks for watching. I hope this gives you a useful starting point for
exploring local AI and experimenting with an assistant of your own.
