"""Gera dados SINTETICOS para o experimento (nenhum dado real do Sentinela).

Recria as tabelas (scripts/sql/schema.sql) e as popula via COPY. Simula um banco
multi-tenant: `--empresas N` empresas, cada uma com `--tamanho` linhas em cada
tabela principal (ocorrencias, fichas, vistorias) e cerca de 1,7 visita por
vistoria (razao observada em producao: 611 / 351). A empresa k tem as unidades
2k-1 e 2k (a empresa 1 tem as unidades 1 e 2, como MG e ES hoje).
Tudo e deterministico a partir de `--semente`.

Uso:
    python scripts/gerar_dados.py --tamanho 8000 --empresas 5 --semente 42

Atencao: APAGA e recria as tabelas no banco de laboratorio.
"""

import argparse
import datetime as dt
import random
import string
import sys

from comum import REFERENCIA, SQL_DIR, TABELAS, conectar

# Tamanho (em caracteres) da coluna fora da linha `fichas.dados_extras`. Calibrado para
# reproduzir a largura media de 3,4 kB da linha de producao (ver PROPOSTA.md, 6.5).
# Definido pelo argumento --largura-extra. Ocupa disco: 400 mil fichas ocupam cerca de 1,2 GB.
LARGURA_EXTRA = 3000

PESOS_UNIDADE = (0.6, 0.4)  # distribuicao aproximada MG/ES (calibrar com agregados reais)
STATUS = ("ABERTA", "EM_ANALISE", "ENCERRADA", "ARQUIVADA")
PESOS_STATUS = (0.10, 0.10, 0.70, 0.10)
FONTES = ("SIGMA", "CAA_DIGITAL", "TELEFONE", "RONDA")
BAIRROS = ("Centro", "Industrial", "Jardim Alvorada", "Vila Nova", "Santa Rita", "Boa Vista")
CIDADES = ("Cidade A", "Cidade B", "Cidade C", "Cidade D")
JANELA_DIAS = 3 * 365  # datas distribuidas nos ultimos 3 anos (calibrar com producao)

# Fichas sem foto: o EXPLAIN ANALYZE em producao (25/11/2026) devolveu 1.841 fichas ativas
# sem foto na unidade 1, de 8.010 fichas (ao menos 23%). A pagina da consulta real tem 32
# linhas (media de linhas por chamada no pg_stat_statements). Valor calibrado: 25%.
PROPORCAO_FICHA_SEM_FOTO = 0.25

# Vistorias: distribuicoes ASSUMIDAS, a calibrar com as consultas de contagem por
# status1 e em_rota em producao (ver PROPOSTA.md).
STATUS1 = ("PRESERVADO", "ABERTO", "NECESSARIO_REPARO", "OUTRO")
PESOS_STATUS1 = (0.70, 0.10, 0.10, 0.10)
PROPORCAO_EM_ROTA = 0.90
# Numero de visitas por vistoria (media 1,7).
VISITAS_VALORES = (0, 1, 2, 3, 4)
VISITAS_PESOS = (0.25, 0.25, 0.20, 0.15, 0.15)


def unidades_da_empresa(empresa: int) -> tuple[int, int]:
    return (2 * empresa - 1, 2 * empresa)


def texto_enchimento(rng: random.Random, minimo: int, maximo: int) -> str:
    """Texto de enchimento para dar volume as linhas. Conteudo sem significado."""
    n = rng.randint(minimo, maximo)
    palavras = ("alfa", "beta", "gama", "delta", "sigma", "omega", "teta", "kappa")
    return " ".join(rng.choice(palavras) for _ in range(n))


def linhas_ocorrencias(n: int, rng: random.Random, empresa: int):
    unidades = unidades_da_empresa(empresa)
    for i in range(n):
        data = REFERENCIA - dt.timedelta(days=rng.randint(0, JANELA_DIAS))
        acion = data + dt.timedelta(days=rng.randint(0, 2))
        yield (
            rng.choices(unidades, PESOS_UNIDADE)[0],
            empresa,
            data,
            acion,
            dt.time(rng.randint(0, 23), rng.randint(0, 59)),
            rng.choices(STATUS, PESOS_STATUS)[0],
            rng.choice(FONTES),
            rng.choice(BAIRROS),
            rng.choice(CIDADES),
            f"Rua Sintetica {rng.randint(1, 999)}",
            f"BO{rng.randint(10**6, 10**7 - 1)}",
            f"SINT-{empresa}-{i:07d}",
            texto_enchimento(rng, 10, 40),
        )


def texto_largo(rng: random.Random, tamanho: int) -> str | None:
    """Um texto de `tamanho` caracteres, gerado uma vez e reaproveitado em todas as linhas
    (nao ocupa memoria extra). Vai para a coluna fora da linha `dados_extras`."""
    if tamanho <= 0:
        return None
    return "".join(rng.choices(string.ascii_lowercase + " ", k=tamanho))


def linhas_fichas(n: int, rng: random.Random, empresa: int):
    unidades = unidades_da_empresa(empresa)
    agora = dt.datetime.combine(REFERENCIA, dt.time(12, 0))
    extras = texto_largo(random.Random(f"extras:{LARGURA_EXTRA}"), LARGURA_EXTRA)
    for i in range(n):
        criacao = agora - dt.timedelta(
            days=rng.randint(0, JANELA_DIAS), seconds=rng.randint(0, 86399)
        )
        sem_foto = rng.random() < PROPORCAO_FICHA_SEM_FOTO
        yield (
            rng.choices(unidades, PESOS_UNIDADE)[0],
            empresa,
            rng.random() < 0.95,
            criacao,
            f"Pessoa Sintetica {empresa}-{i:07d}",
            f"Mae Sintetica {rng.randint(1, 10**5)}",
            texto_enchimento(rng, 4, 12),
            texto_enchimento(rng, 2, 8),
            None if sem_foto else f"https://exemplo.invalid/foto/{empresa}/{i}.jpg",
            texto_enchimento(rng, 2, 10),
            extras,
        )


def linhas_vistorias(n: int, rng: random.Random, empresa: int):
    unidades = unidades_da_empresa(empresa)
    for i in range(n):
        yield (
            rng.choices(unidades, PESOS_UNIDADE)[0],
            empresa,
            REFERENCIA - dt.timedelta(days=rng.randint(0, 2 * 365)),
            rng.choices(STATUS1, PESOS_STATUS1)[0],
            rng.random() < PROPORCAO_EM_ROTA,
            f"SITE{empresa}-{i:06d}",
            f"Rua Sintetica {rng.randint(1, 999)}",
            rng.choice(CIDADES),
            texto_enchimento(rng, 5, 30),
        )


def linhas_visitas(vistorias: list[tuple[int, int]], rng: random.Random):
    """Visitas de passagem: de 0 a 4 por vistoria, em datas aleatorias do ultimo ano.
    `vistorias` e a lista (id, tenant_id); a visita herda a empresa da vistoria."""
    for vistoria_id, empresa in vistorias:
        for _ in range(rng.choices(VISITAS_VALORES, VISITAS_PESOS)[0]):
            yield (empresa, vistoria_id, REFERENCIA - dt.timedelta(days=rng.randint(0, 365)))


# tabela -> (gerador, colunas, indice da coluna de data usada na ordem cronologica)
CONFIG = {
    "ocorrencias": (
        linhas_ocorrencias,
        "unidade_id, tenant_id, data_vandalismo, data_acionamento, hora_acionamento, "
        "status, fonte, bairro, cidade, rua, numero_bo, numeroocorrencia, observacoes",
        2,
    ),
    "fichas": (
        linhas_fichas,
        "unidade_id, tenant_id, ativo, data_criacao, nome, mae, descricao, perfil, foto_url, "
        "observacoes, dados_extras",
        3,
    ),
    "vistorias": (
        linhas_vistorias,
        "unidade_id, tenant_id, data_vistoria, status1, em_rota, sigla, endereco, cidade, observacoes",
        2,
    ),
}


def carregar(conn, tabela: str, colunas: str, linhas: list) -> int:
    with conn.cursor() as cur:
        with cur.copy(f"COPY {tabela} ({colunas}) FROM STDIN") as copia:
            for linha in linhas:
                copia.write_row(linha)
    conn.execute(f"ANALYZE {tabela}")
    return conn.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]


def main() -> int:
    global LARGURA_EXTRA
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tamanho", type=int, default=10_000,
                    help="linhas por tabela principal, POR EMPRESA")
    ap.add_argument("--empresas", type=int, default=1, help="numero de empresas (tenants)")
    ap.add_argument("--semente", type=int, default=42)
    ap.add_argument(
        "--ordem-insercao",
        choices=("aleatoria", "cronologica"),
        default="aleatoria",
        help="ordem fisica das linhas em relacao a data (afeta a eficiencia do indice)",
    )
    ap.add_argument("--largura-extra", type=int, default=LARGURA_EXTRA,
                    help="caracteres da coluna fora da linha fichas.dados_extras (0 desliga). "
                         "Use o MESMO valor em todas as execucoes comparadas")
    ap.add_argument("--forcar", action="store_true", help="permite banco diferente de 'lab5'")
    args = ap.parse_args()

    LARGURA_EXTRA = args.largura_extra

    with conectar() as conn:
        banco = conn.execute("SELECT current_database()").fetchone()[0]
        if banco != "lab5" and not args.forcar:
            print(f"Recusado: o banco e '{banco}', esperado 'lab5'. Use --forcar se for de proposito.")
            return 1

        conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))

        for tabela in TABELAS:
            gerador, colunas, idx_data = CONFIG[tabela]
            linhas = []
            for empresa in range(1, args.empresas + 1):
                # Uma semente por (tabela, empresa), derivada da semente global.
                rng = random.Random(f"{args.semente}:{tabela}:{args.tamanho}:{empresa}")
                linhas.extend(gerador(args.tamanho, rng, empresa))
            rng = random.Random(f"{args.semente}:{tabela}:ordem")
            if args.ordem_insercao == "cronologica":
                linhas.sort(key=lambda r: r[idx_data])
            else:
                rng.shuffle(linhas)
            total = carregar(conn, tabela, colunas, linhas)
            print(f"{tabela}: {total} linhas em {args.empresas} empresa(s) "
                  f"(semente={args.semente}, ordem={args.ordem_insercao})")

        # As visitas herdam a empresa da vistoria. Ids lidos do banco (ordem por id).
        vistorias = conn.execute("SELECT id, tenant_id FROM vistorias ORDER BY id").fetchall()
        rng = random.Random(f"{args.semente}:vistoria_visitas:{args.tamanho}:{args.empresas}")
        visitas = list(linhas_visitas(vistorias, rng))
        total = carregar(conn, "vistoria_visitas", "tenant_id, vistoria_id, data_visita", visitas)
        print(f"vistoria_visitas: {total} linhas")

    return 0


if __name__ == "__main__":
    sys.exit(main())
