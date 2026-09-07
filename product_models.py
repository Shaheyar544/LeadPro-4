"""The deliberately small U.S. V0.1 search contract."""
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

_STATE_NAMES = """AL|Alabama
AK|Alaska
AZ|Arizona
AR|Arkansas
CA|California
CO|Colorado
CT|Connecticut
DE|Delaware
FL|Florida
GA|Georgia
HI|Hawaii
ID|Idaho
IL|Illinois
IN|Indiana
IA|Iowa
KS|Kansas
KY|Kentucky
LA|Louisiana
ME|Maine
MD|Maryland
MA|Massachusetts
MI|Michigan
MN|Minnesota
MS|Mississippi
MO|Missouri
MT|Montana
NE|Nebraska
NV|Nevada
NH|New Hampshire
NJ|New Jersey
NM|New Mexico
NY|New York
NC|North Carolina
ND|North Dakota
OH|Ohio
OK|Oklahoma
OR|Oregon
PA|Pennsylvania
RI|Rhode Island
SC|South Carolina
SD|South Dakota
TN|Tennessee
TX|Texas
UT|Utah
VT|Vermont
VA|Virginia
WA|Washington
WV|West Virginia
WI|Wisconsin
WY|Wyoming
DC|District of Columbia"""
US_STATES = {}
for _line in _STATE_NAMES.splitlines():
    _code, _name = _line.split("|")
    US_STATES[_code.lower()] = _code
    US_STATES[_name.lower()] = _code


class LeadGenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=2, max_length=50)
    target_count: int = Field(ge=1, le=100, strict=True)
    opportunity_profile: Literal["website_conversion"]

    @field_validator("category", "city", "state", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if not isinstance(value, str):
            raise ValueError("Must be text")
        if len(value) > 200:
            raise ValueError("Value is too long")
        if any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("Control and invisible format characters are not allowed")
        return " ".join(value.split())

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value):
        normalized = US_STATES.get(value.lower())
        if normalized is None:
            raise ValueError("Enter a U.S. state name or two-letter abbreviation (or DC)")
        return normalized
