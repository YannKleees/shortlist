"""One way to talk to a language model: Claude when an API key is set, otherwise Ollama on this machine.

Claude is what a hosted Shortlist uses, since a small server cannot run a local model. Ollama keeps everything
on your laptop and costs nothing.
"""

import json

import requests

from . import letters

CLAUDE_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, provider="ollama", model="", url=letters.DEFAULT_URL, api_key="", post=requests.post, get=requests.get, claude=None):
        self.provider = provider
        self.model = model or (CLAUDE_MODEL if provider == "claude" else letters.DEFAULT_MODEL)
        self.url, self.api_key, self.post, self.get = url, api_key, post, get
        self._claude = claude  # an Anthropic client, or a stand in for tests

    @property
    def label(self):
        return f"Claude ({self.model})" if self.provider == "claude" else self.model

    def status(self):
        if self.provider == "claude":
            return {"online": bool(self.api_key or self._claude), "models": [self.model], "provider": "claude"}
        return {**letters.status(self.url, get=self.get), "provider": "ollama"}

    def client(self):
        if self._claude is None:
            import anthropic
            self._claude = anthropic.Anthropic(api_key=self.api_key or None)
        return self._claude

    def _claude_call(self, system, user, effort, fmt=None):
        import anthropic
        output_config = {"effort": effort}
        if fmt:
            output_config["format"] = {"type": "json_schema", "schema": fmt}
        try:
            r = self.client().beta.messages.create(
                model=self.model, max_tokens=16000, system=system, messages=[{"role": "user", "content": user}],
                output_config=output_config, betas=[FALLBACK_BETA], fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise LLMError("Claude refused the API key. Check it in Settings.") from None
        except anthropic.RateLimitError:
            raise LLMError("Claude is busy right now. Try again in a minute.") from None
        except anthropic.APIConnectionError:
            raise LLMError("Could not reach Claude. Are you online?") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude returned an error ({e.status_code}).") from None
        if r.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        if not text:
            raise LLMError("Claude returned an empty answer.")
        return text

    def chat(self, system, user, effort="medium"):
        """Plain text, for letters and revisions."""
        if self.provider == "claude":
            return self._claude_call(system, user, effort)
        try:
            return letters.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                model=self.model, url=self.url, post=self.post)
        except Exception:
            raise LLMError(f"The local model did not answer. Start Ollama and run: ollama pull {self.model}") from None

    def json(self, system, user, schema, effort="low"):
        """An object that follows `schema`, for the CV review and job analysis."""
        if self.provider == "claude":
            text = self._claude_call(system, user, effort, fmt=schema)
        else:
            try:
                r = self.post(f"{self.url.rstrip('/')}/api/chat", json={
                    "model": self.model, "stream": False, "format": schema, "options": {"temperature": 0.2},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=300)
                r.raise_for_status()
                text = letters.clean_reply(r.json()["message"]["content"])
            except Exception:
                raise LLMError(f"The local model did not answer. Start Ollama and run: ollama pull {self.model}") from None
        try:
            data = json.loads(text)
        except ValueError:
            raise LLMError("The model answered in a form Shortlist could not read. Try again.") from None
        if not isinstance(data, dict):
            raise LLMError("The model answered in a form Shortlist could not read. Try again.")
        return data
