"""Minimal interoperable DOCX export of the editor's supported Markdown subset."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

def word_document(markdown):
    paragraphs=[]
    for line in markdown.splitlines():
        heading=re.match(r'^(#{1,3})\s+(.*)',line)
        style=f'<w:pStyle w:val="Heading{len(heading[1])}"/>' if heading else ''
        line=heading[2] if heading else line
        # Keep list markers as literal text: portable and no missing numbering definitions.
        runs=[]
        for part in re.split(r'(\*\*[^*]+\*\*|\*[^*]+\*)',line):
            bold=part.startswith('**') and part.endswith('**') and len(part)>4
            italic=not bold and part.startswith('*') and part.endswith('*') and len(part)>2
            value=part[2:-2] if bold else part[1:-1] if italic else part
            value=''.join(c for c in value if c in '\t\n\r' or ord(c)>=32)
            props='<w:b/>' if bold else '<w:i/>' if italic else ''
            runs.append(f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(value)}</w:t></w:r>')
        paragraphs.append(f'<w:p><w:pPr>{style}<w:spacing w:after="140" w:line="360" w:lineRule="auto"/></w:pPr>{"".join(runs)}</w:p>')
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    document=f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{ns}"><w:body>{"".join(paragraphs)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    styles=f'''<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{ns}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="宋体"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'''
    for level,size in [(1,32),(2,27),(3,24)]:styles+=f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:outlineLvl w:val="{level-1}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>'
    styles+='</w:styles>'
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml',document)
        z.writestr('word/styles.xml',styles)
        z.writestr('word/_rels/document.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    return buf.getvalue()
