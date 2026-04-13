"""
db_connector.py — 내부 DB 파일 파서.

지원 형식: CSV, JSON, JSONL, TXT, MD
각 파일을 레코드 단위로 파싱해 텍스트 청크 리스트를 반환합니다.
"""

import csv
import json
import io
from pathlib import Path
from typing import Any


def parse_file(filename: str, content: bytes) -> list[str]:
    """파일 내용을 텍스트 청크 리스트로 변환."""
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".csv":
            return _parse_csv(content)
        elif ext in (".json",):
            return _parse_json(content)
        elif ext == ".jsonl":
            return _parse_jsonl(content)
        elif ext in (".txt", ".md"):
            return _parse_text(content)
        else:
            # 알 수 없는 형식은 텍스트로 처리
            return _parse_text(content)
    except Exception:
        # 파싱 실패 시 raw text로 폴백
        return _parse_text(content)


def _parse_csv(content: bytes) -> list[str]:
    """CSV → 각 행을 'key: value, key: value ...' 형태의 문자열로 변환."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    chunks: list[str] = []
    for row in reader:
        parts = [f"{k}: {v}" for k, v in row.items() if v and str(v).strip()]
        if parts:
            chunks.append(" | ".join(parts))
    return chunks


def _parse_json(content: bytes) -> list[str]:
    """JSON → 배열이면 각 원소, 객체면 단일 청크."""
    text = content.decode("utf-8", errors="replace")
    data = json.loads(text)
    if isinstance(data, list):
        return [_flatten(item) for item in data]
    else:
        return [_flatten(data)]


def _parse_jsonl(content: bytes) -> list[str]:
    """JSONL → 각 줄을 청크로."""
    chunks: list[str] = []
    for line in content.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chunks.append(_flatten(json.loads(line)))
        except json.JSONDecodeError:
            chunks.append(line)
    return chunks


def _parse_text(content: bytes) -> list[str]:
    """TXT/MD → 빈 줄 기준으로 단락 분리."""
    text = content.decode("utf-8", errors="replace")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paragraphs if paragraphs else [text.strip()]


def _flatten(obj: Any, prefix: str = "") -> str:
    """중첩 dict/list를 평탄화해 읽기 쉬운 문자열로 변환."""
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            parts.append(_flatten(v, key))
        return " | ".join(p for p in parts if p)
    elif isinstance(obj, list):
        items = [_flatten(item, prefix) for item in obj[:20]]  # 최대 20개
        return f"{prefix}: [{', '.join(i for i in items if i)}]" if prefix else ", ".join(items)
    else:
        val = str(obj).strip()
        if not val or val == "None":
            return ""
        return f"{prefix}: {val}" if prefix else val
