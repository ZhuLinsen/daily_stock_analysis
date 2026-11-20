"""Request-scoped model selection. This reference carries no credentials."""
from typing import Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from pydantic.json_schema import SkipJsonSchema
from typing_extensions import Annotated

CHATGPT_SIWC = "chatgpt_siwc"
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatGPTModelSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["chatgpt_siwc"]
    connection_id: NonEmpty
    model: NonEmpty


# An omitted request field defaults to None. A supplied field must be an object.
ChatGPTModelSourceInput = Annotated[
    Union[ChatGPTModelSource, SkipJsonSchema[None]],
    BeforeValidator(ChatGPTModelSource.model_validate),
    Field(default_factory=lambda: None),
]
