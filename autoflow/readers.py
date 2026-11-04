"""Adaptadores de entrada com limites, linhas de origem e rejeição de fórmulas."""

import csv
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

from .domain import COLUMNS, REQUIRED, key

MAX_BYTES = 10 * 1024 * 1024
MAX_EXPANDED = 50 * 1024 * 1024
MAX_ROWS = 100_000


class InputError(ValueError):
    """Arquivo não pode ser interpretado com segurança."""


def headers(values) -> list[str]:
    names = [key(v) for v in values]
    if len(names) != len(set(names)):
        raise InputError("Cabeçalhos duplicados após normalização.")
    if not REQUIRED.issubset(names):
        raise InputError("Cabeçalhos obrigatórios: id, nome, data, tipo, valor.")
    if not set(names).issubset(COLUMNS):
        raise InputError("Coluna desconhecida. Permitidas: " + ", ".join(COLUMNS))
    return names


def mapped(names, values):
    if len(values) != len(names):
        return {}, "quantidade de campos diferente do cabeçalho"
    if any(isinstance(v, str) and len(v) > 4096 for v in values):
        return {}, "campo excede 4096 caracteres"
    return dict(zip(names, values, strict=True)), None


def csv_rows(path: Path, delimiter: str | None):
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            sample = source.read(8192)
            source.seek(0)
            if not sample.strip():
                raise InputError("Arquivo vazio.")
            if delimiter is None:
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
                except csv.Error as exc:
                    raise InputError("Separador ambíguo; informe --delimiter.") from exc
            reader = csv.reader(source, delimiter=delimiter, strict=True)
            names = headers(next(reader))
            for count, values in enumerate(reader, 1):
                if count > MAX_ROWS:
                    raise InputError("Limite de 100.000 linhas excedido.")
                if not values or not any(str(v).strip() for v in values):
                    continue
                row, error = mapped(names, values)
                yield reader.line_num, row, error
    except (UnicodeError, csv.Error) as exc:
        raise InputError("CSV inválido; use UTF-8 e aspas/separadores consistentes.") from exc


def xlsx_rows(path: Path, sheet: str | None):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(i.file_size for i in entries) > MAX_EXPANDED:
                raise InputError("XLSX excede os limites de expansão (50 MiB / 1.000 entradas).")
        workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("XLSX inválido ou não suportado.") from exc
    try:
        if sheet:
            if sheet not in workbook.sheetnames:
                raise InputError("A aba solicitada não existe.")
            worksheet = workbook[sheet]
        elif len(workbook.sheetnames) != 1:
            raise InputError("Arquivo com múltiplas abas; informe --sheet.")
        else:
            worksheet = workbook.active
        if (worksheet.max_column or 0) > len(COLUMNS):
            raise InputError("XLSX contém colunas fora do contrato.")
        if (worksheet.max_row or 0) > MAX_ROWS + 1:
            raise InputError("Limite de 100.000 linhas excedido.")
        iterator = worksheet.iter_rows()
        first = next(iterator, None)
        if first is None:
            raise InputError("Aba vazia.")
        names = headers([c.value for c in first])
        for number, cells in enumerate(iterator, 2):
            if number > MAX_ROWS + 1:
                raise InputError("Limite de 100.000 linhas excedido.")
            if all(c.value is None for c in cells):
                continue
            if any(c.data_type in {"f", "e"} for c in cells):
                yield number, {}, "fórmulas e células de erro não são aceitas"
                continue
            row, error = mapped(names, [c.value for c in cells])
            yield number, row, error
    finally:
        workbook.close()


def read_rows(path: Path, delimiter: str | None = None, sheet: str | None = None):
    if not path.is_file():
        raise InputError("Entrada deve ser um arquivo existente.")
    if path.stat().st_size > MAX_BYTES:
        raise InputError("Arquivo excede 10 MiB.")
    if delimiter is not None and delimiter not in {",", ";", "\t"}:
        raise InputError("Separador deve ser vírgula, ponto e vírgula ou tabulação.")
    if path.suffix.lower() == ".csv":
        if sheet:
            raise InputError("--sheet só é aceito para XLSX.")
        yield from csv_rows(path, delimiter)
    elif path.suffix.lower() == ".xlsx":
        if delimiter:
            raise InputError("--delimiter só é aceito para CSV.")
        yield from xlsx_rows(path, sheet)
    else:
        raise InputError("Formato não suportado; use .csv ou .xlsx.")
