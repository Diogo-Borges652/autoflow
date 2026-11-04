"""Audita nomes versionados e todos os blobs alcançáveis sem imprimir valores."""

import re
import subprocess
from pathlib import PurePosixPath


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    filenames = git("ls-files", "-z").decode().split("\0")
    problems = []
    for name in filter(None, filenames):
        path = PurePosixPath(name)
        if (
            path.name.startswith(".env")
            or path.suffix in {".key", ".pem", ".db", ".sqlite"}
            or set(path.parts) & {".venv", "node_modules", "output", "secrets", ".private"}
        ):
            problems.append("nome de arquivo não publicável: " + name)
    patterns = [
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        rb"gh[pousr]_[A-Za-z0-9]{30,}",
        rb"github_pat_[A-Za-z0-9_]{40,}",
        rb"sk-(?:proj-)?[A-Za-z0-9_-]{40,}",
        rb"AKIA[A-Z0-9]{16}",
        rb"/home/[A-Za-z0-9_.-]+/",
    ]
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    count = 0
    for line in objects:
        sha, _, name = line.partition(" ")
        if git("cat-file", "-t", sha).strip() != b"blob":
            continue
        count += 1
        data = git("cat-file", "blob", sha)
        if any(re.search(pattern, data) for pattern in patterns):
            problems.append("padrão sensível no objeto " + sha[:12] + " (" + name + ")")
    for problem in problems:
        print(problem)
    print(f"Objetos de conteúdo examinados: {count}; achados: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
