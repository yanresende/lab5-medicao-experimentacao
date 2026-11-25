"""Roda a coleta completa da Sprint 2 (Matrizes A e B), em sequencia e de forma retomavel.

Para cada banco (numero de empresas x linhas por empresa), gera os dados uma vez e roda
todas as execucoes que usam esse banco. Cada execucao grava dados/<nome>.csv e o
.meta.json correspondente, e e validada logo em seguida. Execucoes cujo CSV ja existe
sao puladas (para retomar depois de uma interrupcao), a menos que se use --refazer.

Matriz A (P1 e P2): estudo v2, estatistica `ausente` e `atualizada`, 1, 2, 5, 10 e 50
empresas, 8.000 linhas por empresa.
Matriz B (P3): estudo vistorias, estatistica `ausente` (como a producao hoje), tamanhos
350 x 1, 1.000 x 1, 8.000 x 1 e 8.000 x 5 (os dois ultimos reaproveitam os bancos da
Matriz A). Antes de cada execucao da Matriz B a equivalencia da reescrita e conferida.

Uso:
    python scripts/rodar_matrizes.py              # tudo, com os parametros da proposta
    python scripts/rodar_matrizes.py --so B_      # so as execucoes cujo nome comeca por B_
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable

# (empresas, linhas por empresa, [(nome da execucao, estudo, estatistica de tenant_id)])
PLANO = [
    (1, 8000, [("A_01emp_ausente", "v2", "ausente"), ("A_01emp_atualizada", "v2", "atualizada"),
               ("B_8000x1", "vistorias", "ausente")]),
    (2, 8000, [("A_02emp_ausente", "v2", "ausente"), ("A_02emp_atualizada", "v2", "atualizada")]),
    (5, 8000, [("A_05emp_ausente", "v2", "ausente"), ("A_05emp_atualizada", "v2", "atualizada"),
               ("B_8000x5", "vistorias", "ausente")]),
    (10, 8000, [("A_10emp_ausente", "v2", "ausente"), ("A_10emp_atualizada", "v2", "atualizada")]),
    (50, 8000, [("A_50emp_ausente", "v2", "ausente"), ("A_50emp_atualizada", "v2", "atualizada")]),
    (1, 350, [("B_350x1", "vistorias", "ausente")]),
    (1, 1000, [("B_1000x1", "vistorias", "ausente")]),
]


def rodar(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd[1:]), flush=True)
    resultado = subprocess.run(cmd, cwd=RAIZ)
    if resultado.returncode != 0:
        raise SystemExit(f"Falhou (codigo {resultado.returncode}): {' '.join(cmd)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeticoes", type=int, default=30)
    ap.add_argument("--aquecimento", type=int, default=5)
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--timeout-s", type=float, default=60.0)
    ap.add_argument("--so", default="", help="roda so as execucoes cujo nome comeca com este prefixo")
    ap.add_argument("--refazer", action="store_true", help="refaz execucoes que ja tem CSV")
    args = ap.parse_args()

    inicio = time.time()
    for empresas, tamanho, execucoes in PLANO:
        pendentes = [e for e in execucoes
                     if e[0].startswith(args.so)
                     and (args.refazer or not (RAIZ / "dados" / f"{e[0]}.csv").exists())]
        if not pendentes:
            continue
        print(f"\n=== Banco: {empresas} empresa(s) x {tamanho} linhas "
              f"({time.time() - inicio:.0f} s desde o inicio)", flush=True)
        rodar([PY, "scripts/gerar_dados.py", "--tamanho", str(tamanho),
               "--empresas", str(empresas), "--semente", str(args.semente)])

        for nome, estudo, estatistica in pendentes:
            print(f"\n--- {nome}", flush=True)
            if estudo == "vistorias":
                rodar([PY, "scripts/verificar_equivalencia.py"])
            saida = f"dados/{nome}.csv"
            rodar([PY, "scripts/benchmark.py", "--estudo", estudo,
                   "--estatistica-tenant", estatistica,
                   "--repeticoes", str(args.repeticoes), "--aquecimento", str(args.aquecimento),
                   "--semente", str(args.semente), "--timeout-s", str(args.timeout_s),
                   "--saida", saida])
            rodar([PY, "scripts/validar.py", saida])

    print(f"\nConcluido em {time.time() - inicio:.0f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
