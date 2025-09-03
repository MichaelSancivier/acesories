import streamlit as st
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
from datetime import date

st.set_page_config(page_title="Cálculo de Rescisão de Acessórios", layout="wide")

st.title("Calculo de Rescisão de acessórios.")
st.caption("Ferramenta de cálculo para rescisão de acessórios.")

# === Parâmetros ===
CHAVE_TABELAS = st.sidebar.selectbox(
    "Chave para cruzar as tabelas auxiliares",
    options=["servico_acessorio", "classe"],
    index=0,
    help="Escolha a coluna da base que casa com a coluna 'chave' das tabelas de cancelamento e de não devolução."
)

hoje = date.today()

# === Uploads ===
st.sidebar.markdown("### Upload dos arquivos (CSV/Excel)")
base_file = st.sidebar.file_uploader("Base de dados (CSV ou Excel)", type=["csv", "xlsx"])
cancel_file = st.sidebar.file_uploader("Tabela de cancelamento (CSV ou Excel)", type=["csv", "xlsx"])
multa_file = st.sidebar.file_uploader("Tabela de multa por não devolução (CSV ou Excel)", type=["csv", "xlsx"])

def read_any(f):
    if f is None: return None
    name = f.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(f)
    return pd.read_excel(f)

# === Carregar dados ===
base_df = read_any(base_file)
cancel_df = read_any(cancel_file)
multa_df = read_any(multa_file)

if base_df is None:
    st.info("Faça o upload da **base de dados** para começar.")
    st.stop()

# Normaliza nomes de colunas esperadas
expected_cols = {
    "cliente","placa","classe","termo","servico_acessorio",
    "inicio_vigencia","fim_vigencia","numero_fatura_servico",
    "valor_mensalidade","instalado",
    "meses_restantes","taxa_multa_25pct",
    "valor_taxa_cancelamento","valor_multa_nao_devolucao"
}
base_df.columns = [c.strip().lower() for c in base_df.columns]

missing_min = {"cliente","classe","termo","servico_acessorio","fim_vigencia","valor_mensalidade","instalado"} - set(base_df.columns)
if missing_min:
    st.error(f"Colunas obrigatórias ausentes na base: {sorted(missing_min)}")
    st.stop()

# === Converte tipos básicos ===
for col in ["inicio_vigencia","fim_vigencia"]:
    if col in base_df.columns:
        base_df[col] = pd.to_datetime(base_df[col], errors="coerce").dt.date

base_df["valor_mensalidade"] = pd.to_numeric(base_df["valor_mensalidade"], errors="coerce").fillna(0.0)
if base_df["instalado"].dtype != bool:
    # aceita True/False, 1/0, "sim"/"não"
    base_df["instalado"] = base_df["instalado"].astype(str).str.strip().str.lower().map(
        {"true":True,"false":False,"1":True,"0":False,"sim":True,"nao":False,"não":False}
    ).fillna(False)

# === Meses restantes ===
def months_remaining(end_date, today=hoje):
    if pd.isna(end_date): return 0
    delta_days = (end_date - today).days
    if delta_days <= 0: return 0
    return int(np.ceil(delta_days / 30.0))

if "meses_restantes" not in base_df.columns or base_df["meses_restantes"].isna().any():
    base_df["meses_restantes"] = base_df["fim_vigencia"].apply(months_remaining)

# === Multa 25% ===
if "taxa_multa_25pct" not in base_df.columns or base_df["taxa_multa_25pct"].isna().any():
    base_df["taxa_multa_25pct"] = base_df["valor_mensalidade"] * base_df["meses_restantes"] * 0.25

# === Merge com tabelas auxiliares ===
if cancel_df is not None:
    cancel_df.columns = [c.strip().lower() for c in cancel_df.columns]
    if "chave" in cancel_df.columns and "valor_taxa_cancelamento" in cancel_df.columns:
        base_df = base_df.merge(
            cancel_df[["chave","valor_taxa_cancelamento"]].rename(columns={"chave":CHAVE_TABELAS}),
            on=CHAVE_TABELAS, how="left"
        )

if multa_df is not None:
    multa_df.columns = [c.strip().lower() for c in multa_df.columns]
    if "chave" in multa_df.columns and "valor_multa_nao_devolucao" in multa_df.columns:
        base_df = base_df.merge(
            multa_df[["chave","valor_multa_nao_devolucao"]].rename(columns={"chave":CHAVE_TABELAS}),
            on=CHAVE_TABELAS, how="left"
        )

# Garante numeric
for col in ["valor_taxa_cancelamento","valor_multa_nao_devolucao"]:
    if col in base_df.columns:
        base_df[col] = pd.to_numeric(base_df[col], errors="coerce")

base_df[["valor_taxa_cancelamento","valor_multa_nao_devolucao"]] = base_df[["valor_taxa_cancelamento","valor_multa_nao_devolucao"]].fillna(0.0)

# === Status do contrato ===
def status_row(vig, inst):
    if vig > 0 and inst:  return "Com vigência e instalado"
    if vig > 0 and not inst: return "Com vigência e não instalado"
    if vig == 0 and inst: return "Sem vigência e instalado"
    return "Sem vigência e não instalado"

base_df["status_do_contrato"] = base_df.apply(
    lambda r: status_row(r["meses_restantes"], bool(r["instalado"])), axis=1
)

# === Valores a cobrar ===
def valor_com_devolucao(r):
    stt = r["status_do_contrato"]
    multa25 = r["taxa_multa_25pct"]
    taxa_cancel = r["valor_taxa_cancelamento"]
    if stt in ["Com vigência e instalado", "Com vigência e não instalado"]:
        return multa25 + taxa_cancel
    if stt == "Sem vigência e instalado":
        return taxa_cancel
    return 0.0

def valor_sem_devolucao(r):
    stt = r["status_do_contrato"]
    multa25 = r["taxa_multa_25pct"]
    multa_nd = r["valor_multa_nao_devolucao"]
    if stt in ["Com vigência e instalado", "Com vigência e não instalado"]:
        return multa25 + multa_nd
    if stt == "Sem vigência e instalado":
        return multa_nd
    return 0.0

base_df["valor_cobrar_com_devolucao"] = base_df.apply(valor_com_devolucao, axis=1)
base_df["valor_cobrar_sem_devolucao"]  = base_df.apply(valor_sem_devolucao, axis=1)

# === Filtros ===
col_f1, col_f2 = st.columns([1,1])
with col_f1:
    cliente_sel = st.selectbox("Cliente", options=["(Tudo)"] + sorted(base_df["cliente"].astype(str).unique().tolist()))
with col_f2:
    termos_unicos = base_df["termo"].astype(str).unique().tolist()
    termo_sel = st.selectbox("Termo", options=["(Tudo)"] + sorted(termos_unicos))

f = base_df.copy()
if cliente_sel != "(Tudo)":
    f = f[f["cliente"].astype(str) == cliente_sel]
if termo_sel != "(Tudo)":
    f = f[f["termo"].astype(str) == termo_sel]

# === Métricas à direita ===
m1, m2, m3, m4 = st.columns([1,1,1,1])
m1.metric("Valor Total dos Contratos com Devolução", f"R$ {f['valor_cobrar_com_devolucao'].sum():,.2f}")
m2.metric("Valor Total dos Contratos sem Devolução", f"R$ {f['valor_cobrar_sem_devolucao'].sum():,.2f}")
m3.metric("Quantidade de Contratos", f"{f['termo'].nunique():,}")
m4.metric("Quantidade de Acessórios", f"{len(f):,}")

# === Tabela principal ===
cols_show = [
    "classe","termo","servico_acessorio","status_do_contrato",
    "valor_cobrar_com_devolucao","valor_cobrar_sem_devolucao"
]
available = [c for c in cols_show if c in f.columns]
st.dataframe(
    f[available].sort_values(["classe","termo","servico_acessorio"]).reset_index(drop=True),
    use_container_width=True
)
