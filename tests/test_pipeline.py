import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from autoflow.cli import main
from autoflow.domain import COLUMNS, process
from autoflow.readers import InputError, read_rows
from autoflow.report import export, render_html, safe_cell

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = ROOT / "examples/registros.csv"

    def csv(self, body, encoding="utf-8"):
        path = self.root / "input.csv"
        path.write_text(body, encoding=encoding)
        return path

    def workbook(self, formula=False, multiple=False):
        path = self.root / "input.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Entrada"
        sheet.append(COLUMNS)
        sheet.append(
            ["001", "Fictício", "", "Teste", "2026-01-01", "receita", "=1+1" if formula else 12.50]
        )
        if multiple:
            book.create_sheet("Outra")
        book.save(path)
        book.close()
        return path

    def test_demo_counts_and_values(self):
        summary = process(read_rows(self.source)).summary()
        self.assertEqual(
            [summary[k] for k in ("linhas_lidas", "aceitos", "duplicados", "rejeitados")],
            [9, 5, 2, 2],
        )
        self.assertEqual(summary["saldo"], "3404.60")
        self.assertEqual(summary["receitas"], "3900.50")
        self.assertEqual(summary["despesas"], "495.90")

    def test_csv_utf8_bom_and_comma(self):
        path = self.csv(
            "ID,NOME,DATA,TIPO,VALOR\n001,Fictício,2026-01-01,receita,10.00\n", "utf-8-sig"
        )
        self.assertEqual(process(read_rows(path)).records[0].id, "001")

    def test_missing_headers(self):
        path = self.csv("nome;data\nFictício;2026-01-01\n")
        with self.assertRaises(InputError):
            list(read_rows(path, ";"))

    def test_duplicate_headers_after_normalization(self):
        path = self.csv("id;nome;data;tipo;valor;NOME\n")
        with self.assertRaises(InputError):
            list(read_rows(path, ";"))

    def test_unknown_columns(self):
        path = self.csv("id;nome;data;tipo;valor;senha\n")
        with self.assertRaises(InputError):
            list(read_rows(path, ";"))

    def test_extra_fields_are_rejected_not_silently_lost(self):
        path = self.csv("id;nome;data;tipo;valor\n001;Fictício;2026-01-01;receita;10;extra\n")
        self.assertEqual(process(read_rows(path, ";")).summary()["rejeitados"], 1)

    def test_invalid_encoding(self):
        path = self.root / "input.csv"
        path.write_bytes(b"id;nome;data;tipo;valor\n1;\xff;2026-01-01;receita;1\n")
        with self.assertRaises(InputError):
            list(read_rows(path, ";"))

    def test_empty_and_header_only(self):
        with self.assertRaises(InputError):
            list(read_rows(self.csv("")))
        self.assertEqual(process(read_rows(self.csv("id;nome;data;tipo;valor\n"), ";")).total, 0)

    def test_multiline_and_blank_line_numbers(self):
        path = self.csv(
            'id;nome;data;tipo;valor\n\n1;"Nome\nFictício";2026-01-01;receita;1\n'
            "2;Outro;invalido;receita;1\n"
        )
        result = process(read_rows(path, ";"))
        self.assertEqual(result.records[0].nome, "Nome Fictício")
        self.assertEqual(result.issues[0].linha, 5)

    def test_xlsx_read_and_leading_zero(self):
        record = process(read_rows(self.workbook())).records[0]
        self.assertEqual(record.id, "001")
        self.assertEqual(record.valor, "12.50")

    def test_xlsx_formula_rejected(self):
        result = process(read_rows(self.workbook(formula=True)))
        self.assertEqual(result.summary()["rejeitados"], 1)
        self.assertEqual(result.records, [])

    def test_multiple_sheets_require_choice(self):
        path = self.workbook(multiple=True)
        with self.assertRaises(InputError):
            list(read_rows(path))
        self.assertEqual(len(process(read_rows(path, sheet="Entrada")).records), 1)
        with self.assertRaises(InputError):
            list(read_rows(path, sheet="Inexistente"))

    def test_invalid_xlsx(self):
        path = self.root / "input.xlsx"
        path.write_text("not a zip")
        self.assertEqual(main([str(path), "--output", str(self.root / "out")]), 2)

    def test_zip_expansion_limit(self):
        path = self.root / "input.xlsx"
        with ZipFile(path, "w") as archive:
            archive.writestr("payload", "x" * 200)
        with patch("autoflow.readers.MAX_EXPANDED", 100), self.assertRaises(InputError):
            list(read_rows(path))

    def test_input_and_row_limits(self):
        with patch("autoflow.readers.MAX_BYTES", 1), self.assertRaises(InputError):
            list(read_rows(self.source))
        with patch("autoflow.readers.MAX_ROWS", 1), self.assertRaises(InputError):
            list(read_rows(self.source))

    def test_options_and_extension_errors(self):
        path = self.root / "input.txt"
        path.write_text("sample")
        for input_path, kwargs in [
            (path, {}),
            (self.source, {"sheet": "aba"}),
            (self.source, {"delimiter": "|"}),
            (self.workbook(), {"delimiter": ";"}),
        ]:
            with self.subTest(path=input_path, kwargs=kwargs), self.assertRaises(InputError):
                list(read_rows(input_path, **kwargs))

    def test_cli_export_all_formats_and_strict_exit(self):
        out = self.root / "out"
        command = [
            sys.executable,
            "-m",
            "autoflow",
            str(self.source),
            "--output",
            str(out),
            "--strict",
            "--demo",
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(len(list(out.iterdir())), 6)
        summary = json.loads((out / "resumo.json").read_text())
        self.assertTrue(summary["demonstracao"])
        self.assertEqual(len(summary["entrada_sha256"]), 64)
        with (out / "registros.csv").open(encoding="utf-8-sig") as source:
            records = list(csv.DictReader(source, delimiter=";"))
        self.assertEqual(len(records), 5)
        workbook = load_workbook(out / "resultado.xlsx", read_only=True)
        try:
            self.assertEqual(len(list(workbook["Registros"].rows)), 6)
            self.assertEqual(len(list(workbook["Ocorrencias"].rows)), 5)
        finally:
            workbook.close()
        self.assertIn("Demonstração com dados fictícios", (out / "relatorio.html").read_text())
        self.assertNotIn("Empresa Exemplo", (out / "execucao.log").read_text())

    def test_existing_output_is_never_overwritten(self):
        out = self.root / "out"
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("preserve")
        self.assertEqual(main([str(self.source), "--output", str(out)]), 2)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_failed_export_leaves_no_partial_output(self):
        out = self.root / "out"
        with patch("autoflow.report.write_xlsx", side_effect=OSError("disk full")):
            self.assertEqual(main([str(self.source), "--output", str(out)]), 2)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_concurrent_output_lock(self):
        (self.root / ".out.lock").touch()
        self.assertEqual(main([str(self.source), "--output", str(self.root / "out")]), 2)
        self.assertTrue((self.root / ".out.lock").exists())

    def test_missing_input_no_traceback(self):
        self.assertEqual(
            main([str(self.root / "missing.csv"), "--output", str(self.root / "out")]), 2
        )

    def test_formula_injection_escaped_in_both_exports(self):
        path = self.csv("id;nome;categoria;data;tipo;valor\n1;=1+1;@formula;2026-01-01;receita;1\n")
        result = process(read_rows(path))
        out = self.root / "out"
        export(result, out, {"versao": "test", "entrada_sha256": "0" * 64, "demonstracao": True})
        self.assertIn("'=1+1", (out / "registros.csv").read_text(encoding="utf-8-sig"))
        workbook = load_workbook(out / "resultado.xlsx")
        try:
            self.assertEqual(workbook["Registros"]["B2"].data_type, "s")
        finally:
            workbook.close()
        for value in ("=1+1", " +1", "-1", "@cmd", "\t=1"):
            self.assertTrue(safe_cell(value).startswith("'"))

    def test_html_escapes_untrusted_category(self):
        path = self.csv(
            "id;nome;categoria;data;tipo;valor\n1;Teste;<script>alert(1)</script>;"
            "2026-01-01;receita;1\n"
        )
        summary = {
            **process(read_rows(path)).summary(),
            "versao": "test",
            "entrada_sha256": "0" * 64,
            "demonstracao": True,
        }
        report = render_html(summary)
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("Content-Security-Policy", report)

    def test_empty_report(self):
        path = self.csv("id;nome;data;tipo;valor\n")
        self.assertEqual(main([str(path), "--output", str(self.root / "out")]), 0)
        self.assertIn("Nenhum registro válido", (self.root / "out/relatorio.html").read_text())
