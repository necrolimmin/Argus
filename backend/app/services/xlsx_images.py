"""Pictures placed on the first sheet of a workbook, by the row they sit in.

A picture gets into an .xlsx in one of three ways; all are read straight
from the zip, so nothing has to be decoded to find out whose photo it is:

- floating over the cells (Insert → Picture): a drawing anchored to a cell;
- placed in a cell (Excel 365 "Place in cell"): rich data the cell points to;
- WPS Office's picture in a cell: =DISPIMG("ID_…") plus xl/cellimages.xml.
"""

import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DISPIMG = re.compile(r'DISPIMG\(\s*"([^"]+)"')


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(z: zipfile.ZipFile, part: str) -> ET.Element | None:
    try:
        return ET.fromstring(z.read(part))
    except KeyError:
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id → (type, zip path of the target) for one part."""
    folder, name = posixpath.split(part)
    root = _xml(z, posixpath.join(folder, "_rels", name + ".rels"))
    out = {}
    for rel in root if root is not None else ():
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External" or not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id")] = (rel.get("Type", ""), path)
    return out


def _first_sheet(z: zipfile.ZipFile) -> str | None:
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        return None
    sheet = next((e for e in wb.iter() if _local(e.tag) == "sheet"), None)
    if sheet is None:
        return None
    return _rels(z, "xl/workbook.xml").get(sheet.get(f"{{{R}}}id"), ("", None))[1]


def _floating(z: zipfile.ZipFile, sheet: str, add) -> None:
    for kind, drawing in _rels(z, sheet).values():
        if not kind.endswith("/drawing"):
            continue
        root = _xml(z, drawing)
        media = _rels(z, drawing)
        for anchor in root if root is not None else ():
            start = next((e for e in anchor if _local(e.tag) == "from"), None)
            if start is None:  # absolute anchors belong to no cell
                continue
            row = int(next(e for e in start if _local(e.tag) == "row").text) + 1
            for blip in anchor.iter():
                if _local(blip.tag) == "blip" and blip.get(f"{{{R}}}embed") in media:
                    add(row, media[blip.get(f"{{{R}}}embed")][1])


def _rich_values(z: zipfile.ZipFile) -> list[str | None]:
    """Excel 365 in-cell pictures: rich value index → zip path of the image."""
    values = _xml(z, "xl/richData/rdrichvalue.xml")
    if values is None:
        return []
    structures = _xml(z, "xl/richData/rdrichvaluestructure.xml")
    key_at = []
    for s in structures if structures is not None else ():
        keys = [k.get("n") for k in s]
        key_at.append(keys.index("_rvRel:LocalImageIdentifier") if "_rvRel:LocalImageIdentifier" in keys else None)
    rel_list = _xml(z, "xl/richData/richValueRel.xml")
    rel_ids = [r.get(f"{{{R}}}id") for r in rel_list] if rel_list is not None else []
    targets = _rels(z, "xl/richData/richValueRel.xml")
    out = []
    for rv in values:
        s = int(rv.get("s", "0"))
        pos = key_at[s] if s < len(key_at) else None
        vs = [v.text for v in rv]
        try:
            out.append(targets[rel_ids[int(vs[pos])]][1])
        except (TypeError, IndexError, ValueError, KeyError):
            out.append(None)
    return out


def _value_metadata(z: zipfile.ZipFile) -> list[int | None]:
    """A cell's vm (1-based) → rich value index, via xl/metadata.xml."""
    meta = _xml(z, "xl/metadata.xml")
    if meta is None:
        return []
    future = []
    for block in meta.iter():
        if _local(block.tag) == "futureMetadata" and block.get("name") == "XLRICHVALUE":
            for bk in block:
                rvb = next((e for e in bk.iter() if _local(e.tag) == "rvb"), None)
                future.append(int(rvb.get("i")) if rvb is not None else None)
    out = []
    for block in meta:
        if _local(block.tag) == "valueMetadata":
            for bk in block:
                rc = next((e for e in bk if _local(e.tag) == "rc"), None)
                v = int(rc.get("v")) if rc is not None else -1
                out.append(future[v] if 0 <= v < len(future) else None)
    return out


def _wps_images(z: zipfile.ZipFile) -> dict[str, str]:
    root = _xml(z, "xl/cellimages.xml")
    if root is None:
        return {}
    media = _rels(z, "xl/cellimages.xml")
    out = {}
    for pic in root.iter():
        if _local(pic.tag) != "pic":
            continue
        name = next((e.get("name") for e in pic.iter() if _local(e.tag) == "cNvPr"), None)
        blip = next((e.get(f"{{{R}}}embed") for e in pic.iter() if _local(e.tag) == "blip"), None)
        if name and blip in media:
            out[name] = media[blip][1]
    return out


def _in_cells(z: zipfile.ZipFile, sheet: str, add) -> None:
    rich = _rich_values(z)
    vm_map = _value_metadata(z) if rich else []
    wps = _wps_images(z)
    if not rich and not wps:
        return
    with z.open(sheet) as f:
        for _, cell in ET.iterparse(f):
            if _local(cell.tag) != "c":
                continue
            ref = cell.get("r", "")
            row = int(re.sub(r"\D", "", ref) or 0)
            vm = cell.get("vm")
            if vm and vm.isdigit() and 0 < int(vm) <= len(vm_map):
                i = vm_map[int(vm) - 1]
                if i is not None and i < len(rich) and rich[i]:
                    add(row, rich[i])
            if wps:
                for e in cell:
                    if _local(e.tag) == "f" and e.text:
                        m = DISPIMG.search(e.text)
                        if m and m.group(1) in wps:
                            add(row, wps[m.group(1)])
            cell.clear()


def images_by_row(z: zipfile.ZipFile) -> dict[int, list[str]]:
    """Row number (1-based) → zip paths of the pictures in that row, in order."""
    sheet = _first_sheet(z)
    out: dict[int, list[str]] = {}
    if not sheet:
        return out

    def add(row: int, path: str) -> None:
        if row > 0 and path not in out.setdefault(row, []):
            out[row].append(path)

    _floating(z, sheet, add)
    _in_cells(z, sheet, add)
    return out
