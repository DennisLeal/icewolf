"""Grounded description of the current desktop assistant."""

import re


CAPABILITIES = (
    "I am Icewolf, a local-first AI voice assistant running on your computer. "
    "I am software, not a person, and I use a local language model to help answer questions.",
    "You can speak to me using push to talk or wake listening, or type in the conversation. "
    "My voice recognition, speech synthesis, and local model can work offline when their models are installed. "
    "Voice conversations currently require a running local model.",
    "I can use attached advisor agents and search documents you add to them. "
    "I can also show project links.",
    "With internet access, I can look up public GitHub repository information and search YouTube, "
    "then open a matching video in your browser. For example, ask me to search YouTube for piano music. "
    "The browser may require you to start playback.",
    "If you connect Gmail, I can attempt to find and read messages, write and send email, "
    "reply to a selected message, add or remove labels, mark messages read or unread, archive, or change stars. "
    "Sending and organizing do not require a separate confirmation; moving a message to Trash does. "
    "I can make mistakes, and some requests need clarification. Gmail requires internet access.",
    "I cannot currently record your screen, camera, or computer audio. "
    "I do not monitor your inbox in the background, and I cannot handle arbitrary tasks or email attachments. "
    "My responses and actions can be wrong, so check important results.",
)


def is_capabilities_request(text: str) -> bool:
    normalized = re.sub(r"[^\w\s']", " ", text.lower().replace("’", "'"))
    normalized = " ".join(normalized.split())
    normalized = re.sub(r"^(?:(?:hey\s+)?ice\s*wolf\s+)?", "", normalized)
    normalized = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", normalized)
    normalized = re.sub(r"\s+(?:please|for me)$", "", normalized)
    return bool(re.fullmatch(
        r"(?:who are you|who is ice\s*wolf|what are you|introduce yourself"
        r"|tell me (?:(?:more|thoroughly) )?(?:about yourself|who you are|what you can do)"
        r"|(?:explain|describe|list) (?:(?:thoroughly|in detail) )?(?:yourself|your (?:capabilities|abilities|features))"
        r"|what (?:can|could) you do|what are your (?:capabilities|abilities|features)"
        r"|what (?:are you capable of|do you do))",
        normalized,
    ))
