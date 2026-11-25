"""Utilitarios compartilhados pelos scripts do experimento."""

import datetime as dt
import os
import re
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parent.parent
SQL_DIR = Path(__file__).resolve().parent / "sql"

# Data fixa de referencia ("hoje" do experimento): o conteudo gerado e as consultas
# dependem so da semente e desta data, nao do dia da execucao.
REFERENCIA = dt.date(2026, 11, 1)

# Tabelas principais (todas com o mesmo numero de linhas por empresa).
# vistoria_visitas e derivada de vistorias.
TABELAS = ("ocorrencias", "fichas", "vistorias")

# Estudo -> condicao -> arquivos de indices (em scripts/sql/) aplicados nessa condicao.
# Condicao sem arquivos = nenhum indice do estudo.
#
# Estudo "v2" (listagens de ocorrencias e fichas):
#   sem_indice            nenhum indice alem da chave primaria
#   v2                    somente os indices da migracao V2 (unidade_id, data DESC)
#   producao              V2 + indice de tenant (V76): o estado de producao hoje
#   tenant_unidade_data   candidato: (tenant_id, unidade_id, data DESC)
#   tenant_data           candidato: (tenant_id, data DESC)
# Estudo "vistorias" (consulta de alertas):
#   sem_indice / com_indice  (indice em vistoria_visitas)
ESTUDOS = {
    "v2": {
        "sem_indice": [],
        "v2": ["indices_v2.sql"],
        "producao": ["indices_v2.sql", "indices_tenant.sql"],
        "tenant_unidade_data": ["indices_tenant_unidade_data.sql"],
        "tenant_data": ["indices_tenant_data.sql"],
    },
    "vistorias": {
        # sem_indice = producao hoje (so o indice simples de tenant em vistoria_visitas)
        "sem_indice": ["indices_vistoria_visitas_tenant.sql"],
        "com_indice": ["indices_vistoria_visitas_tenant.sql", "indice_vistoria_visitas.sql"],
    },
}
MODOS_PLANO = ("custom", "generic")


def conectar(autocommit: bool = True) -> psycopg.Connection:
    """Conecta no PostgreSQL do laboratorio. Padrao: o conteiner do docker-compose."""
    return psycopg.connect(
        host=os.getenv("LAB5_PGHOST", "localhost"),
        port=int(os.getenv("LAB5_PGPORT", "5433")),
        dbname=os.getenv("LAB5_PGDATABASE", "lab5"),
        user=os.getenv("LAB5_PGUSER", "lab5"),
        password=os.getenv("LAB5_PGPASSWORD", "lab5"),
        autocommit=autocommit,
    )


def _ler_indices(arquivo: str) -> dict[str, tuple[str, str]]:
    padrao = re.compile(r"^CREATE INDEX IF NOT EXISTS (\w+) ON (\w+) ", re.IGNORECASE)
    resultado = {}
    for linha in (SQL_DIR / arquivo).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        achou = padrao.match(linha)
        if achou:
            resultado[achou.group(1)] = (achou.group(2), linha)
    return resultado


def indices_da_condicao(estudo: str, condicao: str) -> dict[str, tuple[str, str]]:
    """{nome_do_indice: (tabela, instrucao_sql)} que existem nessa condicao."""
    resultado = {}
    for arquivo in ESTUDOS[estudo][condicao]:
        resultado.update(_ler_indices(arquivo))
    return resultado


def todos_os_indices(estudo: str) -> dict[str, tuple[str, str]]:
    """Uniao dos indices de todas as condicoes do estudo (o que precisa ser removido antes)."""
    resultado = {}
    for condicao in ESTUDOS[estudo]:
        resultado.update(indices_da_condicao(estudo, condicao))
    return resultado
