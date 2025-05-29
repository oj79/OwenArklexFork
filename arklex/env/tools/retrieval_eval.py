import argparse
import json
import logging
import os
from typing import Any, Dict, List, Tuple

from arklex.utils.graph_state import LLMConfig
from arklex.utils.model_config import MODEL
from arklex.env.tools.RAG.retrievers.faiss_retriever import FaissRetrieverExecutor
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

def _dot(u: List[float], v: List[float]) -> float:
    return sum(a * b for a, b in zip(u, v))


def _rerank(
        query: str,
        docs_scores: List[Tuple[Any, float]],
        retriever: FaissRetrieverExecutor,
        model: str = "",
) -> List[Tuple[Any, float]]:
    """Optionally re-rank the documents based on a cross-encoder or embedding similarity"""
    try:
        if model:
            from sentence_transformers import CrossEncoder

            cross = CrossEncoder(model)
            pairs = [[query, doc.page_content] for doc, _ in docs_scores]
            scores = cross.predict(pairs)
            scored = list(zip(docs_scores, scores))
            scored.sort(key = lambda x: x[1], reverse = True)
            return [ds for ds, _ in scored]
    except Exception as err:
        logger.warning("Cross encoder re-rank failed: %s", err)

    # Fallback to embedding similarity
    q_emb = retriever.embedding_model.embed_query(query)
    doc_embs = retriever.embedding_model.embed_documents(
        [doc.page_content for doc, _ in docs_scores]
    )
    sims = [_dot(q_emb, de) for de in doc_embs]
    scored = list(zip(docs_scores, sims))
    scored.sort(key = lambda x: x[1], reverse = True)
    return [ds for ds, _ in scored]


def evaluate_query(
        query: str,
        relevant: List[str],
        retriever: FaissRetrieverExecutor,
        k: int,
        rerank_model: str = "",
) -> Tuple[float, float]:
    docs_scores = retriever.retrieve_w_score(query)
    if rerank_model is not None:
        docs_scores =_rerank(query, docs_scores, retriever, rerank_model)
    top = [doc.metadata.get("source") or doc.metadata.get("title") for doc, _ in docs_scores[:k]]
    hits = sum(1 for doc in top if doc in relevant)
    precision = hits / k if k else 0.0
    recall = hits / len(relevant) if relevant else 0.0
    return precision, recall


def evaluate(index_dir: str, gt_file: str, k: int, rerank_model: str = "") -> None:
    llm_cfg = LLMConfig(
        model_type_or_path=MODEL["model_type_or_path"],
        llm_provider=MODEL["llm_provider"],
    )
    retriever = FaissRetrieverExecutor.load_docs(index_dir, llm_cfg)
    data = json.load(open(gt_file))
    precisions: List[float] = []
    recalls: List[float] = []

    for item in data:
        q = item["query"]
        rel = item.get("relevant", [])
        p, r = evaluate_query(q, rel, retriever, k, rerank_model)
        precisions.append(p)
        recalls.append(r)
        print(f"Query: {q}\n Precision@{k}: {p:.3f} Recall@{k}: {r:.3f}\n")

    if precisions:
        avg_p = sum(precisions) / len(precisions)
        avg_r = sum(recalls) / len(recalls)
        print(f"Average Precision@{k}: {avg_p:.3f}")
        print(f"Average Recall@{k}: {avg_r:.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
    parser.add_argument("--index-dir", required=True, help="Path to FAISS data dir")
    parser.add_argument(
        "--ground-truth",
        required=True,
        help="JSON file with queries and relevant document sources",
    )
    parser.add_argument("--k", type=int, default=5, help="Top k docs to evaluate")
    parser.add_argument(
        "--rerank-model",
        type=str,
        default="",
        help="Optional sentence transformers cross encoder model for reranking",
    )
    args = parser.parse_args()
    evaluate(args.index_dir, args.ground_truth, args.k, args.rerank_model)