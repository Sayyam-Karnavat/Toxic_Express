"""/meta: static product configuration for the frontend (categories, reactions, limits, help)."""

from fastapi import APIRouter, Response

from media_processing import MAX_IMAGE_BYTES, MAX_VIDEO_BYTES, MAX_VIDEO_SECONDS
from models import Category, CommentFlair, ReactionKind, ReportReason
from reputation import BADGES

router = APIRouter(tags=["meta"])

CATEGORY_LABELS = {
    Category.work: "Work",
    Category.tech: "Tech",
    Category.money: "Money",
    Category.relationships: "Relationships",
    Category.health: "Health",
    Category.customer_service: "Customer Service",
    Category.commute: "Commute",
    Category.life: "Life",
}
REACTION_LABELS = {
    ReactionKind.same: "Same here",
    ReactionKind.hug: "Hugs",
    ReactionKind.rage: "Rage with you",
    ReactionKind.lol: "Lol",
}
CRISIS_RESOURCES = [
    {"region": "International", "name": "Find a Helpline", "url": "https://findahelpline.com"},
    {
        "region": "US",
        "name": "988 Suicide & Crisis Lifeline",
        "phone": "988",
        "url": "https://988lifeline.org",
    },
    {
        "region": "UK & IE",
        "name": "Samaritans",
        "phone": "116 123",
        "url": "https://www.samaritans.org",
    },
    {
        "region": "India",
        "name": "Tele-MANAS",
        "phone": "14416",
        "url": "https://telemanas.mohfw.gov.in",
    },
]


@router.get("/meta")
async def meta(response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {
        "categories": [{"value": c.value, "label": CATEGORY_LABELS[c]} for c in Category],
        "reactions": [{"value": r.value, "label": REACTION_LABELS[r]} for r in ReactionKind],
        "flairs": [f.value for f in CommentFlair],
        "report_reasons": [r.value for r in ReportReason],
        "badges": BADGES,
        "limits": {
            "title": 120,
            "body": 5000,
            "comment": 2000,
            "tags": 5,
            "images": 4,
            "image_bytes": MAX_IMAGE_BYTES,
            "video_bytes": MAX_VIDEO_BYTES,
            "video_seconds": MAX_VIDEO_SECONDS,
            "edit_window_minutes": 15,
        },
        "crisis_resources": CRISIS_RESOURCES,
    }
