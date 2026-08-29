from enum import StrEnum

from pydantic import BaseModel, field_validator


class Industry(StrEnum):
    MANUFACTURING = "manufacturing"
    TECHNOLOGY = "technology"
    EDUCATION = "education"


class Role(StrEnum):
    PLANT_MANAGER = "plant_manager"
    OPERATIONS_MANAGER = "operations_manager"
    ENGINEER = "engineer"
    STUDENT = "student"


class CompanySize(StrEnum):
    SMALL = "1-49"
    MEDIUM = "50-249"
    LARGE = "250+"


class Region(StrEnum):
    EUROPE = "europe"
    NORTH_AMERICA = "north_america"
    LATIN_AMERICA = "latin_america"


def _as_str(value) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)


class Targeting(BaseModel):
    industries: list[str]
    roles: list[str]
    company_sizes: list[str]
    regions: list[str]

    @field_validator("industries", "roles", "company_sizes", "regions", mode="before")
    @classmethod
    def coerce_str_list(cls, value):
        if not isinstance(value, list):
            return value
        return [_as_str(item) for item in value]


class Creative(BaseModel):
    headline: str
    body: str
    cta: str


class Email(BaseModel):
    subject: str
    body: str


class LandingPage(BaseModel):
    headline: str
    body: str = ""
    bullets: list[str] = []
    proof: str | None = None
    highlight: str | None = None
    cta: str
    price: str | None


class Campaign(BaseModel):
    company: str
    targeting: Targeting
    ad: Creative
    page: LandingPage
    email: Email | None = None
