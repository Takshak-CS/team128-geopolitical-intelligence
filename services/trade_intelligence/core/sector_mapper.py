"""Sector catalog, HS product codes, and BACI sector-mapping helpers.

Sectors partition the Harmonized System: every HS92 chapter belongs to exactly
one named sector, so the named sectors add up to ``all``. That keeps sector
comparisons honest (fragility's "share of imports" is a share of the country's
real imports, not of an arbitrary subset) and lets one pass over the raw BACI
files label every product row with a single sector.

Below the sector level an analysis can be narrowed to one product, given as an
HS code of two digits (a chapter, "17" sugars), four (a heading, "1701" cane or
beet sugar), or six (a subheading, "170111" raw cane sugar). The product-level
store that answers those is built by ``scripts/build_cache.py``.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# Sector id -> label, HS chapters, and what it covers. The first three are the
# original sectors and keep their ids, because the orchestrator and saved
# queries use them.
SECTOR_DEFINITIONS: dict[str, dict] = {
    "energy": {
        "label": "Energy",
        "chapters": (27,),
        "description": "Crude oil, refined fuels, natural gas, coal and electricity",
    },
    "agriculture": {
        "label": "Food & agriculture",
        "chapters": tuple(range(1, 25)),
        "description": "Live animals, crops, food, beverages and tobacco",
    },
    "electronics": {
        "label": "Machinery & electronics",
        "chapters": (84, 85, 90),
        "description": "Machinery, computers, semiconductors, telecoms and precision instruments",
    },
    "minerals": {
        "label": "Ores & minerals",
        "chapters": (25, 26),
        "description": "Metal ores, salt, sulphur, stone and cement",
    },
    "chemicals": {
        "label": "Chemicals",
        "chapters": (28, 29, 31, 32, 33, 34, 35, 36, 37, 38),
        "description": "Inorganic and organic chemicals, rare-earth compounds, fertilisers, paints, cosmetics",
    },
    "pharmaceuticals": {
        "label": "Pharmaceuticals",
        "chapters": (30,),
        "description": "Medicines, vaccines, blood products and medical dressings",
    },
    "plastics": {
        "label": "Plastics & rubber",
        "chapters": (39, 40),
        "description": "Plastics in primary forms and articles, natural and synthetic rubber, tyres",
    },
    "metals": {
        "label": "Base metals",
        "chapters": tuple(chapter for chapter in range(72, 84) if chapter != 77),
        "description": "Iron and steel, copper, nickel, aluminium, zinc, tin, cobalt, tungsten",
    },
    "precious_metals": {
        "label": "Precious metals & gems",
        "chapters": (71,),
        "description": "Gold, silver, platinum, diamonds and jewellery",
    },
    "textiles": {
        "label": "Textiles, clothing & leather",
        "chapters": (41, 42, 43) + tuple(range(50, 68)),
        "description": "Fibres, fabrics, apparel, footwear, hides and leather goods",
    },
    "wood_paper": {
        "label": "Wood & paper",
        "chapters": tuple(range(44, 50)),
        "description": "Timber, wood products, pulp, paper and printed matter",
    },
    "vehicles": {
        "label": "Vehicles, aircraft & ships",
        "chapters": (86, 87, 88, 89),
        "description": "Cars and parts, railway equipment, aircraft, spacecraft and ships",
    },
    "arms": {
        "label": "Arms & ammunition",
        "chapters": (93,),
        "description": "Military weapons, firearms, ammunition and parts",
    },
    "manufactures": {
        "label": "Other manufactures",
        "chapters": (68, 69, 70, 91, 92, 94, 95, 96, 97, 99),
        "description": "Glass, ceramics, furniture, toys, watches, art and unclassified goods",
    },
}

SUPPORTED_SECTORS = ("all",) + tuple(SECTOR_DEFINITIONS)
SPECIFIC_SECTORS = tuple(SECTOR_DEFINITIONS)

# The sectors that existed before the catalog was widened. Their prose labels
# ("Energy sector") are kept exactly, since saved claims and tests quote them.
LEGACY_SECTORS = ("energy", "agriculture", "electronics")

CHAPTER_TO_SECTOR: dict[int, str] = {
    chapter: sector
    for sector, definition in SECTOR_DEFINITIONS.items()
    for chapter in definition["chapters"]
}

# Short names for the HS92 chapters, for grouping products in a picker. Chapter
# 77 is reserved in the HS and 98 is unused by BACI.
HS_CHAPTERS: dict[int, str] = {
    1: "Live animals", 2: "Meat and edible offal", 3: "Fish and seafood",
    4: "Dairy, eggs and honey", 5: "Other animal products", 6: "Live plants and flowers",
    7: "Vegetables", 8: "Fruit and nuts", 9: "Coffee, tea and spices", 10: "Cereals",
    11: "Milling products, malt and starch", 12: "Oil seeds, sugar cane and misc. crops",
    13: "Lacs, gums and resins", 14: "Vegetable plaiting materials",
    15: "Animal and vegetable fats and oils", 16: "Meat and fish preparations",
    17: "Sugars and confectionery", 18: "Cocoa and cocoa preparations",
    19: "Cereal, flour and bakery preparations", 20: "Vegetable and fruit preparations",
    21: "Miscellaneous edible preparations", 22: "Beverages, spirits and vinegar",
    23: "Food industry residues and animal feed", 24: "Tobacco",
    25: "Salt, sulphur, earths, stone and cement", 26: "Ores, slag and ash",
    27: "Mineral fuels, oil, gas and coal", 28: "Inorganic chemicals and rare earths",
    29: "Organic chemicals", 30: "Pharmaceutical products", 31: "Fertilisers",
    32: "Tanning and dyeing extracts, paints", 33: "Essential oils, perfumes and cosmetics",
    34: "Soaps, waxes and cleaning products", 35: "Albuminoids, glues and enzymes",
    36: "Explosives and matches", 37: "Photographic goods", 38: "Miscellaneous chemical products",
    39: "Plastics", 40: "Rubber", 41: "Raw hides, skins and leather",
    42: "Leather goods and handbags", 43: "Furskins", 44: "Wood and wood products", 45: "Cork",
    46: "Basketware", 47: "Wood pulp", 48: "Paper and paperboard", 49: "Printed matter",
    50: "Silk", 51: "Wool and animal hair", 52: "Cotton", 53: "Other vegetable textile fibres",
    54: "Man-made filaments", 55: "Man-made staple fibres", 56: "Wadding, felt, twine and ropes",
    57: "Carpets", 58: "Special woven fabrics and lace", 59: "Coated and industrial textiles",
    60: "Knitted fabrics", 61: "Knitted apparel", 62: "Non-knitted apparel",
    63: "Other textile articles and used clothing", 64: "Footwear", 65: "Headgear",
    66: "Umbrellas and walking sticks", 67: "Feathers and artificial flowers",
    68: "Stone, plaster and cement articles", 69: "Ceramics", 70: "Glass and glassware",
    71: "Pearls, precious stones and metals", 72: "Iron and steel",
    73: "Articles of iron or steel", 74: "Copper", 75: "Nickel", 76: "Aluminium", 78: "Lead",
    79: "Zinc", 80: "Tin", 81: "Other base metals (tungsten, cobalt, ...)",
    82: "Tools and cutlery", 83: "Miscellaneous base metal articles",
    84: "Machinery, computers and reactors", 85: "Electrical machinery and electronics",
    86: "Railway equipment", 87: "Vehicles other than railway", 88: "Aircraft and spacecraft",
    89: "Ships and boats", 90: "Optical, medical and precision instruments",
    91: "Clocks and watches", 92: "Musical instruments", 93: "Arms and ammunition",
    94: "Furniture, lighting and prefabricated buildings", 95: "Toys, games and sports equipment",
    96: "Miscellaneous manufactured articles", 97: "Works of art and antiques",
    99: "Commodities not specified",
}

_PRODUCT_PATTERN = re.compile(r"^\d{1,6}$")


def normalize_sector(sector: Optional[str]) -> str:
    """Normalize a sector selection to a supported value."""
    if sector is None:
        return "all"

    normalized = str(sector).strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        return "all"
    if normalized not in SUPPORTED_SECTORS:
        supported = ", ".join(SUPPORTED_SECTORS)
        raise ValueError(f"Unsupported sector '{sector}'. Supported values: {supported}")
    return normalized


def normalize_sector_column(data: pd.DataFrame, column: str = "sector") -> pd.Series:
    """Normalize a sector column to lowercase labels."""
    return data[column].astype(str).str.strip().str.lower().replace({"": "all", "nan": "all", "none": "all"})


def filter_trade_frame_by_sector(data: pd.DataFrame, sector: Optional[str]) -> pd.DataFrame:
    """Filter a normalized trade frame by sector when requested."""
    selected_sector = normalize_sector(sector)
    if selected_sector == "all":
        return data.copy()

    if "sector" not in data.columns:
        raise ValueError("Trade data does not include a sector column for sector-specific filtering.")

    filtered = data[normalize_sector_column(data) == selected_sector].copy()
    if filtered.empty:
        raise ValueError(f"No trade data is available for sector '{selected_sector}'.")
    return filtered.reset_index(drop=True)


def sector_label(sector: Optional[str]) -> str:
    """Short display label for a sector: "Base metals", "All goods"."""
    selected_sector = normalize_sector(sector)
    if selected_sector == "all":
        return "All goods"
    return str(SECTOR_DEFINITIONS[selected_sector]["label"])


def sector_summary_label(sector: Optional[str]) -> str:
    """Return a human-readable label for sector summaries."""
    selected_sector = normalize_sector(sector)
    if selected_sector == "all":
        return "All sectors"
    if selected_sector in LEGACY_SECTORS:
        return f"{selected_sector.title()} sector"
    return f"{sector_label(selected_sector)} sector"


def sector_catalog() -> list[dict]:
    """Every sector with its label, chapters and coverage, for pickers and discovery."""
    rows = [
        {
            "id": "all",
            "label": "All goods",
            "chapters": [],
            "description": "Every product in the BACI HS92 dataset",
        }
    ]
    for sector, definition in SECTOR_DEFINITIONS.items():
        rows.append(
            {
                "id": sector,
                "label": definition["label"],
                "chapters": [f"{chapter:02d}" for chapter in definition["chapters"]],
                "description": definition["description"],
            }
        )
    return rows


def sector_for_chapter(chapter: int) -> str:
    """The sector an HS chapter belongs to; unknown chapters count as other manufactures."""
    return CHAPTER_TO_SECTOR.get(int(chapter), "manufactures")


def baci_sector_mask(product_codes: pd.Series, sector: Optional[str]) -> pd.Series:
    """Return a boolean mask for BACI product codes belonging to a sector."""
    selected_sector = normalize_sector(sector)
    if selected_sector == "all":
        return pd.Series(True, index=product_codes.index)

    numeric_codes = pd.to_numeric(product_codes, errors="coerce").fillna(-1).astype(int)
    chapters = numeric_codes // 10000
    return chapters.isin(SECTOR_DEFINITIONS[selected_sector]["chapters"])


def sector_labels_for_chapters(chapters: pd.Series) -> pd.Series:
    """Map HS chapter numbers onto sector ids, one per row, vectorized."""
    lookup = pd.Series(CHAPTER_TO_SECTOR)
    return chapters.map(lookup).fillna("manufactures").astype("object")


def normalize_product(code: object) -> Optional[str]:
    """Normalize an HS code to 2, 4 or 6 digits, or None when none was given.

    Accepts "1701", "17.01", "1701.11", "170111" and numbers that lost their
    leading zero to a spreadsheet ("10111" is heading 0101 subheading 11).
    """
    if code is None:
        return None
    text = str(code).strip().replace(".", "").replace(" ", "")
    if not text:
        return None
    if not _PRODUCT_PATTERN.match(text):
        raise ValueError(
            f"Product '{code}' is not an HS code. Give 2 digits for a chapter (17), "
            f"4 for a heading (1701) or 6 for a subheading (170111)."
        )
    if len(text) % 2:
        text = text.zfill(len(text) + 1)
    if int(text[:2]) not in HS_CHAPTERS:
        raise ValueError(f"HS chapter '{text[:2]}' does not exist in the HS92 nomenclature.")
    return text


def product_code_range(code: str) -> tuple[int, int]:
    """Inclusive range of six-digit BACI product codes an HS code covers."""
    normalized = normalize_product(code)
    if normalized is None:
        raise ValueError("A product code is required.")
    padding = 6 - len(normalized)
    low = int(normalized) * (10 ** padding)
    high = low + (10 ** padding) - 1
    return low, high


def sector_for_product(code: str) -> str:
    """The sector a product's chapter belongs to."""
    normalized = normalize_product(code)
    if normalized is None:
        raise ValueError("A product code is required.")
    return sector_for_chapter(int(normalized[:2]))
