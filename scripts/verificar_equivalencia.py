"""Confere que a consulta de vistorias reescrita devolve o MESMO resultado da original.

A reescrita (`vistorias_alertas_reescrita`) so e um tratamento valido se for equivalente.
Para evitar empates no LIMIT, o limite e aumentado e os resultados sao comparados como
conjuntos de (id da vistoria, data da ultima checagem).

Uso (com o banco do laboratorio populado por gerar_dados.py):
    python scripts/verificar_equivalencia.py
"""

import sys

import psycopg

from comum import conectar
from consultas import CONSULTAS

LIMITE_ALTO = 1_000_000


def resultado(cur, consulta, params) -> set:
    marcadores = ", ".join(["%s"] * len(params))
    cur.execute(f"DEALLOCATE ALL")
    cur.execute(f"PREPARE p ({consulta.tipos}) AS {consulta.sql}")
    cur.execute(f"EXECUTE p({marcadores})", params)
    colunas = [d.name for d in cur.description]
    i_id = colunas.index("id")
    # A ultima coluna e a data da ultima checagem (nas duas consultas).
    return {(linha[i_id], linha[-1]) for linha in cur.fetchall()}


def main() -> int:
    original = next(c for c in CONSULTAS if c.id == "vistorias_alertas")
    reescrita = next(c for c in CONSULTAS if c.id == "vistorias_alertas_reescrita")
    divergencias = 0
    with conectar() as conn, psycopg.ClientCursor(conn) as cur:
        for (rotulo, params), (_, params_r) in zip(original.variantes, reescrita.variantes):
            params = (*params[:-1], LIMITE_ALTO)
            params_r = (*params_r[:-1], LIMITE_ALTO)
            a = resultado(cur, original, params)
            b = resultado(cur, reescrita, params_r)
            ok = a == b
            divergencias += 0 if ok else 1
            print(f"{rotulo:10} original={len(a):6} reescrita={len(b):6} {'IGUAL' if ok else 'DIFERENTE'}")
    if divergencias:
        print(f"\nFALHA: {divergencias} variante(s) com resultado diferente.")
        return 1
    print("\nOK: a reescrita devolve o mesmo resultado em todas as variantes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
