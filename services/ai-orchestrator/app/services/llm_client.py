import asyncio
import json
import uuid
from typing import AsyncGenerator, Optional
from pydantic import BaseModel
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    finish_reason: str = "stop"
    usage: TokenUsage = TokenUsage()


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self._gemini_client = None
        self._openai_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._gemini_client = genai
        return self._gemini_client

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(api_key=self.api_key)
        return self._openai_client

    async def complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        stream: bool = False,
    ) -> LLMResponse | AsyncGenerator:
        if self.provider == "gemini":
            return await self._gemini_complete(messages, tools, temperature, max_tokens, stream)
        return await self._openai_complete(messages, tools, temperature, max_tokens, stream)

    async def _gemini_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> LLMResponse | AsyncGenerator:
        import google.generativeai as genai
        from google.generativeai.types import content_types

        genai.configure(api_key=self.api_key)

        # Extract system prompt from messages
        system_instruction = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                chat_messages.append(msg)

        # Build generation config
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        # Build tool declarations for Gemini
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool in tools:
                fn = tool.get("function", tool)
                params = fn.get("parameters", {})
                # Gemini expects properties without additionalProperties
                clean_params = {
                    "type": params.get("type", "object"),
                    "properties": params.get("properties", {}),
                }
                if "required" in params:
                    clean_params["required"] = params["required"]
                function_declarations.append(
                    genai.protos.FunctionDeclaration(
                        name=fn["name"],
                        description=fn.get("description", ""),
                        parameters=genai.protos.Schema(
                            type=genai.protos.Type.OBJECT,
                            properties={
                                k: _build_gemini_schema(v)
                                for k, v in clean_params.get("properties", {}).items()
                            },
                            required=clean_params.get("required", []),
                        ),
                    )
                )
            gemini_tools = [genai.protos.Tool(function_declarations=function_declarations)]

        model_kwargs = {
            "model_name": self.model,
            "generation_config": generation_config,
        }
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        model = genai.GenerativeModel(**model_kwargs)

        # Convert messages to Gemini format
        history = []
        last_user_message = None

        for i, msg in enumerate(chat_messages):
            role = msg["role"]
            content = msg["content"]

            if role == "tool":
                # Tool result message - append as function response
                history.append(
                    genai.protos.Content(
                        role="function",
                        parts=[
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=msg.get("name", "tool"),
                                    response={"result": content},
                                )
                            )
                        ],
                    )
                )
            elif role == "user":
                if i == len(chat_messages) - 1:
                    last_user_message = content
                else:
                    history.append(
                        genai.protos.Content(
                            role="user",
                            parts=[genai.protos.Part(text=content)],
                        )
                    )
            elif role == "assistant":
                history.append(
                    genai.protos.Content(
                        role="model",
                        parts=[genai.protos.Part(text=content)],
                    )
                )

        if last_user_message is None and chat_messages:
            last_user_message = chat_messages[-1].get("content", "")

        try:
            chat = model.start_chat(history=history)

            if stream and not tools:
                return self._gemini_stream_generator(chat, last_user_message or "")

            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: chat.send_message(last_user_message or "")
            )

            # Parse response
            tool_calls = []
            text_content = None

            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call.name:
                        args = dict(part.function_call.args)
                        tool_calls.append(
                            ToolCall(
                                id=str(uuid.uuid4()),
                                name=part.function_call.name,
                                arguments=args,
                            )
                        )
                    elif hasattr(part, "text") and part.text:
                        text_content = (text_content or "") + part.text

            usage_meta = response.usage_metadata
            usage = TokenUsage(
                prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
                total_tokens=getattr(usage_meta, "total_token_count", 0) or 0,
            )

            finish_reason = "tool_calls" if tool_calls else "stop"

            return LLMResponse(
                content=text_content,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason=finish_reason,
                usage=usage,
            )

        except Exception as exc:
            logger.error("gemini_completion_error", error=str(exc), model=self.model)
            raise

    async def _gemini_stream_generator(self, chat, message: str) -> AsyncGenerator[str, None]:
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: chat.send_message(message, stream=True)
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text

    async def _openai_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> LLMResponse | AsyncGenerator:
        client = self._get_openai_client()

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if stream and not tools:
            return self._openai_stream_generator(client, kwargs)

        try:
            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            tool_calls = None
            if message.tool_calls:
                tool_calls = [
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                    for tc in message.tool_calls
                ]

            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

            return LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
                usage=usage,
            )

        except Exception as exc:
            logger.error("openai_completion_error", error=str(exc), model=self.model)
            raise

    async def _openai_stream_generator(self, client, kwargs) -> AsyncGenerator[str, None]:
        kwargs["stream"] = True
        async with await client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content

    async def embed(self, text: str) -> list[float]:
        if self.provider == "openai":
            client = self._get_openai_client()
            response = await client.embeddings.create(
                input=text,
                model=settings.EMBEDDING_MODEL,
            )
            return response.data[0].embedding
        else:
            # Fall back to a simple hash-based embedding for non-OpenAI providers
            # In production, use a dedicated embedding service
            try:
                from openai import AsyncOpenAI
                if settings.OPENAI_API_KEY:
                    embed_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                    response = await embed_client.embeddings.create(
                        input=text,
                        model=settings.EMBEDDING_MODEL,
                    )
                    return response.data[0].embedding
            except Exception as exc:
                logger.warning("embedding_fallback", error=str(exc))
            # Return zero vector as last resort
            return [0.0] * 1536


def _build_gemini_schema(prop: dict) -> "genai.protos.Schema":
    import google.generativeai as genai

    type_map = {
        "string": genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "number": genai.protos.Type.NUMBER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array": genai.protos.Type.ARRAY,
        "object": genai.protos.Type.OBJECT,
    }
    prop_type = type_map.get(prop.get("type", "string"), genai.protos.Type.STRING)

    schema_kwargs = {
        "type": prop_type,
        "description": prop.get("description", ""),
    }

    if prop_type == genai.protos.Type.OBJECT and "properties" in prop:
        schema_kwargs["properties"] = {
            k: _build_gemini_schema(v) for k, v in prop["properties"].items()
        }
        if "required" in prop:
            schema_kwargs["required"] = prop["required"]
    elif prop_type == genai.protos.Type.ARRAY and "items" in prop:
        schema_kwargs["items"] = _build_gemini_schema(prop["items"])

    return genai.protos.Schema(**schema_kwargs)


def create_llm_client() -> LLMClient:
    if settings.LLM_PROVIDER == "gemini":
        return LLMClient(
            provider="gemini",
            model=settings.GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY,
        )
    return LLMClient(
        provider="openai",
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
