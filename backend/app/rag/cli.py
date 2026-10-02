"""uv run baton-search "how do I connect my domain?" [--audience customer|agent|any] [--mode rerank|hybrid|dense|keyword] [--k 5]"""

import argparse
import time

from app.console import utf8_console
from app.rag.retriever import MODES, Retriever


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description="Search the knowledge index")
    parser.add_argument("query", nargs="+")
    parser.add_argument("--audience", default="customer", choices=["customer", "agent", "any"])
    parser.add_argument("--mode", choices=MODES, help="default: rerank when RERANKER_MODEL is set, else hybrid")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    query = " ".join(args.query)

    retriever = Retriever()
    started = time.perf_counter()
    found = retriever.search(query, audience=args.audience, mode=args.mode, top_k=args.k)
    elapsed = (time.perf_counter() - started) * 1000
    print(f'\n"{query}"  ·  {args.mode or "default mode"}, {args.audience}  ·  confidence {found.confidence:.3f}  ·  {elapsed:.0f} ms over {retriever.size} chunks\n')
    for i, r in enumerate(found.results, 1):
        section = f" › {' › '.join(r['headingPath'])}" if r["headingPath"] else ""
        shared = f"  (+ same text in {len(r['alsoIn'])} other articles)" if r["alsoIn"] else ""
        rerank = f" · rerank {r['rerankScore']:.3f}" if "rerankScore" in r else ""
        print(f"{i}. [{r['similarity']:.3f} · bm25 {r['keywordScore']}{rerank}] {r['title']}{section}{shared}")
        print(f"   {r['source']} · {r['url']}")
        print(f"   {' '.join(r['text'].split())[:200]}…\n")


if __name__ == "__main__":
    main()
