"""Run Locust inside Docker, next to the containerized API under test (npm run loadtest:api -- --docker).

    npm run loadtest:docker -- -u 300 -r 5 -t 3m            # headless; thresholds decide the exit code
    npm run loadtest:docker -- -u 300 -t 3m --csv results/x  # CSVs land in loadtest/results/

Extra arguments go straight to Locust. The agents' password is read from the local Vault and passed in.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_vault  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

env = {**os.environ, "LOADTEST_AGENT_PASSWORD": local_vault.read("keycloak")["BATON_DEMO_PASSWORD"]}
args = sys.argv[1:] or ["-u", "150", "-r", "5", "-t", "3m"]
command = ["docker", "compose", "-f", str(ROOT / "loadtest/docker-compose.yml"), "--profile", "locust", "run", "--rm", "locust",
           "-f", "locustfile.py", "--host", "http://api:8787", "--headless", "--only-summary", *args]  # fmt: skip
sys.exit(subprocess.call(command, env=env))
