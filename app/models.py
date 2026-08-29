from enum import StrEnum

from pydantic import BaseModel


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


class Targeting(BaseModel):
    industries: list[Industry]
    roles: list[Role]
    company_sizes: list[CompanySize]
    regions: list[Region]


class Creative(BaseModel):
    headline: str
    body: str
    cta: str


class LandingPage(BaseModel):
    headline: str
    body: str
    cta: str
    price: str | None


class Campaign(BaseModel):
    company: str
    targeting: Targeting
    ad: Creative
    page: LandingPage
