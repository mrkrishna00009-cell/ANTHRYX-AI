"""Compliance Copilot.

No LLM provider of any kind exists in this project for open-ended text
generation - Bhashini is ASR/OCR/NMT only, never a general-purpose
language model, and no OpenAI/Anthropic/etc. integration was ever built
here. Building one now, under audit pressure, would be new scope wearing
a "bug fix" label - so this Copilot is honestly what the current
architecture can support: a deterministic keyword search over the real,
persisted M0 statutory-rule corpus (StatutoryRule), optionally combined
with a specific mine's real obligation/finding state when mine context
is given.

Every fact in a response is copied verbatim from a real database row -
rule_code, title, statute, clause, severity, obligation_status,
last_satisfied_date, or a finding's own observation text. Nothing is
composed by a language model, because none exists to call. The
provider/mode field says exactly this, every time, so a reviewer never
mistakes it for an LLM answer.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.field_evidence import FieldEvidence, InspectionFinding
from models.statutory import MineObligation, StatutoryRule

PROVIDER_MODE = "DETERMINISTIC_RETRIEVAL"  # never "LLM" - no such provider is configured anywhere


def answer_question(session: Session, question: str, mine_id: uuid.UUID | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        return {
            "provider_mode": PROVIDER_MODE, "question": question, "matched_rules": [],
            "answer": None,
            "status": "INVALID_QUERY",
            "detail": "A non-empty question is required.",
        }

    # Deterministic keyword match against the real, persisted rule corpus -
    # no fuzzy scoring model, no embeddings, no external call.
    tokens = [t.lower() for t in question.replace("?", " ").split() if len(t) > 2]
    if not tokens:
        return {
            "provider_mode": PROVIDER_MODE, "question": question, "matched_rules": [],
            "answer": None, "status": "NO_MATCH",
            "detail": "No searchable terms in the question.",
        }

    rules = session.execute(select(StatutoryRule)).scalars().all()
    scored = []
    for r in rules:
        haystack = f"{r.rule_code} {r.title} {r.statute} {r.clause}".lower()
        hits = sum(1 for t in tokens if t in haystack)
        if hits > 0:
            scored.append((hits, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [r for _, r in scored[:3]]

    if not top:
        return {
            "provider_mode": PROVIDER_MODE, "question": question, "matched_rules": [],
            "answer": None, "status": "NO_SOURCE_FOUND",
            "detail": (
                "No statutory rule in this project's seeded corpus matched the question's "
                "terms. This does not mean no such rule exists in CMR 2017/Mines Act 1952 - "
                "only that the demo's proof-of-concept rule set (15-20 rules) does not cover it."
            ),
        }

    matched_rules = []
    for r in top:
        entry = {
            "rule_code": r.rule_code, "title": r.title, "statute": r.statute,
            "clause": r.clause, "severity": r.severity.value, "authority": r.authority,
            "clause_verification": r.clause_verification.value,
        }
        if mine_id is not None:
            obligation = session.execute(
                select(MineObligation).where(MineObligation.mine_id == mine_id, MineObligation.rule_id == r.id)
            ).scalar_one_or_none()
            if obligation is not None:
                entry["mine_obligation_status"] = obligation.status.value
                entry["mine_last_satisfied_date"] = (
                    obligation.last_satisfied_date.isoformat() if obligation.last_satisfied_date else None
                )
                latest_finding = session.execute(
                    select(InspectionFinding, FieldEvidence.server_timestamp)
                    .join(FieldEvidence, FieldEvidence.id == InspectionFinding.evidence_id)
                    .where(FieldEvidence.mine_id == mine_id, InspectionFinding.rule_id == r.id)
                    .order_by(FieldEvidence.server_timestamp.desc()).limit(1)
                ).first()
                if latest_finding is not None:
                    f, ts = latest_finding
                    entry["mine_latest_finding"] = {
                        "compliant": f.compliant, "observed_at": ts.isoformat(),
                        "observation": f.observation,
                    }
        matched_rules.append(entry)

    # The "answer" is assembled entirely from the matched rows above -
    # never freeform generated text.
    top_rule = matched_rules[0]
    answer_lines = [
        f"{top_rule['rule_code']} ({top_rule['statute']} {top_rule['clause']}): {top_rule['title']}. "
        f"Severity: {top_rule['severity']}. Authority: {top_rule['authority']}."
    ]
    if top_rule["clause_verification"] != "VERIFIED":
        answer_lines.append(
            "This clause reference is seeded as a proof of concept and has not been "
            "independently verified against the statute text."
        )
    if "mine_obligation_status" in top_rule:
        answer_lines.append(f"For this mine, current obligation status: {top_rule['mine_obligation_status']}.")
    if "mine_latest_finding" in top_rule:
        lf = top_rule["mine_latest_finding"]
        answer_lines.append(
            f"Most recent field inspection ({lf['observed_at'][:10]}): "
            + ("non-compliant" if lf["compliant"] is False else "compliant")
            + (f" — {lf['observation']}" if lf["observation"] else "")
        )

    return {
        "provider_mode": PROVIDER_MODE, "question": question,
        "matched_rules": matched_rules, "answer": " ".join(answer_lines),
        "status": "GROUNDED_ANSWER",
        "detail": (
            f"{len(matched_rules)} rule(s) matched by keyword search over the seeded M0 corpus. "
            "Every fact above is copied from a real database row - no language model was called."
        ),
    }
