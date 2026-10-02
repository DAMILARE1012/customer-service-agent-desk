"""Evaluation data: WixQA question sets (with expert answers and the articles needed) and a small
hand-written set of off-topic questions."""

import json

from app.config import settings
from app.ingest.remote_file import sync_remote_file

BASE = "https://huggingface.co/datasets/Wix/WixQA/resolve/main"
QUESTION_SETS = {
    "expert": "wixqa_expertwritten/test.jsonl",  # 200 real support tickets, answers written by Wix experts
    "simulated": "wixqa_simulated/test.jsonl",  # 200 questions distilled from real support chats
}

# Questions the help centre cannot answer: they show how high similarity gets when nothing relevant
# exists. A small set — treat thresholds derived from it as estimates and add real out-of-scope
# questions from your chat logs to sharpen them.
OFF_TOPIC_QUESTIONS = [
    "What's the weather forecast for Lagos this weekend?", "Can you recommend a good recipe for jollof rice?",
    "How do I file my annual income tax return?", "What are the early symptoms of the flu?",
    "Who won the Champions League final last year?", "How do I change the oil in my car?",
    "What's the fastest way to learn Spanish?", "Can you help me plan a two-week trip to Japan?",
    "How many calories are in an avocado?", "How do I unclog a kitchen sink?",
    "Is it safe to take ibuprofen with coffee?", "How do I stop my puppy from biting?",
    "What vegetables should I plant in spring?", "Can you write a short poem about the ocean?",
    "How long should I boil an egg for a runny yolk?", "What is the capital of Australia?",
    "How do I fix a flat bicycle tire?", "Which laptop is best for video editing?",
    "How do I apply for a passport renewal?", "What's a good workout routine for beginners?",
    "How do I remove a red wine stain from carpet?", "When is the next solar eclipse visible from Europe?",
    "How do I negotiate a higher salary?", "What's the difference between a crocodile and an alligator?",
    "My washing machine is leaking water, what should I do?", "Can I bring a power bank in my checked luggage?",
    "How do I start investing in index funds?", "What's the best time of year to visit Paris?",
    "How do I make a sourdough starter?", "Why is the sky blue?",
    "How do I get rid of ants in my kitchen?", "Which vaccines does a six-month-old baby need?",
    "How do I jump-start a car battery?", "Which phone has the best camera right now?",
    "How can I improve my personal credit score?", "What's a healthy breakfast for school kids?",
    "How do I cancel my gym membership contract?", 'Can you translate "good morning" into Yoruba?',
    "How much should I tip at a restaurant in the US?", "What causes a headache behind the eyes?",
]  # fmt: skip


def load_questions(name: str) -> list[dict]:
    """[{question, answer, articleIds}] — downloaded once, then reused (delete the file to refetch)."""
    if name not in QUESTION_SETS:
        raise ValueError(f'Unknown question set "{name}". Use: {", ".join(QUESTION_SETS)}')
    dest = settings.raw_path / "wixqa" / "eval" / f"{QUESTION_SETS[name].split('/')[0]}.jsonl"
    if not dest.exists():
        sync_remote_file(f"{BASE}/{QUESTION_SETS[name]}", dest)
    rows = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"question": r["question"], "answer": r["answer"], "articleIds": r["article_ids"]} for r in rows]
