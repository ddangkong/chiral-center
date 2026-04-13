from sentence_transformers import SentenceTransformer
import numpy as np

class Embedder:
    _model = None

    @classmethod
    def get_model(cls, model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
        if cls._model is None:
            cls._model = SentenceTransformer(model_name)
        return cls._model

    @classmethod
    def embed(cls, texts: list[str], model_name: str = "all-MiniLM-L6-v2") -> list[list[float]]:
        """Embed a list of texts into vectors."""
        model = cls.get_model(model_name)
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    @classmethod
    def embed_single(cls, text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
        """Embed a single text."""
        return cls.embed([text], model_name)[0]
