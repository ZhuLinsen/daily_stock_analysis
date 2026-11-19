"""Map one DSA Agent turn onto a cumulative Responses input."""
import json

from src.agent.llm_adapter import LLMResponse, ToolCall
from src.llm.chatgpt_responses import request_responses
from src.llm.model_source import CHATGPT_SIWC
from src.services.chatgpt_oauth_service import ChatGPTError, get_chatgpt_service

_NAMESPACE = "dsa_market_data"


class ChatGPTToolAdapter:
    def __init__(self, source, timeout):
        self.source = source
        self.timeout = timeout
        self.items = None
        self.cursor = 0
        self.pending = []
        self.call_ids = set()

    def call_with_tools(self, messages, tools, timeout=None):
        try:
            return self._call(messages, tools, timeout)
        except ChatGPTError as exc:
            return LLMResponse(provider="error", content=str(exc), usage=exc.usage or {})

    def _call(self, messages, tools, timeout):
        functions = {
            declaration["function"]["name"]: {"type": "function", **declaration["function"], "strict": False}
            for declaration in tools
        }
        if self.items is None:
            self.instructions = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
            self.items = [
                {"role": message["role"], "content": message["content"]}
                for message in messages if message["role"] in {"user", "assistant", "developer"}
            ]
        else:
            results = messages[self.cursor:]
            if [(row.get("tool_call_id"), row.get("name")) for row in results] != self.pending or any(
                row.get("role") != "tool" for row in results
            ):
                raise ChatGPTError("chatgpt_protocol_error", "DSA tool results did not match the pending calls")
            self.items.extend({
                "type": "function_call_output", "call_id": row["tool_call_id"], "output": row["content"],
            } for row in results)

        response = request_responses(
            get_chatgpt_service(), self.source, call_type="agent", items=self.items, instructions=self.instructions,
            timeout=self.timeout if timeout is None else timeout,
            tools=[{
                "type": "namespace", "name": _NAMESPACE,
                "description": "Daily Stock Analysis tools", "tools": list(functions.values()),
            }] if functions else None,
        )
        self.items.extend(response.items)
        calls = []
        for item in response.items:
            if item.get("type") == "custom_tool_call":
                raise response.output_error("ChatGPT requested an unsupported custom tool")
            if item.get("type") != "function_call":
                continue
            call_id, name = item.get("call_id"), item.get("name")
            if item.get("namespace") != _NAMESPACE or name not in functions:
                raise response.output_error("ChatGPT requested an unknown tool")
            if not isinstance(call_id, str) or not call_id.strip() or call_id in self.call_ids:
                raise response.output_error("ChatGPT returned an invalid or duplicate call_id")
            try:
                arguments = json.loads(item.get("arguments", ""))
            except (ValueError, TypeError):
                arguments = None
            if not isinstance(arguments, dict):
                raise response.output_error("ChatGPT tool arguments must be a JSON object")
            self.call_ids.add(call_id)
            calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

        if calls:
            # Runner appends a normalized assistant item, then one result per call.
            self.cursor = len(messages) + 1
            self.pending = [(call.id, call.name) for call in calls]
        return LLMResponse(
            provider=CHATGPT_SIWC, model=response.model, usage=response.usage,
            tool_calls=calls, content=None if calls else response.final_text(),
        )
