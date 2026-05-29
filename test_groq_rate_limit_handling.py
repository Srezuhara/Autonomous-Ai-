import unittest

import llm_client


class FakeResponse:
    def __init__(self, headers=None, body=None, text=""):
        self.headers = headers or {}
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class GroqRateLimitHandlingTests(unittest.TestCase):
    def test_tpm_429_is_temporary_wait(self):
        resp = FakeResponse(
            headers={
                "retry-after": "7.66s",
                "x-ratelimit-reset-tokens": "7.66s",
            },
            body={
                "error": {
                    "message": "Rate limit reached on tokens per minute (TPM)",
                    "type": "tokens",
                    "code": "rate_limit_exceeded",
                }
            },
        )

        info = llm_client._classify_429(resp)

        self.assertEqual(info.kind, "tpm_wait")
        self.assertAlmostEqual(info.wait_seconds, 7.66)

    def test_daily_429_is_quota_limit(self):
        resp = FakeResponse(
            headers={"retry-after": "86400s"},
            body={
                "error": {
                    "message": "Rate limit reached on tokens per day (TPD)",
                    "type": "tokens",
                    "code": "rate_limit_exceeded",
                }
            },
        )

        info = llm_client._classify_429(resp)

        self.assertEqual(info.kind, "daily_limit")
        self.assertEqual(info.wait_seconds, 0.0)

    def test_success_headers_update_model_state(self):
        model = "unit-test-model"
        llm_client._update_rate_state_from_headers(
            model,
            {
                "x-ratelimit-limit-tokens": "6000",
                "x-ratelimit-remaining-tokens": "4200",
                "x-ratelimit-reset-tokens": "2m",
            },
        )

        status = llm_client.get_rate_limit_status()
        model_status = next(item for item in status["models"] if item["model"] == model)

        self.assertEqual(model_status["limit_tokens"], 6000)
        self.assertEqual(model_status["remaining_tokens"], 4200)
        self.assertGreater(model_status["reset_tokens_seconds"], 0)

    def test_groq_provider_never_calls_ollama_on_rate_limit(self):
        old_provider = llm_client.LLM_PROVIDER
        old_keys = llm_client._groq_keys
        old_call_groq = llm_client._call_groq
        old_call_ollama = llm_client._call_ollama
        ollama_called = {"value": False}

        def fake_groq(*args, **kwargs):
            raise llm_client.GroqRateLimitError("temporary TPM wait")

        def fake_ollama(*args, **kwargs):
            ollama_called["value"] = True
            return "bad fallback"

        try:
            llm_client.LLM_PROVIDER = "groq"
            llm_client._groq_keys = ["gsk_unit_test"]
            llm_client._call_groq = fake_groq
            llm_client._call_ollama = fake_ollama

            with self.assertRaises(RuntimeError):
                llm_client.generate_text("hello", agent_name="tester")

            self.assertFalse(ollama_called["value"])
        finally:
            llm_client.LLM_PROVIDER = old_provider
            llm_client._groq_keys = old_keys
            llm_client._call_groq = old_call_groq
            llm_client._call_ollama = old_call_ollama


if __name__ == "__main__":
    unittest.main()
