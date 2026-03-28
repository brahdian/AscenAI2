"""
RAG (Retrieval-Augmented Generation) service with hybrid search, reranking,
and hallucination guardrails.

Pipeline:
1. Hybrid retrieval: dense vector search (Qdrant) + BM25 keyword search (in-memory)
2. Reciprocal Rank Fusion (RRF) to merge ranked lists
3. Cross-encoder reranking (sentence-transformers cross-encoder/ms-marco-MiniLM-L-6-v2)
4. Hallucination guardrail: if max reranker score < 0.3, return insufficient_evidence=True
5. Confidence scoring: combined_score = 0.4*retrieval_score + 0.4*reranker_score + 0.2*coverage_score
6. coverage_score = % of query terms found in top-3 chunks
"""
from __future__ import annotations

import asyncio
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum reranker score to consider evidence sufficient.
HALLUCINATION_SCORE_THRESHOLD: float = 0.3

# RRF constant (60 is the standard value from the original paper).
RRF_K: int = 60

# Thread pool shared across all RAGService instances for blocking ML calls.
_THREAD_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-rerank")

GROUNDING_SYSTEM_PROMPT: str = (
    "Answer ONLY using the provided context. "
    "If the context does not contain sufficient information to answer confidently, "
    "respond with: I don't have enough information to answer that accurately. "
    "Do NOT speculate or use external knowledge."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RankedChunk:
    """A single retrieved chunk with retrieval and reranker scores."""
    content: str
    doc_id: str
    kb_id: str
    title: str
    chunk_index: int
    retrieval_score: float          # raw vector / BM25 score (0–1)
    reranker_score: float = 0.0     # cross-encoder score (set after reranking)
    combined_score: float = 0.0     # final blended score
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """Full result from RAGService.retrieve()."""
    chunks: list[RankedChunk]
    insufficient_evidence: bool
    confidence: float               # 0–1
    bm25_hits: int
    vector_hits: int
    grounding_prompt: str = GROUNDING_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------

class RAGService:
    """
    Enhanced RAG pipeline with hybrid search, reranking, and hallucination guardrails.
    """

    def __init__(self, qdrant_client, embedding_model_name: str = "all-MiniLM-L6-v2") -> None:
        self.qdrant = qdrant_client
        self._embedding_model_name = embedding_model_name
        self._embedding_model = None          # lazy-loaded sentence-transformer
        self._cross_encoder = None            # lazy-loaded cross-encoder
        # Per-collection BM25 indexes: {collection_key: BM25Okapi}
        self._bm25_indexes: dict[str, Any] = {}
        # Tokenized corpus per collection for index rebuilds:
        self._bm25_corpus: dict[str, list[list[str]]] = {}
        # Payload store per collection: list of dicts with content/doc_id/etc.
        self._bm25_payload: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        knowledge_base_ids: list[str],
        top_k: int = 5,
        hybrid: bool = True,
    ) -> RetrievalResult:
        """
        Execute the full hybrid RAG pipeline and return a RetrievalResult.
        """
        log = logger.bind(tenant_id=tenant_id, query_len=len(query), top_k=top_k, hybrid=hybrid)

        if not knowledge_base_ids:
            log.warning("rag_retrieve_no_kb_ids")
            return RetrievalResult(
                chunks=[],
                insufficient_evidence=True,
                confidence=0.0,
                bm25_hits=0,
                vector_hits=0,
            )

        try:
            # Step 1a: Dense vector search
            vector_results = await self._vector_search(query, tenant_id, knowledge_base_ids, top_k)
            vector_hits = len(vector_results)

            # Step 1b: BM25 keyword search (only when hybrid=True)
            bm25_results: list[RankedChunk] = []
            bm25_hits = 0
            if hybrid:
                bm25_results = await self._bm25_search(query, tenant_id, knowledge_base_ids, top_k)
                bm25_hits = len(bm25_results)

            log.info(
                "rag_retrieval_complete",
                vector_hits=vector_hits,
                bm25_hits=bm25_hits,
            )

            # Step 2: RRF fusion
            if hybrid and bm25_results:
                fused_chunks = self._rrf_fusion(vector_results, bm25_results, k=RRF_K)
            else:
                fused_chunks = vector_results

            # Keep top_k * 2 for reranker to choose from
            candidate_chunks = fused_chunks[: top_k * 2]

            if not candidate_chunks:
                return RetrievalResult(
                    chunks=[],
                    insufficient_evidence=True,
                    confidence=0.0,
                    bm25_hits=bm25_hits,
                    vector_hits=vector_hits,
                )

            # Step 3: Cross-encoder reranking
            reranked_chunks = await self._rerank(query, candidate_chunks)
            reranked_chunks = reranked_chunks[:top_k]

            # Step 4: Hallucination guardrail
            max_reranker_score = max((c.reranker_score for c in reranked_chunks), default=0.0)
            insufficient_evidence = max_reranker_score < HALLUCINATION_SCORE_THRESHOLD

            # Step 5: Confidence scoring
            confidence = self._compute_confidence(reranked_chunks, query)

            log.info(
                "rag_pipeline_complete",
                chunks_returned=len(reranked_chunks),
                max_reranker_score=round(max_reranker_score, 4),
                insufficient_evidence=insufficient_evidence,
                confidence=round(confidence, 4),
            )

            return RetrievalResult(
                chunks=reranked_chunks,
                insufficient_evidence=insufficient_evidence,
                confidence=confidence,
                bm25_hits=bm25_hits,
                vector_hits=vector_hits,
            )

        except Exception as exc:
            log.error("rag_retrieve_failed", error=str(exc), exc_info=exc)
            return RetrievalResult(
                chunks=[],
                insufficient_evidence=True,
                confidence=0.0,
                bm25_hits=0,
                vector_hits=0,
            )

    # ------------------------------------------------------------------
    # Step 1a: Dense vector search
    # ------------------------------------------------------------------

    async def _vector_search(
        self,
        query: str,
        tenant_id: str,
        kb_ids: list[str],
        top_k: int,
    ) -> list[RankedChunk]:
        """Query Qdrant with a dense embedding vector."""
        if self.qdrant is None:
            logger.warning("rag_qdrant_unavailable")
            return []

        try:
            query_vector = await self._embed(query)
            from app.core.config import settings
            collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"

            from qdrant_client.models import Filter, FieldCondition, MatchAny
            search_filter = None
            if kb_ids:
                search_filter = Filter(
                    must=[
                        FieldCondition(
                            key="kb_id",
                            match=MatchAny(any=kb_ids),
                        )
                    ]
                )

            loop = asyncio.get_event_loop()
            hits = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: self.qdrant.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=top_k,
                    query_filter=search_filter,
                    with_payload=True,
                ),
            )

            chunks: list[RankedChunk] = []
            for hit in hits:
                payload: dict = hit.payload or {}
                chunks.append(
                    RankedChunk(
                        content=payload.get("content", ""),
                        doc_id=payload.get("doc_id", str(hit.id)),
                        kb_id=payload.get("kb_id", ""),
                        title=payload.get("title", ""),
                        chunk_index=payload.get("chunk_index", 0),
                        retrieval_score=float(hit.score),
                        metadata={
                            "content_type": payload.get("content_type", "text"),
                            "source": "vector",
                        },
                    )
                )
            return chunks

        except Exception as exc:
            logger.error("rag_vector_search_failed", error=str(exc), exc_info=exc)
            return []

    # ------------------------------------------------------------------
    # Step 1b: BM25 keyword search
    # ------------------------------------------------------------------

    async def _bm25_search(
        self,
        query: str,
        tenant_id: str,
        kb_ids: list[str],
        top_k: int,
    ) -> list[RankedChunk]:
        """BM25 search using in-memory indexes per collection."""
        results: list[RankedChunk] = []
        for kb_id in kb_ids:
            try:
                index_key = f"{tenant_id}:{kb_id}"
                if index_key not in self._bm25_indexes:
                    await self._build_bm25_index(tenant_id, kb_id)

                bm25 = self._bm25_indexes.get(index_key)
                payloads = self._bm25_payload.get(index_key, [])
                if bm25 is None or not payloads:
                    continue

                tokenized_query = self._tokenize(query)
                loop = asyncio.get_event_loop()
                scores = await loop.run_in_executor(
                    _THREAD_POOL,
                    lambda bm=bm25, tq=tokenized_query: bm.get_scores(tq),
                )

                # Normalize scores to [0, 1]
                max_score = float(max(scores)) if scores.any() and max(scores) > 0 else 1.0

                # Sort by score descending
                indexed_scores = sorted(
                    enumerate(scores), key=lambda x: x[1], reverse=True
                )[:top_k]

                for idx, score in indexed_scores:
                    if score <= 0:
                        continue
                    payload = payloads[idx]
                    results.append(
                        RankedChunk(
                            content=payload.get("content", ""),
                            doc_id=payload.get("doc_id", ""),
                            kb_id=payload.get("kb_id", kb_id),
                            title=payload.get("title", ""),
                            chunk_index=payload.get("chunk_index", 0),
                            retrieval_score=float(score) / max_score,
                            metadata={
                                "content_type": payload.get("content_type", "text"),
                                "source": "bm25",
                            },
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "rag_bm25_search_failed",
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                    error=str(exc),
                )

        return results

    async def _build_bm25_index(self, tenant_id: str, kb_id: str) -> Any:
        """Build a BM25Okapi index from all Qdrant payloads for a given (tenant, kb)."""
        from rank_bm25 import BM25Okapi

        index_key = f"{tenant_id}:{kb_id}"
        if self.qdrant is None:
            logger.warning("rag_bm25_qdrant_unavailable", index_key=index_key)
            return None

        try:
            from app.core.config import settings
            collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            scroll_filter = Filter(
                must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]
            )

            loop = asyncio.get_event_loop()
            # Scroll all points for the KB (paginated)
            all_payloads: list[dict[str, Any]] = []
            offset = None
            while True:
                result, next_offset = await loop.run_in_executor(
                    _THREAD_POOL,
                    lambda off=offset: self.qdrant.scroll(
                        collection_name=collection_name,
                        scroll_filter=scroll_filter,
                        with_payload=True,
                        with_vectors=False,
                        limit=200,
                        offset=off,
                    ),
                )
                for point in result:
                    all_payloads.append(point.payload or {})
                if next_offset is None:
                    break
                offset = next_offset

            if not all_payloads:
                logger.info("rag_bm25_index_empty", index_key=index_key)
                return None

            tokenized_corpus = [self._tokenize(p.get("content", "")) for p in all_payloads]
            bm25 = BM25Okapi(tokenized_corpus)
            self._bm25_indexes[index_key] = bm25
            self._bm25_corpus[index_key] = tokenized_corpus
            self._bm25_payload[index_key] = all_payloads

            logger.info(
                "rag_bm25_index_built",
                index_key=index_key,
                doc_count=len(all_payloads),
            )
            return bm25

        except Exception as exc:
            logger.error("rag_bm25_index_build_failed", index_key=index_key, error=str(exc))
            return None

    def invalidate_bm25_index(self, tenant_id: str, kb_id: str) -> None:
        """Remove a cached BM25 index so it is rebuilt on next query."""
        index_key = f"{tenant_id}:{kb_id}"
        self._bm25_indexes.pop(index_key, None)
        self._bm25_corpus.pop(index_key, None)
        self._bm25_payload.pop(index_key, None)
        logger.info("rag_bm25_index_invalidated", index_key=index_key)

    # ------------------------------------------------------------------
    # Step 2: Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    def _rrf_fusion(
        self,
        vector_results: list[RankedChunk],
        bm25_results: list[RankedChunk],
        k: int = 60,
    ) -> list[RankedChunk]:
        """
        Merge two ranked lists using Reciprocal Rank Fusion.
        RRF score(d) = sum(1 / (k + rank_i(d))) for each list i.
        """
        # Build content-keyed dedup map (use doc_id + chunk_index as key)
        chunk_map: dict[str, RankedChunk] = {}
        rrf_scores: dict[str, float] = {}

        def _key(chunk: RankedChunk) -> str:
            return f"{chunk.doc_id}:{chunk.chunk_index}"

        for rank, chunk in enumerate(vector_results, start=1):
            ck = _key(chunk)
            chunk_map[ck] = chunk
            rrf_scores[ck] = rrf_scores.get(ck, 0.0) + 1.0 / (k + rank)

        for rank, chunk in enumerate(bm25_results, start=1):
            ck = _key(chunk)
            if ck not in chunk_map:
                chunk_map[ck] = chunk
            rrf_scores[ck] = rrf_scores.get(ck, 0.0) + 1.0 / (k + rank)

        # Sort by RRF score descending
        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        fused: list[RankedChunk] = []
        for ck in sorted_keys:
            chunk = chunk_map[ck]
            # Normalize RRF score to approximate [0, 1] — max possible is 2/k+1
            chunk.retrieval_score = min(rrf_scores[ck] * k, 1.0)
            fused.append(chunk)

        return fused

    # ------------------------------------------------------------------
    # Step 3: Cross-encoder reranking
    # ------------------------------------------------------------------

    async def _rerank(self, query: str, chunks: list[RankedChunk]) -> list[RankedChunk]:
        """
        Score each chunk with a cross-encoder and sort descending.
        Runs the model in a ThreadPoolExecutor to avoid blocking the event loop.
        """
        if not chunks:
            return chunks

        try:
            model = await self._load_cross_encoder()
            if model is None:
                # Fallback: use retrieval_score as reranker_score
                for chunk in chunks:
                    chunk.reranker_score = chunk.retrieval_score
                    chunk.combined_score = chunk.retrieval_score
                return sorted(chunks, key=lambda c: c.combined_score, reverse=True)

            pairs = [(query, chunk.content) for chunk in chunks]

            loop = asyncio.get_event_loop()
            scores: list[float] = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: model.predict(pairs).tolist(),
            )

            # Normalize via sigmoid so scores land in (0, 1)
            import math
            def _sigmoid(x: float) -> float:
                return 1.0 / (1.0 + math.exp(-x))

            for chunk, raw_score in zip(chunks, scores):
                chunk.reranker_score = _sigmoid(float(raw_score))

            # Step 5 (inline): compute combined_score now that we have reranker scores
            coverage = self._coverage_score(chunks[:3], query)
            for chunk in chunks:
                chunk.combined_score = (
                    0.4 * chunk.retrieval_score
                    + 0.4 * chunk.reranker_score
                    + 0.2 * coverage
                )

            return sorted(chunks, key=lambda c: c.combined_score, reverse=True)

        except Exception as exc:
            logger.warning("rag_rerank_failed", error=str(exc), exc_info=exc)
            for chunk in chunks:
                chunk.reranker_score = chunk.retrieval_score
                chunk.combined_score = chunk.retrieval_score
            return chunks

    # ------------------------------------------------------------------
    # Step 5: Confidence scoring
    # ------------------------------------------------------------------

    def _compute_confidence(self, chunks: list[RankedChunk], query: str) -> float:
        """
        combined_score = 0.4 * avg_retrieval + 0.4 * avg_reranker + 0.2 * coverage_score
        coverage_score = fraction of query terms found in top-3 chunks.
        """
        if not chunks:
            return 0.0

        top3 = chunks[:3]
        avg_retrieval = sum(c.retrieval_score for c in top3) / len(top3)
        avg_reranker = sum(c.reranker_score for c in top3) / len(top3)
        coverage = self._coverage_score(top3, query)

        return min(1.0, 0.4 * avg_retrieval + 0.4 * avg_reranker + 0.2 * coverage)

    def _coverage_score(self, chunks: list[RankedChunk], query: str) -> float:
        """Fraction of unique query terms found in the given chunks."""
        if not chunks or not query:
            return 0.0
        query_terms = set(self._tokenize(query))
        if not query_terms:
            return 0.0
        combined_text = " ".join(c.content.lower() for c in chunks)
        found = sum(1 for t in query_terms if t in combined_text)
        return found / len(query_terms)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple whitespace + punctuation tokenizer for BM25."""
        return re.sub(r"[^\w\s]", " ", text.lower()).split()

    async def _embed(self, text: str) -> list[float]:
        """Generate a dense embedding, preferring OpenAI when configured."""
        from app.core.config import settings

        if getattr(settings, "OPENAI_API_KEY", None):
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    json={"model": settings.EMBEDDING_MODEL, "input": text},
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]

        # Fallback: sentence-transformers local model
        model = await self._load_embedding_model()
        if model is not None:
            loop = asyncio.get_event_loop()
            vector = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: model.encode(text, normalize_embeddings=True).tolist(),
            )
            return vector

        # Last resort: hash-based pseudo-embedding (dev only)
        import hashlib
        dim = getattr(settings, "EMBEDDING_DIMENSION", 384)
        digest = hashlib.sha256(text.encode()).digest()
        seed = int.from_bytes(digest[:8], "big")
        values: list[float] = []
        for _ in range(dim):
            seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            values.append((seed / 0xFFFFFFFFFFFFFFFF) * 2 - 1)
        norm = sum(v ** 2 for v in values) ** 0.5 or 1.0
        return [v / norm for v in values]

    async def _load_embedding_model(self):
        """Lazy-load sentence-transformer embedding model."""
        if self._embedding_model is not None:
            return self._embedding_model
        try:
            from sentence_transformers import SentenceTransformer
            loop = asyncio.get_event_loop()
            self._embedding_model = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: SentenceTransformer(self._embedding_model_name),
            )
            return self._embedding_model
        except Exception as exc:
            logger.warning("rag_embedding_model_load_failed", error=str(exc))
            return None

    async def _load_cross_encoder(self):
        """Lazy-load cross-encoder model for reranking."""
        if self._cross_encoder is not None:
            return self._cross_encoder
        try:
            from sentence_transformers import CrossEncoder
            loop = asyncio.get_event_loop()
            self._cross_encoder = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2"),
            )
            return self._cross_encoder
        except Exception as exc:
            logger.warning("rag_cross_encoder_load_failed", error=str(exc))
            return None


# ---------------------------------------------------------------------------
# BatchIndexingWorker
# ---------------------------------------------------------------------------

class BatchIndexingWorker:
    """
    Asynchronous document indexing worker that:
    1. Splits text into overlapping chunks
    2. Embeds each chunk with sentence-transformers
    3. Upserts chunks into Qdrant
    Indexing is fire-and-forget (asyncio background task).
    """

    def __init__(self, qdrant_client, rag_service: RAGService) -> None:
        self.qdrant = qdrant_client
        self.rag = rag_service

    async def index_document(
        self,
        doc_id: str,
        content: str,
        tenant_id: str,
        kb_id: str,
        chunk_size: int = 512,
        overlap: int = 50,
    ) -> None:
        """
        Start background indexing — returns immediately, indexes in background task.
        """
        asyncio.create_task(
            self._do_index(doc_id, content, tenant_id, kb_id, chunk_size, overlap),
            name=f"index_doc:{doc_id}",
        )

    async def _do_index(
        self,
        doc_id: str,
        content: str,
        tenant_id: str,
        kb_id: str,
        chunk_size: int,
        overlap: int,
    ) -> None:
        """Internal coroutine that performs the actual chunking + embedding + upsert."""
        log = logger.bind(doc_id=doc_id, tenant_id=tenant_id, kb_id=kb_id)
        try:
            chunks = self._chunk_text(content, chunk_size, overlap)
            log.info("batch_indexing_started", total_chunks=len(chunks))

            from app.core.config import settings
            collection_name = f"{settings.QDRANT_COLLECTION_PREFIX}{tenant_id.replace('-', '_')}"

            points: list = []
            for i, chunk_text in enumerate(chunks):
                vector = await self.rag._embed(chunk_text)

                if not points:
                    # Ensure collection exists with correct dimensionality
                    await self._ensure_collection(collection_name, len(vector))

                from qdrant_client.models import PointStruct
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{i}"))
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "doc_id": doc_id,
                            "kb_id": kb_id,
                            "tenant_id": tenant_id,
                            "content": chunk_text,
                            "chunk_index": i,
                            "title": "",
                            "content_type": "text",
                        },
                    )
                )

            if points:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    _THREAD_POOL,
                    lambda: self.qdrant.upsert(
                        collection_name=collection_name,
                        points=points,
                    ),
                )
                # Invalidate BM25 index so it's rebuilt fresh on next query
                self.rag.invalidate_bm25_index(tenant_id, kb_id)
                log.info("batch_indexing_complete", points_upserted=len(points))

        except Exception as exc:
            log.error("batch_indexing_failed", error=str(exc), exc_info=exc)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        """
        Split text into overlapping word-boundary chunks.
        Uses word-level splits to avoid breaking tokens mid-word.
        """
        words = text.split()
        if not words:
            return []

        chunks: list[str] = []
        step = max(1, chunk_size - overlap)
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunks.append(" ".join(words[start:end]))
            if end == len(words):
                break
            start += step
        return chunks

    async def _ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """Create the Qdrant collection if it doesn't already exist."""
        try:
            from qdrant_client.models import Distance, VectorParams
            loop = asyncio.get_event_loop()
            collections = await loop.run_in_executor(
                _THREAD_POOL,
                lambda: self.qdrant.get_collections(),
            )
            existing = {c.name for c in collections.collections}
            if collection_name not in existing:
                await loop.run_in_executor(
                    _THREAD_POOL,
                    lambda: self.qdrant.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=vector_size,
                            distance=Distance.COSINE,
                        ),
                    ),
                )
                logger.info("batch_indexing_collection_created", collection=collection_name)
        except Exception as exc:
            logger.warning(
                "batch_indexing_ensure_collection_failed",
                collection=collection_name,
                error=str(exc),
            )
