"""ChatGPT plan usage through the existing ordinary report backend contract."""
from src.llm.chatgpt_responses import request_responses
from src.llm.generation_backend import GenerationCapabilities, GenerationError, GenerationErrorCode, GenerationResult
from src.llm.model_source import CHATGPT_SIWC
from src.services.chatgpt_oauth_service import ChatGPTError, get_chatgpt_service


class SiwcGenerationBackend:
    backend_id = CHATGPT_SIWC
    capabilities = GenerationCapabilities(True, False, True, False, False, False)

    def __init__(self, source, timeout):
        self.source = source
        self.timeout = timeout

    def generate(
        self, prompt, generation_config, *, system_prompt=None, stream=False,
        stream_progress_callback=None, response_validator=None, audit_context=None,
    ):
        try:
            response = request_responses(
                get_chatgpt_service(), self.source, items=[{"role": "user", "content": prompt}],
                instructions=system_prompt or "", timeout=self.timeout, progress=stream_progress_callback,
            )
            if any(item.get("type") in {"function_call", "custom_tool_call"} for item in response.items):
                raise response.output_error("ChatGPT returned a tool call for an ordinary report")
            text = response.final_text()
        except ChatGPTError as exc:
            raise GenerationError(
                GenerationErrorCode.TIMEOUT if exc.code == "chatgpt_timeout" else GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                "generation", False, False, CHATGPT_SIWC, details={"safe_error": str(exc)},
            ) from None
        if response_validator is not None:
            try:
                response_validator(text)
            except GenerationError as exc:
                exc.retryable = False
                exc.fallbackable = False
                exc.details["safe_error"] = str(response.output_error(exc.message))
                raise
        return GenerationResult(text, response.model, CHATGPT_SIWC, CHATGPT_SIWC, response.usage)
