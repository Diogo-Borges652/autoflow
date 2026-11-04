"""Exportações determinísticas e publicação de uma pasta completa por rename."""

import csv
import html
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from openpyxl import Workbook

from .domain import COLUMNS, Result

ISSUE_COLUMNS = ("linha", "codigo", "motivo", "linha_original")


def safe_cell(value):
    """Neutraliza interpretação de fórmulas em leitores de CSV/planilha."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path: Path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_cell(row.get(k, "")) for k in columns})


def write_xlsx(path: Path, records, issues):
    workbook = Workbook(write_only=True)
    for name, columns, rows in [
        ("Registros", COLUMNS, records),
        ("Ocorrencias", ISSUE_COLUMNS, issues),
    ]:
        sheet = workbook.create_sheet(name)
        sheet.append(list(columns))
        for row in rows:
            sheet.append([safe_cell(row.get(k, "")) for k in columns])
    workbook.save(path)
    workbook.close()


def brl(value: str) -> str:
    whole, cents = value.lstrip("-").split(".")
    sign = "-" if value.startswith("-") else ""
    return "R$ " + sign + f"{int(whole):,}".replace(",", ".") + "," + cents


def render_html(summary: dict) -> str:
    escape = html.escape
    cards = "".join(
        f"<article><h2>{label}</h2><strong>{escape(str(value))}</strong></article>"
        for label, value in [
            ("Registros aceitos", summary["aceitos"]),
            ("Receitas", brl(summary["receitas"])),
            ("Despesas", brl(summary["despesas"])),
            ("Saldo", brl(summary["saldo"])),
        ]
    )

    def table(title, items):
        rows = (
            "".join(
                "<tr><th scope='row'>"
                + escape(name)
                + "</th>"
                + "".join(
                    "<td>" + escape(brl(values[k])) + "</td>"
                    for k in ("receitas", "despesas", "saldo")
                )
                + "</tr>"
                for name, values in items.items()
            )
            or '<tr><td colspan="4">Nenhum registro válido neste arquivo.</td></tr>'
        )
        return f"""<section><h2>{title}</h2><div class="table"><table>
<caption>{title} — apenas registros aceitos</caption><thead><tr>
<th scope="col">Grupo</th><th scope="col">Receitas</th><th scope="col">Despesas</th>
<th scope="col">Saldo</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""

    notice = (
        "Demonstração com dados fictícios."
        if summary["demonstracao"]
        else "Dados fornecidos pelo operador; trate os arquivos de saída como privados."
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>AutoFlow — Relatório de processamento</title>
<style>
:root{{color-scheme:light;font-family:system-ui,sans-serif;color:#162e2a;background:#f3f5f1}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1100px;margin:auto;padding:48px 24px}}
header{{border-bottom:2px solid #184e43;padding-bottom:28px}}
.brand{{font-weight:750;letter-spacing:.12em}}
h1{{font-size:clamp(2rem,5vw,3.5rem);letter-spacing:-.04em;margin-bottom:12px}}
p{{line-height:1.6;max-width:78ch}}.muted{{color:#465e57}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:32px 0}}
article,section{{background:#fff;border:1px solid #c9d8d1;border-radius:12px;padding:22px}}
article h2{{font-size:.85rem;font-weight:550;margin:0 0 16px}}
strong{{font-size:clamp(1.2rem,2vw,1.6rem)}}
section{{margin:20px 0}}section h2{{margin-top:0}}.table{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;text-align:left}}
th,td{{padding:14px 10px;border-bottom:1px solid #dce5df}}
td{{text-align:right;white-space:nowrap}}caption{{text-align:left;margin-bottom:10px;color:#465e57}}
footer{{font-size:.875rem;margin-top:32px;overflow-wrap:anywhere}}code{{font-size:.8rem}}
@media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}main{{padding:28px 16px}}}}
@media(max-width:420px){{.cards{{grid-template-columns:1fr}}}}
@media print{{body{{background:white}}main{{padding:0}}}}
</style></head><body><main><header><p class="brand">AUTOFLOW / OPERAÇÕES</p>
<h1>Dados organizados.<br>Decisões conferíveis.</h1>
<p class="muted">Relatório local gerado a partir do arquivo fornecido. Não consulta bancos,
serviços financeiros ou sistemas externos. {notice}</p>
</header><div class="cards">{cards}</div><section><h2>Qualidade da entrada</h2>
<p>{summary["linhas_lidas"]} linhas não vazias lidas ·
{summary["normalizados"]} registros aceitos normalizados ·
{summary["duplicados"]} duplicatas excluídas ·
{summary["rejeitados"]} linhas inválidas rejeitadas.</p>
<p>O primeiro registro válido de cada ID foi mantido. Consulte <code>ocorrencias.csv</code>
para os números das linhas rejeitadas e os conflitos.
Campos opcionais ausentes não são inferidos.</p></section>
{table("Consolidação por categoria", summary["por_categoria"])}
{table("Evolução mensal", summary["por_mes"])}
<footer>AutoFlow {escape(summary["versao"])} · Valores em BRL, precisão de centavos.<br>
SHA-256 da entrada: <code>{escape(summary["entrada_sha256"])}</code></footer>
</main></body></html>"""


def export(result: Result, destination: Path, metadata: dict) -> dict:
    """Não sobrescreve destinos; entradas privadas nunca são copiadas para relatórios."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destino já existe; escolha uma pasta nova.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / ("." + destination.name + ".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    temporary = None
    try:
        os.close(descriptor)
        temporary = Path(tempfile.mkdtemp(prefix=".autoflow-", dir=destination.parent))
        records = [asdict(r) for r in result.records]
        issues = [asdict(i) for i in result.issues]
        summary = {**result.summary(), **metadata}
        write_csv(temporary / "registros.csv", COLUMNS, records)
        write_csv(temporary / "ocorrencias.csv", ISSUE_COLUMNS, issues)
        write_xlsx(temporary / "resultado.xlsx", records, issues)
        (temporary / "resumo.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (temporary / "relatorio.html").write_text(render_html(summary), encoding="utf-8")
        (temporary / "execucao.log").write_text(
            f"INFO processamento concluído: lidas={result.total} "
            f"aceitas={len(records)} ocorrencias={len(issues)}\n",
            encoding="utf-8",
        )
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Destino criado durante a execução; nada foi substituído.")
        temporary.rename(destination)
        return summary
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)
        lock.unlink(missing_ok=True)
