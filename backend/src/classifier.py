import re
from dataclasses import dataclass
from typing import Optional

from langchain_groq import ChatGroq
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.config import get_settings

settings = get_settings()

SUPPORTED_INTENTS = [
    "backup_failure",
    "restore_request",
    "licensing",
    "access_issue",
    "performance",
    "installation",
    "configuration",
    "billing",
    "feature_request",
    "general_inquiry",
]

ESCALATE_PATTERNS = [
    r"(speak|talk|chat).{0,15}(human|agent|person|representative|someone)",
    r"(real|live|actual).{0,10}(person|agent|human)",
    r"(lawsuit|legal|lawyer|attorney|sue)",
    r"data loss|lost.{0,10}(all|my) data|everything.{0,5}gone",
    r"production.{0,10}(down|offline|not working)",
    r"critical outage|all backups failed",
]

RULE_PATTERNS = [
    (r"backup.{0,30}(fail|error|stuck|not running|abort)", "backup_failure", 0.92),
    (r"(job|task).{0,15}(fail|error|status code)",          "backup_failure", 0.88),
    (r"CV-\d{4,6}",                                          "backup_failure", 0.93),
    (r"(restore|recover|recovery|rollback)",                 "restore_request", 0.91),
    (r"(cleanroom|disaster recovery|DR test)",               "restore_request", 0.88),
    (r"(licens|expired|activation|serial key|renewal)",      "licensing",       0.91),
    (r"(login|password|sign.?in|access denied|locked out|mfa|2fa|sso)", "access_issue", 0.90),
    (r"(slow|performance|latency|timeout|hung|freezing|bottleneck)", "performance", 0.86),
    (r"(install|uninstall|upgrade|downgrade|deploy agent)",  "installation",    0.85),
    (r"(configure|setup|config|setting|wizard|onboard)",     "configuration",   0.83),
    (r"(invoice|charge|payment|subscription|billing|refund)","billing",         0.90),
    (r"(feature request|enhancement|suggestion|roadmap)",    "feature_request", 0.87),
]


@dataclass
class IntentResult:
    intent: str
    confidence: float
    method: str          # "rule" | "llm" | "fallback"
    escalate: bool = False
    escalate_reason: str = ""


def classify_intent_local_patterns(text: str) -> IntentResult:
    """
    Rule-based classification only — no LLM calls.
    Used directly in unit tests so we don't spend money on tests.
    """
    text_lower = text.lower().strip()

    for pattern in ESCALATE_PATTERNS:
        if re.search(pattern, text_lower):
            return IntentResult(
                intent="_escalate", confidence=1.0, method="rule",
                escalate=True, escalate_reason="explicit_escalation_request",
            )

    for pattern, intent, confidence in RULE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return IntentResult(intent=intent, confidence=confidence, method="rule")

    return IntentResult(intent="general_inquiry", confidence=0.5, method="fallback")


async def classify_intent(text: str) -> IntentResult:
    """
    Full two-layer classification: fast rules first, LLM fallback for ambiguous cases.
    Used in the production backend. Tests use classify_intent_local_patterns instead.
    """
    local_result = classify_intent_local_patterns(text)

    if local_result.escalate or local_result.intent != "general_inquiry":
        return local_result

    return await _llm_classify(text)


async def _llm_classify(text: str) -> IntentResult:
    intents_list = ", ".join(SUPPORTED_INTENTS)

    llm = ChatGroq(
        model=settings.groq_model,
        temperature=0,
        max_tokens=20,
        groq_api_key=settings.groq_api_key,
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"Classify the support message into exactly one of these intents: {intents_list}. "
            "Respond with ONLY the intent string. Nothing else.",
        ),
        ("human", "{text}"),
    ])

    chain = prompt | llm | StrOutputParser()
    raw = await chain.ainvoke({"text": text[:600]})
    raw = raw.strip().lower()

    intent = raw if raw in SUPPORTED_INTENTS else "general_inquiry"
    confidence = 0.75 if intent != "general_inquiry" else 0.50

    return IntentResult(intent=intent, confidence=confidence, method="llm")


def get_priority_for_intent(intent: str, customer_tier: str = "standard") -> str:
    base = {
        "backup_failure": "P1", "restore_request": "P1",
        "access_issue": "P2",   "performance": "P2",
        "licensing": "P2",      "installation": "P3",
        "configuration": "P3",  "billing": "P2",
        "feature_request": "P4","general_inquiry": "P3",
    }.get(intent, "P3")

    if customer_tier in ("enterprise", "premium") and base in ("P3", "P4"):
        return {"P3": "P2", "P4": "P3"}.get(base, base)

    return base


def get_team_for_intent(intent: str) -> str:
    return {
        "backup_failure":  "backup_team",
        "restore_request": "backup_team",
        "access_issue":    "security_team",
        "performance":     "platform_sre",
        "licensing":       "license_team",
        "installation":    "ops_team",
        "configuration":   "ops_team",
        "billing":         "billing_team",
        "feature_request": "product_team",
        "general_inquiry": "general_support",
    }.get(intent, "general_support")