import io
import re
import time
import zipfile

import pytest

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-face-" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"png-face-" * 20


@pytest.fixture
def tree(client, admin):
    company = client.post("/api/org-units", json={"name": "Компания"}, headers=admin).json()
    branch = client.post("/api/org-units", json={"name": "Ташкент", "parent_id": company["id"]},
                         headers=admin).json()
    return {"company": company, "branch": branch}


@pytest.fixture(autouse=True)
def fake_faces(monkeypatch):
    from app.services.recognizer import FaceCheckError

    async def embed(image, filename):
        if b"no-face" in image:
            raise FaceCheckError("face_not_found")
        return b"\0" * 2048

    monkeypatch.setattr("app.api.employee_import.embed_photo", embed)


def _book(rows, pictures=()):
    """A workbook with floating pictures at (row, image bytes)."""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image
    from PIL import Image as Pil

    wb = Workbook()
    ws = wb.active
    ws.append(["Фамилия", "Имя", "Отчество", "Табельный номер", "Должность", "Телефон", "Подразделение", "Фото"])
    for r in rows:
        ws.append(r)
    for row, color in pictures:
        buf = io.BytesIO()
        Pil.new("RGB", (40, 40), color).save(buf, "PNG")
        buf.seek(0)
        ws.add_image(Image(buf), f"H{row}")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _with_in_cell_picture(book: bytes, cell: str, image: bytes) -> bytes:
    """Rewrite a workbook the way Excel 365 stores a picture placed in a cell."""
    src = zipfile.ZipFile(io.BytesIO(book))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rf'<c r="{cell}"([^>]*)>'.encode(), rf'<c r="{cell}"\1 vm="1">'.encode(), data)
            z.writestr(item, data)
        z.writestr("xl/metadata.xml", """<metadata xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:xlrd="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata">
<metadataTypes count="1"><metadataType name="XLRICHVALUE"/></metadataTypes>
<futureMetadata name="XLRICHVALUE" count="1"><bk><extLst><ext uri="{3e2802c4-a4d2-4d8b-9148-e3be6c30e623}">
<xlrd:rvb i="0"/></ext></extLst></bk></futureMetadata>
<valueMetadata count="1"><bk><rc t="1" v="0"/></bk></valueMetadata></metadata>""")
        z.writestr("xl/richData/rdrichvaluestructure.xml", """<rvStructures
 xmlns="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata" count="1">
<s t="_localImage"><k n="_rvRel:LocalImageIdentifier" t="i"/><k n="CalcOrigin" t="i"/></s></rvStructures>""")
        z.writestr("xl/richData/rdrichvalue.xml", """<rvData
 xmlns="http://schemas.microsoft.com/office/spreadsheetml/2017/richdata" count="1">
<rv s="0"><v>0</v><v>5</v></rv></rvData>""")
        z.writestr("xl/richData/richValueRel.xml", """<richValueRels
 xmlns="http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><rel r:id="rId1"/></richValueRels>""")
        z.writestr("xl/richData/_rels/richValueRel.xml.rels", """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
 Target="../media/image9.jpeg"/></Relationships>""")
        z.writestr("xl/media/image9.jpeg", image)
    return out.getvalue()


def _with_wps_picture(book: bytes, cell: str, image: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(book))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for item in src.infolist():
            data = src.read(item)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rf'<c r="{cell}"[^>]*>.*?</c>'.encode(),
                              rf'<c r="{cell}" t="str"><f>_xlfn.DISPIMG("ID_A1B2",1)</f><v>=DISPIMG("ID_A1B2",1)</v></c>'.encode(),
                              data)
            z.writestr(item, data)
        z.writestr("xl/cellimages.xml", """<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData"
 xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<etc:cellImage><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="ID_A1B2"/><xdr:cNvPicPr/></xdr:nvPicPr>
<xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill></xdr:pic></etc:cellImage></etc:cellImages>""")
        z.writestr("xl/_rels/cellimages.xml.rels", """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
 Target="media/wps1.jpeg"/></Relationships>""")
        z.writestr("xl/media/wps1.jpeg", image)
    return out.getvalue()


def _preview(client, admin, data, name="staff.xlsx"):
    r = client.post("/api/employees/import/preview", files={"file": (name, data)}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, admin, token):
    r = client.post("/api/employees/import", json={"token": token}, headers=admin)
    assert r.status_code == 202, r.text
    for _ in range(100):
        job = client.get(f"/api/employees/import/{token}", headers=admin).json()
        if job["finished"]:
            return job
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def test_template_lists_units(client, admin, tree):
    from openpyxl import load_workbook

    r = client.get("/api/employees/import/template", headers=admin)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[0] == "Сотрудники"
    assert [c.value for c in wb["Подразделения"]["A"]][1:] == ["Компания", "Компания / Ташкент"]


def test_floating_pictures_follow_their_rows(client, admin, tree):
    book = _book(
        [
            ["Иванов", "Иван", "", 101, "Инженер", "", "Компания / Ташкент", ""],
            ["Петров", "Пётр", "", "102", "", "", "Ташкент", ""],
            ["", "", "", "", "", "", "Ташкент", ""],
            ["Сидоров", "", "", "", "", "", "Нигде", ""],
        ],
        pictures=[(2, "red"), (2, "blue"), (3, "green")],
    )
    preview = _preview(client, admin, book)
    rows = {r["row"]: r for r in preview["rows"]}
    assert rows[2]["full_name"] == "Иванов Иван" and rows[2]["personnel_number"] == "101"
    assert len(rows[2]["photos"]) == 2 and len(rows[3]["photos"]) == 1
    assert rows[3]["org_unit_id"] == tree["branch"]["id"]  # the tail of the path is enough
    assert rows[4]["errors"] == ["name_required"]
    assert rows[5]["errors"] == ["unit_not_found"]
    assert client.get(rows[2]["photos"][0]["url"]).status_code == 200

    job = _run(client, admin, preview["token"])
    assert (job["created"], job["photos"], job["skipped_rows"]) == (2, 3, [4, 5])
    staff = client.get("/api/employees", headers=admin).json()["items"]
    assert {e["full_name"]: len(e["photos"]) for e in staff} == {"Иванов Иван": 2, "Петров Пётр": 1}


def test_in_cell_pictures_excel_and_wps(client, admin, tree):
    rows = [["Иванов", "", "", 1, "", "", "Ташкент", "#VALUE!"], ["Петров", "", "", 2, "", "", "Ташкент", "фото"]]
    book = _with_wps_picture(_with_in_cell_picture(_book(rows), "H2", JPEG), "H3", PNG)
    preview = _preview(client, admin, book)
    assert [len(r["photos"]) for r in preview["rows"]] == [1, 1]
    assert preview["rows"][1]["photos"][0]["path"].endswith(".png")


def test_zip_photos_by_number_and_update(client, admin, tree):
    pack = io.BytesIO()
    with zipfile.ZipFile(pack, "w") as z:
        z.writestr("staff.csv", "Фамилия;Имя;Отчество;Таб;Должность;Телефон;Подразделение;Фото\n"
                                "Иванов;Иван;;7;Инженер;;Ташкент;\n"
                                "Петров;;;8;;;Ташкент;petrov.jpg\n"
                                "Сидоров;;;9;;;Ташкент;nobody.jpg\n")
        z.writestr("photos/7.jpg", JPEG)
        z.writestr("photos/7_2.jpg", JPEG + b"2")
        z.writestr("photos/70.jpg", JPEG + b"70")
        z.writestr("photos/petrov.jpg", JPEG + b"no-face")
    preview = _preview(client, admin, pack.getvalue(), "staff.zip")
    rows = {r["row"]: r for r in preview["rows"]}
    assert len(rows[2]["photos"]) == 2 and len(rows[3]["photos"]) == 1
    assert rows[4]["warnings"] == ["photo_not_found"]
    job = _run(client, admin, preview["token"])
    assert job["created"] == 3 and job["photos"] == 2
    assert [(p["row"], p["code"]) for p in job["photo_problems"]] == [(3, "face_not_found")]

    # Loading the same people again updates them and does not add the same photos twice.
    book = _book([["Иванов", "Иван", "Иванович", 7, "", "", "Ташкент", ""]])
    preview = _preview(client, admin, book)
    assert preview["rows"][0]["action"] == "update"
    job = _run(client, admin, preview["token"])
    assert (job["created"], job["updated"]) == (0, 1)
    emp = next(e for e in client.get("/api/employees", headers=admin).json()["items"] if e["personnel_number"] == "7")
    assert emp["full_name"] == "Иванов Иван Иванович" and emp["position"] == "Инженер" and len(emp["photos"]) == 2


def test_repeated_number_and_bad_file(client, admin, tree):
    book = _book([["А", "", "", 5, "", "", "Ташкент", ""], ["Б", "", "", 5, "", "", "Ташкент", ""]])
    rows = _preview(client, admin, book)["rows"]
    assert rows[1]["errors"] == ["number_repeated"]
    r = client.post("/api/employees/import/preview", files={"file": ("x.xlsx", b"not a zip")}, headers=admin)
    assert r.status_code == 422 and r.json()["detail"] == "import_unreadable"
