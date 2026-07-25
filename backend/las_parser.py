"""
LAS (Log ASCII Standard) file parser for oil & gas well log data.

Supports LAS 2.0 format — the industry standard for wireline log data.
Parses: version, well info, curve definitions, parameters, and data.
"""
import re
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, TextIO
import io


# Normalize vendor mnemonics into canonical families used by the app
CURVE_ALIASES = {
    # Depth/index
    'DEPTH': 'DEPT',

    # Caliper
    'CALI': 'CAL',
    'HCAL': 'CAL',
    'DCAL': 'CAL',

    # Gamma Ray family
    'GRGC': 'GR',       # KGS: GR corrected
    'CGR': 'GR',        # Corrected GR
    'SGR': 'GR',        # Spectral GR

    # Resistivity family (canonical deep target)
    'RESD': 'RT',
    'ILD': 'RILD',
    'RILD': 'RILD',
    'RILM': 'RILM',
    'RES': 'RT',
    'CILD': 'RT',       # KGS: Conductivity converted
    'CILM': 'RILM',     # KGS: Medium conductivity
    'RLL3': 'RLL3',
    'RXORT': 'RXO',

    # Sonic family
    'DTP': 'DT',
    'DT35': 'DT',       # KGS: DT variant
    'SPOR': 'DT',       # KGS: Sonic porosity (proxy)

    # Density family
    'DEN': 'RHOB',      # KGS: Density
    'DPOR': 'DPOR',     # KGS: Density porosity (separate track)
    'CNLS': 'NPHI',     # KGS: Compensated neutron → neutron porosity
    'NPRL': 'NPHI',     # KGS: Neutron porosity
    'RHOC': 'RHOB',     # Corrected density
    'DGA': 'DGA',       # KGS: Density (gamma-gamma) — keep separate

    # SP family
    'SPCG': 'SP',       # KGS: SP corrected
    'SPRL': 'SP',       # KGS: SP

    # Misc
    'CLDC': 'CAL',      # KGS: Caliper
    'DCOR': 'DRHO',     # KGS: Density correction
    'PDPE': 'PE',       # KGS: Photoelectric
    'DPRL': 'NPHI',     # KGS: Density porosity (neutron proxy)
    'FEFE': 'PE',       # KGS: Iron/PE

    # Common no-op canonical mnemonics (explicit for readability)
    'GR': 'GR',
    'SP': 'SP',
    'SPC': 'SP',
    'CAL': 'CAL',
    'RT': 'RT',
    'RXO': 'RXO',
    'NPHI': 'NPHI',
    'RHOB': 'RHOB',
    'DT': 'DT',
    'PE': 'PE',
    'PEF': 'PE',
    'DRHO': 'DRHO',
    'DPOR': 'DPOR',
    'DGA': 'DGA',
    'MI': 'MI',
    'MN': 'MN',
}

# Additional curve track configs for non-standard canonical names
EXTRA_CURVE_TRACKS = {
    'DPOR': {'track': 6, 'color': '#f39c12', 'scale': (0.45, -0.15), 'unit': 'PU', 'name': 'Density Porosity'},
    'DGA':  {'track': 6, 'color': '#e67e22', 'scale': (1.95, 2.95), 'unit': 'GM/CC', 'name': 'Gamma-Gamma Density'},
    'RLL3': {'track': 3, 'color': '#f39c12', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Laterolog 3'},
    'RILM': {'track': 3, 'color': '#e67e22', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Medium Induction'},
    'DTS':  {'track': 6, 'color': '#16a085', 'scale': (240, 40), 'unit': 'US/F', 'name': 'Shear Sonic'},
    'PE':   {'track': 6, 'color': '#8e44ad', 'scale': (0, 10), 'unit': 'B/E', 'name': 'Photoelectric'},
    'SP':   {'track': 1, 'color': '#9b59b6', 'scale': (-160, 40), 'unit': 'MV', 'name': 'Spontaneous Potential'},
    'TEMP': {'track': 1, 'color': '#e84393', 'scale': (0, 200), 'unit': 'DEGC', 'name': 'Temperature'},
    'MSFL': {'track': 4, 'color': '#f39c12', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Micro-SFL'},
}


# ── Auto-extend the alias table from the logging-method registry ─────────────
# The method registry (backend/methods.py) is the broader source of truth for
# vendor mnemonic → canonical family. We fold in any alias it knows that the
# curated table above does not already define, so newly recognized methods flow
# through the parser without overriding hand-tuned behaviour.
try:
    from methods import ALIAS_TO_CANONICAL as _METHOD_ALIASES
except ImportError:  # pragma: no cover - package-relative import
    from backend.methods import ALIAS_TO_CANONICAL as _METHOD_ALIASES

for _raw, _canon in _METHOD_ALIASES.items():
    CURVE_ALIASES.setdefault(_raw, _canon)

DEPTH_CANDIDATES = ('DEPT', 'DEPTH', 'MD', 'TVD')


@dataclass
class LASCurve:
    """Curve definition from ~C section."""
    mnemonic: str       # как в файле: "GK", "GZ1", "МПЗ" — имя не переписываем
    unit: str           # e.g. "GAPI", "G/C3", "V/V"
    value: str          # API code or description
    description: str    # full description
    canonical: str = "" # нормализованное имя для подбора трека/метода

    def __repr__(self):
        return f"LASCurve({self.mnemonic}, {self.unit})"


@dataclass
class LASParameter:
    """Parameter from ~P section."""
    mnemonic: str
    unit: str
    value: str
    description: str


@dataclass
class LASWell:
    """Well header info from ~W section."""
    start: float = 0.0
    stop: float = 0.0
    step: float = 0.0
    null: float = -999.25
    well_name: str = ""
    uwi: str = ""           # Unique Well Identifier
    field: str = ""
    location: str = ""
    province: str = ""
    country: str = ""
    operator: str = ""
    service_company: str = ""
    date: str = ""
    api: str = ""
    x: Optional[float] = None          # X устья из шапки (~W X)
    y: Optional[float] = None          # Y устья из шапки (~W Y)
    rkb: Optional[float] = None        # альтитуда стола ротора (RKB / KB / EREF / ALT)
    depth_unit: str = ""               # единица индекса из STRT/STOP (M или FT)

    def __repr__(self):
        return f"LASWell({self.well_name}, {self.uwi})"


@dataclass
class LASFile:
    """Parsed LAS file."""
    version: str = "2.0"
    well: LASWell = field(default_factory=LASWell)
    curves: List[LASCurve] = field(default_factory=list)
    parameters: List[LASParameter] = field(default_factory=list)
    data: Dict[str, np.ndarray] = field(default_factory=dict)
    depth_key: str = ""     # mnemonic of the depth/index curve

    @property
    def depth(self) -> np.ndarray:
        """Get the depth array."""
        if self.depth_key and self.depth_key in self.data:
            return self.data[self.depth_key]
        return np.array([])

    @property
    def curve_names(self) -> List[str]:
        """Get list of curve mnemonics (excluding depth)."""
        return [c.mnemonic for c in self.curves if c.mnemonic != self.depth_key]

    def get_curve(self, mnemonic: str) -> Optional[np.ndarray]:
        """Get curve data by mnemonic."""
        return self.data.get(mnemonic)

    def to_dict(self) -> dict:
        """Serialize for JSON response."""
        return {
            "version": self.version,
            "well": {
                "name": self.well.well_name,
                "uwi": self.well.uwi,
                "field": self.well.field,
                "location": self.well.location,
                "operator": self.well.operator,
                "date": self.well.date,
                "start": self.well.start,
                "stop": self.well.stop,
                "step": self.well.step,
                "null": self.well.null,
                "x": self.well.x,
                "y": self.well.y,
                "rkb": self.well.rkb,
                "depth_unit": self.well.depth_unit,
            },
            "curves": [
                {
                    "mnemonic": c.mnemonic,
                    "unit": c.unit,
                    "description": c.description,
                    "canonical": c.canonical or c.mnemonic,
                }
                for c in self.curves
            ],
            "parameters": [
                {"mnemonic": p.mnemonic, "value": p.value, "unit": p.unit}
                for p in self.parameters
            ],
            "depth_key": self.depth_key,
            "num_points": len(self.depth),
        }


class LASParser:
    """
    Parse LAS 2.0/3.0 files.

    LAS format sections:
        ~V - Version info
        ~W - Well info (start, stop, step, null, well name, etc.)
        ~C - Curve definitions
        ~P - Parameters
        ~A - Data (ASCII)
        ~O - Other (comments)

    Also handles non-standard sections (KGS, IQ, Tops, etc.)
    and comma-delimited LAS 3.0 files.
    """

    # Regex to parse a LAS line: mnemonic.unit value : description
    # Mnemonic accepts Latin AND Cyrillic letters (Ѐ-ӿ) so Russian
    # ГИС mnemonics (ГК, ПС, НГК, ГГКп, АК, ДС, БК ...) parse correctly.
    LINE_RE = re.compile(
        r'^\s*(?P<mnemonic>[A-Za-z0-9_\-Ѐ-ӿ]+)'  # mnemonic (Latin+Cyrillic, no dots)
        r'\s*(?:\.(?P<unit>[^\s:]*))?'            # optional .unit (supports "MNEM.UNIT" and "MNEM .UNIT")
        r'\s*(?P<value>[^:]*)'                     # optional/empty value before colon
        r'(?::\s*(?P<description>.*))?$'           # optional : description
    )

    # Candidate encodings tried in order when decoding raw LAS bytes. Russian
    # field files are frequently CP1251 or CP866 rather than UTF-8.
    ENCODINGS = ('utf-8-sig', 'utf-8', 'cp1251', 'cp866', 'iso-8859-5', 'latin-1')

    @staticmethod
    def decode_bytes(data: bytes) -> str:
        """Decode LAS bytes, auto-detecting UTF-8 / Cyrillic code pages.

        UTF-8 wins when valid. Otherwise the single-byte candidates are scored:
        CP1251 and CP866 both decode almost any byte, so picking the first that
        "works" mis-decodes DOS-encoded (CP866) Russian files into mojibake.
        We therefore score by how plausibly Cyrillic the result looks.
        """
        if isinstance(data, str):
            return data
        for enc in ("utf-8-sig", "utf-8"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                pass

        # Header region carries the mnemonics/descriptions we care about.
        head = data[:20000]

        def score(text: str) -> int:
            s = 0
            for ch in text:
                o = ord(ch)
                if 0x0410 <= o <= 0x044F or ch in "Ёё":       # Cyrillic letters
                    s += 2
                elif 0x0402 <= o <= 0x040F or 0x2010 <= o <= 0x2122:
                    s -= 2                                     # rare/mojibake glyphs
                elif 0x2500 <= o <= 0x25FF:
                    s -= 1                                     # box-drawing (CP866 noise)
            return s

        best, best_score = None, None
        for enc in ("cp1251", "cp866", "koi8-r", "iso-8859-5"):
            try:
                text = head.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
            sc = score(text)
            if best_score is None or sc > best_score:
                best, best_score = enc, sc
        if best:
            return data.decode(best, errors="replace")
        return data.decode("latin-1", errors="replace")

    @staticmethod
    def parse_file(filepath: str) -> LASFile:
        """Parse a LAS file from disk (encoding auto-detected)."""
        with open(filepath, 'rb') as f:
            return LASParser.parse_bytes(f.read())

    @staticmethod
    def parse_bytes(data: bytes) -> LASFile:
        """Parse a LAS file from raw bytes with encoding auto-detection."""
        return LASParser.parse_string(LASParser.decode_bytes(data))

    @staticmethod
    def parse_string(content: str) -> LASFile:
        """Parse a LAS file from string content."""
        return LASParser.parse(io.StringIO(content))

    @staticmethod
    def _canonical_mnemonic(mnemonic: str) -> str:
        m = (mnemonic or '').strip().upper()
        # User-defined custom aliases take precedence over built-ins. Looked up
        # live so mappings taught at runtime affect subsequent uploads.
        try:
            import methods as _methods
        except ImportError:  # pragma: no cover
            from backend import methods as _methods
        if m in _methods.CUSTOM_ALIASES:
            return _methods.CUSTOM_ALIASES[m]
        return CURVE_ALIASES.get(m, m)

    @staticmethod
    def parse(f: TextIO) -> LASFile:
        """Parse a LAS file from a file-like object."""
        result = LASFile()
        current_section = None
        in_curve_section = False   # True only while inside ~C section
        data_lines = []
        wrap = False
        delimiter = None  # None = whitespace (default), ',' = comma, '\t' = tab

        for line in f:
            line = line.rstrip('\n\r')

            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Section header — ANY ~X line ends the previous section
            if stripped.startswith('~'):
                section_char = stripped[1].upper() if len(stripped) > 1 else ''
                if section_char == 'V':
                    current_section = 'version'
                elif section_char == 'W':
                    current_section = 'well'
                elif section_char == 'C':
                    current_section = 'curves'
                    in_curve_section = True
                elif section_char == 'P':
                    current_section = 'parameters'
                    in_curve_section = False
                elif section_char == 'A':
                    current_section = 'data'
                    in_curve_section = False
                    if 'WRAP' in stripped.upper() or 'YES' in stripped.upper():
                        wrap = True
                elif section_char == 'O':
                    current_section = 'other'
                    in_curve_section = False
                else:
                    # Non-standard section (Tops, IQ, Geo_Report, etc.)
                    # Treat as unknown — don't continue parsing as curves
                    current_section = 'unknown'
                    in_curve_section = False
                continue

            # Parse based on current section
            if current_section == 'data':
                data_lines.append(stripped)
            elif current_section in ('version', 'well', 'curves', 'parameters'):
                match = LASParser.LINE_RE.match(stripped)
                if match:
                    mnemonic = LASParser._canonical_mnemonic(match.group('mnemonic'))
                    unit = (match.group('unit') or '').strip()
                    value = (match.group('value') or '').strip()
                    description = (match.group('description') or '').strip()

                    if current_section == 'version':
                        if mnemonic.upper() == 'VERS':
                            result.version = value
                        elif mnemonic.upper() == 'WRAP':
                            wrap = value.upper() == 'YES'
                        elif mnemonic.upper() == 'DLM':
                            # LAS 3.0 delimiter
                            dl = value.strip().upper()
                            if dl == 'COMMA':
                                delimiter = ','
                            elif dl == 'TAB':
                                delimiter = '\t'

                    elif current_section == 'well':
                        LASParser._parse_well_field(result.well, mnemonic, value, unit)

                    elif current_section == 'curves' and in_curve_section:
                        # Only accept valid curve mnemonics (must start with a
                        # letter, not numeric-only).
                        raw_mnem = (match.group('mnemonic') or '').strip().upper()
                        canonical = mnemonic.upper()
                        if raw_mnem and raw_mnem[0].isalpha():
                            existing = {c.mnemonic for c in result.curves}
                            # Имя кривой оставляем как в файле — геолог ищет на
                            # планшете GZ1..GZ5 и МПЗ, а не переименованные
                            # канонические имена. Нормализованное имя хранится
                            # отдельно и используется для подбора трека/метода.
                            name = raw_mnem
                            if name in existing:
                                i = 2
                                while f"{name}_{i}" in existing:
                                    i += 1
                                name = f"{name}_{i}"
                            result.curves.append(LASCurve(
                                mnemonic=name,
                                unit=unit,
                                value=value,
                                description=description,
                                canonical=canonical,
                            ))

                    elif current_section == 'parameters':
                        result.parameters.append(LASParameter(
                            mnemonic=mnemonic,
                            unit=unit,
                            value=value,
                            description=description,
                        ))

        # Set depth key with fallback: DEPT/DEPTH/MD/TVD, else first curve
        if result.curves:
            mnems = [c.mnemonic for c in result.curves]
            result.depth_key = next((m for m in DEPTH_CANDIDATES if m in mnems), result.curves[0].mnemonic)

        # Parse data section
        LASParser._parse_data(result, data_lines, wrap, delimiter)

        return result

    @staticmethod
    def _parse_well_field(well: LASWell, mnemonic: str, value: str, unit: str = ""):
        """Map ~W fields to LASWell attributes."""
        up = mnemonic.upper()

        # Единица глубины берётся из STRT/STOP/STEP — по ней определяем метры/футы.
        if up in ('STRT', 'STOP', 'STEP') and unit and not well.depth_unit:
            u = unit.strip().upper().lstrip('.')
            if u.startswith('M'):
                well.depth_unit = 'M'
            elif u.startswith('F'):
                well.depth_unit = 'FT'

        # Координаты устья и альтитуда — часто есть прямо в шапке (RMS-экспорт).
        _geo = {'X': 'x', 'XCOORD': 'x', 'X_COORD': 'x', 'XWELL': 'x',
                'Y': 'y', 'YCOORD': 'y', 'Y_COORD': 'y', 'YWELL': 'y',
                'RKB': 'rkb', 'KB': 'rkb', 'EKB': 'rkb', 'EREF': 'rkb',
                'ELEV': 'rkb', 'ALT': 'rkb', 'APD': 'rkb', 'GL': 'rkb'}
        if up in _geo:
            try:
                num = float(str(value).replace(',', '.'))
            except (TypeError, ValueError):
                num = None
            if num is not None and getattr(well, _geo[up]) is None:
                setattr(well, _geo[up], num)
            return

        mapping = {
            'STRT': 'start',
            'STOP': 'stop',
            'STEP': 'step',
            'NULL': 'null',
            'WELL': 'well_name',
            'UWI': 'uwi',
            'UWI1': 'uwi',
            'FLD': 'field',
            'LOC': 'location',
            'PROV': 'province',
            'CTRY': 'country',
            'OPER': 'operator',
            'SRVC': 'service_company',
            'DATE': 'date',
            'API': 'api',
        }
        attr = mapping.get(up)
        if attr:
            if attr in ('start', 'stop', 'step', 'null'):
                try:
                    setattr(well, attr, float(value))
                except ValueError:
                    pass
            else:
                setattr(well, attr, value)

    @staticmethod
    def _parse_data(las: LASFile, data_lines: List[str], wrap: bool, delimiter=None):
        """Parse the ~A data section into numpy arrays."""
        num_curves = len(las.curves)
        if num_curves == 0 or not data_lines:
            return

        def split_line(line: str) -> list:
            """Split a data line using the detected delimiter or whitespace.

            Russian РИГИС exports write categorical codes as quoted strings
            (e.g. "94", "" for a blank), so quotes are stripped here — otherwise
            lithology/collector/saturation columns parse as all-NaN.
            """
            parts = line.split(delimiter) if delimiter else line.split()
            return [p.strip().strip('"').strip("'") for p in parts]

        if wrap:
            # Wrapped format: data continues on next line
            all_values = []
            current_row = []
            for line in data_lines:
                values = split_line(line)
                current_row.extend(values)
                if len(current_row) >= num_curves:
                    all_values.append(current_row[:num_curves])
                    current_row = current_row[num_curves:]
        else:
            all_values = []
            for line in data_lines:
                values = split_line(line)
                if len(values) >= num_curves:
                    all_values.append(values[:num_curves])

        if not all_values:
            return

        # Convert to numpy arrays
        for i, curve in enumerate(las.curves):
            try:
                col_data = []
                for row in all_values:
                    try:
                        col_data.append(float(row[i]))
                    except (ValueError, IndexError):
                        col_data.append(las.well.null)
                arr = np.array(col_data, dtype=np.float64)
                # Replace null sentinels with NaN (supports exact and float-noise matches)
                if np.isfinite(las.well.null):
                    arr[np.isclose(arr, las.well.null, rtol=0.0, atol=1e-9)] = np.nan
                las.data[curve.mnemonic] = arr
            except Exception:
                las.data[curve.mnemonic] = np.full(len(all_values), np.nan)


# ─── Common curve mnemonics and their standard track assignments ────

CURVE_TRACKS = {
    # Track 1: GR, SP, CAL
    'GR':   {'track': 2, 'color': '#2ecc71', 'scale': (0, 150), 'unit': 'GAPI', 'name': 'Gamma Ray'},
    'SGR':  {'track': 2, 'color': '#27ae60', 'scale': (0, 150), 'unit': 'GAPI', 'name': 'Spectral GR'},
    'CGR':  {'track': 2, 'color': '#1abc9c', 'scale': (0, 150), 'unit': 'GAPI', 'name': 'Corrected GR'},
    'SP':   {'track': 1, 'color': '#3498db', 'scale': (-200, 200), 'unit': 'MV', 'name': 'Spontaneous Potential'},
    'CAL':  {'track': 1, 'color': '#e67e22', 'scale': (6, 16), 'unit': 'IN', 'name': 'Caliper'},
    'HCAL': {'track': 1, 'color': '#e67e22', 'scale': (6, 16), 'unit': 'IN', 'name': 'Hole Caliper'},
    'BS':   {'track': 1, 'color': '#d35400', 'scale': (6, 16), 'unit': 'IN', 'name': 'Bit Size'},

    # Track 2: Resistivity (log scale)
    'RT':   {'track': 3, 'color': '#e74c3c', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Deep Resistivity'},
    'RXO':  {'track': 4, 'color': '#c0392b', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Flushed Zone Resistivity'},
    'RILD': {'track': 3, 'color': '#e74c3c', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Deep Induction'},
    'RILM': {'track': 3, 'color': '#e67e22', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Medium Induction'},
    'RLL3': {'track': 3, 'color': '#f39c12', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Laterolog 3'},
    'RLLS': {'track': 3, 'color': '#f1c40f', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Shallow Laterolog'},
    'MSFL': {'track': 4, 'color': '#f39c12', 'scale': (0.2, 2000), 'log': True, 'unit': 'OHMM', 'name': 'Micro-Spherically Focused'},

    # Track 3: Porosity
    'NPHI': {'track': 6, 'color': '#3498db', 'scale': (0.45, -0.15), 'unit': 'V/V', 'name': 'Neutron Porosity'},
    'RHOB': {'track': 6, 'color': '#e74c3c', 'scale': (1.95, 2.95), 'unit': 'G/C3', 'name': 'Bulk Density'},
    'RHOZ': {'track': 6, 'color': '#e74c3c', 'scale': (1.95, 2.95), 'unit': 'G/C3', 'name': 'Density (Z-axis)'},
    'DT':   {'track': 6, 'color': '#9b59b6', 'scale': (140, 40), 'unit': 'US/F', 'name': 'Sonic Transit Time'},
    'DTC':  {'track': 6, 'color': '#9b59b6', 'scale': (140, 40), 'unit': 'US/F', 'name': 'Compressional Slowness'},
    'DTS':  {'track': 6, 'color': '#8e44ad', 'scale': (300, 50), 'unit': 'US/F', 'name': 'Shear Slowness'},
    'PEF':  {'track': 6, 'color': '#1abc9c', 'scale': (0, 10), 'unit': 'B/E', 'name': 'Photoelectric Factor'},
    'DRHO': {'track': 6, 'color': '#95a5a6', 'scale': (-0.2, 0.2), 'unit': 'G/C3', 'name': 'Density Correction'},

    # Track 4: Saturation / Formation
    'SW':    {'track': 10, 'color': '#3498db', 'scale': (0, 1), 'unit': 'V/V', 'name': 'Water Saturation'},
    'PHIE':  {'track': 8, 'color': '#2ecc71', 'scale': (0, 0.4), 'unit': 'V/V', 'name': 'Effective Porosity'},
    'PHIT':  {'track': 8, 'color': '#27ae60', 'scale': (0, 0.4), 'unit': 'V/V', 'name': 'Total Porosity'},
    'VSH':   {'track': 9, 'color': '#e67e22', 'scale': (0, 1), 'unit': 'V/V', 'name': 'Shale Volume'},
    'BVW':   {'track': 8, 'color': '#2980b9', 'scale': (0, 0.4), 'unit': 'V/V', 'name': 'Bulk Volume Water'},
    'PERM':  {'track': 12, 'color': '#16a085', 'scale': (0.01, 10000), 'log': True, 'unit': 'MD', 'name': 'Permeability'},
}

# Track layout defaults
TRACK_CONFIG = {
    1: {'name': 'GR / SP / CAL', 'width': 80},
    2: {'name': 'Resistivity', 'width': 80},
    3: {'name': 'Porosity', 'width': 80},
    4: {'name': 'Saturation', 'width': 80},
}

# Merge extra tracks into CURVE_TRACKS at module load
CURVE_TRACKS.update(EXTRA_CURVE_TRACKS)


# ── Русский стандарт ГИС: треки/шкалы для канонических мнемоник ──────────────
# Раскладка треков планшета (номер = 1-based индекс трека):
#   1  Стандартный каротаж   ДС, КС, ПС
#   2  Радиоактивный         ГК, НГК
#   3  Сопротивление (лог)   ИК, БК, БКЗ (ГЗ1–ГЗ5)
#   4  Микрозонды            МКЗ, МГЗ, МПЗ
#   5  ЯМК                   U1–U3
#   6  Расширенный           АК, ГГКп
#   7  Газовый каротаж       GAZ
#   8  Пористость            Кп        0–0.4
#   9  Глинистость           Кгл       0–0.4
#   10 Нефтенасыщенность     Кнг       0–1
#   11 РИГИС                 литология / коллектор / насыщение
#   12 Прочее                всё, что не опознано
CURVE_TRACKS.update({
    'DS':   {'track': 1, 'color': '#95a5a6', 'scale': (100, 400), 'unit': 'мм',  'name': 'ДС'},
    'BS':   {'track': 1, 'color': '#7f8c8d', 'scale': (100, 400), 'unit': 'мм',  'name': 'Долото'},
    'KS':   {'track': 1, 'color': '#e74c3c', 'scale': (0.2, 2000), 'log': True, 'unit': 'Ом·м', 'name': 'КС'},
    'PS':   {'track': 1, 'color': '#9b59b6', 'scale': (-100, 100), 'unit': 'мВ', 'name': 'ПС'},
    'RS':   {'track': 1, 'color': '#16a085', 'scale': (0, 10),   'unit': 'Ом·м', 'name': 'РС'},
    'TEMP': {'track': 1, 'color': '#fd79a8', 'scale': (0, 100),  'unit': '°C',   'name': 'Термометрия'},

    'GK':   {'track': 2, 'color': '#2ecc71', 'scale': (0, 20),   'unit': 'мкР/ч',   'name': 'ГК'},
    'NGK':  {'track': 2, 'color': '#3498db', 'scale': (0, 10),   'unit': 'усл.ед.', 'name': 'НГК'},

    'IK':   {'track': 3, 'color': '#e67e22', 'scale': (0.2, 2000), 'log': True, 'unit': 'мСм/м', 'name': 'ИК'},
    'BK':   {'track': 3, 'color': '#c0392b', 'scale': (0.2, 2000), 'log': True, 'unit': 'Ом·м', 'name': 'БК'},
    'BKZ':  {'track': 3, 'color': '#f39c12', 'scale': (0.2, 2000), 'log': True, 'unit': 'Ом·м', 'name': 'БКЗ (ГЗ)'},

    'MKZ':  {'track': 4, 'color': '#d35400', 'scale': (0.2, 2000), 'log': True, 'unit': 'Ом·м', 'name': 'МКЗ'},

    'YMK':  {'track': 5, 'color': '#af7ac5', 'scale': (0, 10),   'unit': 'усл.ед.', 'name': 'ЯМК'},

    'AK':   {'track': 6, 'color': '#1abc9c', 'scale': (500, 150), 'unit': 'мкс/м', 'name': 'АК'},
    'AKS':  {'track': 6, 'color': '#48c9b0', 'scale': (700, 200), 'unit': 'мкс/м', 'name': 'АК (S)'},
    'GGKP': {'track': 6, 'color': '#c0392b', 'scale': (1.8, 3.0), 'unit': 'г/см³', 'name': 'ГГКп'},
    'PE':   {'track': 6, 'color': '#8e44ad', 'scale': (0, 10),   'unit': 'б/э',   'name': 'ФЭП'},
    'DRHO': {'track': 6, 'color': '#bdc3c7', 'scale': (-0.5, 0.5), 'unit': 'г/см³', 'name': 'Поправка ρ'},

    'GAZ':  {'track': 7, 'color': '#e84393', 'scale': (0, 100),  'unit': 'усл.ед.', 'name': 'Газовый каротаж'},

    # fixed=True — границы заданы отраслевым соглашением и автоподбором не трогаются
    'KP':   {'track': 8,  'color': '#f1c40f', 'scale': (0, 0.4), 'unit': 'д.ед.', 'name': 'Кп',  'fixed': True},
    'KGL':  {'track': 9,  'color': '#7f8c8d', 'scale': (0, 0.4), 'unit': 'д.ед.', 'name': 'Кгл', 'fixed': True},
    'KNG':  {'track': 10, 'color': '#2980b9', 'scale': (0, 1),   'unit': 'д.ед.', 'name': 'Кнг', 'fixed': True},
    'KPR':  {'track': 12, 'color': '#af7ac5', 'scale': (0.01, 1000), 'log': True, 'unit': 'мД', 'name': 'Кпр'},

    # Категориальные колонки РИГИС — рисуются как заливка по кодам, не кривой
    'LITH': {'track': 11, 'color': '#a0522d', 'unit': 'код', 'name': 'Литология',  'categorical': 'lithology'},
    'COLL': {'track': 11, 'color': '#3fb950', 'unit': 'код', 'name': 'Коллектор',  'categorical': 'collector'},
    'SAT':  {'track': 11, 'color': '#8b5a2b', 'unit': 'код', 'name': 'Насыщение',  'categorical': 'saturation'},
})
