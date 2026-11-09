"""Generate a standard Word document using only Python's standard library."""
from io import BytesIO
import re
from xml.etree import ElementTree as ET
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", W)
FIELDS = (("url", "Portal address"), ("email", "Email"), ("username", "Username"),
          ("applicant_id", "Applicant / student ID"), ("password", "Password"),
          ("status", "Application status"), ("notes", "Notes"))


def labeled_value(line, label):
    prefix = label + ":"
    if line == prefix:
        return ""
    if not line.startswith(prefix + " "):
        raise ValueError(f"Expected the {label} field in the account export.")
    return line[len(prefix) + 1:]


def word_accounts(path):
    """Read the report's visible text without opening Word or extracting files."""
    try:
        with zipfile.ZipFile(path) as archive:
            member = archive.getinfo("word/document.xml")
            if member.file_size > 16 * 1024 * 1024:
                raise ValueError("The Word document is too large to import.")
            xml = archive.read(member)
        if b"<!DOCTYPE" in xml.replace(b"\x00", b"").upper():
            raise ValueError("Unsupported Word document markup.")
        body = ET.fromstring(xml).find(f"{{{W}}}body")
        if body is None:
            raise ValueError("Missing Word document body.")
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError("This is not a readable .docx account export.") from error

    breaks = {f"{{{W}}}br": "\n", f"{{{W}}}cr": "\n", f"{{{W}}}tab": "\t"}
    paragraphs = ["".join((node.text or "") if node.tag == f"{{{W}}}t" else breaks.get(node.tag, "")
                           for node in paragraph.iter()) for paragraph in body.findall(f"{{{W}}}p")]
    if len(paragraphs) < 4 or paragraphs[0] != "College Portal Accounts" or not paragraphs[1].startswith("Profile: "):
        raise ValueError("Use a Word export made by College Portals.")
    count = labeled_value(paragraphs[2], "Saved accounts")
    records = paragraphs[4:]
    width = len(FIELDS) + 1
    if count == "0" and records == ["No saved accounts in this profile."]:
        return []
    if len(records) % width or count != str(len(records) // width):
        raise ValueError("The Word export's account count or layout does not match its contents.")
    return [{"college": records[i], **{key: labeled_value(records[i + j], label)
             for j, (key, label) in enumerate(FIELDS, 1)}} for i in range(0, len(records), width)]


def word_export(accounts, profile_name):
    document = ET.Element(f"{{{W}}}document")
    body = ET.SubElement(document, f"{{{W}}}body")

    def paragraph(text, style=None, label=None):
        if re.search(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]", text):
            raise ValueError("A field contains control characters that Word cannot display. Remove them and try again.")
        p = ET.SubElement(body, f"{{{W}}}p")
        if style:
            properties = ET.SubElement(p, f"{{{W}}}pPr")
            ET.SubElement(properties, f"{{{W}}}pStyle", {f"{{{W}}}val": style})
        if label:
            run = ET.SubElement(p, f"{{{W}}}r")
            props = ET.SubElement(run, f"{{{W}}}rPr")
            ET.SubElement(props, f"{{{W}}}b")
            ET.SubElement(run, f"{{{W}}}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = label
        run = ET.SubElement(p, f"{{{W}}}r")
        for i, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
            if i:
                ET.SubElement(run, f"{{{W}}}br")
            ET.SubElement(run, f"{{{W}}}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = line

    paragraph("College Portal Accounts", "Title")
    paragraph(profile_name, label="Profile: ")
    paragraph(str(len(accounts)), label="Saved accounts: ")
    paragraph("Contains readable passwords. Keep this document private.")
    for account in sorted(accounts, key=lambda a: a["college"].casefold()):
        paragraph(account["college"], "Heading1")
        for key, label in FIELDS:
            paragraph(account[key], label=label + ": ")
    if not accounts:
        paragraph("No saved accounts in this profile.")
    section = ET.SubElement(body, f"{{{W}}}sectPr")
    ET.SubElement(section, f"{{{W}}}pgSz", {f"{{{W}}}w": "12240", f"{{{W}}}h": "15840"})
    ET.SubElement(section, f"{{{W}}}pgMar", {f"{{{W}}}{k}": "1080" for k in ("top", "bottom", "left", "right")})
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''
    root_rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    doc_rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    styles = f'''<w:styles xmlns:w="{W}">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120"/><w:widowControl/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
</w:styles>'''
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in {"[Content_Types].xml": content_types, "_rels/.rels": root_rels,
                           "word/_rels/document.xml.rels": doc_rels, "word/styles.xml": styles,
                           "word/document.xml": ET.tostring(document, encoding="utf-8", xml_declaration=True)}.items():
            archive.writestr(path, data)
    return output.getvalue()
