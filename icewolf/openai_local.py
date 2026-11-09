"""OpenAI-compatible chat backend restricted to IPv4 loopback."""

from .ollama import OllamaClient, SYSTEM_PROMPT


class LocalOpenAIClient(OllamaClient):
    def __init__(self, model: str, port: int = 1234, timeout: float = 180):
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ValueError("Provide a valid local model identifier.")
        if not 1 <= port <= 65535:
            raise ValueError("Local LLM port must be between 1 and 65535.")
        self.model = model
        self.timeout = timeout
        self.port = port
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def check_model(self) -> None:
        response = self._request("GET", "/v1/models")
        models = response.get("data")
        if not isinstance(models, list):
            raise RuntimeError("Local LLM returned an invalid model list.")
        if not any(isinstance(item, dict) and item.get("id") == self.model for item in models):
            raise RuntimeError(
                f"Model {self.model!r} is not available on the local endpoint. "
                "Load it in the server and use its exact model ID."
            )

    def reply(self, text: str) -> str:
        messages = self.messages + [{"role": "user", "content": text}]
        response = self._post("/v1/chat/completions", {
            "model": self.model, "messages": messages, "stream": False,
        })
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("Local LLM returned invalid chat choices.")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Local LLM returned an empty or invalid assistant response.")
        content = content.strip()
        self.messages = [messages[0]] + (
            messages[1:] + [{"role": "assistant", "content": content}]
        )[-20:]
        return content
