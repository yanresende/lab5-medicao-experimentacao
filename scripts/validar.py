"""Valida um CSV de medicoes antes de qualquer analise (sanidade, nao inferencia).

Checagens:
  - colunas esperadas presentes; celulas vazias so onde ha timeout;
  - tempos finitos e positivos nas medicoes completas;
  - sem medicao duplicada;
  - desenho balanceado: toda celula (estudo, consulta, variante, modo, condicao) tem
    o mesmo numero de medicoes, e cada estudo tem a condicao `sem_indice` mais ao
    menos uma outra.
Reporta (sem tratar como erro): mediana de cada condicao, razao em relacao a
`sem_indice`, plano mais frequente e medicoes censuradas por timeout.

Uso:
    python scripts/validar.py dados/medicoes_<...>.csv
"""

import argparse
import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

OBRIGATORIAS = [
    "execucao_id", "empresas", "estatistica_tenant", "tamanho", "estudo", "consulta_id", "variante", "condicao",
    "ordem_condicao", "modo_plano", "rodada", "tempo_exec_ms", "tempo_plan_ms",
    "linhas_estimadas", "linhas_reais_no_scan", "linhas_lidas",
    "shared_hit", "shared_read", "tem_sort", "nos", "estourou_timeout",
]
CAMPOS_DE_MEDICAO = ["tempo_exec_ms", "tempo_plan_ms", "linhas_estimadas", "linhas_reais_no_scan", "linhas_lidas",
                     "shared_hit", "shared_read", "tem_sort", "nos"]


def mediana(valores: list[float]) -> float:
    return statistics.median(valores) if valores else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    args = ap.parse_args()

    with args.csv.open(newline="", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        faltam = [c for c in OBRIGATORIAS if c not in (leitor.fieldnames or [])]
        if faltam:
            print(f"ERRO: colunas ausentes: {faltam}")
            return 1
        linhas = list(leitor)
    if not linhas:
        print("ERRO: CSV sem medicoes")
        return 1

    erros = []
    for i, l in enumerate(linhas, start=2):
        timeout = l["estourou_timeout"] == "1"
        vazias = [c for c in OBRIGATORIAS if l[c] == "" and (not timeout or c not in CAMPOS_DE_MEDICAO)]
        if vazias:
            erros.append(f"linha {i}: celulas vazias {vazias}")
        if not timeout:
            for c in ("tempo_exec_ms", "tempo_plan_ms"):
                try:
                    v = float(l[c])
                except ValueError:
                    erros.append(f"linha {i}: {c} nao numerico ({l[c]!r})")
                    continue
                if not math.isfinite(v) or v <= 0:
                    erros.append(f"linha {i}: {c} invalido ({l[c]})")

    chave = lambda l: (l["execucao_id"], l["estudo"], l["consulta_id"], l["variante"],
                       l["condicao"], l["modo_plano"], l["rodada"])
    duplicadas = [k for k, n in Counter(chave(l) for l in linhas).items() if n > 1]
    if duplicadas:
        erros.append(f"{len(duplicadas)} medicoes duplicadas, ex.: {duplicadas[0]}")

    celulas = defaultdict(list)
    for l in linhas:
        celulas[(l["estudo"], l["consulta_id"], l["variante"], l["modo_plano"], l["condicao"])].append(l)
    contagens = {len(v) for v in celulas.values()}
    if len(contagens) != 1:
        erros.append(f"desenho desbalanceado: celulas com {sorted(contagens)} medicoes")
    for estudo in {l["estudo"] for l in linhas}:
        conds = {l["condicao"] for l in linhas if l["estudo"] == estudo}
        if "sem_indice" not in conds or len(conds) < 2:
            erros.append(f"estudo {estudo}: condicoes encontradas {sorted(conds)}")

    censuradas = sum(1 for l in linhas if l["estourou_timeout"] == "1")
    empresas = sorted({l["empresas"] for l in linhas})
    tamanhos = sorted({l["tamanho"] for l in linhas})
    print(f"Arquivo: {args.csv}")
    print(f"Empresas: {empresas} | linhas por tabela: {tamanhos} | medicoes: {len(linhas)} | "
          f"celulas: {len(celulas)} | por celula: {sorted(contagens)} | censuradas: {censuradas}")
    print()
    print(f"{'estudo':9} {'consulta':25} {'variante':14} {'plano':8} {'condicao':20} "
          f"{'mediana ms':>11} {'vs sem':>7}  plano")

    consultas = sorted({k[:4] for k in celulas})
    for estudo, cid, var, modo in consultas:
        def tempos(cond):
            return [float(x["tempo_exec_ms"]) for x in celulas.get((estudo, cid, var, modo, cond), [])
                    if x["estourou_timeout"] != "1"]
        base = mediana(tempos("sem_indice"))
        condicoes = sorted({k[4] for k in celulas if k[:4] == (estudo, cid, var, modo)},
                           key=lambda c: (c != "sem_indice", c))
        for cond in condicoes:
            t = tempos(cond)
            m = mediana(t)
            m_txt = f"{m:11.3f}" if t else f"{'timeout':>11}"
            razao = f"{base / m:7.1f}" if t and tempos("sem_indice") and m else f"{'-':>7}"
            planos = Counter(x["nos"] for x in celulas.get((estudo, cid, var, modo, cond), []) if x["nos"])
            plano = planos.most_common(1)[0][0] if planos else "-"
            print(f"{estudo:9} {cid:25} {var:14} {modo:8} {cond:20} {m_txt} {razao}  {plano[:60]}")
    print("\n(medianas em ms; apenas conferencia, a analise estatistica fica na Sprint 2)")

    if erros:
        print("\nPROBLEMAS ENCONTRADOS:")
        for e in erros[:20]:
            print(f" - {e}")
        return 1
    print("\nOK: dados validos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
