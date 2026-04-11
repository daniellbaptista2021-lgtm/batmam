---
name: "pdf"
description: "Generate, read, merge, split, and manipulate PDF documents"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: business
---

# PDF — Document Generation and Manipulation

Handle all PDF operations using Python libraries.

## Libraries
- **pypdf**: read, merge, split, rotate, extract text/metadata
- **reportlab**: create new PDFs (reports, invoices, certificates)
- **pdfplumber**: extract text and tables with layout preservation

## Reading PDFs
```python
from pypdf import PdfReader
reader = PdfReader("document.pdf")
text = "".join(page.extract_text() for page in reader.pages)
```

## Creating PDFs
```python
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("output.pdf", pagesize=A4)
styles = getSampleStyleSheet()
elements = [
    Paragraph("Title", styles["Title"]),
    Spacer(1, 12),
    Paragraph("Body text.", styles["Normal"]),
]
doc.build(elements)
```

## Merging PDFs
```python
from pypdf import PdfWriter
writer = PdfWriter()
for f in ["doc1.pdf", "doc2.pdf"]:
    writer.append(f)
writer.write("merged.pdf")
writer.close()
```

## Splitting PDFs
```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    w = PdfWriter()
    w.add_page(page)
    w.write(f"page_{i+1}.pdf")
    w.close()
```

## Table Extraction
```python
import pdfplumber
with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        for table in page.extract_tables():
            for row in table:
                print(row)
```

## Rules
- Handle file-not-found errors gracefully
- Process large PDFs page-by-page for memory efficiency
- Use professional fonts and consistent styling when creating
- Include page numbers and headers/footers for reports
- Save to current working directory unless specified
