"""What the bot tells a customer when nobody is available to take their request (see app/team.py)."""


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return f"{name[0]}{'•' * max(1, min(len(name) - 1, 6))}@{domain}"


def reply_email(conversation: dict) -> str | None:
    """Where an agent's reply can reach the customer if they've left: the email they left, else the one
    their website vouched for."""
    return ((conversation.get("contact") or {}).get("email")) or (conversation["customer"].get("email") or None)


def offline_notice(team: dict, conversation: dict) -> str:
    when = f"we’re back {team['backAtText']}" if team.get("backAtText") else "everyone is away right now"
    email = mask_email(reply_email(conversation))
    follow = (
        f"We’ll email you at {email} as soon as someone replies — you don’t need to keep this chat open."
        if email
        else "Leave your email below and we’ll reply there, so you don’t need to keep this chat open."
    )
    return f"I’ve passed this to our support team, but nobody is available at the moment — {when}. {follow}"
