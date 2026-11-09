# Icewolf 0.2.0: installation and demonstration script

This is a recording guide for Dennis. **Show** describes screen actions;
**Say** is narration; **Ask Icewolf** is a request to speak or type in the app.
Wait for each response; the model's answers and processing time will vary.
Use only a build that includes the project-links command and Gmail scope update.

## 1. Prepare the recording

**Before recording:**

1. Close private windows and disable sensitive notifications. Icewolf's
   conversation can display names, email subjects, previews and local paths.
2. Connect a microphone and speakers. Choose your Windows default devices.
3. Keep a non-sensitive sample document ready for the agent walkthrough.
4. Have internet available for initial setup, Gmail and GitHub. Core speech and
   model processing can run offline once the required files are installed.
5. Do not display your Google client JSON, authorization screen, email content
   or personal study materials during the recording.

**Say:** "Hi, I'm Dennis. Today I'll show you how I install Icewolf and how I
use it as a local-first AI voice assistant on my Windows PC. We'll also look at
the features that are still in development."

## 2. Install and launch Icewolf

**Show:**

1. Locate `Icewolf-Setup.exe`. On the development PC the installer is in the
   project's `dist` folder. This locally built installer is not automatically
   available as a GitHub Release.
2. Close any running Icewolf session and run the installer. The package is
   unsigned, so Windows may show a publisher warning; verify the source
   before deciding whether to continue.
3. Follow the installer wizard. Choose the optional desktop shortcut and,
   on the original development PC, optionally copy existing project settings
   and agent data. Migration never overwrites existing destination files.
4. Open Icewolf from the Start menu or desktop shortcut.
5. Start Ollama and make sure a local language model is installed. Icewolf
   does not install Ollama or its language models. Open **Configuration**,
   choose the Ollama model and select a local Faster-Whisper model folder if
   the cached `base.en` folder is not already selected.
6. If needed, use the setup instructions in the README to install Ollama and
   download a local model and Whisper model once. The installer includes the
   Kokoro voice files but not an Ollama or Whisper model.

**Say:** "Icewolf installs for my Windows user. I also need Ollama and a local
language model, plus a local Whisper model for speech recognition. The
installer includes the Kokoro voice. After setup, the core voice pipeline can
operate offline; Gmail and GitHub are optional online exceptions."

**Say:** "The installer keeps user data separately from the program, and the
optional migration doesn't delete the original files. The app does not start
the microphone automatically."

## 3. Introduce the dashboard and architecture

**Show:** Point to Conversation, Voice view, Configuration, the animated
center, status and the system resource indicators.

**Say:** "The dashboard shows conversation, assistant status and local system
information. The animated core reflects listening and speaking levels. I can
also reduce its motion in Configuration."

**Say:** "Icewolf is built in Python with PyQt. Silero detects speech,
Faster-Whisper transcribes it, Ollama runs the local language model, and
Kokoro turns the reply into speech. These steps take time, so local doesn't
mean zero latency."

## 4. Wake Icewolf and continue a conversation

**Show:**

1. Select English under **Typed conversation language**, then close
   Configuration.
2. Select **Start listening** and wait for **Wake listening — say Hey
   Icewolf**.
3. **Ask Icewolf:** "Hey Icewolf."
4. Wait for the greeting and **Conversation listening — speak now**.
5. **Ask Icewolf:** "Suggest an easy snack."
6. After the answer and listening status return, **ask:** "What could I drink
   with that?"

**Say:** "I wake Icewolf once per session, then ask follow-up questions without
repeating the wake phrase. The microphone closes while it processes or speaks,
so I can't interrupt it mid-reply."

**Show:** Stop listening. Open **Configuration** and point to **Wait after you
stop speaking**.

**Say:** "A longer pause gives me more time to think without being interrupted;
a shorter pause makes responses start sooner but can cut off a longer pause."

## 5. Show the project links

**Show:** Return to Conversation and start a voice session as above, or type
the command with English selected.

**Say:** "Icewolf will display the repository links in its Conversation
window. The Jarvis project inspired the visual direction; Icewolf is its own
local-first implementation."

**Ask Icewolf:** "Show project links."

**Show:** The Conversation displays both:

- Icewolf: https://github.com/DennisLeal/icewolf
- Original Jarvis inspiration: https://github.com/ethanplusai/jarvis

**Say:** "Displaying these links does not contact GitHub. I can visit them
later or use the separate GitHub repository feature."

If voice recognition misses the command, type **show project links** instead.
This command requires English; it displays links, not a repository analysis.

## 6. Voice view, avatar and tray

**Show:** Open **Voice view**, then return to **Conversation**. Choose
**Avatar-only mode**, drag the avatar, and choose **Open HUD**.

**Say:** "The focused Voice view and compact avatar control the same session.
The avatar sits behind ordinary windows. I can restore the HUD from the
avatar or, if available, the Windows system tray. Show desktop may minimize
the avatar too."

## 7. Create a specialist advisor

**Show:**

1. Select **Create agent**. Show the prefilled NICE IEX Administrator name and
   responsibilities; explain they can be changed.
2. Select **Select study materials**, choose a safe sample PDF with selectable
   text, Word document, UTF-8 text file, or Markdown file, and select **Save**.
3. In **Agent roles**, select and attach the agent if it is not already attached.
4. Ask a question matching the sample, such as **"Ask NICE IEX Administrator
   agent to explain forecast settings."** Show the source citations when present.
5. Point to **Add study materials** and **Manage study materials** for updates.

**Say:** "This creates a local document-backed advisor, not a trained model.
Icewolf looks up matching passages and sends those excerpts to the local model.
It can make mistakes, so I check the sources. The agent cannot log into NICE
IEX or make changes. Extracted material is stored locally without encryption."

**Say:** "The built-in Research, Coding and Marketing roles provide advice,
not independent browsing, code execution or autonomous actions."

## 8. Explore a public GitHub repository

**Show:** Select **GitHub repo**, paste one of the public URLs above and add
an optional question. Select **Check repository** and wait for the result.
Skip this step if GitHub is unavailable.

**Say:** "This separate feature contacts GitHub online and reads public
repository metadata and a README excerpt. It does not inspect the source
code, and its answer should be checked against the original."

## 9. Gmail: what it does and does not do

**Show:** With private email hidden, point to **Connect or reconnect Gmail**
in Configuration. Do not record the Google login or credential file.

**Say:** "Gmail is optional and uses the internet. This build requests Gmail
modify permission, but the only implemented email feature is an inbox report:
it can display recent senders, subjects and previews, and speak shortened
sender names and subjects. It cannot yet send, draft, delete, label, or change
messages, even though the permission is broader."

**Say:** "To connect, I select the Google OAuth desktop-client JSON, review
the Google consent screen and authorize the requested scope. If an older
connection needs updated permission, I use Connect or reconnect Gmail again."

**Optional, only with safe data:** Ask **"Check my Gmail"** and show the
report. Otherwise skip the live inbox to protect privacy.

## 10. Experimental typed languages

**Show:** Stop listening. In **Configuration**, select Tagalog, Cebuano or
Hiligaynon under **Typed conversation language**; type a short greeting in
Conversation and wait for the reply. Restore English afterwards.

**Say:** "These languages are experimental for typed conversation only.
Quality depends on the local model and Hiligaynon may be unreliable. Voice,
agent commands and conversation integrations currently require English."

## 11. Closing and next steps

**Show:** Return to Conversation, select English, and stop listening.

**Say:** "That's Icewolf 0.2.0: a local-first voice assistant, dashboard,
avatar and document-based advisor, with optional online integrations.
Autonomous document creation and sending email are not implemented yet.
Thanks for watching."
