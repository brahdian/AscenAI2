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
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str = "",
        vertex_project: str = "",
        vertex_location: str = "us-central1",
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.vertex_project = vertex_project
        self.vertex_location = vertex_location
        self._gemini_client = None
        self._openai_client = None
        self._vertex_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=self.api_key)
        return self._gemini_client

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(api_key=self.api_key)
        return self._openai_client

    def _get_vertex_client(self):
        """Initialize Vertex AI client (uses Application Default Credentials)."""
        if self._vertex_client is None:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(project=self.vertex_project, location=self.vertex_location)
            self._vertex_client = GenerativeModel(self.model)
        return self._vertex_client

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
        if self.provider == "vertex":
            return await self._vertex_complete(messages, tools, temperature, max_tokens, stream)
        return await self._openai_complete(messages, tools, temperature, max_tokens, stream)

    async def _gemini_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> LLMResponse | AsyncGenerator:
        from google import genai
        from google.genai import types

        client = self._get_gemini_client()

        # Extract system prompt from messages
        system_instruction = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = (system_instruction or "") + msg["content"]
            else:
                chat_messages.append(msg)

        # Convert messages to google-genai Content format
        contents = []
        for msg in chat_messages:
            role = msg["role"]
            content = msg.get("content", "")

            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg.get("name", "tool"),
                                response={"result": content},
                            )
                        ],
                    )
                )
            elif role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=content)],
                    )
                )
            elif role == "assistant":
                contents.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=content)],
                    )
                )

        # Build tool declarations for Gemini
        gemini_tools = None
        if tools:
            function_declarations = []
            for tool in tools:
                fn = tool.get("function", tool)
                params = fn.get("parameters", {})
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=fn["name"],
                        description=fn.get("description", ""),
                        parameters=_build_genai_schema(params),
                    )
                )
            gemini_tools = [types.Tool(function_declarations=function_declarations)]

        config_kwargs = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        generate_config = types.GenerateContentConfig(**config_kwargs)

        try:
            if stream and not tools:
                return self._gemini_stream_generator(client, contents, generate_config)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=generate_config,
                ),
            )

            # Parse response
            tool_calls = []
            text_content = None

            for candidate in (response.candidates or []):
                for part in (candidate.content.parts if candidate.content else []):
                    if hasattr(part, "function_call") and part.function_call and part.function_call.name:
                        args = dict(part.function_call.args or {})
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

    async def _gemini_stream_generator(self, client, contents, config) -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        response_iter = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            ),
        )
        for chunk in response_iter:
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

    async def _vertex_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> LLMResponse | AsyncGenerator:
        from vertexai.generative_models import GenerativeModel, GenerationConfig, Tool, FunctionDeclaration, Schema, Type
        import vertexai

        vertexai.init(project=self.vertex_project, location=self.vertex_location)

        # Extract system prompt
        system_instruction = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                chat_messages.append(msg)

        generation_config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        # Build Vertex AI tool declarations
        vertex_tools = None
        if tools:
            declarations = []
            for tool in tools:
                fn = tool.get("function", tool)
                params = fn.get("parameters", {})
                props = {}
                for k, v in params.get("properties", {}).items():
                    props[k] = _build_vertex_schema(v)
                declarations.append(
                    FunctionDeclaration(
                        name=fn["name"],
                        description=fn.get("description", ""),
                        parameters=Schema(
                            type=Type.OBJECT,
                            properties=props,
                            required=params.get("required", []),
                        ),
                    )
                )
            vertex_tools = [Tool(function_declarations=declarations)]

        model_kwargs = {}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        model = GenerativeModel(self.model, **model_kwargs)

        # Convert messages to Vertex AI Content format
        from vertexai.generative_models import Content, Part
        history = []
        last_user_message = None

        for i, msg in enumerate(chat_messages):
            role = msg["role"]
            content = msg["content"]

            if role == "tool":
                from vertexai.generative_models import FunctionResponse
                history.append(
                    Content(
                        role="function",
                        parts=[Part.from_function_response(name=msg.get("name", "tool"), response={"result": content})],
                    )
                )
            elif role == "user":
                if i == len(chat_messages) - 1:
                    last_user_message = content
                else:
                    history.append(Content(role="user", parts=[Part.from_text(content)]))
            elif role == "assistant":
                history.append(Content(role="model", parts=[Part.from_text(content)]))

        if last_user_message is None and chat_messages:
            last_user_message = chat_messages[-1].get("content", "")

        try:
            chat = model.start_chat(history=history)

            send_kwargs = {"generation_config": generation_config}
            if vertex_tools:
                send_kwargs["tools"] = vertex_tools

            if stream and not tools:
                return self._vertex_stream_generator(chat, last_user_message or "", send_kwargs)

            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: chat.send_message(last_user_message or "", **send_kwargs)
            )

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

            return LLMResponse(
                content=text_content,
                tool_calls=tool_calls if tool_calls else None,
                finish_reason="tool_calls" if tool_calls else "stop",
                usage=usage,
            )

        except Exception as exc:
            logger.error("vertex_completion_error", error=str(exc), model=self.model)
            raise

    async def _vertex_stream_generator(self, chat, message: str, send_kwargs: dict) -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        send_kwargs = {**send_kwargs, "stream": True}
        response = await loop.run_in_executor(
            None, lambda: chat.send_message(message, **send_kwargs)
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text

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


def _build_genai_schema(params: dict) -> dict:
    """Convert JSON Schema parameters dict to google-genai compatible schema dict."""
    return params


def _build_vertex_schema(prop: dict):
    """Build a Vertex AI Schema from a JSON Schema property dict."""
    from vertexai.generative_models import Schema, Type

    type_map = {
        "string": Type.STRING,
        "integer": Type.INTEGER,
        "number": Type.NUMBER,
        "boolean": Type.BOOLEAN,
        "array": Type.ARRAY,
        "object": Type.OBJECT,
    }
    prop_type = type_map.get(prop.get("type", "string"), Type.STRING)
    kwargs = {"type": prop_type, "description": prop.get("description", "")}

    if prop_type == Type.OBJECT and "properties" in prop:
        kwargs["properties"] = {k: _build_vertex_schema(v) for k, v in prop["properties"].items()}
        if "required" in prop:
            kwargs["required"] = prop["required"]
    elif prop_type == Type.ARRAY and "items" in prop:
        kwargs["items"] = _build_vertex_schema(prop["items"])

    return Schema(**kwargs)


def create_llm_client() -> LLMClient:
    if settings.LLM_PROVIDER == "gemini":
        return LLMClient(
            provider="gemini",
            model=settings.GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY,
        )
    if settings.LLM_PROVIDER == "vertex":
        return LLMClient(
            provider="vertex",
            model=settings.GEMINI_MODEL,
            vertex_project=settings.VERTEX_PROJECT_ID,
            vertex_location=settings.VERTEX_LOCATION,
        )
    return LLMClient(
        provider="openai",
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
    )
