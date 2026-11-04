"""Interface de linha de comando; falhas não expõem conteúdo nem credenciais."""

import argparse
import hashlib
import logging
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException

from . import __version__
from .domain import process
from .readers import InputError, read_rows
from .report import export


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="autoflow", description="Valida e consolida registros administrativos CSV/XLSX."
    )
    parser.add_argument("input", type=Path, help="CSV UTF-8 ou XLSX, até 10 MiB")
    parser.add_argument("--output", required=True, type=Path, help="pasta de saída nova")
    parser.add_argument("--delimiter", choices=[",", ";", "\t"], help="separador CSV explícito")
    parser.add_argument("--sheet", help="aba XLSX (obrigatória se houver várias)")
    parser.add_argument("--strict", action="store_true", help="retorna 3 se houver ocorrências")
    parser.add_argument(
        "--demo", action="store_true", help="identifica dados fictícios no relatório"
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger = logging.getLogger("autoflow")
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError
        # Limit is checked before hashing. A second hash detects concurrent edits.
        rows = read_rows(args.input, args.delimiter, args.sheet)
        from .readers import MAX_BYTES

        if not args.input.is_file() or args.input.stat().st_size > MAX_BYTES:
            raise InputError("Entrada inexistente ou maior que 10 MiB.")
        before = hashlib.sha256(args.input.read_bytes()).hexdigest()
        result = process(rows)
        after = hashlib.sha256(args.input.read_bytes()).hexdigest()
        if before != after:
            raise InputError("Entrada mudou durante a leitura; repita com uma cópia estável.")
        summary = export(
            result,
            args.output,
            {
                "versao": __version__,
                "entrada_sha256": before,
                "demonstracao": args.demo,
            },
        )
    except FileExistsError:
        logger.error("Destino existente ou outra execução em andamento; use uma pasta nova.")
        return 2
    except InputError as exc:
        logger.error("%s", exc)
        return 2
    except (OSError, ValueError, KeyError, ParseError, DefusedXmlException):
        logger.error("Falha ao ler ou exportar. Verifique formato, permissões e espaço em disco.")
        return 2
    logger.info(
        "Lidas=%s aceitas=%s duplicadas=%s rejeitadas=%s",
        summary["linhas_lidas"],
        summary["aceitos"],
        summary["duplicados"],
        summary["rejeitados"],
    )
    return 3 if args.strict and result.issues else 0
