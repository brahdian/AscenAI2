"""
LLM client with:
  - Per-call hard timeout (LLM_TIMEOUT_SECONDS)
  - Simple in-process circuit breaker (5 consecutive failures → open for 60 s)
  - Structured error logging without leaking credentials
"""
import asyncio
import json
import time
import uuid
from typing import AsyncGenerator, Optional

import structlog
from pydantic import BaseModel

from app.core.config import settings


def _record_llm_error(
    provider: str,
    model: str,
    error_type: str,
    error_msg: str,
    session_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """
    Dual-destination LLM error recorder.

    1. **Docker logs (structlog)** — always emitted, picked up by `docker logs`
       and any log-shipper (Loki, CloudWatch, etc.).
    2. **Jaeger / any OTEL backend (span event)** — attached to the *current*
       active span so the error appears inline on the Jaeger trace timeline.
       Jaeger is a *tracing* tool, not a log aggregator; the correct primitive
       is a span event (recorded_exception), not a log message.
       This is a no-op when OTEL is disabled or no span is active.
    """
    fields: dict = {
        "provider": provider,
        "model": model,
        "error_type": error_type,
        "error": error_msg,
    }
    if session_id:
        fields["session_id"] = session_id
    if extra:
        fields.update(extra)

    # 1. Docker / stdout via structlog
    logger.error("llm_api_error", **fields)

    # 2. OTEL span event → Jaeger (graceful no-op when OTEL not initialised)
    try:
        from opentelemetry import trace as _otel_trace
        span = _otel_trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("llm.provider", provider)
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.error_type", error_type)
            if session_id:
                span.set_attribute("session.id", session_id)
            span.record_exception(
                RuntimeError(error_msg),
                attributes={
                    "llm.error_type": error_type,
                    "llm.provider": provider,
                    **(extra or {}),
                },
            )
            span.set_status(
                _otel_trace.Status(
                    _otel_trace.StatusCode.ERROR,
                    description=f"{provider}/{model}: {error_type}",
                )
            )
    except Exception:
        # Never let observability code crash the request path
        pass
from app.core.metrics import (
    LLM_TOKENS, LLM_LATENCY, LLM_ERRORS, LLM_CIRCUIT_OPENS,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError

# One breaker per provider (singleton per worker, backed by Redis)
_breakers: dict[str, CircuitBreaker] = {}

def _get_breaker(provider: str) -> CircuitBreaker:
    """Return the shared CircuitBreaker for the given LLM provider.
    
    Redis is injected lazily on first async call via complete().
    """
    if provider not in _breakers:
        _breakers[provider] = CircuitBreaker(
            name=f"llm_{provider}",
            redis=None,  # Injected lazily on first complete() call
            failure_threshold=5,
            recovery_timeout=60,
        )
    return _breakers[provider]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str = "",
        vertex_project: str = "",
        vertex_location: str = "us-central1",
        redis=None,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.vertex_project = vertex_project
        self.vertex_location = vertex_location
        self._gemini_client = None
        self._openai_client = None
        self._vertex_client = None
        # Wire Redis into the shared circuit breaker immediately if provided.
        if redis is not None:
            self.set_redis(redis)

    def set_redis(self, redis) -> None:
        """Inject the Redis client into this provider's circuit breaker.

        Call this once at startup after the Redis pool is initialized.
        The breaker is a module-level singleton so the change is visible
        across all LLMClient instances for the same provider.
        """
        breaker = _get_breaker(self.provider)
        breaker.redis = redis
        logger.info("llm_circuit_breaker_redis_injected", provider=self.provider)

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
        if self._vertex_client is None:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(project=self.vertex_project, location=self.vertex_location)
            self._vertex_client = GenerativeModel(self.model)
        return self._vertex_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        stream: bool = False,
        session_id: Optional[str] = None,
    ) -> "LLMResponse | AsyncGenerator":
        breaker = _get_breaker(self.provider)
        _t0 = time.monotonic()
        
        async def _run_llm_call():
            return await asyncio.wait_for(
                self._dispatch(messages, tools, temperature, max_tokens, stream, session_id),
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            
        try:
            result = await breaker.call(_run_llm_call)
            
            LLM_LATENCY.labels(provider=self.provider, model=self.model).observe(
                time.monotonic() - _t0
            )
            # Emit token metrics from non-streaming responses
            if isinstance(result, LLMResponse) and result.usage:
                LLM_TOKENS.labels(provider=self.provider, model=self.model, type="prompt").inc(
                    result.usage.prompt_tokens
                )
                LLM_TOKENS.labels(provider=self.provider, model=self.model, type="completion").inc(
                    result.usage.completion_tokens
                )
            return result
        except asyncio.TimeoutError:
            LLM_ERRORS.labels(provider=self.provider, model=self.model, error_type="timeout").inc()
            _record_llm_error(
                provider=self.provider,
                model=self.model,
                error_type="timeout",
                error_msg=f"LLM call timed out after {settings.LLM_TIMEOUT_SECONDS}s",
                extra={"timeout_s": settings.LLM_TIMEOUT_SECONDS},
            )
            raise TimeoutError(
                f"LLM call to {self.provider}/{self.model} timed out "
                f"after {settings.LLM_TIMEOUT_SECONDS}s"
            )
        except CircuitOpenError as exc:
            LLM_ERRORS.labels(provider=self.provider, model=self.model, error_type="circuit_open").inc()
            _record_llm_error(
                provider=self.provider,
                model=self.model,
                error_type="circuit_open",
                error_msg=str(exc),
            )
            raise
        except Exception as exc:
            LLM_ERRORS.labels(provider=self.provider, model=self.model, error_type="api_error").inc()
            _record_llm_error(
                provider=self.provider,
                model=self.model,
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )
            raise

    async def _dispatch(self, messages, tools, temperature, max_tokens, stream, session_id):
        if self.provider == "gemini":
            return await self._gemini_complete(messages, tools, temperature, max_tokens, stream, session_id)
        if self.provider == "vertex":
            return await self._vertex_complete(messages, tools, temperature, max_tokens, stream)
        return await self._openai_complete(messages, tools, temperature, max_tokens, stream)

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _gemini_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        session_id: Optional[str] = None,
    ) -> "LLMResponse | AsyncGenerator":
        from google import genai
        from google.genai import types

        client = self._get_gemini_client()

        system_instruction = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = (system_instruction or "") + msg["content"]
            else:
                chat_messages.append(msg)

        contents = []
        for msg in chat_messages:
            role = msg["role"]
            content = msg.get("content", "")
            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(
                            name=msg.get("name", "tool"),
                            response={"result": content},
                        )],
                    )
                )
            elif role == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=content)]))
            elif role == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part.from_text(text=content)]))

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

        # Build generation config — implicit caching is automatic on Gemini 2.5+ models
        # (no explicit client.caches.create needed; Google applies 90% discount automatically)
        config_kwargs: dict = {"max_output_tokens": max_tokens, "temperature": temperature}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        generate_config = types.GenerateContentConfig(**config_kwargs)

        if stream and not tools:
            return self._gemini_stream_generator(client, contents, generate_config)

        loop = asyncio.get_event_loop()
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=generate_config,
                    ),
                ),
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.error("gemini_generate_content_failed", error=str(exc))
            raise

        # TYPE SAFETY: Gemini SDK can return None or True in certain error/edge cases
        if response is None or isinstance(response, bool):
            logger.error("gemini_returned_boolean_or_none", type=type(response).__name__, response=str(response))
            raise ValueError(f"Gemini API returned invalid {type(response).__name__} instead of response object")

        tool_calls = []
        text_content = None
        
        # TYPE SAFETY: Ensure candidates is iterable
        candidates = getattr(response, "candidates", [])
        if not isinstance(candidates, list):
            logger.warning("gemini_candidates_not_list", type=type(candidates).__name__, session_id=session_id)
            candidates = []

        for candidate in candidates:
            if not hasattr(candidate, "content") or not candidate.content:
                continue
            parts = getattr(candidate.content, "parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if hasattr(part, "function_call") and part.function_call and part.function_call.name:
                    args = dict(part.function_call.args or {})
                    tool_calls.append(ToolCall(id=str(uuid.uuid4()), name=part.function_call.name, arguments=args))
                elif hasattr(part, "text") and part.text:
                    text_content = (text_content or "") + str(part.text)

        usage_meta = getattr(response, "usage_metadata", None)
        usage = TokenUsage(
            prompt_tokens=int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage_meta, "total_token_count", 0) or 0),
        )

        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
        )

    async def _gemini_stream_generator(self, client, contents, config) -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        response_iter = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.models.generate_content_stream(
                    model=self.model, contents=contents, config=config
                ),
            ),
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        for chunk in response_iter:
            if chunk.text:
                yield str(chunk.text)

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    async def _openai_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> "LLMResponse | AsyncGenerator":
        client = self._get_openai_client()
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if stream and not tools:
            return self._openai_stream_generator(client, kwargs)

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

    async def _openai_stream_generator(self, client, kwargs) -> AsyncGenerator[str, None]:
        kwargs["stream"] = True
        async with await client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content

    # ------------------------------------------------------------------
    # Vertex AI
    # ------------------------------------------------------------------

    async def _vertex_complete(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        session_id: Optional[str] = None,
    ) -> "LLMResponse | AsyncGenerator":
        from vertexai.generative_models import GenerativeModel, GenerationConfig, Tool, FunctionDeclaration, Schema, Type
        import vertexai

        vertexai.init(project=self.vertex_project, location=self.vertex_location)

        system_instruction = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                chat_messages.append(msg)

        generation_config = GenerationConfig(temperature=temperature, max_output_tokens=max_tokens)

        vertex_tools = None
        if tools:
            declarations = []
            for tool in tools:
                fn = tool.get("function", tool)
                params = fn.get("parameters", {})
                props = {k: _build_vertex_schema(v) for k, v in params.get("properties", {}).items()}
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

        from vertexai.generative_models import Content, Part
        history = []
        last_user_message = None
        for i, msg in enumerate(chat_messages):
            role = msg["role"]
            content = msg["content"]
            if role == "tool":
                history.append(Content(role="function", parts=[
                    Part.from_function_response(name=msg.get("name", "tool"), response={"result": content})
                ]))
            elif role == "user":
                if i == len(chat_messages) - 1:
                    last_user_message = content
                else:
                    history.append(Content(role="user", parts=[Part.from_text(content)]))
            elif role == "assistant":
                history.append(Content(role="model", parts=[Part.from_text(content)]))

        model_kwargs = {}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction
        model = GenerativeModel(self.model, **model_kwargs)

        chat = model.start_chat(history=history)
        send_kwargs: dict = {"generation_config": generation_config}
        if vertex_tools:
            send_kwargs["tools"] = vertex_tools

        if stream and not tools:
            return self._vertex_stream_generator(chat, last_user_message or "", send_kwargs)

        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: chat.send_message(last_user_message or "", **send_kwargs)),
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        tool_calls = []
        text_content = None
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call.name:
                    tool_calls.append(ToolCall(
                        id=str(uuid.uuid4()),
                        name=part.function_call.name,
                        arguments=dict(part.function_call.args),
                    ))
                elif hasattr(part, "text") and part.text:
                    text_content = (text_content or "") + part.text

        usage_meta = response.usage_metadata
        usage = TokenUsage(
            prompt_tokens=int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            total_tokens=int(getattr(usage_meta, "total_token_count", 0) or 0),
        )
        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
        )

    async def _vertex_stream_generator(self, chat, message: str, send_kwargs: dict) -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        send_kwargs = {**send_kwargs, "stream": True}
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: chat.send_message(message, **send_kwargs)),
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        for chunk in response:
            if chunk.text:
                yield str(chunk.text)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        if self.provider == "gemini":
            client = self._get_gemini_client()
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.embed_content(
                        model=settings.EMBEDDING_MODEL,
                        contents=text,
                    ),
                ),
                timeout=10.0,
            )
            # handle both single string and list responses
            if hasattr(response, "embeddings") and response.embeddings:
                return response.embeddings[0].values
            return response.embedding.values

        if self.provider == "vertex":
            from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
            model = TextEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: model.get_embeddings([TextEmbeddingInput(text)])
            )
            return embeddings[0].values

        if self.provider == "openai":
            client = self._get_openai_client()
            response = await asyncio.wait_for(
                client.embeddings.create(input=text, model=settings.EMBEDDING_MODEL),
                timeout=10.0,
            )
            return response.data[0].embedding

        return [0.0] * settings.EMBEDDING_DIMENSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_genai_schema(params: dict) -> dict:
    return params


def _build_vertex_schema(prop: dict):
    from vertexai.generative_models import Schema, Type

    type_map = {
        "string": Type.STRING, "integer": Type.INTEGER, "number": Type.NUMBER,
        "boolean": Type.BOOLEAN, "array": Type.ARRAY, "object": Type.OBJECT,
    }
    prop_type = type_map.get(prop.get("type", "string"), Type.STRING)
    kwargs: dict = {"type": prop_type, "description": prop.get("description", "")}
    if prop_type == Type.OBJECT and "properties" in prop:
        kwargs["properties"] = {k: _build_vertex_schema(v) for k, v in prop["properties"].items()}
        if "required" in prop:
            kwargs["required"] = prop["required"]
    elif prop_type == Type.ARRAY and "items" in prop:
        kwargs["items"] = _build_vertex_schema(prop["items"])
    return Schema(**kwargs)


def get_embedding_fn():
    """
    Return an async callable that embeds a text string into a float vector.

    Uses sentence-transformers (all-MiniLM-L6-v2, 384-dim) in a thread pool
    so the CPU-bound call doesn't block the event loop.
    """
    _model = None

    async def _embed(text: str) -> list[float]:
        nonlocal _model
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _run():
            nonlocal _model
            if _model is None:
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore
                    _model = SentenceTransformer("all-MiniLM-L6-v2")
                except ImportError:
                    # Fallback: return zero vector
                    return [0.0] * 384
            return _model.encode(text, normalize_embeddings=True).tolist()

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return await loop.run_in_executor(executor, _run)

    return _embed


def create_llm_client(redis=None) -> LLMClient:
    """Factory for LLMClient. Pass the Redis client from app startup so the
    circuit breaker has its shared state store from the very first request."""
    if settings.LLM_PROVIDER == "gemini":
        return LLMClient(
            provider="gemini", model=settings.GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY, redis=redis,
        )
    if settings.LLM_PROVIDER == "vertex":
        return LLMClient(
            provider="vertex", model=settings.GEMINI_MODEL,
            vertex_project=settings.VERTEX_PROJECT_ID,
            vertex_location=settings.VERTEX_LOCATION,
            redis=redis,
        )
    return LLMClient(
        provider="openai", model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY, redis=redis,
    )
