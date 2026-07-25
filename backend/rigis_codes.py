"""
РИГИС code books: lithology, reservoir (collector) and saturation.

Russian interpreted LAS carry categorical columns (ЛИТОЛОГИЯ / КОЛЛЕКТОР /
НАСЫЩЕНИЕ) whose values are numeric codes. This module maps those codes to
their Russian name, an English name and a drawing style so the viewer can
render a proper lithology column (brick = limestone, dots = sandstone, …) and
show the name under the cursor.

`pattern` is a small vocabulary the frontend knows how to draw:
    sand, silt, clay, shale, limestone, dolomite, marl, carbonate, gypsum,
    anhydrite, coal, salt, crystalline, conglomerate, weathered, bitumen, none
"""
from __future__ import annotations

from typing import Dict, Optional

# ── Lithology ────────────────────────────────────────────────────────────────
LITHOLOGY: Dict[int, dict] = {
    5:   {"ru": "Песчаник", "en": "Sandstone", "pattern": "sand", "color": "#e8c56a"},
    6:   {"ru": "Алевролит", "en": "Siltstone", "pattern": "silt", "color": "#c8b98a"},
    7:   {"ru": "Аргиллит", "en": "Argillite", "pattern": "shale", "color": "#7f8c8d"},
    8:   {"ru": "Известняк", "en": "Limestone", "pattern": "limestone", "color": "#7fd4e8"},
    9:   {"ru": "Доломит", "en": "Dolomite", "pattern": "dolomite", "color": "#9fd3b0"},
    10:  {"ru": "Мергель", "en": "Marl", "pattern": "marl", "color": "#a9c7a0"},
    11:  {"ru": "Карбонатная порода", "en": "Carbonate rock", "pattern": "carbonate", "color": "#8fd0dd"},
    12:  {"ru": "Гипс", "en": "Gypsum", "pattern": "gypsum", "color": "#d9c2e8"},
    13:  {"ru": "Ангидрит", "en": "Anhydrite", "pattern": "anhydrite", "color": "#c9a7e0"},
    15:  {"ru": "Уголь", "en": "Lignite", "pattern": "coal", "color": "#2f3640"},
    16:  {"ru": "Соль каменная", "en": "Rock salt", "pattern": "salt", "color": "#f0e6d2"},
    17:  {"ru": "Кристаллическая порода", "en": "Crystalline rock", "pattern": "crystalline", "color": "#b0a08a"},
    18:  {"ru": "Песчаник глинистый", "en": "Argillaceous sandstone", "pattern": "sand_clay", "color": "#d8bd7e"},
    19:  {"ru": "Известняк доломитизированный", "en": "Dolomitic limestone", "pattern": "limestone_dol", "color": "#8ed2d8"},
    20:  {"ru": "Доломит известковистый", "en": "Limy dolomite", "pattern": "dolomite", "color": "#a6d6bb"},
    21:  {"ru": "Известняк глинистый", "en": "Marlstone", "pattern": "limestone_clay", "color": "#93c6d0"},
    22:  {"ru": "Доломит глинистый", "en": "Argillaceous dolomite", "pattern": "dolomite_clay", "color": "#9cc3ac"},
    23:  {"ru": "Известняк сульфатизированный", "en": "Sulphatized limestone", "pattern": "limestone", "color": "#a8cfe0"},
    24:  {"ru": "Доломит сульфатизированный", "en": "Sulphatized dolomite", "pattern": "dolomite", "color": "#a8ccbb"},
    39:  {"ru": "Песчаник карбонатизированный", "en": "Carbonated sandstone", "pattern": "sand_carb", "color": "#dfc98d"},
    44:  {"ru": "Глины битуминозные", "en": "Bituminous clays", "pattern": "bitumen", "color": "#5d4b3a"},
    46:  {"ru": "Ангидрит глинистый", "en": "Clayey anhydrite", "pattern": "anhydrite", "color": "#bfa3d2"},
    47:  {"ru": "Известняк глинистый сульфатиз.", "en": "Sulphatized marlstone", "pattern": "limestone_clay", "color": "#9ac3d0"},
    48:  {"ru": "Известняк доломитиз. сульфат.", "en": "Sulphatized dolomitic limestone", "pattern": "limestone_dol", "color": "#93cdd4"},
    49:  {"ru": "Известняк глин. доломитиз.", "en": "Dolomitic marlstone", "pattern": "limestone_dol", "color": "#96c9cf"},
    50:  {"ru": "Доломит глинистый сульфатиз.", "en": "Sulphatized argillaceous dolomite", "pattern": "dolomite_clay", "color": "#9ec6b0"},
    51:  {"ru": "Известняк битумин.", "en": "Bituminous limestone", "pattern": "bitumen", "color": "#6d7f86"},
    52:  {"ru": "Известняк глин. битум.", "en": "Bituminous marlstone", "pattern": "bitumen", "color": "#66757c"},
    86:  {"ru": "Доломит известков. глинист.", "en": "Argillo-calcareous dolomite", "pattern": "dolomite_clay", "color": "#a2c9b4"},
    90:  {"ru": "Кора выветривания", "en": "Weathering crust", "pattern": "weathered", "color": "#b98f6b"},
    91:  {"ru": "Песчано-алевролит", "en": "Siltstoned sandstone", "pattern": "sand_silt", "color": "#dcc78d"},
    92:  {"ru": "Песчано-алевролит уплотнённый", "en": "Compacted siltstoned sandstone", "pattern": "sand_silt", "color": "#cdb87e"},
    93:  {"ru": "Алевролит глинистый уплотнённый", "en": "Compacted argillaceous siltstone", "pattern": "silt_clay", "color": "#bfae83"},
    94:  {"ru": "Глина", "en": "Clay", "pattern": "clay", "color": "#8d8577"},
    95:  {"ru": "Конгломераты", "en": "Conglomerates", "pattern": "conglomerate", "color": "#c0a080"},
    104: {"ru": "Песчаник полимиктовый", "en": "Polymictic sandstone", "pattern": "sand", "color": "#e3c377"},
}

# ── Reservoir / collector ────────────────────────────────────────────────────
COLLECTOR: Dict[int, dict] = {
    1:  {"ru": "Коллектор", "en": "Reservoir", "color": "#3fb950"},
    2:  {"ru": "Неколлектор", "en": "No reservoir", "color": "#484f58"},
    4:  {"ru": "Не оценено", "en": "Not estimated", "color": "#6e7681"},
    74: {"ru": "Возможный коллектор", "en": "Possible reservoir", "color": "#9ad86a"},
}

# ── Saturation ───────────────────────────────────────────────────────────────
SATURATION: Dict[int, dict] = {
    4:   {"ru": "Не оценено", "en": "Not estimated", "color": "#6e7681"},
    26:  {"ru": "Нефтенасыщ.", "en": "Oil-saturated", "color": "#8b5a2b"},
    27:  {"ru": "Газонасыщ.", "en": "Gas-saturated", "color": "#e74c3c"},
    28:  {"ru": "Водонасыщ.", "en": "Water-saturated", "color": "#3498db"},
    29:  {"ru": "Битумонасыщ.", "en": "Bitumen-saturated", "color": "#4b3621"},
    30:  {"ru": "Обводнённый", "en": "Water-encroached", "color": "#5dade2"},
    31:  {"ru": "Обводнен. пресн. вод.", "en": "Fresh water-encroached", "color": "#85c1e9"},
    32:  {"ru": "Без насыщения", "en": "Unsaturated", "color": "#566573"},
    33:  {"ru": "Неясно", "en": "Not clear", "color": "#7f8c8d"},
    34:  {"ru": "Нефтеводонасыщ.", "en": "Oil and water-saturated", "color": "#a9743f"},
    35:  {"ru": "Газоводонасыщ.", "en": "Gas and water-saturated", "color": "#e59866"},
    36:  {"ru": "Водонефтенасыщ.", "en": "Water and oil-saturated", "color": "#7fa6c9"},
    37:  {"ru": "Водогазонасыщ.", "en": "Water and gas-saturated", "color": "#76b7d1"},
    38:  {"ru": "Насыщение не оценено", "en": "Saturation not estimated", "color": "#6e7681"},
    88:  {"ru": "Нефтегазонасыщ.", "en": "Oil and gas-saturated", "color": "#c0672c"},
    89:  {"ru": "Газоконденсат", "en": "Gas condensate", "color": "#ec7063"},
    96:  {"ru": "Слабонефтенасыщ.", "en": "Weakly oil-saturated", "color": "#b08050"},
    97:  {"ru": "Остаточное нефтенасыщ.", "en": "Residual oil", "color": "#96704a"},
    98:  {"ru": "Газо- или нефтенасыщ.", "en": "Gas or oil saturated", "color": "#d3743c"},
    99:  {"ru": "Слабогазонасыщ.", "en": "Weakly gas-saturated", "color": "#ef9a8a"},
    508: {"ru": "Возможно газонасыщенный", "en": "Possibly gas-saturated", "color": "#f1948a"},
    510: {"ru": "Возможно нефтенасыщ.", "en": "Possibly oil-saturated", "color": "#bf8a5d"},
}

_BOOKS = {"lithology": LITHOLOGY, "collector": COLLECTOR, "saturation": SATURATION}


def lookup(book: str, code) -> Optional[dict]:
    """Resolve a numeric code in one of the code books."""
    table = _BOOKS.get(book)
    if table is None or code is None:
        return None
    try:
        c = int(round(float(code)))
    except (TypeError, ValueError):
        return None
    hit = table.get(c)
    if hit:
        return {"code": c, **hit}
    # Unknown code — still render it, labelled by number.
    return {"code": c, "ru": f"код {c}", "en": f"code {c}",
            "pattern": "none", "color": "#30363d"}


def codebook(book: str) -> dict:
    table = _BOOKS.get(book) or {}
    return {str(k): {"code": k, **v} for k, v in table.items()}


def all_codebooks() -> dict:
    return {name: codebook(name) for name in _BOOKS}
