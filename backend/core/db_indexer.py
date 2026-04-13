"""
db_indexer.py — FAISS 기반 내부 DB RAG 인덱서.

프로젝트별 FAISS 벡터 인덱스 + 키워드 검색을 제공합니다.
시뮬레이션, 온톨로지 등에서 빠르게 검색할 수 있습니다.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from utils.logger import log


_DATA_DIR = Path(__file__).parent.parent / "data" / "databases"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class DBRecord:
    id: str
    file_name: str
    project_id: str
    text: str


class _ProjectIndex:
    """프로젝트 하나의 FAISS 인덱스 + 메타데이터."""

    def __init__(self, project_id: str, dim: int = 384):
        import faiss
        self.project_id = project_id
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)  # Inner Product (cosine sim with normalized vectors)
        self.records: list[DBRecord] = []

    def add(self, records: list[DBRecord], embeddings: np.ndarray):
        """레코드 + 임베딩 추가."""
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)
        self.records.extend(records)

    def search(self, query_emb: np.ndarray, top_k: int, threshold: float) -> list[dict]:
        """벡터 검색."""
        if self.index.ntotal == 0:
            return []
        faiss.normalize_L2(query_emb)
        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_emb, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or score < threshold:
                continue
            rec = self.records[idx]
            results.append({"text": rec.text, "score": round(float(score), 4), "file": rec.file_name})
        return results

    def rebuild(self, embeddings: np.ndarray):
        """임베딩으로 인덱스 재구축."""
        import faiss
        self.index = faiss.IndexFlatIP(self.dim)
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)


# faiss import at module level for normalize_L2
import faiss


class DBIndexer:
    """
    FAISS 기반 프로젝트별 DB RAG 인덱서.

    - add_file(): 파일 청크 임베딩 + FAISS 인덱스에 추가
    - search(): FAISS 벡터 검색
    - keyword_search(): 키워드 텍스트 매칭
    - clear_project(): 프로젝트 인덱스 초기화
    """

    _EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self):
        self._projects: dict[str, _ProjectIndex] = {}
        self._model = None
        self._dim = 384
        self._load_from_disk()

    # ── 디스크 영속성 ─────────────────────────────────────────────────────────

    def _project_path(self, project_id: str) -> Path:
        return _DATA_DIR / f"{project_id}.json"

    def _save_project(self, project_id: str):
        proj = self._projects.get(project_id)
        if not proj:
            return
        # FAISS에서 벡터 추출
        vectors = faiss.rev_swig_ptr(proj.index.get_xb(), proj.index.ntotal * self._dim)
        vectors = np.array(vectors).reshape(proj.index.ntotal, self._dim)

        data = []
        for i, rec in enumerate(proj.records):
            data.append({
                "id": rec.id,
                "file_name": rec.file_name,
                "text": rec.text,
                "embedding": vectors[i].tolist(),
            })
        self._project_path(project_id).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def _load_from_disk(self):
        total = 0
        for fp in _DATA_DIR.glob("*.json"):
            try:
                project_id = fp.stem
                data = json.loads(fp.read_text(encoding="utf-8"))
                if not data:
                    continue

                # 임베딩 차원 감지
                sample_emb = data[0].get("embedding", [])
                dim = len(sample_emb) if sample_emb else self._dim

                proj = _ProjectIndex(project_id, dim)
                records = []
                embeddings = []

                for d in data:
                    # 의미 없는 짧은 텍스트 스킵
                    if len(d.get("text", "").strip()) < 5:
                        continue
                    records.append(DBRecord(
                        id=d["id"],
                        file_name=d["file_name"],
                        project_id=project_id,
                        text=d["text"],
                    ))
                    emb = d.get("embedding", [])
                    if len(emb) != dim:
                        emb = [0.0] * dim
                    embeddings.append(emb)

                emb_array = np.array(embeddings, dtype=np.float32)
                proj.add(records, emb_array)
                self._projects[project_id] = proj
                total += len(records)
            except Exception as e:
                log.warning("db_indexer_load_failed", file=fp.name, error=str(e))
        if total:
            log.info("db_indexer_faiss_loaded", projects=len(self._projects), records=total)

    async def reembed_project(self, project_id: str) -> int:
        """프로젝트의 모든 레코드를 현재 모델로 재임베딩."""
        proj = self._projects.get(project_id)
        if not proj or not proj.records:
            return 0
        texts = [r.text for r in proj.records]
        log.info("db_indexer_reembed_start", project=project_id, records=len(texts))
        embeddings = await self._embed(texts)
        emb_array = np.array(embeddings, dtype=np.float32)
        proj.dim = emb_array.shape[1]
        self._dim = proj.dim
        proj.rebuild(emb_array)
        self._save_project(project_id)
        log.info("db_indexer_reembed_done", project=project_id, records=len(texts))
        return len(texts)

    # ── 임베딩 모델 ────────────────────────────────────────────────────────────

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._EMBED_MODEL)
            self._dim = self._model.get_sentence_embedding_dimension()
            log.info("db_indexer_model_loaded", model=self._EMBED_MODEL, dim=self._dim)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: self._model.encode(texts, show_progress_bar=False).tolist()
        )
        return embeddings

    async def _embed_one(self, text: str) -> np.ndarray:
        results = await self._embed([text])
        return np.array([results[0]], dtype=np.float32)

    # ── 인덱스 관리 ───────────────────────────────────────────────────────────

    async def add_file(
        self,
        project_id: str,
        file_name: str,
        chunks: list[str],
    ) -> int:
        """파일 청크를 임베딩해 FAISS 인덱스에 추가."""
        # 의미 없는 짧은 청크 필터링 (구분자, 빈 줄 등)
        chunks = [c for c in chunks if len(c.strip()) >= 5]
        if not chunks:
            return 0

        log.info("db_indexer_add_file", project=project_id, file=file_name, chunks=len(chunks))
        embeddings = await self._embed(chunks)
        emb_array = np.array(embeddings, dtype=np.float32)

        records = [
            DBRecord(
                id=str(uuid.uuid4()),
                file_name=file_name,
                project_id=project_id,
                text=chunk,
            )
            for chunk in chunks
        ]

        if project_id not in self._projects:
            self._projects[project_id] = _ProjectIndex(project_id, emb_array.shape[1])

        self._projects[project_id].add(records, emb_array)
        self._save_project(project_id)
        log.info("db_indexer_indexed", project=project_id, total=self._projects[project_id].index.ntotal)
        return len(records)

    def clear_project(self, project_id: str):
        self._projects.pop(project_id, None)
        fp = self._project_path(project_id)
        if fp.exists():
            fp.unlink()
        log.info("db_indexer_cleared", project=project_id)

    def list_files(self, project_id: str) -> list[str]:
        proj = self._projects.get(project_id)
        if not proj:
            return []
        return list(dict.fromkeys(r.file_name for r in proj.records))

    def record_count(self, project_id: str) -> int:
        proj = self._projects.get(project_id)
        return proj.index.ntotal if proj else 0

    # ── 검색 ──────────────────────────────────────────────────────────────────

    async def search(
        self,
        project_id: str,
        query: str,
        top_k: int = 5,
        threshold: float = 0.05,
    ) -> list[dict]:
        """FAISS 벡터 검색."""
        proj = self._projects.get(project_id)
        if not proj or proj.index.ntotal == 0:
            return []

        query_emb = await self._embed_one(query)
        return proj.search(query_emb, top_k, threshold)

    def keyword_search(
        self,
        project_id: str,
        keywords: list[str],
        top_k: int = 10,
    ) -> list[dict]:
        """키워드 기반 텍스트 + 파일명 매칭 검색."""
        proj = self._projects.get(project_id)
        if not proj or not keywords:
            return []

        scored: list[tuple[float, DBRecord]] = []
        for rec in proj.records:
            text_lower = rec.text.lower()
            fname_lower = rec.file_name.lower()
            # 텍스트 매칭
            text_hits = sum(1 for kw in keywords if kw.lower() in text_lower)
            # 파일명 매칭 (가중치 2배)
            fname_hits = sum(2 for kw in keywords if kw.lower() in fname_lower)
            total = text_hits + fname_hits
            if total > 0:
                scored.append((total, rec))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen_texts = set()
        results = []
        for hits, rec in scored[:top_k]:
            if rec.text not in seen_texts:
                seen_texts.add(rec.text)
                results.append({"text": rec.text, "score": hits / len(keywords), "file": rec.file_name})
        return results

    def file_search(
        self,
        project_id: str,
        keywords: list[str],
        top_k: int = 20,
    ) -> list[dict]:
        """파일명에 키워드가 포함된 파일의 레코드를 반환."""
        proj = self._projects.get(project_id)
        if not proj or not keywords:
            return []

        # 키워드가 파일명에 매칭되는 파일 찾기
        matched_files: set[str] = set()
        for rec in proj.records:
            fname_lower = rec.file_name.lower()
            if any(kw.lower() in fname_lower for kw in keywords):
                matched_files.add(rec.file_name)

        if not matched_files:
            return []

        # 매칭된 파일의 레코드 반환
        results = []
        for rec in proj.records:
            if rec.file_name in matched_files:
                results.append({"text": rec.text, "score": 1.0, "file": rec.file_name})
                if len(results) >= top_k:
                    break
        return results


# 싱글턴
db_indexer = DBIndexer()
