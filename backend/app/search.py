"""
Catalog search.

Working today: BM25 keyword search (rank_bm25) over product name,
category, and description. No external models or network access needed,
so this runs anywhere.

Upgrade path: swap this module's implementation for semantic search
without changing the API contract (search(db, query, top_k) -> list of
(Product, score)). The intended production version:

    from llama_index.core import VectorStoreIndex, Document
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-m3")
    documents = [Document(text=f"{p.name} {p.category} {p.description}",
                           metadata={"product_id": p.id}) for p in products]
    index = VectorStoreIndex.from_documents(documents, embed_model=embed_model)
    # persist `index` to a vector store (pgvector, etc.) instead of rebuilding
    # in memory on every request, then query it for semantic matches.

That needs BAAI/bge-m3's weights, which also live on huggingface.co and
were not reachable from this build environment for the same reason noted
in ingestion.py. BM25 is a reasonable stand-in in the meantime: it won't
catch synonyms or paraphrases the way an embedding model would, but it
will correctly find products by name, SKU fragments, and category terms,
which covers most of what a distributor's team searches for a catalog by.
"""
import re
from typing import List, Tuple

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from . import models

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def search(db: Session, query: str, top_k: int = 10) -> List[Tuple[models.Product, float]]:
    products = db.query(models.Product).all()
    if not products:
        return []

    corpus = [
        _tokenize(f"{p.sku} {p.name} {p.category or ''} {p.description or ''}")
        for p in products
    ]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(zip(products, scores), key=lambda pair: pair[1], reverse=True)
    ranked = [(p, s) for p, s in ranked if s > 0][:top_k]
    return ranked
