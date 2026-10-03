"""The API contract with the React desk. FastAPI validates every response against these models and
publishes them as OpenAPI (GET /docs, /openapi.json). Wire format is camelCase; Python uses snake_case."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.conversation.constants import (
    BotReplyKind,
    ClosedReason,
    HandoffReason,
    HandoffStatus,
    Priority,
    Sender,
    Status,
    SystemEvent,
)


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


# ── Building blocks ──────────────────────────────────────────────────────────


class Person(Model):
    id: str
    name: str


class Customer(Person):
    email: str | None
    tier: str
    location: str
    customer_since: str
    lifetime_value: float
    order_count: int
    previous_conversations: int


class Source(Model):
    id: str
    title: str
    url: str
    category: str
    snippet: str
    score: float = Field(description="Cosine similarity of this chunk to the question")
    doc_id: str | None = None
    cited_in_message_id: str | None = None


class MessageMeta(Model):
    kind: BotReplyKind
    confidence: float | None
    sources: list[Source]
    trace_id: str | None = Field(None, description="Langfuse trace of the turn that produced this reply")


class MessageEvent(Model):
    type: SystemEvent
    reason: HandoffReason | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    closed_reason: ClosedReason | None = None


class Message(Model):
    id: str
    sender: Sender
    text: str
    created_at: int = Field(description="Epoch milliseconds")
    meta: MessageMeta | None = None
    event: MessageEvent | None = None
    author: Person | None = None


class Entity(Model):
    type: str
    label: str
    value: str
    message_id: str


class Attempt(Model):
    question_message_id: str
    reply_message_id: str | None
    question: str
    outcome: str = Field(description="answered | clarified | handed_off")
    confidence: float
    source_id: str | None
    source_title: str | None
    at: int


class Intent(Model):
    label: str
    confidence: float


class Signal(Model):
    reason: HandoffReason
    detail: str
    topic: str | None = None


class SentimentState(Model):
    current: float
    trend: list[float]


class HandoffSentiment(SentimentState):
    label: str


class TriggerMessage(Model):
    id: str
    text: str


class Procedure(Model):
    title: str
    url: str
    similarity: float


class AddedWhileWaiting(Model):
    id: str
    text: str
    at: int


class Escalation(Model):
    from_: Priority = Field(alias="from")
    to: Priority
    why: str
    at: int


class Handoff(Model):
    """The brief the agent receives: everything the bot knew when it stepped aside."""

    id: str
    status: HandoffStatus
    reason: HandoffReason
    reason_label: str
    reason_detail: str
    signals: list[Signal]
    priority: Priority
    requested_at: int
    accepted_at: int | None
    accepted_by: Person | None
    trigger_message: TriggerMessage | None
    summary: str
    intent: Intent | None
    entities: list[Entity]
    bot_attempts: list[Attempt]
    open_questions: list[str]
    sources: list[Source]
    sentiment: HandoffSentiment
    suggested_next_steps: list[str]
    procedure: Procedure | None = None
    returned_at: int | None = None
    added_while_waiting: list[AddedWhileWaiting] = []  # customer messages since the bot stepped aside
    escalated: Escalation | None = None  # priority raised by something added while waiting


class Insights(Model):
    intent: Intent | None
    last_confidence: float | None
    sentiment: SentimentState
    entities: list[Entity]
    attempts: list[Attempt]
    failed_attempts: int


class Copilot(Model):
    text: str
    based_on: str
    confidence: float
    sources: list[Source]


class SessionOutcome(Model):
    """A past support session in brief: the customer timeline and follow-up links."""

    id: str
    subject: str | None
    status: Status
    created_at: int
    closed_at: int | None
    closed_reason: ClosedReason | None
    handoff_reason: HandoffReason | None
    handoff_label: str | None
    handled_by: str | None
    bot_answers: int
    summary: str
    follow_up_of: str | None = None


class Conversation(Model):
    id: str
    customer: Customer
    status: Status
    assignee: Person | None
    subject: str | None
    created_at: int
    updated_at: int
    messages: list[Message]
    insights: Insights
    handoff: Handoff | None
    handoff_history: list[Handoff]
    copilot: Copilot | None
    closed_at: int | None = None
    closed_reason: ClosedReason | None = None
    follow_up_of: SessionOutcome | None = Field(None, description="The closed session this one follows up (agents only)")


class SummaryCustomer(Model):
    id: str
    name: str
    tier: str


class LastMessage(Model):
    sender: Sender
    text: str
    created_at: int


class SummaryHandoff(Model):
    reason: HandoffReason
    priority: Priority
    requested_at: int
    accepted_at: int | None
    added_while_waiting: int = 0
    offline: bool = Field(False, description="Arrived while nobody was available")
    reply_by_email: bool = Field(False, description="The customer can be answered by email")


class ConversationSummary(Model):
    id: str
    status: Status
    assignee: Person | None
    subject: str | None
    created_at: int
    updated_at: int
    customer: SummaryCustomer
    last_message: LastMessage | None
    handoff: SummaryHandoff | None
    sentiment: float
    last_confidence: float | None
    closed_reason: ClosedReason | None = None
    follow_up_of: str | None = None


# ── Who's signed in ──────────────────────────────────────────────────────────


class Agent(Person):
    email: str | None
    capacity: int
    active: bool
    available: bool = Field(True, description="The desk's Online / Away switch")


class Admin(Person):
    email: str | None


class User(Model):
    sub: str = Field(description="Keycloak user id")
    username: str
    name: str
    email: str | None
    roles: list[str]


class PrivacyNotice(Model):
    retention_days: int
    notice: str


class Me(Model):
    user: User
    customer: Customer | None = None
    privacy: PrivacyNotice | None = Field(None, description="Shown to customers in the chat")
    agent: Agent | None = None
    admin: Admin | None = None


# ── The customer's view (no handoff brief, scores or internal notes) ─────────


class CustomerSource(Model):
    title: str
    url: str


class CustomerAuthor(Model):
    name: str


class CustomerMessageView(Model):
    id: str
    sender: Sender
    text: str
    created_at: int
    author: CustomerAuthor | None = None
    sources: list[CustomerSource] = []


class FollowUpLink(Model):
    id: str
    subject: str | None


class Waiting(Model):
    """What a customer waiting for a person is told (see app/team.py)."""

    position: int = Field(description="1 = next in line")
    estimated_minutes: int | None = Field(None, description="Typical recent wait; None when unknown or nobody is in")
    team_available: bool
    back_at_text: str | None = Field(None, description="When the team is next in, e.g. 'Monday at 09:00 (WAT)'")
    reply_email: str | None = Field(None, description="Masked email the reply will go to if they leave")
    ask_for_email: bool


class CustomerConversation(Model):
    id: str
    status: Status
    subject: str | None
    created_at: int
    updated_at: int
    closed_at: int | None = None
    closed_reason: ClosedReason | None = None
    follow_up_of: FollowUpLink | None = None
    agent: CustomerAuthor | None
    messages: list[CustomerMessageView]
    waiting: Waiting | None = None


class CustomerConversationSummary(Model):
    id: str
    status: Status
    subject: str | None
    created_at: int
    updated_at: int
    closed_reason: ClosedReason | None = None
    last_message: LastMessage | None


# ── Admin ────────────────────────────────────────────────────────────────────


class AgentOverview(Agent):
    active_chats: int
    last_seen_at: str | None = None
    signed_in_once: bool = Field(description="Whether the Keycloak user has claimed this profile yet")


class CustomerOverview(Customer):
    conversations: int
    signed_in_once: bool
    last_seen_at: str | None = None


class EraseRequest(Model):
    confirm: str = Field(description="The customer's id, repeated to confirm an irreversible deletion")


class ErasureReport(Model):
    customer_id: str
    conversations: int
    traces: dict
    identity: dict
    complete: bool


class ReviewItem(Model):
    id: str
    kind: str = Field(description="knowledge_gap | test_question")
    status: str = Field(description="pending | approved | published | rejected")
    question: str
    answer: str
    title: str
    examples: list[str]
    agent_answers: list[str]
    conversation_ids: list[str]
    count: int
    published_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None


class ReviewUpdate(Model):
    title: str | None = Field(None, max_length=200)
    question: str | None = Field(None, max_length=2000)
    answer: str | None = Field(None, max_length=20_000)


class AuditEntry(Model):
    id: int
    at: str
    actor_id: str | None
    actor_name: str | None
    actor_role: str | None
    action: str
    conversation_id: str | None
    customer_id: str | None
    detail: dict


class AgentUpdate(Model):
    capacity: int | None = Field(None, ge=1, le=20)
    active: bool | None = None


class PolicyField(Model):
    min: float
    max: float
    integer: bool
    help: str


class Policy(Model):
    values: dict[str, int | float]
    defaults: dict[str, int | float]
    fields: dict[str, PolicyField]
    updated_at: str | None
    updated_by: str | None


# ── Requests ─────────────────────────────────────────────────────────────────


class WidgetSessionRequest(Model):
    identity: str | None = Field(None, description="Identity token signed by your website's backend for a signed-in customer")


class WidgetCustomer(Model):
    id: str
    name: str


class WidgetSession(Model):
    token: str = Field(description="Bearer token for the customer routes")
    expires_at: int = Field(description="Epoch milliseconds")
    kind: str = Field(description="visitor | identified")
    customer: WidgetCustomer


class DemoIdentityRequest(Model):
    customer_id: str


class StartConversation(Model):
    follow_up_of: str | None = Field(None, description="A closed conversation of yours that this one continues")


class CustomerMessage(Model):
    text: str = Field(min_length=1, max_length=4000)


class ContactRequest(Model):
    email: str = Field(min_length=3, max_length=254)


class AvailabilityUpdate(Model):
    available: bool


class BusinessHours(Model):
    enabled: bool = Field(description="Off = always staffed")
    timezone: str = Field(description='IANA name, e.g. "Africa/Lagos"')
    days: list[int] = Field(description="0 = Monday … 6 = Sunday")
    open: str = Field(description='"09:00"')
    close: str = Field(description='"17:00"')


class TeamStatus(Model):
    hours: BusinessHours
    open_now: bool
    agents_online: int
    available: bool
    back_at_text: str | None = None


class AgentMessage(Model):
    text: str = Field(min_length=1, max_length=4000)


class ErrorResponse(Model):
    message: str
