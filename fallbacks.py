"""Deterministic, rule-based recommendations.

Used when Gemini is not configured, fails, returns unusable JSON, or exceeds the budget.
Every function returns the same "raw plan" shape the AI is asked to produce.
"""
from catalog import lookup_home_item


def _r10(x: float) -> int:
    return max(10, int(round(x / 10.0)) * 10)


def _tier(scale: float) -> str:
    return "budget-friendly" if scale < 0.7 else ("mid-range" if scale < 1.1 else "premium")


def home_plan(req: dict) -> dict:
    budget = float(req["budget"])
    lines = []
    for it in req["items"]:
        base, platform = lookup_home_item(it["item"])
        lines.append((it, base, platform))
    base_total = sum(b * it["quantity"] for it, b, _ in lines) or 1
    scale = min(1.6, max(0.2, budget * 0.92 / base_total))
    tier = _tier(scale)
    rooms: dict = {}
    for it, base, platform in lines:
        rooms.setdefault(it["room"], []).append({
            "name": f"{tier.title()} {it['item']} ({req.get('style') or 'Modern'} style)",
            "platform": platform,
            "estimated_price": _r10(base * scale),
            "quantity": it["quantity"],
            "reason": f"A {tier} pick that keeps the {it['room']} within budget.",
            "search_query": f"{it['item']} {req.get('style') or ''}".strip(),
        })
    return {
        "summary": f"A {tier} plan for {len(rooms)} room(s), sized to stay inside your budget.",
        "sections": [{"title": room, "items": items} for room, items in rooms.items()],
        "tips": [
            "Compare prices on IKEA, Amazon and Flipkart before buying - sales change prices weekly.",
            "Buy the big-ticket furniture first and fill remaining budget with decor.",
        ],
    }


_PARTY_SPLIT = {
    "birthday": {"Catering": .45, "Decoration": .20, "Entertainment": .15, "Venue": .15, "Extras": .05},
    "wedding": {"Catering": .40, "Venue": .30, "Decoration": .15, "Entertainment": .10, "Extras": .05},
    "corporate": {"Catering": .40, "Venue": .30, "Entertainment": .10, "Decoration": .10, "Extras": .10},
    "default": {"Catering": .42, "Venue": .20, "Decoration": .18, "Entertainment": .12, "Extras": .08},
}


def party_plan(req: dict) -> dict:
    budget, guests = float(req["budget"]), int(req["guests"])
    split = dict(_PARTY_SPLIT.get(req["event_type"].lower(), _PARTY_SPLIT["default"]))
    if req["venue_type"] == "home":  # no venue cost: share it between catering and decor
        v = split.pop("Venue")
        split["Catering"] += v * 0.6
        split["Decoration"] += v * 0.4
    amounts = {k: budget * 0.95 * share for k, share in split.items()}
    diet = {"veg": "vegetarian", "non-veg": "non-vegetarian", "both": "veg & non-veg"}[req["food_preference"]]
    city = f" in {req['city']}" if req.get("city") else ""
    sections = []
    for name in ("Catering", "Venue", "Decoration", "Entertainment", "Extras"):
        if name not in amounts:
            continue
        amt = amounts[name]
        if name == "Catering":
            main, sweets = amt * 0.8, amt * 0.2
            items = [
                {"name": f"{diet.title()} main-course party order", "platform": "Zomato",
                 "estimated_price": _r10(main / guests), "quantity": guests,
                 "reason": f"Per-plate pricing for {guests} guests{city}.",
                 "search_query": f"party catering {diet} {req['city']}".strip()},
                {"name": "Snacks, starters and desserts", "platform": "Swiggy",
                 "estimated_price": _r10(sweets / guests), "quantity": guests,
                 "reason": "Per-guest allowance for starters and sweets.",
                 "search_query": f"party snacks desserts {req['city']}".strip()},
            ]
        elif name == "Venue":
            stay = req["venue_type"] == "hotel"
            items = [{
                "name": "Guest rooms + small event space" if stay else "Banquet hall / event space booking",
                "platform": "OYO", "estimated_price": _r10(amt), "quantity": 1,
                "reason": "Venue or stay for out-of-town guests." if stay else "Hall rental for the event.",
                "search_query": f"banquet hall {req['city']}".strip()}]
        elif name == "Decoration":
            items = [
                {"name": f"{req['event_type']} balloon, banner and fairy-light kit", "platform": "Amazon",
                 "estimated_price": _r10(amt * 0.6), "quantity": 1,
                 "reason": "Core decoration supplies.",
                 "search_query": f"{req['event_type']} decoration kit"},
                {"name": "Backdrop and photo props", "platform": "Flipkart",
                 "estimated_price": _r10(amt * 0.4), "quantity": 1,
                 "reason": "Photo corner for guests.",
                 "search_query": f"{req['event_type']} backdrop photo props"},
            ]
        elif name == "Entertainment":
            items = [{"name": "DJ / music system or host with games", "platform": "Local vendor",
                      "estimated_price": _r10(amt), "quantity": 1,
                      "reason": "Keeps guests engaged for the event.",
                      "search_query": f"DJ event host {req['city']}".strip()}]
        else:
            items = [{"name": "Return gifts and disposable tableware", "platform": "Amazon",
                      "estimated_price": _r10(amt / guests), "quantity": guests,
                      "reason": "Small per-guest extras.", "search_query": "return gifts party"}]
        sections.append({"title": name, "items": items})
    return {
        "summary": f"{req['event_type']} plan for {guests} guests, split across "
                   f"{', '.join(s['title'].lower() for s in sections)}.",
        "sections": sections,
        "tips": [
            "Confirm the final guest count 3-4 days before to avoid over-ordering food.",
            "Keep roughly 5% of the budget aside for last-minute costs.",
        ],
    }


_JEWELRY_SPLIT = {
    "wedding": [("Necklace set", .45), ("Bangles", .25), ("Earrings", .20), ("Ring", .10)],
    "engagement": [("Ring", .35), ("Necklace / pendant", .35), ("Earrings", .30)],
    "office": [("Earrings", .40), ("Pendant", .35), ("Bracelet", .25)],
    "casual": [("Earrings", .40), ("Pendant", .35), ("Bracelet", .25)],
    "default": [("Necklace", .35), ("Earrings", .35), ("Bracelet / bangles", .20), ("Ring", .10)],
}


def jewelry_plan(req: dict) -> dict:
    budget = float(req["budget"])
    key = next((k for k in _JEWELRY_SPLIT if k in req["occasion"].lower()), "default")
    style = ", ".join(req.get("styles") or []) or "elegant"
    metal = "" if req.get("metal", "Any") in ("", "Any") else f"{req['metal']} "
    sections = []
    for i, (piece, share) in enumerate(_JEWELRY_SPLIT[key]):
        sections.append({"title": piece, "items": [{
            "name": f"{style.title()} {metal}{piece.lower()}".strip(),
            "platform": "Amazon" if i % 2 == 0 else "Flipkart",
            "estimated_price": _r10(budget * 0.95 * share), "quantity": 1,
            "reason": f"Suits a {req['occasion'].lower()} look and your {style.lower()} preference.",
            "search_query": f"{style} {metal}{piece} for {req['occasion']}"}]})
    return {
        "summary": f"A coordinated {style.lower()} jewelry set for a {req['occasion'].lower()}.",
        "outfit_analysis": "",
        "sections": sections,
        "tips": [
            "Choose one statement piece and keep the rest simple.",
            "Check return policy and hallmark/certification before buying.",
        ],
    }


FALLBACKS = {"home": home_plan, "party": party_plan, "jewelry": jewelry_plan}
