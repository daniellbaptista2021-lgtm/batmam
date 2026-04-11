---
name: "spreadsheet"
description: "Generate professional Excel spreadsheets with openpyxl: dashboards, reports, CRM"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: business
---

# Spreadsheet — Professional Excel Generation

Generate production-quality .xlsx files using openpyxl.

## Requirements
- Use **openpyxl** for all Excel generation
- Professional font: Arial or Calibri throughout
- Zero formula errors: no #REF!, #DIV/0!, #VALUE!, #N/A, #NAME?
- Save to the current working directory unless specified otherwise

## Color Coding (Financial Models)
- **Blue text** (0,0,255): hardcoded inputs the user changes
- **Black text** (0,0,0): all formulas and calculations
- **Green text** (0,128,0): links from other worksheets
- **Red text** (255,0,0): external links to other files
- **Yellow background** (255,255,0): key assumptions needing attention

## Number Formatting
- Currency: `$#,##0` — always specify units in headers
- Percentages: `0.0%` (one decimal)
- Years: format as text ("2024" not "2,024")
- Negatives: parentheses `(123)` not `-123`
- Zeros: display as "-"

## Standard Workflow
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers

wb = Workbook()
ws = wb.active
ws.title = "Sheet Name"

# Professional header row
header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
header_font = Font(name="Arial", bold=True, color="FFFFFF", size=11)

# Column widths — always auto-fit or set explicitly
# Freeze panes for headers
ws.freeze_panes = "A2"

# Add data, formulas, formatting
wb.save("output.xlsx")
```

## Common Deliverables
- **Dashboard**: summary sheet with KPIs, charts linked to data sheets
- **Financial Model**: assumptions sheet + projections + scenario toggles
- **CRM/Tracker**: data validation dropdowns, conditional formatting, filters
- **Report**: formatted tables with totals, subtotals, borders

## Rules
- Always set column widths appropriately (no truncated data)
- Always freeze the header row
- Include a formatted header with the company/report name
- Add borders to data tables
- Use number formatting consistently
- Test formulas with edge cases (zero, negative values)
