"""Benchmark: configuracoes de indices comparadas sobre os MESMOS dados.

Dois estudos (ver PROPOSTA.md e scripts/comum.py, que define as condicoes):
  - v2        : listagens de ocorrencias e fichas. Condicoes: sem_indice, v2 (indices
                da migracao V2), producao (V2 + indice de tenant, o estado de hoje) e
                dois candidatos com a empresa na frente. Inclui uma consulta de
                controle (ordena por nome), que nao deveria ganhar nada;
  - vistorias : consulta de alertas de vistorias, que em producao consome 73% do
                tempo do banco. Condicoes: sem_indice (producao) e com_indice
                (indice composto em vistoria_visitas).

Os dados vem de `gerar_dados.py --empresas N`: as consultas medem a empresa 1 e as
demais so aumentam o volume do banco (escala multi-tenant).

Fatores medidos: condicao e modo de plano (custom, generic). As consultas rodam como PREPARE + EXECUTE com `plan_cache_mode`
forcado, porque o pgjdbc passa a usar plano generico apos 5 execucoes e o padrao
`($1 IS NULL OR unidade_id = $2)` pode se comportar diferente nele.

Desenho: ordem das condicoes e dos modos sorteada pela semente; por celula,
`--aquecimento` execucoes descartadas e `--repeticoes` rodadas com a ordem das
consultas sorteada a cada rodada. `--timeout-s` interrompe consultas muito
lentas (registradas como censuradas, nao como erro).

Uso:
    python scripts/benchmark.py --repeticoes 10 --aquecimento 3 --semente 42
"""

import argparse
import csv
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

import psycopg
from psycopg import errors

from comum import (ESTUDOS, MODOS_PLANO, RAIZ, TABELAS, conectar, indices_da_condicao,
                   todos_os_indices)
from consultas import consultas_do_estudo

COLUNAS_CSV = [
    "execucao_id", "empresas", "estatistica_tenant", "tamanho", "estudo", "consulta_id", "variante", "condicao",
    "ordem_condicao", "modo_plano", "rodada", "tempo_exec_ms", "tempo_plan_ms",
    "linhas_estimadas", "linhas_reais_no_scan", "linhas_lidas", "shared_hit", "shared_read", "tem_sort", "nos", "estourou_timeout",
]


def percorrer(plano: dict):
    """Gera todos os nos do plano, em pre-ordem (inclui InitPlans e SubPlans)."""
    yield plano
    for filho in plano.get("Plans", []):
        yield from percorrer(filho)


def extrair(resultado: list) -> dict:
    """Extrai as metricas M1 a M3 do JSON do EXPLAIN."""
    raiz = resultado[0]
    plano = raiz["Plan"]
    nos = list(percorrer(plano))
    lidas = sum(
        (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0)) * n.get("Actual Loops", 1)
        for n in nos
        if "Scan" in n["Node Type"]
    )
    # Erro de estimativa (PP7): primeiro no de varredura do plano, estimado x real.
    no_scan = next((n for n in nos if "Scan" in n["Node Type"]), None)
    return {
        "tempo_exec_ms": raiz["Execution Time"],
        "tempo_plan_ms": raiz["Planning Time"],
        "linhas_estimadas": no_scan["Plan Rows"] if no_scan else "",
        "linhas_reais_no_scan": no_scan["Actual Rows"] if no_scan else "",
        "linhas_lidas": lidas,
        "shared_hit": plano.get("Shared Hit Blocks", 0),
        "shared_read": plano.get("Shared Read Blocks", 0),
        "tem_sort": any("Sort" in n["Node Type"] for n in nos),
        "nos": ">".join(n["Node Type"] for n in nos),
        "estourou_timeout": 0,
    }


def resultado_timeout() -> dict:
    return {
        "tempo_exec_ms": "", "tempo_plan_ms": "", "linhas_estimadas": "", "linhas_reais_no_scan": "",
        "linhas_lidas": "", "shared_hit": "",
        "shared_read": "", "tem_sort": "", "nos": "", "estourou_timeout": 1,
    }


TABELAS_COM_TENANT = ("ocorrencias", "fichas", "vistorias", "vistoria_visitas")


def apagar_estatistica_tenant(conn) -> None:
    """Remove as estatisticas da coluna tenant_id (reproduz uma coluna recem-adicionada
    pela V76, ainda sem ANALYZE: o planejador cai na selectividade padrao de 0,5%).
    Exige superusuario (o do conteiner do laboratorio e)."""
    for tabela in TABELAS_COM_TENANT:
        conn.execute(
            f"DELETE FROM pg_statistic WHERE starelid = '{tabela}'::regclass AND staattnum = "
            f"(SELECT attnum FROM pg_attribute WHERE attrelid = '{tabela}'::regclass "
            f"AND attname = 'tenant_id')"
        )


def preparar_condicao(conn, estudo: str, condicao: str, estatistica_tenant: str) -> None:
    """Deixa o banco com exatamente os indices da condicao e atualiza as estatisticas."""
    todos = todos_os_indices(estudo)
    for nome in todos:
        conn.execute(f"DROP INDEX IF EXISTS {nome}")
    for _, instrucao in indices_da_condicao(estudo, condicao).values():
        conn.execute(instrucao)
    for tabela in TABELAS_COM_TENANT:
        conn.execute(f"ANALYZE {tabela}")
    if estatistica_tenant == "ausente":
        apagar_estatistica_tenant(conn)
    conn.execute("CHECKPOINT")


def preparar_consultas(cur, consultas) -> None:
    cur.execute("DEALLOCATE ALL")
    for c in consultas:
        cur.execute(f"PREPARE p_{c.id} ({c.tipos}) AS {c.sql}")


def medir(cur, consulta_id: str, params: tuple) -> dict:
    marcadores = ", ".join(["%s"] * len(params))
    cur.execute(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) EXECUTE p_{consulta_id}({marcadores})",
        params,
    )
    return extrair(cur.fetchone()[0])


def metadados(conn, args, ordens: dict, tamanhos: dict) -> dict:
    config = {}
    for chave in ("shared_buffers", "work_mem", "max_parallel_workers_per_gather",
                  "random_page_cost", "effective_cache_size", "track_io_timing"):
        config[chave] = conn.execute(f"SHOW {chave}").fetchone()[0]
    return {
        "inicio": dt.datetime.now().isoformat(timespec="seconds"),
        "postgres": conn.execute("SHOW server_version").fetchone()[0],
        "configuracao": config,
        "argumentos": vars(args),
        "ordens": ordens,
        "linhas_por_tabela": tamanhos,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--estudo", choices=("todos", *ESTUDOS), default="todos")
    ap.add_argument("--repeticoes", type=int, default=10)
    ap.add_argument("--aquecimento", type=int, default=3)
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument("--estatistica-tenant", choices=("atualizada", "ausente"), default="atualizada",
                    help="'ausente' remove as estatisticas de tenant_id apos cada ANALYZE, como a "
                         "producao hoje (coluna da V76 sem ANALYZE)")
    ap.add_argument("--timeout-s", type=float, default=60.0,
                    help="interrompe uma consulta apos este tempo (registrada como censurada)")
    ap.add_argument("--saida", type=Path, default=None,
                    help="CSV de saida (padrao: dados/medicoes_<tamanho>_<data>.csv)")
    args = ap.parse_args()

    rng = random.Random(args.semente)
    estudos = list(ESTUDOS) if args.estudo == "todos" else [args.estudo]

    with conectar() as conn:
        contagens = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in (*TABELAS, "vistoria_visitas")
        }
        principais = {contagens[t] for t in TABELAS}
        if len(principais) != 1:
            print(f"Tabelas principais com tamanhos diferentes: {contagens}")
            return 1
        tamanho = principais.pop()
        empresas = conn.execute("SELECT count(DISTINCT tenant_id) FROM ocorrencias").fetchone()[0]

        ordens = {}
        for e in estudos:
            conds, modos = list(ESTUDOS[e]), list(MODOS_PLANO)
            rng.shuffle(conds)
            rng.shuffle(modos)
            ordens[e] = {"condicoes": conds, "modos": modos}

        meta = metadados(conn, args, ordens, contagens)
        carimbo = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        saida = args.saida or (RAIZ / "dados" / f"medicoes_{empresas}emp_{tamanho}_{carimbo}.csv")
        saida.parent.mkdir(parents=True, exist_ok=True)
        execucao_id = f"{empresas}emp-{tamanho}-{carimbo}"
        t0 = time.time()
        feitas = 0

        conn.execute(f"SET statement_timeout = {int(args.timeout_s * 1000)}")
        if args.estatistica_tenant == "ausente":
            # Impede o autovacuum de refazer a estatistica no meio da execucao.
            for tabela in TABELAS_COM_TENANT:
                conn.execute(f"ALTER TABLE {tabela} SET (autovacuum_enabled = false)")

        with saida.open("w", newline="", encoding="utf-8") as f, \
                psycopg.ClientCursor(conn) as cur:
            escritor = csv.DictWriter(f, fieldnames=COLUNAS_CSV)
            escritor.writeheader()

            for estudo in estudos:
                consultas = consultas_do_estudo(estudo)
                alvos = [(c, rotulo, params) for c in consultas for rotulo, params in c.variantes]

                for posicao, condicao in enumerate(ordens[estudo]["condicoes"], start=1):
                    preparar_condicao(conn, estudo, condicao, args.estatistica_tenant)

                    for modo in ordens[estudo]["modos"]:
                        conn.execute(f"SET plan_cache_mode = force_{modo}_plan")
                        preparar_consultas(cur, consultas)
                        censuradas = set()

                        # Aquecimento (descartado). Uma consulta que estoura o tempo ja
                        # no aquecimento e marcada como censurada e nao e repetida.
                        for _ in range(args.aquecimento):
                            for c, rotulo, params in alvos:
                                if (c.id, rotulo) in censuradas:
                                    continue
                                try:
                                    medir(cur, c.id, params)
                                except errors.QueryCanceled:
                                    censuradas.add((c.id, rotulo))

                        for rodada in range(1, args.repeticoes + 1):
                            rng.shuffle(alvos)
                            for c, rotulo, params in alvos:
                                if (c.id, rotulo) in censuradas:
                                    m = resultado_timeout()
                                else:
                                    try:
                                        m = medir(cur, c.id, params)
                                    except errors.QueryCanceled:
                                        censuradas.add((c.id, rotulo))
                                        m = resultado_timeout()
                                escritor.writerow({
                                    "execucao_id": execucao_id, "empresas": empresas,
                                    "estatistica_tenant": args.estatistica_tenant,
                                    "tamanho": tamanho, "estudo": estudo, "consulta_id": c.id, "variante": rotulo,
                                    "condicao": condicao, "ordem_condicao": posicao,
                                    "modo_plano": modo, "rodada": rodada, **m,
                                })
                                feitas += 1
                        print(f"[{estudo}|{condicao}|{modo}] concluido "
                              f"({feitas} medicoes, {len(censuradas)} censuradas)")

                # Estado final conhecido: o de producao (v2) ou o com indice (vistorias).
                preparar_condicao(conn, estudo,
                                  "producao" if "producao" in ESTUDOS[estudo] else "com_indice",
                                  "atualizada")
        if args.estatistica_tenant == "ausente":
            for tabela in TABELAS_COM_TENANT:
                conn.execute(f"ALTER TABLE {tabela} RESET (autovacuum_enabled)")

        conn.execute("RESET plan_cache_mode")
        conn.execute("RESET statement_timeout")

    meta["fim"] = dt.datetime.now().isoformat(timespec="seconds")
    meta["duracao_s"] = round(time.time() - t0, 1)
    meta_arquivo = saida.with_suffix(".meta.json")
    meta_arquivo.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"CSV: {saida}")
    print(f"Metadados: {meta_arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
