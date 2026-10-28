"""Database tables. SQLModel = Python classes that are also database tables.

SQLite locally, Postgres in production: only DATABASE_URL changes.
JSON-ish fields are stored as text so both databases behave the same.
"""
import json
from datetime import date, datetime
from typing import Optional

from pydantic import NaiveDatetime

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app import config

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)


class Supplier(SQLModel, table=True):
    """The MSME using PayMitra (one per deployment in the MVP)."""
    id: int = Field(default=1, primary_key=True)
    name: str
    owner_name: str
    udyam_no: str
    udyam_category: str          # Micro / Small / Medium
    activity: str                # Manufacturing / Services / Trading
    gstin: str
    opening_cash: float = 0
    payroll_amount: float = 0
    payroll_next_date: date
    monthly_bills: float = 0     # raw material + overheads, spread weekly
    monthly_sales: float = 0     # run-rate used for the forecast after day 45


class Buyer(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    gstin: str
    persona: str                 # prompt payer / monthly payment run / ...
    ap_contact: str
    ap_email: str
    sales_email: str
    finance_head: str
    finance_email: str
    phone: str = ""
    on_treds: bool = False
    sensitive: bool = False      # owner flag: slow the ladder, approve everything
    credit_days: int = 30        # agreed terms (MSMED Act caps this at 45)
    payment_run_day: int = 0     # day of month the buyer pays suppliers (0 = no fixed run)
    avg_days_to_pay: float = 60
    slip_days: int = 0           # how late they usually are vs their own promise
    has_portal: bool = False
    playbook: str = ""           # learned: what this buyer needs before it pays


class PurchaseOrder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(index=True)
    buyer_id: str
    line_no: int
    item: str
    qty: int
    rate: float


class Invoice(SQLModel, table=True):
    id: str = Field(primary_key=True)
    buyer_id: str = Field(index=True)
    invoice_date: date
    amount: float
    item: str = ""
    po_number: Optional[str] = None
    po_line: Optional[int] = None
    qty: int = 0
    billing_gstin: str = ""
    udyam_printed: bool = True
    sent_to: str = ""
    irn: Optional[str] = None
    grn_no: Optional[str] = None
    pod_received: bool = True
    state: str = Field(default="DRAFT", index=True)
    blocker: Optional[str] = None
    promises: str = "[]"         # JSON list of {"amount", "date", "note"}
    paid_amount: float = 0
    paid_date: Optional[date] = None
    financed_amount: float = 0
    last_action: Optional[str] = None
    last_action_at: Optional[NaiveDatetime] = None
    actions_done: str = "[]"     # JSON list of action names already taken
    planted_error: Optional[str] = None  # answer key for the evaluation only

    # helpers -----------------------------------------------------------------
    def get_promises(self) -> list:
        return json.loads(self.promises or "[]")

    def get_actions(self) -> list:
        return json.loads(self.actions_done or "[]")

    def add_action(self, name: str) -> None:
        done = self.get_actions()
        done.append(name)
        self.actions_done = json.dumps(done)
        self.last_action = name
        self.last_action_at = config.now()

    @property
    def outstanding(self) -> float:
        return round(self.amount - self.paid_amount, 2)


class Reply(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: str = Field(index=True)
    buyer_id: str
    channel: str = "email"
    sender: str = ""
    text: str
    received_at: NaiveDatetime = Field(default_factory=config.now)
    processed: bool = False
    intent: Optional[str] = None
    parsed: str = "{}"


class BankTxn(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    txn_date: date
    amount: float
    narration: str
    matched_invoice: Optional[str] = None
    live: bool = False           # arrived after the opening balance was set -> adds to cash


class PortalRecord(SQLModel, table=True):
    """State of the (mock) buyer vendor portal for an invoice."""
    invoice_id: str = Field(primary_key=True)
    status: str                  # LOGGED / ON_HOLD / APPROVED / PAID
    reason: str = ""
    payment_run: Optional[date] = None


class Approval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: str = Field(index=True)
    action: str
    title: str
    reason: str = ""
    draft: str = ""
    payload: str = "{}"          # numbers the executor needs (computed by code)
    autonomy: str = "approve"    # approve | owner
    status: str = Field(default="PENDING", index=True)  # PENDING/APPROVED/EDITED/HELD/DONE
    created_at: NaiveDatetime = Field(default_factory=config.now)
    decided_at: Optional[NaiveDatetime] = None
    decided_via: Optional[str] = None


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: str = Field(index=True)
    agent: str
    action: str
    from_state: str = ""
    to_state: str = ""
    detail: str = ""
    evidence: str = ""
    model: str = ""              # which model (or "code") made this decision
    at: NaiveDatetime = Field(default_factory=config.now)


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    audience: str                # owner | buyer
    direction: str = "out"       # out | in
    channel: str = "whatsapp"    # whatsapp | email | voice
    to: str = ""
    subject: str = ""
    body: str
    invoice_id: Optional[str] = None
    approval_id: Optional[int] = None
    delivered: bool = False      # True when really sent through Twilio
    at: NaiveDatetime = Field(default_factory=config.now)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine, expire_on_commit=False)


def is_empty() -> bool:
    with get_session() as s:
        return s.exec(select(Supplier)).first() is None


def reset_db() -> None:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
