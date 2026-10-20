"""Static reference data: states, NM counties, TEFAP income limits."""
from __future__ import annotations

from typing import Literal

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

NM_COUNTIES: list[str] = [
    "Bernalillo", "Catron", "Chaves", "Cibola", "Colfax", "Curry", "De Baca",
    "Doña Ana", "Eddy", "Grant", "Guadalupe", "Harding", "Hidalgo", "Lea",
    "Lincoln", "Los Alamos", "Luna", "McKinley", "Mora", "Otero", "Quay",
    "Rio Arriba", "Roosevelt", "Sandoval", "San Juan", "San Miguel", "Santa Fe",
    "Sierra", "Socorro", "Taos", "Torrance", "Union", "Valencia",
]

# ---- TEFAP gross income limits (NM TEFAP/USDA Foods, Federal 2026) ----------
# Copied from the paper form. Update here when the state publishes new limits;
# each saved record keeps a snapshot of the limit that applied when it signed.
IncomePeriod = Literal["annual", "monthly", "weekly"]
INCOME_PERIODS: tuple[IncomePeriod, ...] = ("annual", "monthly", "weekly")
TEFAP_LIMITS_YEAR = 2026
TEFAP_LIMITS: dict[int, tuple[int, int, int]] = {
    1: (29_526, 2_461, 568),
    2: (40_034, 3_337, 770),
    3: (50_542, 4_212, 972),
    4: (61_050, 5_088, 1_175),
    5: (71_558, 5_964, 1_377),
    6: (82_066, 6_839, 1_579),
    7: (92_574, 7_715, 1_781),
    8: (103_082, 8_591, 1_983),
}
TEFAP_ADDITIONAL: tuple[int, int, int] = (10_508, 876, 203)


def tefap_limit(household_size: int, period: IncomePeriod) -> int:
    """Gross income limit for a household size and period (9+ uses the 'each additional' rule)."""
    if household_size < 1:
        raise ValueError("household size must be >= 1")
    idx = INCOME_PERIODS.index(period)
    if household_size <= 8:
        return TEFAP_LIMITS[household_size][idx]
    return TEFAP_LIMITS[8][idx] + (household_size - 8) * TEFAP_ADDITIONAL[idx]
