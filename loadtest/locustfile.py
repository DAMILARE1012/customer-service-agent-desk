"""Baton under load — realistic users against the API under test (npm run loadtest:api).

    Visitor          opens the chat widget, asks one to three help-centre questions, keeps the chat open
                     (polling every 4 s like the widget), then leaves; the next visitor arrives
    WaitingCustomer  asks for a person, adds details while waiting, stays until an agent replies or gives
                     up after LOADTEST_MAX_WAIT_S
    Agent            signs in (Keycloak), watches the queue every 4 s, accepts handoffs up to their
                     capacity, replies and resolves — a fixed number of them (LOADTEST_AGENT_USERS)

Run it (see loadtest/README.md):  npm run loadtest            → web UI on http://localhost:8089
                                  npm run loadtest:ci         → headless, fails if a threshold is missed

When the test stops, the thresholds below are checked and the process exits 1 if any is missed, so the
headless run can gate a CI job. Requests are grouped by what they mean ("widget: poll", "desk: accept"…).
"""

import itertools
import os
import random
import sys
import time
from pathlib import Path

from locust import HttpUser, constant_pacing, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_vault  # noqa: E402

KEYCLOAK = local_vault.setting("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
REALM = local_vault.setting("KEYCLOAK_REALM", "baton")
AGENTS = os.environ.get("LOADTEST_AGENTS", "alex.rivera,priya.shah,jade.kim").split(",")
MAX_WAIT_S = float(os.environ.get("LOADTEST_MAX_WAIT_S", "180"))

# Thresholds checked at the end (override with environment variables).
MAX_FAILURE_RATIO = float(os.environ.get("LOADTEST_MAX_FAILURE_RATIO", "0.01"))
P95_LIMITS_MS = {
    "widget: poll": float(os.environ.get("LOADTEST_P95_POLL_MS", "1000")),
    "desk: queue": float(os.environ.get("LOADTEST_P95_QUEUE_MS", "1500")),
    "widget: ask (bot answers)": float(os.environ.get("LOADTEST_P95_ANSWER_MS", "15000")),
}

QUESTIONS = [
    "How do I connect a domain I bought elsewhere to my site?",
    "How long does a refund take to show up?",
    "How do I change my site's template?",
    "How can I add a contact form to my website?",
    "How do I cancel my premium plan?",
    "Can I transfer my site to another account?",
    "How do I set up a custom email address?",
    "Why isn't my site showing up on Google?",
    "How do I add products to my online store?",
    "How do I change the currency in my store?",
]
FOLLOW_UPS = ["Thanks — and how long does that take?", "Is there a fee for that?", "Where do I find that setting?", "Does that work on mobile too?"]
ASK_FOR_PERSON = ["Can I talk to a real person please?", "I'd like to speak to someone from your team.", "Can a human help me with this?"]
DETAILS = ["My order number is #A10293.", "It happened yesterday evening.", "I was charged $49.00 twice.", "I'm using the mobile app."]


class Customer(HttpUser):
    """A widget session: a fresh anonymous visitor each time."""

    abstract = True
    wait_time = constant_pacing(4)  # the widget polls every 4 s

    def begin(self) -> None:
        token = self.client.post("/widget/session", json={}, name="widget: new session").json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.conversation = self.client.post("/me/conversations", json={}, headers=self.headers, name="widget: start chat").json()["id"]

    def say(self, text: str, name: str) -> dict | None:
        with self.client.post(f"/me/conversations/{self.conversation}/messages", json={"text": text}, headers=self.headers,
                              name=name, catch_response=True) as response:  # fmt: skip
            if response.status_code == 409:  # the chat closed meanwhile (an agent resolved it): not an error
                response.success()
                return None
            return response.json() if response.ok else None

    def poll(self, name: str = "widget: poll") -> dict | None:
        response = self.client.get(f"/me/conversations/{self.conversation}", headers=self.headers, name=name)
        return response.json() if response.ok else None

    def leave(self) -> None:
        with self.client.post(f"/me/conversations/{self.conversation}/end", headers=self.headers, name="widget: end chat",
                              catch_response=True) as response:  # fmt: skip
            if response.status_code == 409:  # already closed
                response.success()


class Visitor(Customer):
    weight = 8

    def on_start(self) -> None:
        self.begin()
        self.questions_left = random.randint(1, 3)
        self.polls_left = 0
        self.asked_any = False

    @task
    def step(self) -> None:
        if self.polls_left > 0:  # reading the answer, chat still open
            self.polls_left -= 1
            self.poll()
            return
        if self.questions_left == 0:  # done: this visitor leaves, a new one arrives
            self.leave()
            self.on_start()
            return
        self.say(random.choice(FOLLOW_UPS + QUESTIONS) if self.asked_any else random.choice(QUESTIONS), "widget: ask (bot answers)")
        self.asked_any = True
        self.questions_left -= 1
        self.polls_left = random.randint(2, 6)


class WaitingCustomer(Customer):
    weight = 2

    def on_start(self) -> None:
        self.begin()
        self.say(random.choice(ASK_FOR_PERSON), "widget: ask for a person")
        self.since = time.monotonic()
        self.details_left = random.randint(0, 2)
        self.helped_polls = None

    @task
    def step(self) -> None:
        if self.details_left and random.random() < 0.3:
            self.details_left -= 1
            self.say(random.choice(DETAILS), "widget: add detail while waiting")
            return
        conversation = self.poll("widget: poll")
        if not conversation:
            return
        if conversation["status"] == "resolved":  # helped: next customer
            self.on_start()
            return
        if any(m["sender"] == "agent" for m in conversation["messages"]):
            self.helped_polls = (self.helped_polls or 0) + 1  # read the reply for a couple of polls
            if self.helped_polls > 2:
                self.leave()
                self.on_start()
            return
        if time.monotonic() - self.since > MAX_WAIT_S:  # gave up waiting
            self.leave()
            self.on_start()


class Agent(HttpUser):
    fixed_count = int(os.environ.get("LOADTEST_AGENT_USERS", "3"))
    wait_time = constant_pacing(4)  # the desk polls the queue every 4 s
    identities = itertools.cycle(AGENTS)

    def on_start(self) -> None:
        self.username = next(Agent.identities)
        self.password = os.environ.get("LOADTEST_AGENT_PASSWORD") or local_vault.read("keycloak")["BATON_DEMO_PASSWORD"]
        self.sign_in()
        me = self.client.get("/me", headers=self.headers, name="desk: me").json()["agent"]
        self.agent_id, self.capacity = me["id"], me["capacity"]
        self.replied: set[str] = set()

    def sign_in(self) -> None:
        response = self.client.post(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token", name="keycloak: agent sign-in", data={
            "grant_type": "password", "client_id": "baton-loadtest", "username": self.username, "password": self.password,
        })  # fmt: skip
        if response.status_code != 200:
            raise SystemExit("Agent sign-in failed — run `npm run loadtest:setup` first (adds the baton-loadtest Keycloak client).")
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        self.signed_in_at = time.monotonic()

    @task
    def work_the_queue(self) -> None:
        if time.monotonic() - self.signed_in_at > 240:  # access tokens last 5 minutes
            self.sign_in()
        queue = self.client.get("/conversations", headers=self.headers, name="desk: queue").json()
        mine = [c for c in queue if c["status"] == "agent_active" and (c.get("assignee") or {}).get("id") == self.agent_id]
        for conversation in mine[:1]:  # one action per poll, like a person
            cid = conversation["id"]
            if cid not in self.replied:
                self.client.post(f"/conversations/{cid}/agent-messages", json={"text": "Thanks for waiting — I can help with that. Here's what to do next."},
                                 headers=self.headers, name="desk: reply")  # fmt: skip
                self.replied.add(cid)
            else:
                self.client.post(f"/conversations/{cid}/resolve", headers=self.headers, name="desk: resolve")
                self.replied.discard(cid)
            return
        if len(mine) >= self.capacity:
            return
        rank = {"urgent": 0, "high": 1, "normal": 2}
        waiting = sorted((c for c in queue if c["status"] == "handoff_pending"), key=lambda c: (rank.get(c["handoff"]["priority"], 3), c["handoff"]["requestedAt"]))
        if waiting:
            with self.client.post(f"/conversations/{waiting[0]['id']}/handoff/accept", headers=self.headers, name="desk: accept",
                                  catch_response=True) as response:  # fmt: skip
                if response.status_code == 409:  # another agent got there first, or at capacity: normal on a busy desk
                    response.success()


@events.quitting.add_listener
def check_thresholds(environment, **_) -> None:
    stats = environment.stats
    problems = []
    if stats.total.num_requests and stats.total.fail_ratio > MAX_FAILURE_RATIO:
        problems.append(f"failure ratio {stats.total.fail_ratio:.2%} > {MAX_FAILURE_RATIO:.2%}")
    for name, limit in P95_LIMITS_MS.items():
        entry = next((e for (n, _m), e in stats.entries.items() if n == name), None)
        if entry and entry.num_requests:
            p95 = entry.get_response_time_percentile(0.95)
            status = "ok" if p95 <= limit else "MISSED"
            print(f"  {status:6} {name}: p95 {p95:.0f} ms (limit {limit:.0f} ms) over {entry.num_requests} requests")
            if p95 > limit:
                problems.append(f"{name} p95 {p95:.0f} ms > {limit:.0f} ms")
    print(f"  total: {stats.total.num_requests} requests, {stats.total.fail_ratio:.2%} failed, {stats.total.total_rps:.1f} req/s")
    if problems:
        print("Thresholds missed: " + "; ".join(problems))
        environment.process_exit_code = 1
    else:
        print("All thresholds met.")
