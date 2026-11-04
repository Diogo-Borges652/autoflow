"""Regras puras de validação; nenhum acesso a arquivos ou rede."""

import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

COLUMNS = ("id", "nome", "email", "categoria", "data", "tipo", "valor")
REQUIRED = {"id", "nome", "data", "tipo", "valor"}


def text(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str("" if value is None else value)).split())


def key(value: object) -> str:
    value = unicodedata.normalize("NFKD", text(value).lower())
    return "".join(c for c in value if not unicodedata.combining(c))


def money(value: object) -> Decimal:
    """Aceita decimal canônico ou brasileiro; rejeita arredondamento implícito."""
    raw = text(value)
    if isinstance(value, bool):
        raise ValueError("valor inválido")
    if re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,2}", raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        raise ValueError("valor deve ser positivo com até duas casas decimais")
    try:
        amount = Decimal(raw)
        if not 0 < amount <= Decimal("999999999.99"):
            raise ValueError("valor fora do intervalo (0, 999999999.99]")
        return amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("valor inválido") from exc


def civil_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw)
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
        return datetime.strptime(raw, "%d/%m/%Y").date()
    raise ValueError("data deve usar AAAA-MM-DD ou DD/MM/AAAA")


@dataclass(frozen=True)
class Record:
    id: str
    nome: str
    email: str
    categoria: str
    data: str
    tipo: str
    valor: str


@dataclass(frozen=True)
class Issue:
    linha: int
    codigo: str
    motivo: str
    linha_original: int | None = None


@dataclass
class Result:
    records: list[Record] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    total: int = 0
    normalized: int = 0

    def summary(self) -> dict:
        revenue = Decimal("0.00")
        expense = Decimal("0.00")
        groups = defaultdict(lambda: {"receitas": Decimal("0.00"), "despesas": Decimal("0.00")})
        months = defaultdict(lambda: {"receitas": Decimal("0.00"), "despesas": Decimal("0.00")})
        for record in self.records:
            amount = Decimal(record.valor)
            kind = "receitas" if record.tipo == "receita" else "despesas"
            groups[record.categoria][kind] += amount
            months[record.data[:7]][kind] += amount
            if record.tipo == "receita":
                revenue += amount
            else:
                expense += amount

        def serialize(items):
            return {
                k: {
                    **{a: str(b) for a, b in v.items()},
                    "saldo": str(v["receitas"] - v["despesas"]),
                }
                for k, v in sorted(items.items())
            }

        return {
            "linhas_lidas": self.total,
            "aceitos": len(self.records),
            "duplicados": sum(i.codigo.startswith("duplicado") for i in self.issues),
            "rejeitados": sum(not i.codigo.startswith("duplicado") for i in self.issues),
            "normalizados": self.normalized,
            "receitas": str(revenue),
            "despesas": str(expense),
            "saldo": str(revenue - expense),
            "por_categoria": serialize(groups),
            "por_mes": serialize(months),
        }


def validate(row: dict) -> Record:
    if any(
        isinstance(v, str) and re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v) for v in row.values()
    ):
        raise ValueError("caractere de controle não permitido")
    for name in REQUIRED:
        if row.get(name) is None or not text(row[name]):
            raise ValueError(f"campo obrigatório ausente: {name}")
    identity = text(row["id"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
        raise ValueError("id deve conter de 1 a 64 letras ASCII, números, _ ou -")
    name = text(row["nome"])
    category = text(row.get("categoria")) or "Sem categoria"
    email = text(row.get("email")).lower()
    if len(name) > 160 or len(category) > 80:
        raise ValueError("nome ou categoria excede o limite")
    if email and (len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)):
        raise ValueError("email inválido; deixe vazio se desconhecido")
    kind = key(row["tipo"])
    if kind not in {"receita", "despesa"}:
        raise ValueError("tipo deve ser receita ou despesa")
    try:
        day = civil_date(row["data"]).isoformat()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("data inválida; use AAAA-MM-DD ou DD/MM/AAAA") from exc
    return Record(identity, name, email, category, day, kind, str(money(row["valor"])))


def process(rows) -> Result:
    result = Result()
    seen: dict[str, tuple[int, Record]] = {}
    for line, row, error in rows:
        result.total += 1
        try:
            if error:
                raise ValueError(error)
            record = validate(row)
        except (ValueError, TypeError, OverflowError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "formato de campo inválido"
            result.issues.append(Issue(line, "invalido", reason))
            continue
        if record.id in seen:
            original_line, original = seen[record.id]
            same = original == record
            result.issues.append(
                Issue(
                    line,
                    "duplicado" if same else "duplicado_conflitante",
                    "ID repetido" if same else "ID repetido com conteúdo diferente",
                    original_line,
                )
            )
            continue
        seen[record.id] = (line, record)
        result.records.append(record)
        if any(
            str(row.get(k) if row.get(k) is not None else "") != v
            for k, v in asdict(record).items()
        ):
            result.normalized += 1
    return result
