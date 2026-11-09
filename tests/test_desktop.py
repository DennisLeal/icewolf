import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLineEdit
from PyQt6.QtCore import QEventLoop, QPoint, QTimer

from icewolf.audio import SpeechTooLong
from icewolf.agents import Agent, AgentStore, Passage
from icewolf.github_repo import RepositoryOverview
from icewolf.desktop import (
    CONVERSATION_MAX_SECONDS, AssistantWorker, CoreDisplay, IcewolfWindow, create_speaker,
)


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = IcewolfWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_microphone_is_off_on_startup(self):
        self.assertIsNone(self.window.worker)
        self.assertIn("microphone off", self.window.status.text())
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertEqual(self.window.wake_button.text(), "Enable Hey Icewolf")
        self.assertFalse(hasattr(self.window, "voice_input"))
        self.assertIn("No agents", self.window.agent_status.text())

    def test_clear_resets_conversation_and_log(self):
        self.window.client = MagicMock()
        self.window.append_message("You", "Hello")
        self.window.clear_conversation()
        self.window.client.clear_history.assert_called_once()
        self.assertEqual(self.window.log.toPlainText(), "")

    def test_missing_whisper_is_reported_without_starting_worker(self):
        self.window.whisper_input.clear()
        self.window.start_wake()
        self.assertIsNone(self.window.worker)
        self.assertIn("select a local Whisper", self.window.status.text())
        self.assertEqual(self.window.core.state, "ERROR")

    def test_core_indicator_tracks_actual_worker_status(self):
        for status, expected in (
            ("Ready — microphone off", "STANDBY"),
            ("Wake listening — say Hey Jarvis", "WAKE LISTENING"),
            ("Wake detected — speak now", "LISTENING"),
            ("Transcribing", "PROCESSING"),
            ("Thinking", "PROCESSING"),
            ("Speaking", "SPEAKING"),
            ("Error — microphone off", "ERROR"),
        ):
            with self.subTest(status=status):
                self.window.set_status(status)
                self.assertEqual(self.window.core.state, expected)
                self.assertEqual(self.window.status.text(), status)

    def test_busy_controls_preserve_microphone_opt_in(self):
        self.window.set_busy(True)
        self.assertFalse(self.window.wake_button.isEnabled())
        self.assertFalse(self.window.push_button.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())
        self.window.set_busy(False)
        self.assertTrue(self.window.wake_button.isEnabled())
        self.assertFalse(self.window.stop_button.isEnabled())

    def test_main_voice_button_starts_and_stops_wake_session(self):
        with patch.object(self.window, "start_worker") as start:
            self.window.push_button.click()
            start.assert_called_once_with("wake")
        worker = MagicMock()
        worker.mode = "wake"
        self.window.worker = worker
        self.window.set_busy(True)
        self.assertTrue(self.window.push_button.isEnabled())
        self.assertIn("STOP", self.window.push_button.text())
        self.assertTrue(self.window.push_button.property("listening"))
        self.window.push_button.click()
        worker.stop.assert_called_once()
        self.assertFalse(self.window.push_button.isEnabled())
        self.window.worker = None
        self.window.set_busy(False)
        self.assertFalse(self.window.push_button.property("listening"))

    def test_github_link_routes_to_public_overview_and_local_model(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "")
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        overview = RepositoryOverview("https://github.com/a/b", "Example", "Python", "Text", False)
        client.repository_reply.return_value = "A documented project."
        with patch("icewolf.desktop.github_repo.fetch_overview", return_value=overview) as fetch:
            worker.respond("What is it? https://github.com/a/b", speaker)
        fetch.assert_called_once_with("https://github.com/a/b")
        client.repository_reply.assert_called_once_with(overview, "What is it?")
        client.reply.assert_not_called()
        self.assertTrue(any(role == "Sources consulted" and "source code not inspected" in text
                            for role, text in messages))
        speaker.say.assert_called_once()

    def test_github_request_without_url_explains_how_to_provide_one(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "")
        with patch("icewolf.desktop.github_repo.fetch_overview") as fetch:
            worker.respond("Please check a GitHub repository", speaker)
        fetch.assert_not_called()
        client.reply.assert_not_called()
        self.assertIn("paste", speaker.say.call_args.args[0])

    def test_explicit_negative_github_request_does_not_access_network(self):
        worker = AssistantWorker(MagicMock(), "text", "")
        speaker = MagicMock()
        with patch("icewolf.desktop.github_repo.fetch_overview") as fetch:
            worker.respond("Don't check https://github.com/a/b", speaker)
        fetch.assert_not_called()
        self.assertIn("will not", speaker.say.call_args.args[0])

    def test_repo_button_stops_active_voice_before_opening_dialog(self):
        worker = MagicMock()
        worker.mode = "wake"
        self.window.worker = worker
        self.window.set_busy(True)
        self.assertTrue(self.window.repo_button.isEnabled())
        self.window.repo_button.click()
        worker.stop.assert_called_once()
        self.assertTrue(self.window.pending_repo)
        with patch.object(self.window, "open_repo_dialog") as dialog:
            self.window.worker_finished()
        dialog.assert_called_once()
        self.assertFalse(self.window.pending_repo)

    def test_voice_resumes_without_another_wake_phrase(self):
        client, speaker, voice, stream = (MagicMock() for _ in range(4))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        worker = AssistantWorker(client, "resume_wake", "whisper")
        def capture(*args, **kwargs):
            worker.stop()
            return None
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener") as wake:
            worker.run()
        wake.assert_not_called()
        speaker.say.assert_not_called()
        voice._record_until_silence.assert_called_once()

    def test_repo_dialog_submits_link_and_question(self):
        def submit():
            dialog = QApplication.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            fields[0].setText("https://github.com/owner/repo")
            fields[1].setText("What is it?")
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        with patch.object(self.window, "start_worker") as start:
            QTimer.singleShot(0, submit)
            self.window.open_repo_dialog()
        start.assert_called_once_with("text", "What is it? https://github.com/owner/repo")

    def test_repo_dialog_cancellation_resumes_voice(self):
        self.window.resume_after_repo = True
        def cancel():
            QApplication.activeModalWidget().reject()
        with patch.object(self.window, "start_worker") as start:
            QTimer.singleShot(0, cancel)
            self.window.open_repo_dialog()
        start.assert_called_once_with("resume_wake")
        self.assertFalse(self.window.resume_after_repo)

    def test_stopping_repo_request_cancels_voice_resume(self):
        self.window.worker = MagicMock()
        self.window.resume_after_repo = True
        self.window.stop_worker()
        self.assertFalse(self.window.resume_after_repo)
        self.window.worker = None

    def test_one_wake_opens_conversation_for_ten_requests(self):
        client = MagicMock()
        client.reply.side_effect = [f"Reply {i}." for i in range(10)]
        speaker, voice, stream, wake = (MagicMock() for _ in range(4))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        voice.transcribe.side_effect = [f"Request {i}" for i in range(10)]
        worker = AssistantWorker(client, "wake", "whisper")
        statuses = []
        worker.status_changed.connect(statuses.append)
        wake.wait.return_value = True
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 11:
                worker.stop()
                return None
            return "audio"
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake):
            worker.run()
        wake.wait.assert_called_once()
        self.assertEqual(client.reply.call_count, 10)
        self.assertEqual(speaker.say.call_count, 11)
        self.assertIn("Dennis", speaker.say.call_args_list[0].args[0])
        self.assertEqual(statuses.count("Wake listening — say Hey Icewolf"), 1)
        self.assertEqual(statuses.count("Conversation listening — speak now"), 11)
        self.assertEqual([call.args[0] for call in client.reply.call_args_list],
                         [f"Request {i}" for i in range(10)])
        self.assertTrue(all(call.kwargs.get("wait_for_speech") is True
                            for call in voice._record_until_silence.call_args_list))
        self.assertTrue(all(call.args[0] == CONVERSATION_MAX_SECONDS
                            and call.kwargs["end_silence_seconds"] == 3.0
                            and call.kwargs["fail_on_limit"] is True
                            for call in voice._record_until_silence.call_args_list))

    def test_overlong_request_is_not_transcribed_and_session_continues(self):
        client, speaker, voice, stream, wake = (MagicMock() for _ in range(5))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        wake.wait.return_value = True
        worker = AssistantWorker(client, "wake", "whisper", end_silence_seconds=4.5)
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 1:
                raise SpeechTooLong()
            worker.stop()
            return None
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake):
            worker.run()
        self.assertEqual(voice._record_until_silence.call_count, 2)
        self.assertEqual(voice._record_until_silence.call_args.kwargs["end_silence_seconds"], 4.5)
        voice.transcribe.assert_not_called()
        client.reply.assert_not_called()
        self.assertTrue(any(role == "System" and "not sent" in text for role, text in messages))
        wake.wait.assert_called_once()

    def test_pause_setting_is_saved_and_passed_to_worker(self):
        self.window.settings = MagicMock()
        self.window.speech_pause.setValue(4.5)
        self.window.settings.setValue.assert_called_with("conversation_silence_seconds", 4.5)
        self.window.whisper_input.setText("whisper")
        with patch("icewolf.desktop.OllamaClient"), \
             patch("icewolf.desktop.AssistantWorker") as worker:
            self.window.start_wake()
        self.assertEqual(worker.call_args.args[5], 4.5)
        self.assertFalse(self.window.speech_pause.isEnabled())
        self.window.worker = None
        self.window.set_busy(False)

    def test_pause_setting_survives_reopening_window(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch("icewolf.desktop.ROOT", Path(folder)):
            first = IcewolfWindow()
            first.speech_pause.setValue(5.5)
            first.settings.sync()
            first.close()
            second = IcewolfWindow()
            try:
                self.assertEqual(second.speech_pause.value(), 5.5)
            finally:
                second.close()

    def test_stop_during_wake_or_greeting_does_not_open_conversation(self):
        for stage in ("wake", "greeting"):
            with self.subTest(stage=stage):
                client, speaker, voice, stream, wake = (MagicMock() for _ in range(5))
                stream.__enter__.return_value = stream
                voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream),
                                           PortAudioError=OSError)
                worker = AssistantWorker(client, "wake", "whisper")
                def wait(source, stop_event):
                    if stage == "wake":
                        stop_event.set()
                        return False
                    return True
                def say(*args, **kwargs):
                    worker.stop()
                wake.wait.side_effect = wait
                speaker.say.side_effect = say
                with patch("icewolf.desktop.create_speaker", return_value=speaker), \
                     patch("icewolf.desktop.VoicePipeline", return_value=voice), \
                     patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake):
                    worker.run()
                voice._record_until_silence.assert_not_called()
                client.reply.assert_not_called()

    def test_empty_transcript_keeps_conversation_listening(self):
        client, speaker, voice, stream, wake = (MagicMock() for _ in range(5))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        wake.wait.return_value = True
        worker = AssistantWorker(client, "wake", "whisper")
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 2:
                worker.stop()
                return None
            return "audio"
        voice._record_until_silence.side_effect = capture
        voice.transcribe.return_value = ""
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake):
            worker.run()
        wake.wait.assert_called_once()
        self.assertEqual(voice._record_until_silence.call_count, 2)
        self.assertIn(("System", "No speech recognized."), messages)
        client.reply.assert_not_called()

    def test_text_worker_uses_client_and_speaks(self):
        client = MagicMock()
        client.reply.return_value = "Hello there."
        speaker = MagicMock()
        worker = AssistantWorker(client, "text", "", "Hello")
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        with patch("icewolf.desktop.create_speaker", return_value=speaker):
            worker.run()
        client.check_model.assert_called_once()
        client.reply.assert_called_once_with("Hello")
        speaker.say.assert_called_once_with("Hello there.", stop_event=worker.stop_event)
        self.assertEqual(messages, [("Icewolf", "Hello there.")])

    def test_worker_reports_initialization_failure(self):
        client = MagicMock()
        client.check_model.side_effect = RuntimeError("offline model unavailable")
        worker = AssistantWorker(client, "text", "", "Hello")
        errors = []
        worker.failed.connect(errors.append)
        worker.run()
        self.assertIn("offline model unavailable", errors[0])

    def test_stop_prevents_speech_after_reply(self):
        client = MagicMock()
        worker = AssistantWorker(client, "text", "", "Hello")
        speaker = MagicMock()
        def reply(text):
            worker.stop()
            return "Hello there."
        client.reply.side_effect = reply
        worker.respond("Hello", speaker)
        speaker.say.assert_not_called()

    def test_wake_session_transcribes_and_speaks_then_stops(self):
        client = MagicMock()
        client.reply.return_value = "Ready."
        speaker = MagicMock()
        voice = MagicMock()
        stream = MagicMock()
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        voice._record_until_silence.return_value = "audio"
        voice.transcribe.return_value = "Hello"
        worker = AssistantWorker(client, "wake", "whisper")
        wake = MagicMock()
        wake.wait.return_value = True
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 2:
                worker.stop()
                return None
            return "audio"
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake):
            worker.run()
        voice.transcribe.assert_called_once_with("audio")
        client.reply.assert_called_once_with("Hello")
        self.assertEqual(speaker.say.call_count, 2)
        self.assertEqual(speaker.say.call_args.args[0], "Ready.")
        wake.wait.assert_called_once()

    def test_agent_attachment_and_role_execution(self):
        self.window.toggle_agent()
        self.assertIn("Research", self.window.agents)
        self.assertEqual(self.window.attach_button.text(), "Detach agent")
        self.assertIn("idle", self.window.agent_status.text())
        self.window.update_agents("Research", True)
        self.assertIn("active", self.window.agent_status.text())
        client = MagicMock()
        client.agent_reply.return_value = "Research advice."
        speaker = MagicMock()
        worker = AssistantWorker(client, "text", "", agents={"Research"})
        worker.respond("Ask research agent to explain caching", speaker)
        client.agent_reply.assert_called_once_with("Research", "explain caching")
        speaker.say.assert_called_once_with("Research advice.", stop_event=worker.stop_event)
        self.window.toggle_agent()
        self.assertIn("No agents", self.window.agent_status.text())
        self.assertEqual(self.window.attach_button.text(), "Attach agent")

    def test_custom_agent_routes_to_document_context_and_shows_sources(self):
        client, speaker, store = MagicMock(), MagicMock(), MagicMock()
        store.search.return_value = [Passage("manual.pdf, page 2", "forecast details")]
        client.document_agent_reply.return_value = "Use the forecast settings [1]."
        agent = Agent("NICE IEX Administrator", "Give documented advice")
        worker = AssistantWorker(client, "text", "", agents={agent.name},
                                 custom_agents=[agent], agent_store=store)
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        worker.respond("Ask NICE IEX Administrator agent to explain forecast settings", speaker)
        store.search.assert_called_once_with(agent.name, "explain forecast settings")
        client.document_agent_reply.assert_called_once_with(
            agent.name, agent.instructions, "explain forecast settings", store.search.return_value)
        self.assertIn(("Sources consulted", "[1] manual.pdf, page 2"), messages)
        speaker.say.assert_called_once()

    def test_custom_agent_does_not_invent_an_answer_without_matching_documents(self):
        client, speaker, store = MagicMock(), MagicMock(), MagicMock()
        store.search.return_value = []
        agent = Agent("NICE IEX Administrator", "Help")
        worker = AssistantWorker(client, "text", "", agents={agent.name},
                                 custom_agents=[agent], agent_store=store)
        worker.respond("ask NICE IEX Administrator about forecasting", speaker)
        client.document_agent_reply.assert_not_called()
        self.assertIn("could not find", speaker.say.call_args.args[0])

    def test_custom_agents_are_loaded_into_selector(self):
        with tempfile.TemporaryDirectory() as folder, patch("icewolf.desktop.ROOT", Path(folder)):
            store = AgentStore(Path(folder) / "data" / "agents.sqlite3")
            store.create_agent("NICE IEX Administrator", "Help", [])
            window = IcewolfWindow()
            try:
                self.assertGreaterEqual(window.agent_select.findText("NICE IEX Administrator"), 0)
                self.assertEqual(window.custom_agents[0].name, "NICE IEX Administrator")
            finally:
                window.close()

    def test_create_agent_wizard_saves_and_attaches(self):
        with tempfile.TemporaryDirectory() as folder, patch("icewolf.desktop.ROOT", Path(folder)):
            window = IcewolfWindow()
            try:
                def save_dialog():
                    dialog = QApplication.activeModalWidget()
                    buttons = dialog.findChild(QDialogButtonBox)
                    buttons.button(QDialogButtonBox.StandardButton.Save).click()
                QTimer.singleShot(0, save_dialog)
                window.open_agent_wizard()
                self.assertIn("NICE IEX Administrator", window.agents)
                self.assertEqual(window.agent_select.currentText(), "NICE IEX Administrator")
                self.assertEqual(window.agent_store.list_agents()[0].name, "NICE IEX Administrator")
            finally:
                window.close()

    def test_create_agent_wizard_imports_selected_document(self):
        with tempfile.TemporaryDirectory() as folder, patch("icewolf.desktop.ROOT", Path(folder)):
            path = Path(folder) / "guide.txt"
            path.write_text("Forecast scheduling details", encoding="utf-8")
            window = IcewolfWindow()
            try:
                def fill_dialog():
                    dialog = QApplication.activeModalWidget()
                    choose = next(button for button in dialog.findChildren(
                        type(window.create_agent_button)) if button.text() == "Select study materials")
                    choose.click()
                    dialog.findChild(QDialogButtonBox).button(
                        QDialogButtonBox.StandardButton.Save).click()
                with patch("icewolf.desktop.QFileDialog.getOpenFileNames",
                           return_value=([str(path)], "")):
                    QTimer.singleShot(0, fill_dialog)
                    window.open_agent_wizard()
                self.assertEqual(window.agent_store.list_documents("NICE IEX Administrator"),
                                 ["guide.txt"])
                self.assertIn("Forecast scheduling", window.agent_store.search(
                    "NICE IEX Administrator", "forecast")[0].text)
            finally:
                window.close()

    def test_core_animates_and_tracks_audio_level(self):
        core = CoreDisplay()
        core.resize(400, 240)
        core.show()
        self.app.processEvents()
        first = core.grab().toImage()
        core.animate()
        self.app.processEvents()
        self.assertNotEqual(first, core.grab().toImage())
        self.assertEqual(core.AVATAR_OPACITY, 0.2)
        core.set_state("SPEAKING")
        core.set_level(0.7)
        self.assertGreater(core.level, 0)
        core.set_state("STANDBY")
        self.assertEqual(core.level, 0)
        core.close()

    def test_reduced_motion_stops_and_resumes_animation(self):
        core = CoreDisplay()
        core.animate()
        core.set_reduced_motion(True)
        self.assertFalse(core.timer.isActive())
        self.assertEqual(core.phase, 0)
        core.set_level(0.7)
        self.assertEqual(core.level, 0.7)
        core.set_reduced_motion(False)
        self.assertTrue(core.timer.isActive())
        core.close()

    def test_particle_core_responds_to_audio_with_reduced_motion(self):
        core = CoreDisplay()
        core.resize(400, 240)
        core.set_reduced_motion(True)
        core.set_state("SPEAKING")
        core.show()
        self.app.processEvents()
        silent_frame = core.grab().toImage()
        core.set_level(0.8)
        self.app.processEvents()
        self.assertNotEqual(silent_frame, core.grab().toImage())
        self.assertFalse(core.timer.isActive())
        core.close()

    def test_motion_setting_updates_avatar_and_saves_preference(self):
        with patch.object(self.window.settings, "setValue") as save:
            reduced = not self.window.reduce_motion.isChecked()
            self.window.reduce_motion.setChecked(reduced)
            self.assertEqual(self.window.core.timer.isActive(), not reduced)
            self.assertEqual(self.window.voice_core.timer.isActive(), not reduced)
            save.assert_called_once_with("reduce_motion", reduced)

    def test_voice_view_shares_status_audio_and_listening_controls(self):
        self.window.show()
        self.window.nav_voice.click()
        self.assertEqual(self.window.views.currentIndex(), 1)
        self.assertEqual(self.window.nav_voice.objectName(), "navActive")
        self.window.set_status("Conversation listening — speak now")
        self.window.set_audio_level(0.7)
        self.assertEqual(self.window.voice_core.state, "LISTENING")
        self.assertEqual(self.window.voice_core.level, 0.7)
        self.assertEqual(self.window.core.level, 0.7)
        self.assertEqual(self.window.voice_status.text(), self.window.status.text())
        worker = MagicMock()
        worker.mode = "wake"
        self.window.worker = worker
        self.window.set_busy(True)
        self.assertTrue(self.window.voice_button.isEnabled())
        self.window.voice_button.click()
        worker.stop.assert_called_once()
        self.assertFalse(self.window.push_button.isEnabled())
        self.assertFalse(self.window.voice_button.isEnabled())
        self.window.worker = None
        self.window.set_busy(False)
        self.window.nav_conversation.click()
        self.assertEqual(self.window.views.currentIndex(), 0)
        self.assertEqual(self.window.nav_conversation.objectName(), "navActive")

    def test_voice_view_displays_error_details(self):
        self.window.show_voice()
        self.window.show_error("Microphone unavailable")
        self.assertIn("Microphone unavailable", self.window.voice_status.text())
        self.assertEqual(self.window.voice_core.state, "ERROR")

    def test_status_style_and_conversation_navigation(self):
        self.window.show()
        self.window.set_status("Conversation listening — speak now")
        self.assertEqual(self.window.status.property("state"), "LISTENING")
        self.window.set_status("Error — microphone off")
        self.assertEqual(self.window.status.property("state"), "ERROR")
        self.window.nav_conversation.click()
        self.app.processEvents()
        self.assertTrue(self.window.text_input.hasFocus())

    def test_core_is_centered_in_main_dashboard_at_supported_sizes(self):
        self.window.show()
        for width, height in ((1280, 800), (1000, 680)):
            with self.subTest(width=width, height=height):
                self.window.resize(width, height)
                self.app.processEvents()
                core = self.window.core
                core_center = core.mapTo(self.window, core.rect().center())
                conversation = self.window.log.parentWidget()
                main_left = conversation.mapTo(self.window, QPoint(0, 0)).x()
                main_right = conversation.mapTo(self.window, conversation.rect().topRight()).x()
                self.assertLess(abs(core_center.x() - (main_left + main_right) / 2), 25)
                self.assertGreaterEqual(core.height(), 140)
                self.assertGreaterEqual(core.width(), 240)
                self.assertLessEqual(core.geometry().bottom(), core.parentWidget().rect().bottom())

    def test_desktop_uses_adam(self):
        with patch("icewolf.desktop.KokoroSpeaker") as speaker:
            create_speaker()
        self.assertEqual(speaker.call_args.args[2], "am_adam")

    def test_agent_commands_and_unattached_role(self):
        for command in ("ask research agent to explain caching",
                        "assign research to explain caching",
                        "use research: explain caching"):
            with self.subTest(command=command):
                client, speaker = MagicMock(), MagicMock()
                client.agent_reply.return_value = "Advice."
                worker = AssistantWorker(client, "text", "", agents={"Research"})
                worker.respond(command, speaker)
                client.agent_reply.assert_called_once_with("Research", "explain caching")
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "")
        worker.respond("ask research agent to explain caching", speaker)
        client.agent_reply.assert_not_called()
        self.assertIn("not attached", speaker.say.call_args.args[0])

    def test_voice_connect_opens_dialog_after_worker_finishes(self):
        client = MagicMock()
        speaker = MagicMock()
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        with patch("icewolf.desktop.OllamaClient", return_value=client), \
             patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch.object(self.window, "connect_gmail") as connect:
            self.window.start_worker("text", "connect gmail")
            self.window.worker.finished.connect(loop.quit)
            timeout.start(5000)
            loop.exec()
            self.app.processEvents()
            self.assertTrue(timeout.isActive(), "Worker did not finish")
            connect.assert_called_once_with()
            self.assertIsNone(self.window.worker)

    def test_greeting_and_gmail_connect_commands(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "")
        worker.respond("Hey Icewolf", speaker)
        speaker.say.assert_called_once_with("Hello, Dennis. How can I help?", stop_event=worker.stop_event)
        client.reply.assert_not_called()
        requested = []
        worker.connect_requested.connect(lambda: requested.append(True))
        worker.respond("connect gmail", speaker)
        self.assertEqual(requested, [True])
        self.assertTrue(worker.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
