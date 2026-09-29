"""Input/output schemas (Pydantic v2) for the planner APIs."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _clean(v) -> str:
    return " ".join(str(v or "").split())


class HomeItem(BaseModel):
    room: str = Field(min_length=1, max_length=40)
    item: str = Field(min_length=1, max_length=60)
    quantity: int = Field(default=1, ge=1, le=50)

    @field_validator("room", "item", mode="before")
    @classmethod
    def clean_text(cls, v):
        return _clean(v)


class HomePlannerRequest(BaseModel):
    budget: float = Field(gt=0, le=100_000_000)
    style: str = Field(default="Modern", max_length=60)
    notes: str = Field(default="", max_length=500)
    items: List[HomeItem] = Field(min_length=1, max_length=30)

    @field_validator("style", "notes", mode="before")
    @classmethod
    def clean_text(cls, v):
        return _clean(v)


class PartyPlannerRequest(BaseModel):
    budget: float = Field(gt=0, le=100_000_000)
    guests: int = Field(ge=1, le=5000)
    event_type: str = Field(default="Birthday", min_length=1, max_length=40)
    venue_type: Literal["home", "hall", "hotel"] = "home"
    venue_details: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=60)
    food_preference: Literal["veg", "non-veg", "both"] = "both"
    notes: str = Field(default="", max_length=500)

    @field_validator("event_type", "venue_details", "city", "notes", mode="before")
    @classmethod
    def clean_text(cls, v):
        return _clean(v)


class JewelryPlannerRequest(BaseModel):
    budget: float = Field(gt=0, le=100_000_000)
    occasion: str = Field(default="Party", min_length=1, max_length=40)
    styles: List[str] = Field(default_factory=list, max_length=8)
    metal: str = Field(default="Any", max_length=40)
    notes: str = Field(default="", max_length=500)
    outfit_image: Optional[str] = None  # saved filename, set by the server

    @field_validator("occasion", "metal", "notes", mode="before")
    @classmethod
    def clean_text(cls, v):
        return _clean(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
