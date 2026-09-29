"""Gemini integration: prompt building, multimodal calls, JSON validation, budget checks.

Flow for every planner:
  1. Build a prompt (+ optional outfit image for jewelry).
  2. Ask Gemini for STRICT JSON (response_mime_type=application/json).
  3. Normalise/validate the JSON, compute totals, build platform search links.
  4. If Gemini is unavailable, returns junk, or blows the budget -> rule-based fallback.
"""
import json
import re
from typing import Optional

from catalog import PLATFORMS, build_link, canonical_platform
from config import (GEMINI_API_KEY, GEMINI_FALLBACK_MODEL, GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS,
                    logger)
from fallbacks import FALLBACKS

try:  # the app still runs (in fallback mode) if the SDK is missing
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None

BUDGET_TOLERANCE = 1.05  # AI plans more than 5% over budget are rejected

SYSTEM_INSTRUCTION = (
    "You are PocketSmart AI, a careful budget-planning assistant for shoppers in India. "
    "All prices are in Indian Rupees (INR). Never exceed the user's total budget. "
    "Only recommend from these platforms: " + ", ".join(PLATFORMS) + ". "
    "Do NOT invent URLs. Respond with valid JSON only - no markdown, no commentary."
)

JSON_SHAPE = """Return exactly this JSON shape:
{
  "summary": "2 sentence overview of the plan",
  "outfit_analysis": "only if an outfit image was supplied: colours/style you detected, else empty string",
  "sections": [
    {
      "title": "section name (room / budget category / jewelry piece)",
      "items": [
        {
          "name": "specific product or service",
          "platform": "one of the allowed platforms",
          "estimated_price": <number, INR price of ONE unit>,
          "quantity": <integer>,
          "reason": "one sentence: why it fits the budget, style and need",
          "search_query": "short search phrase to find it on that platform"
        }
      ]
    }
  ],
  "tips": ["2-4 short money-saving tips"]
}
Rules: sum(estimated_price * quantity) across ALL items must be <= the total budget. Give 1-3 items per section."""


# ------------------------------------------------------------------ prompts
def build_prompt(category: str, req: dict) -> str:
    if category == "home":
        lines = "\n".join(f"- {i['room']}: {i['quantity']} x {i['item']}" for i in req["items"])
        body = (f"Plan a HOME INTERIOR shopping list.\nTotal budget: INR {req['budget']:.0f}\n"
                f"Style preference: {req['style']}\nExtra notes: {req['notes'] or 'none'}\n"
                f"Required items:\n{lines}\n"
                "Prefer IKEA for furniture, Amazon for electricals, Flipkart for decor. "
                "Balance functionality, style and price; use one section per room.")
    elif category == "party":
        body = (f"Plan a PARTY budget.\nTotal budget: INR {req['budget']:.0f}\nGuests: {req['guests']}\n"
                f"Event type: {req['event_type']}\nVenue: {req['venue_type']} {req['venue_details']}\n"
                f"City: {req['city'] or 'not specified'}\nFood preference: {req['food_preference']}\n"
                f"Notes: {req['notes'] or 'none'}\n"
                "Allocate the budget across sections Catering, Venue (skip if venue is the user's home), "
                "Decoration, Entertainment and Extras. Use Swiggy/Zomato for food, OYO for venues or "
                "stays, Amazon/Flipkart for decor. For per-person items set quantity = number of guests.")
    else:
        body = (f"Recommend JEWELRY.\nTotal budget: INR {req['budget']:.0f}\nOccasion: {req['occasion']}\n"
                f"Style preferences: {', '.join(req['styles']) or 'no preference'}\n"
                f"Metal preference: {req['metal']}\nNotes: {req['notes'] or 'none'}\n"
                + ("An outfit photo is attached: describe its colours and style in outfit_analysis and "
                   "pick jewelry that complements it.\n" if req.get("outfit_image") else "")
                + "Use one section per jewelry piece (necklace, earrings, bangles, ring...). "
                  "Prefer Amazon and Flipkart.")
    return f"{body}\n\n{JSON_SHAPE}"


# ------------------------------------------------------------------ Gemini call
def gemini_configured() -> bool:
    return bool(GEMINI_API_KEY) and genai is not None


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000),
        )
    return _client


def call_gemini(prompt: str, image_bytes: Optional[bytes] = None, image_mime: str = "image/jpeg") -> str:
    """Send text (+ optional image) to Gemini and return the raw text. Tries the fallback model once."""
    contents: list = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        temperature=0.4,
    )
    last_err: Exception | None = None
    for model in dict.fromkeys([GEMINI_MODEL, GEMINI_FALLBACK_MODEL]):
        try:
            response = _get_client().models.generate_content(model=model, contents=contents, config=config)
            if response.text:
                return response.text
            last_err = ValueError("empty response")
        except Exception as exc:
            logger.warning("Gemini call failed with model %s: %s", model, exc)
            last_err = exc
    raise RuntimeError(f"Gemini request failed: {last_err}")


def extract_json(text: str) -> dict:
    """Parse JSON even if the model wrapped it in ```json fences or added stray text."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in model output")
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


# ------------------------------------------------------------------ normalisation
def _num(value, default: float = 0.0) -> float:
    try:
        return float(re.sub(r"[^\d.\-]", "", str(value))) if value not in (None, "") else default
    except ValueError:
        return default


def normalize_plan(raw: dict, budget: float, source: str, notice: str = "") -> dict:
    """Validate a raw plan, compute totals and attach search links. Raises ValueError if unusable."""
    sections = []
    for sec in (raw.get("sections") or [])[:12]:
        items = []
        for it in (sec.get("items") or [])[:8]:
            name = str(it.get("name") or "").strip()[:120]
            if not name:
                continue
            platform = canonical_platform(str(it.get("platform") or ""))
            price = max(0.0, _num(it.get("estimated_price")))
            qty = int(min(5000, max(1, _num(it.get("quantity"), 1))))
            items.append({
                "name": name,
                "platform": platform,
                "estimated_price": round(price),
                "quantity": qty,
                "total": round(price * qty),
                "reason": str(it.get("reason") or "").strip()[:300],
                "link": build_link(platform, str(it.get("search_query") or name)),
            })
        if items:
            sections.append({"title": str(sec.get("title") or "Recommendations").strip()[:60],
                             "subtotal": sum(i["total"] for i in items), "items": items})
    if not sections:
        raise ValueError("plan has no usable items")
    estimated = sum(s["subtotal"] for s in sections)
    return {
        "summary": str(raw.get("summary") or "").strip()[:600],
        "outfit_analysis": str(raw.get("outfit_analysis") or "").strip()[:600],
        "total_budget": round(budget),
        "estimated_total": estimated,
        "remaining": round(budget) - estimated,
        "within_budget": estimated <= budget,
        "sections": sections,
        "tips": [str(t).strip()[:200] for t in (raw.get("tips") or []) if str(t).strip()][:5],
        "source": source,
        "notice": notice,
    }


# ------------------------------------------------------------------ public API
def generate_plan(category: str, req: dict, image_bytes: Optional[bytes] = None,
                  image_mime: str = "image/jpeg") -> dict:
    """Return a validated plan for category in {'home','party','jewelry'}."""
    budget = float(req["budget"])
    notice = ""
    if gemini_configured():
        try:
            raw = extract_json(call_gemini(build_prompt(category, req), image_bytes, image_mime))
            plan = normalize_plan(raw, budget, source="gemini")
            if plan["estimated_total"] <= budget * BUDGET_TOLERANCE:
                return plan
            notice = "The AI plan exceeded your budget, so a budget-safe plan was generated instead."
            logger.info("Gemini plan over budget (%s > %s); using fallback", plan["estimated_total"], budget)
        except Exception as exc:
            logger.warning("Gemini plan unusable (%s); using fallback", exc)
            notice = "The AI service was unavailable, so a rule-based plan was generated."
    else:
        notice = "Demo mode: no Gemini API key configured, so a rule-based plan was generated."
    plan = normalize_plan(FALLBACKS[category](req), budget, source="fallback", notice=notice)
    if not plan["within_budget"]:
        plan["notice"] = (notice + " " if notice else "") + (
            "Your budget is too low for everything requested - raise the budget or remove some items.")
    return plan
