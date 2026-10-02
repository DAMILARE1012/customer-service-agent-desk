"""Remove personal details from text before it leaves a conversation (review queue, test questions).

Rule-based, so it is predictable and auditable: emails, card numbers (Luhn-checked), IBANs, phone
numbers, IP addresses, order numbers, and the names we know (the customer's). It can't catch every
free-form detail — a street address typed in prose, a relative's name — which is why everything it
produces goes to a human reviewer before it is published anywhere.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
CARD_LIKE = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().-]{7,}\d(?![\w.])")
ORDER = re.compile(r"(?i)\b(order|invoice|ticket|case)(\s*(?:no\.?|number|#)?\s*)#?\s*[A-Z]{0,3}-?\d{4,}\b|#\d{4,}\b")


def _luhn(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        n = int(ch) * (2 if double else 1)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


def _card(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    return "[CARD]" if 13 <= len(digits) <= 19 and _luhn(digits) else match.group()


def _phone(match: re.Match) -> str:
    digits = len(re.sub(r"\D", "", match.group()))
    return "[PHONE]" if 9 <= digits <= 15 else match.group()  # E.164: at most 15 digits


def _order(match: re.Match) -> str:
    return f"{match.group(1)} [ORDER]" if match.group(1) else "[ORDER]"


def redact(text: str, names: list[str] | tuple[str, ...] = ()) -> str:
    if not text:
        return text
    out = EMAIL.sub("[EMAIL]", text)
    out = IBAN.sub("[IBAN]", out)
    out = CARD_LIKE.sub(_card, out)
    out = IP.sub("[IP]", out)
    out = ORDER.sub(_order, out)
    out = PHONE.sub(_phone, out)
    for name in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        out = re.sub(rf"(?i)\b{re.escape(name)}\b", "[NAME]", out)
    return out


def customer_names(conversation: dict) -> list[str]:
    """The customer's full name and its parts — the names a transcript most often contains."""
    name = (conversation.get("customer") or {}).get("name") or ""
    return [name, *name.split()]
