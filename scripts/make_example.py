"""Reproduz a planilha fictícia a partir do CSV canônico versionado."""

import csv
from pathlib import Path

from openpyxl import Workbook

root = Path(__file__).resolve().parents[1]
workbook = Workbook()
workbook.properties.creator = "AutoFlow — demonstração fictícia"
workbook.properties.lastModifiedBy = "AutoFlow"
sheet = workbook.active
sheet.title = "Registros"
with (root / "examples/registros.csv").open(encoding="utf-8", newline="") as source:
    for row in csv.reader(source, delimiter=";"):
        sheet.append(row)
sheet.freeze_panes = "A2"
sheet.auto_filter.ref = sheet.dimensions
workbook.save(root / "examples/registros.xlsx")
workbook.close()
