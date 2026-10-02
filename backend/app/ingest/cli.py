"""uv run baton-ingest [--check] [--rebuild] [--reembed] [--source a,b] [--limit N]"""

import argparse
import sys
import time

from app.config import settings
from app.console import utf8_console
from app.ingest.pipeline import run_ingestion


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description=f"Build or incrementally update the knowledge index in {settings.index_path}")
    parser.add_argument("--check", action="store_true", help="ask every source for changes now, ignoring refresh windows")
    parser.add_argument("--rebuild", action="store_true", help="re-parse every source even if unchanged (vectors still reused for identical text)")
    parser.add_argument("--reembed", action="store_true", help="discard cached vectors and embed everything again")
    parser.add_argument("--source", help="only these sources, comma-separated (others are kept as they are)")
    parser.add_argument("--limit", type=int, help="only the first N documents per source (quick experiments)")
    args = parser.parse_args()

    def log(message: str) -> None:
        print(f"{time.strftime('%H:%M:%S')}  {message}", flush=True)

    try:
        report = run_ingestion(
            check=args.check,
            rebuild=args.rebuild,
            reembed=args.reembed,
            only=[s.strip() for s in args.source.split(",")] if args.source else None,
            limit=args.limit,
            log=log,
        )
    except Exception as error:  # noqa: BLE001 — report any failure plainly and exit non-zero
        print(f"\nIngestion failed: {error}", file=sys.stderr)
        sys.exit(1)

    print("\nSources")
    for s in report["sources"]:
        d = s.get("documents")
        docs = f" · docs +{d['added']} ~{d['changed']} -{d['removed']} ={d['unchanged']}" if d else ""
        reason = f" · {s['reason']}" if s.get("reason") else ""
        print(f"  {s['source']:<8} {s['action']:<10} {s['chunks']:>6} chunks{docs}{reason}")
    if report["removedSources"]:
        print(f"  removed: {', '.join(report['removedSources'])}")
    extra = f" · resumed {report['resumed']}" if report.get("resumed") else ""
    dupes = f" · {report['duplicates']} duplicates share a vector" if report.get("duplicates") is not None else ""
    print(
        f"\nIndex    {report['total']} chunks · embedded {report['embedded']} · reused {report['reused']}{extra}{dupes} · removed {report['removedChunks']}"
        f"\n         wrote {report['wrote']} in {report['duration']:.1f}s"
    )


if __name__ == "__main__":
    main()
