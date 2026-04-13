"""Korean NER entity extraction using KoELECTRA."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from utils.logger import log

# NER tag -> knowledge graph entity type mapping
# KoELECTRA naver-ner uses: PER, ORG, LOC, DAT, TIM, NUM, EVT, ANM, PLT, MAT, TRM, CVL, FLD, AFW
NER_TYPE_MAP = {
    "PER": "Person",
    "ORG": "Organization",
    "LOC": "Location",
    "DAT": "Date",
    "TIM": "Time",
    "NUM": "Number",
    "EVT": "Event",
    "ANM": "Animal",
    "PLT": "Plant",
    "MAT": "Material",
    "TRM": "Term",       # 학술/전문 용어
    "CVL": "Title",      # 직위/직함
    "FLD": "Field",      # 학문/분야
    "AFW": "Artifact",   # 인공물/작품
    # Legacy mappings (fallback)
    "NOH": "Number",
    "POH": "Product",
}


@dataclass
class NEREntity:
    name: str
    type: str          # mapped type (Person, Organization, etc.)
    ner_tag: str       # original NER tag (PER, ORG, etc.)
    confidence: float
    source_text: str = ""  # surrounding context


class KoNERExtractor:
    """Lazy-loaded Korean NER using KoELECTRA model."""

    def __init__(self, model_name: str = "monologg/koelectra-base-v3-naver-ner"):
        self._model_name = model_name
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return
        from transformers import pipeline
        log.info("koner_loading", model=self._model_name)
        self._pipeline = pipeline(
            "ner",
            model=self._model_name,
            tokenizer=self._model_name,
            aggregation_strategy="none",
        )
        log.info("koner_loaded")

    def _merge_bio_tokens(self, tokens: list[dict], full_text: str) -> list[NEREntity]:
        """Merge BIO-tagged tokens into entities.

        KoELECTRA naver-ner uses TAG-B / TAG-I format (e.g. ORG-B, ORG-I).
        """
        entities: list[NEREntity] = []
        current_tokens: list[dict] = []
        current_tag: str = ""

        def _flush():
            nonlocal current_tokens, current_tag
            if not current_tokens:
                return
            # Merge token words
            words = []
            for t in current_tokens:
                w = t["word"]
                if w.startswith("##"):
                    words.append(w[2:])
                else:
                    words.append(w)
            name = "".join(words).strip()
            if len(name) < 2:
                current_tokens = []
                current_tag = ""
                return
            avg_score = sum(t["score"] for t in current_tokens) / len(current_tokens)
            start = current_tokens[0].get("start", 0)
            end = current_tokens[-1].get("end", start + len(name))
            mapped_type = NER_TYPE_MAP.get(current_tag, current_tag)
            entities.append(NEREntity(
                name=name,
                type=mapped_type,
                ner_tag=current_tag,
                confidence=float(avg_score),
                source_text=full_text[max(0, start - 30):end + 30],
            ))
            current_tokens = []
            current_tag = ""

        for token in tokens:
            label = token.get("entity", "O")
            if label == "O":
                _flush()
                continue
            # Parse TAG-B or TAG-I format
            if "-" in label:
                parts = label.rsplit("-", 1)
                tag, bio = parts[0], parts[1]
            else:
                tag, bio = label, "B"

            if bio == "B":
                _flush()
                current_tag = tag
                current_tokens = [token]
            elif bio == "I" and tag == current_tag:
                current_tokens.append(token)
            else:
                _flush()
                current_tag = tag
                current_tokens = [token]

        _flush()
        return entities

    def extract(self, text: str) -> list[NEREntity]:
        """Extract entities from a single text."""
        self._load()
        # HuggingFace NER has a max token limit, chunk if needed
        MAX_LEN = 500  # characters per chunk for NER
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]

        raw_entities: list[NEREntity] = []
        for chunk in chunks:
            try:
                results = self._pipeline(chunk)
                # Filter out O tags
                non_o = [r for r in results if r.get("entity", "O") != "O"]
                merged = self._merge_bio_tokens(non_o, chunk)
                raw_entities.extend(merged)
            except Exception as e:
                log.warning("koner_chunk_failed", error=str(e)[:100])

        return self._deduplicate(raw_entities)

    def extract_from_chunks(self, chunks: list[str]) -> list[NEREntity]:
        """Extract from multiple text chunks, deduplicate across all."""
        all_entities: list[NEREntity] = []
        for chunk in chunks:
            all_entities.extend(self.extract(chunk))
        return self._deduplicate(all_entities)

    def _deduplicate(self, entities: list[NEREntity]) -> list[NEREntity]:
        """Deduplicate by name+type, keeping highest confidence."""
        best: dict[tuple[str, str], NEREntity] = {}
        for e in entities:
            key = (e.name.lower().strip(), e.type)
            if key not in best or e.confidence > best[key].confidence:
                best[key] = e
        return sorted(best.values(), key=lambda e: e.confidence, reverse=True)

    def extract_with_rules(self, text: str) -> list[NEREntity]:
        """Rule-based extraction for patterns NER might miss."""
        rules_entities: list[NEREntity] = []

        # Money patterns: $1.5B, 150억원, 2,500만 달러
        for m in re.finditer(
            r'[\$\u20a9][\d,.]+[BKMGT]?(?:\uc5b5|\ub9cc|\ucc9c)?(?:\s*(?:\uc6d0|\ub2ec\ub7ec|\uc720\ub85c|\uc5d4))?',
            text,
        ):
            rules_entities.append(NEREntity(
                name=m.group().strip(), type="Number", ner_tag="NOH",
                confidence=0.99, source_text=text[max(0, m.start() - 20):m.end() + 20],
            ))

        # Percentage: 30%, 15.5%
        for m in re.finditer(r'\d+\.?\d*\s*%', text):
            rules_entities.append(NEREntity(
                name=m.group().strip(), type="Number", ner_tag="NOH",
                confidence=0.99, source_text=text[max(0, m.start() - 20):m.end() + 20],
            ))

        # Korean law/regulation patterns: ~법, ~규제, ~협정, ~조약
        for m in re.finditer(
            r'[\uac00-\ud7a3]+(?:\ubc95|\uaddc\uc81c|\ud611\uc815|\uc870\uc57d|\uaddc\uc815|\uc9c0\uce68|\ubc95\uc548|\ubc95\ub960|\uc870\ub840)',
            text,
        ):
            name = m.group().strip()
            if len(name) >= 3:
                rules_entities.append(NEREntity(
                    name=name, type="Policy", ner_tag="POL",
                    confidence=0.95, source_text=text[max(0, m.start() - 20):m.end() + 20],
                ))

        return rules_entities


# Singleton (lazy-loaded)
koner = KoNERExtractor()
