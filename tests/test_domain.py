import unittest
from datetime import date, datetime
from decimal import Decimal

from autoflow.domain import civil_date, money, process, validate
from autoflow.report import brl


def sample(**changes):
    return {
        "id": "001",
        "nome": " Empresa  Fictícia ",
        "email": "TESTE@example.invalid",
        "categoria": "Serviços",
        "data": "12/01/2026",
        "tipo": "RECEITA",
        "valor": "1.234,50",
        **changes,
    }


class DomainTests(unittest.TestCase):
    def test_negative_balance_keeps_sign_below_one_real(self):
        self.assertEqual(brl("-0.50"), "R$ -0,50")
        self.assertEqual(brl("-1234.50"), "R$ -1.234,50")

    def test_numeric_zero_id_and_control_characters(self):
        self.assertEqual(validate(sample(id=0)).id, "0")
        with self.assertRaises(ValueError):
            validate(sample(nome="texto\x01inválido"))

    def test_money_brazilian_and_canonical(self):
        for value in ("1.234,50", "1234,50", "1234.50", Decimal("1234.5")):
            with self.subTest(value=value):
                self.assertEqual(money(value), Decimal("1234.50"))

    def test_money_rejects_ambiguous_negative_nonfinite_and_precision(self):
        for value in (
            "1.234",
            "1,234.00",
            "-1",
            "0",
            "NaN",
            "Infinity",
            "1e3",
            "9999999999",
            True,
            None,
            "12.345,6.7",
            "0.001",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    def test_dates(self):
        for value in ("2024-02-29", "29/02/2024", date(2024, 2, 29), datetime(2024, 2, 29)):
            self.assertEqual(civil_date(value), date(2024, 2, 29))

    def test_invalid_dates(self):
        for value in ("2026-02-29", "31/04/2026", "01-02-26", "2026-1-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                civil_date(value)

    def test_normalization_and_missing_optional_fields(self):
        record = validate(sample(categoria="", email=""))
        self.assertEqual(record.id, "001")
        self.assertEqual(record.nome, "Empresa Fictícia")
        self.assertEqual(record.categoria, "Sem categoria")
        self.assertEqual(record.email, "")
        self.assertEqual(record.valor, "1234.50")
        self.assertEqual(record.data, "2026-01-12")

    def test_validation_errors(self):
        for change in (
            {"id": ""},
            {"id": "../escape"},
            {"nome": ""},
            {"nome": "a" * 161},
            {"email": "no-at"},
            {"tipo": "outro"},
            {"valor": ""},
            {"categoria": "a" * 81},
            {"data": "31/02/2026"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(sample(**change))

    def test_duplicates_and_conflicts_keep_first_valid(self):
        result = process(
            [
                (2, sample(valor=""), None),
                (3, sample(), None),
                (4, sample(), None),
                (5, sample(valor="4"), None),
            ]
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(
            [i.codigo for i in result.issues], ["invalido", "duplicado", "duplicado_conflitante"]
        )
        self.assertEqual(result.issues[-1].linha_original, 3)
        self.assertEqual(result.summary()["receitas"], "1234.50")

    def test_exact_totals_and_grouping(self):
        result = process(
            [
                (2, sample(valor="0.10"), None),
                (3, sample(id="002", valor="0.20"), None),
                (4, sample(id="003", valor="0.30", tipo="despesa", data="2026-02-01"), None),
            ]
        )
        summary = result.summary()
        self.assertEqual(summary["saldo"], "0.00")
        self.assertEqual(summary["por_mes"]["2026-01"]["receitas"], "0.30")
        self.assertEqual(summary["por_mes"]["2026-02"]["despesas"], "0.30")
        self.assertEqual(summary["por_categoria"]["Serviços"]["saldo"], "0.00")

    def test_empty_result(self):
        summary = process([]).summary()
        self.assertEqual(summary["saldo"], "0.00")
        self.assertEqual(summary["aceitos"], 0)

    def test_row_error_is_preserved_without_raw_values(self):
        result = process([(4, {}, "quantidade de campos diferente do cabeçalho")])
        self.assertEqual(result.issues[0].linha, 4)
        self.assertEqual(result.summary()["rejeitados"], 1)
