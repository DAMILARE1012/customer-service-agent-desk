"""Start the API under load test: http://127.0.0.1:8799 against its own database (baton_load), the fake
LLM (npm run loadtest:llm), no Langfuse traces, no emails, and the widget's rate limits lifted so one
machine can play hundreds of customers. Your normal API on :8787 and its data are untouched.

    npm run loadtest:api                           # one process, from source
    npm run loadtest:api -- --docker --workers 4   # the Linux container with 4 processes — measure scaling here
    npm run loadtest:api -- --docker --down        # stop the container

Several processes: use --docker. On Windows, uvicorn's worker processes can't reliably share the listening
socket (WinError 10022): workers die and restart, and the numbers mean nothing.

Secrets come from the local Vault; nothing is read from .env except plain settings.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_vault  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "baton_load"


def ensure_database(password: str) -> None:
    host, port = "127.0.0.1", local_vault.setting("BATON_DB_PORT", "5433")
    with psycopg.connect(host=host, port=port, user="baton", password=password, dbname="postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone():
            conn.execute(f'CREATE DATABASE "{DATABASE}"')
            print(f"created database {DATABASE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--workers", type=int, default=1, help="API processes (default 1)")
    parser.add_argument("--llm", default="http://127.0.0.1:8798", help="the fake LLM (npm run loadtest:llm)")
    parser.add_argument("--docker", action="store_true", help="run the API image (and the fake LLM) in Docker instead")
    parser.add_argument("--down", action="store_true", help="with --docker: stop the containers")
    args = parser.parse_args()
    compose = ["docker", "compose", "-f", str(ROOT / "loadtest/docker-compose.yml")]
    if args.docker and args.down:
        sys.exit(subprocess.call([*compose, "down"]))

    db_password = local_vault.read("database")["BATON_DB_PASSWORD"]
    api_secrets = local_vault.read("api")
    ensure_database(db_password)
    if args.docker:
        env = {**os.environ, "LOADTEST_WORKERS": str(args.workers), "LOADTEST_DB_PASSWORD": db_password,
               "LOADTEST_WIDGET_SIGNING_SECRET": api_secrets["WIDGET_SIGNING_SECRET"],
               "LOADTEST_WIDGET_IDENTITY_SECRET": api_secrets["WIDGET_IDENTITY_SECRET"]}  # fmt: skip
        print(f"API under test in Docker on http://127.0.0.1:8799 · {args.workers} process(es) · fake LLM on :8798 (stop the local one first)")
        sys.exit(subprocess.call([*compose, "up", "-d", "--force-recreate"], env=env))
    env = {
        **os.environ,
        "VAULT_ADDR": "",  # this process passes the few secrets it needs; no Langfuse keys → no traces
        "SERVER_PORT": str(args.port),
        "API_WORKERS": str(args.workers),
        "DATABASE_URL": f"postgresql://baton:{db_password}@127.0.0.1:{local_vault.setting('BATON_DB_PORT', '5433')}/{DATABASE}",
        "GROQ_BASE_URL": args.llm,
        "GROQ_API_KEY": "loadtest-fake-llm",
        "WIDGET_SIGNING_SECRET": api_secrets["WIDGET_SIGNING_SECRET"],
        "WIDGET_IDENTITY_SECRET": api_secrets["WIDGET_IDENTITY_SECRET"],
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
        "KEYCLOAK_ADMIN_CLIENT_SECRET": "",
        "ONLINE_EVAL_SAMPLE_RATE": "0",
        "REVIEW_INTERVAL_MINUTES": "0",  # the review pipeline would compete for CPU
        "SMTP_HOST": "",  # alerts are logged, not emailed
        "WIDGET_SESSIONS_PER_HOUR": "1000000",
        "WIDGET_MESSAGES_PER_MINUTE": "100000",
        "CORS_ORIGIN": "*",
    }
    print(f"API under test on http://127.0.0.1:{args.port} · {args.workers} process(es) · database {DATABASE} · LLM {args.llm}")
    process = subprocess.Popen([sys.executable, "-c", "from app.api.main import run; run()"], cwd=ROOT / "backend", env=env)
    try:
        sys.exit(process.wait())
    except KeyboardInterrupt:
        process.terminate()
        sys.exit(process.wait())


if __name__ == "__main__":
    main()
