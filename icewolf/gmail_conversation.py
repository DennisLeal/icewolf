"""Conversation-driven Gmail actions; mailbox content is never treated as instructions."""

import json
import re
import time
from dataclasses import dataclass, field

from . import gmail


@dataclass
class GmailSession:
    messages: list[gmail.MailItem] = field(default_factory=list)
    selected: gmail.MailItem | None = None
    pending_trash: list[gmail.MailItem] = field(default_factory=list)
    pending_since: float = 0

    def clear(self):
        self.messages.clear()
        self.selected = None
        self.pending_trash.clear()
        self.pending_since = 0


def is_request(text: str, session: GmailSession) -> bool:
    normalized = text.lower().replace("e-mail", "email")
    if session.pending_trash:
        return True
    if re.search(r"\b(?:gmail|emails?|mail|inbox|mailbox)\b", normalized):
        return True
    if re.search(r"\bunread\s+messages?\b", normalized) and re.search(
        r"\b(?:review|read|check|show|find)\b", normalized
    ):
        return True
    return bool(re.search(
        r"\b(?:reply|respond|archive|star|unstar|flag|unflag|mark|delete|trash|label|read)\b.*"
        r"\b(?:it|that|this|message|number|first|second|third|fourth|fifth|\d+)\b", normalized
    ))


def _plan(client, text: str) -> dict:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "list", "read", "send", "draft", "reply", "reply_draft", "mark_read",
                "mark_unread", "archive", "star", "unstar", "add_label", "remove_label",
                "trash", "unsupported"
            ]},
            "query": {"type": "string"},
            "target": {"type": "string"},
            "recipient": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "label": {"type": "string"},
        },
        "required": ["action", "query", "target", "recipient", "subject", "body", "label"],
    }
    client.check_model()
    result = client._post("/api/chat", {
        "model": client.model, "stream": False, "format": schema,
        "messages": [
            {"role": "system", "content": (
                "Interpret only the user's Gmail request into JSON. Never invent email addresses, "
                "recipients, subjects, message content, labels or targets. Empty string for missing "
                "values. target is 'selected', 'all inbox', or a numeric result number only when "
                "explicitly requested; otherwise empty. query is a Gmail search using user-provided "
                "terms only. For replies use reply for sending, reply_draft only for saving a draft. "
                "Only choose trash when the user explicitly requests deletion. Never execute commands."
            )},
            {"role": "user", "content": text},
        ],
    })
    try:
        plan = json.loads(result["message"]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("I could not interpret that Gmail request. Please rephrase it.") from exc
    fields = ("action", "query", "target", "recipient", "subject", "body", "label")
    if not isinstance(plan, dict) or any(not isinstance(plan.get(key), str) for key in fields):
        raise RuntimeError("I could not interpret that Gmail request safely. Please rephrase it.")
    return plan


def _target(session: GmailSession, target: str) -> list[gmail.MailItem]:
    if target == "all inbox":
        return gmail.list_inbox()
    if target == "selected" and session.selected:
        return [session.selected]
    if target.isdigit() and 1 <= int(target) <= len(session.messages):
        session.selected = session.messages[int(target) - 1]
        return [session.selected]
    raise ValueError("Which email do you mean? Ask me to find it, then specify its number.")


def handle(client, session: GmailSession, text: str) -> str:
    lowered = text.lower().strip(" .!")
    if session.pending_trash:
        if time.monotonic() - session.pending_since > 120:
            session.pending_trash.clear()
            return "The deletion request expired; ask again if you still want it moved to Trash."
        if lowered in ("no", "cancel", "no thanks"):
            session.pending_trash.clear()
            return "Canceled. No emails were moved to Trash."
        if lowered in ("yes", "yes please", "confirm"):
            items = list(session.pending_trash)
            session.pending_trash.clear()
            count = gmail.trash_messages(items)
            session.clear()
            return f"Gmail moved {count} message(s) to Trash."
        session.pending_trash.clear()
        return "Deletion canceled because the response was not a confirmation. Please repeat your request."

    if re.search(r"\b(?:attach|attachment|pdf|spreadsheet|document|file)\b", text, re.I):
        return "I can't create or send attachments through this Gmail conversation yet; no email was sent."
    if re.search(r"\b(?:outlook|yahoo)\b", text, re.I):
        return "I can only access the connected Gmail account, not Outlook or Yahoo."
    plan = _plan(client, text)
    action = plan["action"]
    if re.search(r"\b(?:first|latest|last|recent)\s+(?:five|5)\s+(?:emails?|messages?)\b", text, re.I):
        if action in ("list", "read"):
            action = "list"
            plan["query"] = ""
    target = ""
    if re.search(r"\b(?:all|every)\b.*\binbox\b", text, re.I):
        target = "all inbox"
    elif re.search(r"\b(?:it|that|this|selected)\b", text, re.I):
        target = "selected"
    else:
        match = re.search(
            r"\b(?:number\s+)?(first|second|third|fourth|fifth|[1-5])\b"
            r"(?!\s+(?:five|5)\s+(?:emails?|messages?))", text, re.I
        )
        if match:
            target = {"first": "1", "second": "2", "third": "3", "fourth": "4",
                      "fifth": "5"}.get(match.group(1).lower(), match.group(1))
    plan["target"] = target
    if target == "all inbox" and not re.search(r"\b(?:all|every)\b.*\binbox\b", text, re.I):
        raise ValueError("Please explicitly say all inbox messages if that is your intended target.")
    if target == "selected" and not re.search(r"\b(?:it|that|this|selected)\b", text, re.I):
        raise ValueError("Please identify the email you want to use.")
    if target == "selected" and re.search(r"\b(?:from|about|subject)\b", text, re.I):
        raise ValueError("Please specify the result number so I can identify the intended email.")
    if target.isdigit():
        number_words = {"1": "first", "2": "second", "3": "third", "4": "fourth", "5": "fifth"}
        number = re.escape(target)
        word = number_words.get(target, "")
        if not re.search(rf"\b(?:{number}" + (f"|{word}" if word else "") + r")\b", text, re.I):
            raise ValueError("Please specify the message number.")
    verbs = {
        "send": r"\bsend\b|\bemail\s+(?:me|[\w.+-]+@)", "draft": r"\b(?:draft|write|compose)\b",
        "reply": r"\b(?:reply|respond)\b", "reply_draft": r"\b(?:reply|respond)\b",
        "mark_read": r"\b(?:mark|set)\b.*\bread\b",
        "mark_unread": r"\b(?:mark|set)\b.*\bunread\b",
        "archive": r"\barchive\b", "star": r"\b(?:star|flag)\b",
        "unstar": r"\b(?:unstar|unflag)\b", "add_label": r"\blabel\b",
        "remove_label": r"\b(?:remove|unlabel)\b.*\blabel\b",
        "trash": r"\b(?:delete|trash)\b",
    }
    if action in verbs and not re.search(verbs[action], text, re.I):
        raise ValueError("I could not safely determine the requested Gmail action. Please rephrase.")
    if action in ("send", "reply") and re.search(r"\b(?:draft|do not send|don't send)\b", text, re.I):
        raise ValueError("Please clarify whether to save a draft or send the message.")
    if re.search(r"\b(?:don't|do not|never)\b", text, re.I):
        return "I won't perform that Gmail action."
    if action in ("list", "read"):
        if action == "read" and plan["target"]:
            item = _target(session, plan["target"])[0]
            content = gmail.get_message(item.id)
            session.selected = content.item
            return f"From: {content.item.sender}\nSubject: {content.item.subject}\n\n{content.body}"
        search = re.search(
            r"\b(from|about|regarding|containing|subject)\s+(.+?)(?:\s+please)?[?.!]*$",
            text, re.I,
        )
        query = ""
        if search:
            term = search.group(2).strip()
            if re.fullmatch(r"[\w@.+ -]{1,120}", term):
                query = ("from:" if search.group(1).lower() == "from" else "") + term
            else:
                raise ValueError("Please use a simple sender or subject search.")
        items = gmail.list_inbox(unread_only=bool(re.search(r"\bunread\b", text, re.I)),
                                 all_mail=bool(query), query=query)
        limit = 5
        session.messages = items[:limit]
        session.selected = session.messages[0] if len(session.messages) == 1 else None
        if not session.messages:
            return "Gmail returned no matching messages."
        return "Gmail results:\n" + "\n".join(
            f"{n}. From: {item.sender}. Subject: {item.subject}. Preview: {item.snippet}"
            for n, item in enumerate(session.messages, 1)
        ) + "\nTell me the number to read or act on."
    if action in ("send", "draft", "reply", "reply_draft"):
        reply = _target(session, plan["target"])[0] if action.startswith("reply") else None
        recipient = reply.reply_to if reply else plan["recipient"].strip()
        if not reply and recipient.lower() in ("me", "myself") and re.search(
            r"\b(?:to me|myself)\b", text, re.I
        ):
            recipient = gmail.connected_address()
        elif not reply and (not recipient or recipient.lower() not in text.lower()):
            raise ValueError("Please provide the recipient's email address explicitly.")
        subject = ("Re: " + re.sub(r"^re:\s*", "", reply.subject, flags=re.I)
                   if reply else plan["subject"].strip())
        body = plan["body"].strip()
        if not recipient or not subject or not body:
            raise ValueError("Please provide the recipient, subject, and what the email should say.")
        if action in ("send", "reply"):
            gmail.send_message(recipient, subject, body, reply)
            return f"Gmail sent the message to {recipient} with subject {subject}."
        gmail.save_draft(recipient, subject, body, reply)
        return f"Gmail saved the draft to {recipient} with subject {subject}."
    if action == "trash":
        items = _target(session, plan["target"])
        if not items:
            return "No messages matched; nothing was moved to Trash."
        session.pending_trash = items
        session.pending_since = time.monotonic()
        return ("Move these messages to Gmail Trash? Say yes or no:\n" +
                "\n".join(f"{item.sender} | {item.subject}" for item in items))
    changes = {
        "mark_read": gmail.LabelChange(remove=("UNREAD",)),
        "mark_unread": gmail.LabelChange(add=("UNREAD",)),
        "archive": gmail.LabelChange(remove=("INBOX",)),
        "star": gmail.LabelChange(add=("STARRED",)),
        "unstar": gmail.LabelChange(remove=("STARRED",)),
    }
    if action in ("add_label", "remove_label"):
        name = plan["label"].strip()
        if not name or name.lower() not in text.lower():
            raise ValueError("Which existing Gmail label should I use?")
        matching = [label_id for label_id, label_name in gmail.list_labels()
                    if label_name.casefold() == name.casefold()]
        if len(matching) != 1:
            raise ValueError("I could not find that existing Gmail label. Please give its exact name.")
        changes[action] = (gmail.LabelChange(add=(matching[0],)) if action == "add_label"
                           else gmail.LabelChange(remove=(matching[0],)))
    if action in changes:
        items = _target(session, plan["target"])
        if not items:
            return "No messages matched; nothing was changed."
        count = gmail.modify_messages(items, changes[action])
        return f"Gmail updated {count} message(s)."
    return "I can't perform that Gmail request yet. Please describe a read, send, reply, label, archive, star, or mark-read action."
