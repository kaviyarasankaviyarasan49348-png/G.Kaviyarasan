"""Platform link builder and baseline price catalogue (INR) used by the offline fallback.

PocketSmart does not scrape retailers. The AI (or the fallback) proposes *what* to buy and
roughly what it costs; this module builds *search links* for the named platform so the user
can verify real listings and live prices. This avoids hallucinated product URLs.
"""
from urllib.parse import quote_plus

PLATFORMS = ["Amazon", "Flipkart", "IKEA", "Swiggy", "Zomato", "OYO", "Myntra", "Local vendor"]

_LINKS = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "ikea": "https://www.ikea.com/in/en/search/?q={q}",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "zomato": "https://www.zomato.com/search?q={q}",
    "oyo": "https://www.oyorooms.com/search?query={q}",
    "myntra": "https://www.myntra.com/{q}",
}


def canonical_platform(name: str) -> str:
    n = (name or "").strip().lower()
    for p in PLATFORMS:
        if p.lower() == n or p.lower() in n:
            return p
    return "Local vendor"


def build_link(platform: str, query: str) -> str:
    q = quote_plus((query or "").strip()[:100])
    template = _LINKS.get(platform.lower())
    if template:
        return template.format(q=q.replace("+", "-") if platform.lower() == "myntra" else q)
    return f"https://www.google.com/search?q={q}"


# keyword -> (baseline unit price in INR, best platform). Longest keyword wins.
HOME_ITEMS = {
    "dining table": (9000, "IKEA"), "coffee table": (3500, "IKEA"), "study table": (5000, "IKEA"),
    "side table": (2000, "IKEA"), "bedside": (2500, "IKEA"), "tv unit": (7500, "IKEA"),
    "table": (4000, "IKEA"), "dining chair": (2200, "IKEA"), "chair": (2500, "IKEA"),
    "sofa": (16000, "IKEA"), "bed": (14000, "IKEA"), "mattress": (8500, "Amazon"),
    "wardrobe": (12000, "IKEA"), "shelf": (4500, "IKEA"), "bookcase": (4500, "IKEA"),
    "storage": (1800, "IKEA"), "ceiling fan": (2400, "Amazon"), "fan": (2400, "Amazon"),
    "chandelier": (6000, "Amazon"), "light": (900, "Amazon"), "lamp": (1100, "Amazon"),
    "chimney": (9500, "Amazon"), "curtain": (1400, "Flipkart"), "rug": (2600, "Flipkart"),
    "carpet": (2600, "Flipkart"), "cushion": (350, "Flipkart"), "wall art": (900, "Flipkart"),
    "painting": (1200, "Flipkart"), "mirror": (1900, "IKEA"), "plant": (450, "Flipkart"),
    "curtains": (1400, "Flipkart"), "clock": (700, "Flipkart"), "bedsheet": (900, "Flipkart"),
}
DEFAULT_HOME_ITEM = (2000, "Amazon")


def lookup_home_item(name: str):
    n = (name or "").lower()
    for key in sorted(HOME_ITEMS, key=len, reverse=True):
        if key in n:
            return HOME_ITEMS[key]
    return DEFAULT_HOME_ITEM


ROOMS = ["Living Room", "Bedroom", "Kitchen", "Dining Room", "Bathroom", "Study / Home Office",
         "Kids Room", "Balcony"]
HOME_ITEM_SUGGESTIONS = ["Lights", "Ceiling fans", "Dining table", "Sofa", "Bed", "Wardrobe",
                         "Curtains", "Rug", "Wall art", "Study table", "TV unit", "Coffee table",
                         "Bookshelf", "Mirror", "Storage unit", "Chimney"]
PARTY_TYPES = ["Birthday", "Wedding", "Corporate", "Anniversary", "Baby shower", "Housewarming",
               "Farewell", "Festival"]
OCCASIONS = ["Wedding", "Engagement", "Party", "Festival", "Office / Formal", "Casual / Daily",
             "Date night", "Graduation"]
JEWELRY_STYLES = ["Traditional", "Modern", "Minimalist", "Statement", "Vintage", "Boho", "Ethnic",
                  "Temple", "Kundan", "Oxidised"]
