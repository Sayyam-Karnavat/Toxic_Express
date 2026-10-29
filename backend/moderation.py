"""Layered content moderation.

1. Local rules (fast, deterministic): personal-info/doxxing detection, blocklist, link spam.
2. OpenAI omni-moderation (free) for text and images.
3. A policy that suits a venting site: swearing is fine, threats/hate/doxxing are not, and
   self-harm signals are published with crisis resources instead of being silenced.

Callers get a Verdict. ModerationUnavailableError means "could not decide": the caller must keep
the content unpublished and retry later (fail-safe).
"""

import asyncio
import base64
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import httpx

from config import settings
from http_client import get_http_client
from retry import http_retry, raise_for_retryable

logger = logging.getLogger(__name__)

OPENAI_MODERATION_URL = "https://api.openai.com/v1/moderations"
MODEL = "omni-moderation-latest"

Action = Literal["allow", "review", "reject"]
_SEVERITY = {"allow": 0, "review": 1, "reject": 2}


class ModerationUnavailableError(Exception):
    pass


@dataclass
class Verdict:
    action: Action = "allow"
    crisis: bool = False
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    provider: str = "local"

    def merge(self, other: "Verdict") -> "Verdict":
        action = self.action if _SEVERITY[self.action] >= _SEVERITY[other.action] else other.action
        scores = dict(self.scores)
        for k, v in other.scores.items():
            scores[k] = max(v, scores.get(k, 0.0))
        return Verdict(
            action=action,
            crisis=self.crisis or other.crisis,
            reasons=list(dict.fromkeys(self.reasons + other.reasons)),
            scores=scores,
            provider=other.provider if other.provider != "local" else self.provider,
        )

    def as_json(self) -> dict:
        top = dict(sorted(self.scores.items(), key=lambda kv: -kv[1])[:6])
        return {
            "action": self.action,
            "crisis": self.crisis,
            "reasons": self.reasons,
            "scores": {k: round(v, 4) for k, v in top.items()},
            "provider": self.provider,
        }


# --- Local rules -------------------------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w])(?:\+?\d[\s\-.()]{0,2}){10,15}(?![\w])")
_TOLL_FREE = re.compile(r"^(?:\+?1)?(800|888|877|866|855|844|833)\d{7}$")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_ADDRESS = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b"
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return len(digits) >= 13 and checksum % 10 == 0


@lru_cache
def _blocklist() -> tuple[re.Pattern[str], ...]:
    path = Path(settings.moderation_blocklist_path)
    if not path.is_file():
        return ()
    terms = [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return tuple(re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in terms)


def detect_personal_info(text: str) -> list[str]:
    found: list[str] = []
    if _EMAIL.search(text):
        found.append("email address")
    for match in _PHONE.finditer(text):
        raw = match.group().strip()
        digits = re.sub(r"\D", "", raw)
        # Bare digit runs are usually order/ticket numbers; phones are written with + or separators.
        looks_like_phone = raw.startswith("+") or len(re.findall(r"[\s\-.()]", raw)) >= 2
        if 10 <= len(digits) <= 15 and looks_like_phone and not _TOLL_FREE.match(digits):
            found.append("phone number")
            break
    if _SSN.search(text):
        found.append("government ID number")
    if any(_luhn_ok(m.group()) for m in _CARD.finditer(text)):
        found.append("card number")
    if _ADDRESS.search(text):
        found.append("street address")
    return found


def check_local_rules(text: str) -> Verdict:
    pii = detect_personal_info(text)
    if pii:
        return Verdict("reject", reasons=[f"personal_info:{kind}" for kind in pii])
    if any(p.search(text) for p in _blocklist()):
        return Verdict("reject", reasons=["blocked_term"])
    if len(_URL.findall(text)) > 3:
        return Verdict("review", reasons=["link_spam"])
    return Verdict()


# --- Policy ------------------------------------------------------------------------------------

# Category thresholds tuned for venting: anger and insults about situations are expected, so the
# harassment/violence bars are high; anything involving minors or targeted threats is strict.
REJECT_AT = {
    "sexual/minors": 0.2,
    "hate/threatening": 0.5,
    "harassment/threatening": 0.7,
    "illicit/violent": 0.85,
}
REVIEW_AT = {
    "hate": 0.6,
    "harassment": 0.85,
    "violence": 0.85,
    "violence/graphic": 0.6,
    "sexual": 0.6,
    "illicit": 0.85,
    "self-harm/instructions": 0.5,
}
CRISIS_AT = {"self-harm": 0.5, "self-harm/intent": 0.4, "self-harm/instructions": 0.4}


def apply_policy(scores: dict[str, float], provider: str = "openai") -> Verdict:
    verdict = Verdict(scores=scores, provider=provider)
    for category, threshold in REJECT_AT.items():
        if scores.get(category, 0.0) >= threshold:
            verdict.action = "reject"
            verdict.reasons.append(category)
    if verdict.action != "reject":
        for category, threshold in REVIEW_AT.items():
            if scores.get(category, 0.0) >= threshold:
                verdict.action = "review"
                verdict.reasons.append(category)
    verdict.crisis = any(scores.get(c, 0.0) >= t for c, t in CRISIS_AT.items())
    return verdict


# --- Provider ----------------------------------------------------------------------------------


async def _call_openai(inputs: list[dict]) -> dict[str, float]:
    api_key = settings.openai_api_key.get_secret_value()
    response: httpx.Response | None = None
    try:
        async with asyncio.timeout(settings.moderation_timeout_seconds * 2):
            async for attempt in http_retry(
                attempts=3, max_seconds=settings.moderation_timeout_seconds * 2
            ):
                with attempt:
                    response = await get_http_client().post(
                        OPENAI_MODERATION_URL,
                        json={"model": MODEL, "input": inputs},
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=settings.moderation_timeout_seconds,
                    )
                    raise_for_retryable(response)
    except Exception as exc:  # timeouts, transport errors, 4xx/5xx after retries
        logger.warning("moderation API unavailable: %r", exc)
        raise ModerationUnavailableError(str(exc)) from exc
    assert response is not None
    scores: dict[str, float] = {}
    for result in response.json().get("results", []):
        for category, score in (result.get("category_scores") or {}).items():
            scores[category] = max(float(score), scores.get(category, 0.0))
    return scores


def _provider_enabled() -> bool:
    return bool(settings.openai_api_key.get_secret_value())


async def moderate_text(text: str) -> Verdict:
    local = check_local_rules(text)
    if local.action == "reject" or not _provider_enabled():
        return local
    scores = await _call_openai([{"type": "text", "text": text[:10000]}])
    return local.merge(apply_policy(scores))


async def moderate_image(jpeg_bytes: bytes) -> Verdict:
    if not _provider_enabled():
        return Verdict(provider="none")
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
    scores = await _call_openai([{"type": "image_url", "image_url": {"url": data_url}}])
    return apply_policy(scores)


async def moderate_images(images: list[bytes], concurrency: int = 3) -> Verdict:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(data: bytes) -> Verdict:
        async with semaphore:
            return await moderate_image(data)

    verdict = Verdict(provider="none" if not _provider_enabled() else "openai")
    for result in await asyncio.gather(*(one(img) for img in images)):
        verdict = verdict.merge(result)
    return verdict


def rejection_message(verdict: Verdict) -> str:
    if any(r.startswith("personal_info:") for r in verdict.reasons):
        kinds = ", ".join(
            r.split(":", 1)[1] for r in verdict.reasons if r.startswith("personal_info:")
        )
        return (
            f"Please remove personal information ({kinds}) before posting. "
            "Venting is fine; exposing people is not."
        )
    return (
        "This crosses the line: threats, hate or sexual content involving minors aren't "
        "allowed. Rant about the situation, not against people's safety."
    )
