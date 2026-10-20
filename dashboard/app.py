"""Ponto de entrada do dashboard (Community Cloud: `dashboard/app.py`).

    uv run streamlit run dashboard/app.py

Só reúne as páginas (`st.navigation`); cada página é uma função `renderizar()` em
`dashboard/paginas/`. O app lê só `dashboard/dados/` (o snapshot): nenhum BigQuery, nenhuma
credencial.
"""

import sys
from pathlib import Path

# o Community Cloud roda `streamlit run dashboard/app.py` da raiz do repositório: põe a raiz no
# caminho para `import dashboard...` funcionar igual ao ambiente local e aos testes
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from dashboard.paginas import decisao, previsao  # noqa: E402

st.set_page_config(page_title="Contratação de energia no mercado livre", layout="wide")

pagina = st.navigation(
    [
        st.Page(decisao.renderizar, title="Decisão de contrato", url_path="decisao", default=True),
        st.Page(previsao.renderizar, title="Previsão de carga", url_path="previsao"),
    ]
)
pagina.run()
