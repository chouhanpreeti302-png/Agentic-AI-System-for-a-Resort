import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

# Fallback menu used if the Excel file is missing or fails to parse.
FALLBACK_MENU = [
    {"name": "Margherita Pizza", "price": 12.0, "category": "mains"},
    {"name": "Grilled Salmon", "price": 18.5, "category": "mains"},
    {"name": "Caesar Salad", "price": 9.5, "category": "salads"},
    {"name": "Club Sandwich", "price": 10.0, "category": "mains"},
    {"name": "French Fries", "price": 4.5, "category": "sides"},
    {"name": "Tomato Soup", "price": 6.0, "category": "soups"},
    {"name": "Chocolate Cake", "price": 7.0, "category": "desserts"},
    {"name": "Fresh Juice", "price": 5.0, "category": "drinks"},
    {"name": "Coffee", "price": 3.5, "category": "drinks"},
]

NAMESPACE_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"ws": NAMESPACE_MAIN}


def _safe_price(raw: str) -> float:
    match = re.search(r"[0-9]+(?:\\.[0-9]+)?", raw or "")
    try:
        return float(match.group()) if match else 0.0
    except Exception:
        return 0.0


def _load_shared_strings(z: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    strings: List[str] = []
    for si in root.findall(f"{{{NAMESPACE_MAIN}}}si"):
        text = "".join(t.text or "" for t in si.iter(f"{{{NAMESPACE_MAIN}}}t"))
        strings.append(text)
    return strings


def _cell_value(cell: ET.Element, shared: List[str]) -> str:
    c_type = cell.get("t")
    v_el = cell.find("ws:v", NS)
    if v_el is not None:
        val = v_el.text or ""
        if c_type == "s":  # shared string
            try:
                return shared[int(val)]
            except Exception:
                return val
        return val
    # Inline string
    is_el = cell.find("ws:is/ws:t", NS)
    if is_el is not None:
        return is_el.text or ""
    return ""


def _parse_sheet(z: zipfile.ZipFile, target: str, shared: List[str], category: str) -> List[Dict]:
    root = ET.fromstring(z.read(target))
    rows = root.findall(".//ws:sheetData/ws:row", NS)
    items: List[Dict] = []
    for idx, row in enumerate(rows):
        cells = {cell.get("r"): _cell_value(cell, shared) for cell in row.findall("ws:c", NS)}
        # Skip header row (assumed first row) or empty entries.
        if idx == 0:
            continue
        name = next((val for coord, val in cells.items() if coord and coord.startswith("A")), "").strip()
        price_raw = next((val for coord, val in cells.items() if coord and coord.startswith("C")), "").strip()
        if not name:
            continue
        price = _safe_price(price_raw)
        description = next((val for coord, val in cells.items() if coord and coord.startswith("B")), "").strip()
        items.append({"name": name, "price": price, "category": category, "description": description})
    return items


def _load_menu_from_excel() -> Optional[List[Dict]]:
    path = Path(__file__).resolve().parent / "Restaurant_Menu.xlsx"
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as z:
            shared = _load_shared_strings(z)
            workbook = ET.fromstring(z.read("xl/workbook.xml"))
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
            rel_map = {rel.get("Id"): rel.get("Target").lstrip("/") for rel in rels.findall("r:Relationship", rel_ns)}

            sheets = workbook.findall("ws:sheets/ws:sheet", {"ws": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"})
            menu: List[Dict] = []
            for sheet in sheets:
                name = sheet.get("name") or "Unknown"
                rel_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                target = rel_map.get(rel_id)
                if not target:
                    continue
                menu.extend(_parse_sheet(z, target, shared, name))
            return menu or None
    except Exception:
        return None


MENU: List[Dict] = _load_menu_from_excel() or FALLBACK_MENU
