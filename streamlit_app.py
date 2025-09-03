import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP

# ===================== Config =====================
st.set_page_config(page_title="Cálculo de Rescisão de Acessórios", layout="wide")

# Paleta (azul primário e amarelo secundário)
PRIMARY = "#27509b"
SECONDARY = "#fce500"

# CSS global
st.markdown(f"""
<style>
:root {{ --primary: {PRIMARY}; --secondary: {SECONDARY}; }}
h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{ color: var(--primary) !important; }}
div[data-testid="metric-container"] {{
  background: rgba(252,229,0,0.15);
  border-left: 6px solid var(--primary);
  border-radius: 12px;
  padding: .5rem .75rem;
}}
div[data-testid="stMetricValue"], div[data-testid="stMetricLabel"] {{ color: var(--primary) !important; }}
.stButton>button {{ border: 1px solid var(--primary); border-radius: 10px; }}
[data-testid="stDataFrame"] div[role="columnheader"] {{ background: var(--primary) !important; color: #fff !important; }}
</style>
""", unsafe_allow_html=True)

st.title("Calculo de Rescisão de acessórios.")
st.caption("Ferramenta de cálculo para rescisão de acessórios (com/sem devolução).")

# ===================== Utils =====================
def normalize_text(s: str) -> str:
    if s is None: return ""
    s = str(s).strip().lower()
    rep = {"ã":"a","â":"a","á":"a","à":"a","é":"e","ê":"e","í":"i","ó":"o","ô":"o","ú":"u","ç":"c"}
    for k,v in rep.items(): s = s.replace(k,v)
    while "  " in s: s = s.replace("  "," ")
    return s

def parse_date_any(x):
    if pd.isna(x): return pd.NaT
    if isinstance(x, (pd.Timestamp, datetime)): return pd.to_datetime(x)
    x = str(x).strip()
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%d-%m-%Y"):
        try: return pd.to_datetime(x, format=fmt)
        except: pass
    return pd.to_datetime(x, errors="coerce")

def read_any(uploaded):
    if uploaded is None: return None
    name = uploaded.name.lower()
    return pd.read_csv(uploaded) if name.endswith(".csv") else pd.read_excel(uploaded)

# ---------- Formatação BRL (R$ 1.234,56) ----------
def brl(x) -> str:
    if pd.isna(x): x = 0
    q = Decimal(str(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:.2f}"                 # '1234.56'
    inteiro, frac = s.split(".")
    inteiro_rev = inteiro[::-1]
    partes = [inteiro_rev[i:i+3] for i in range(0, len(inteiro_rev), 3)]
    inteiro_pt = ".".join(p[::-1] for p in partes[::-1])
    return f"R$ {inteiro_pt},{frac}"

# ===================== Sidebar - SOMENTE upload da base =====================
st.sidebar.header("Upload da base")
base_file = st.sidebar.file_uploader("Base de dados (CSV/Excel)", type=["csv","xlsx"])
base_df = read_any(base_file)

if base_df is None:
    st.info("Faça o upload da **base principal**. Use os cabeçalhos do arquivo *base_estrutura_oficial.csv*.")
    st.stop()

# ===================== Header mapping (PT -> internos) =====================
HEADER_MAP = {
    "servico/acesorio":"servico_acessorio", "servico/acessorio":"servico_acessorio",
    "cliente":"cliente", "placa":"placa", "classe":"classe", "termo (contrato)":"termo",
    "inicio_vigencia":"inicio_vigencia",
    "fim_vigencia servico/acesorio":"fim_vigencia", "fim_vigencia servico/acessorio":"fim_vigencia", "fim_vigencia":"fim_vigencia",
    "numero de fatura servico/acesorio":"numero_fatura_servico", "numero de fatura servico/acessorio":"numero_fatura_servico",
    "valor mensalidade do servico/acesorio":"valor_mensalidade", "valor mensalidade do servico/acessorio":"valor_mensalidade", "valor mensalidade":"valor_mensalidade",
    "meses restantes (vigencia) do servico/acesorio":"meses_restantes", "meses restantes (vigencia) do servico/acessorio":"meses_restantes",
    "taxa de multa servico/acesorio":"taxa_multa_25pct", "taxa de multa servico/acessorio":"taxa_multa_25pct",
    "valor de cancelamento do servico/acesorio":"valor_taxa_cancelamento", "valor de cancelamento do servico/acessorio":"valor_taxa_cancelamento",
    "status do servico/acesorio no cancelamento":"status_do_contrato", "status do servico/acessorio no cancelamento":"status_do_contrato",
    "valor de multa de nao devolucao do servico/acesorio":"valor_multa_nao_devolucao",
    "valor de multa de nao devolucao do servico/acessorio":"valor_multa_nao_devolucao",
    "valor de multa de não devolução do servico/acesorio":"valor_multa_nao_devolucao",
    "valor de multa de não devolução do servico/acessorio":"valor_multa_nao_devolucao",
    "instalado":"instalado",
}
rename = {c: HEADER_MAP[normalize_text(c)] for c in base_df.columns if normalize_text(c) in HEADER_MAP}
base_df = base_df.rename(columns=rename)
base_df.columns = [normalize_text(c) for c in base_df.columns]

# ===================== Validação & tipos =====================
need = {"cliente","classe","termo","servico_acessorio","valor_mensalidade"}
miss = need - set(base_df.columns)
if miss:
    st.error(f"Colunas obrigatórias ausentes: {sorted(miss)}")
    st.stop()

# datas
if "inicio_vigencia" in base_df.columns: base_df["inicio_vigencia"] = base_df["inicio_vigencia"].apply(parse_date_any)
if "fim_vigencia" in base_df.columns: base_df["fim_vigencia"] = base_df["fim_vigencia"].apply(parse_date_any)

# numéricos
for c in ["valor_mensalidade","valor_taxa_cancelamento","valor_multa_nao_devolucao","taxa_multa_25pct"]:
    if c in base_df.columns: base_df[c] = pd.to_numeric(base_df[c], errors="coerce")

# Meses restantes
hoje = pd.Timestamp(date.today())
if "meses_restantes" not in base_df.columns or base_df["meses_restantes"].isna().any():
    if "fim_vigencia" in base_df.columns:
        dias = (base_df["fim_vigencia"] - hoje).dt.days.fillna(0).clip(lower=0)
        base_df["meses_restantes"] = np.ceil(dias/30.0).astype(int)
    else:
        base_df["meses_restantes"] = 0

# Multa 25%
if "taxa_multa_25pct" not in base_df.columns or base_df["taxa_multa_25pct"].isna().any():
    base_df["taxa_multa_25pct"] = base_df["valor_mensalidade"].fillna(0)*base_df["meses_restantes"].fillna(0)*0.25

# Status
def normalize_status(raw):
    r = normalize_text(raw)
    if "com vigencia" in r and "instalado" in r: return "Com vigência e instalado"
    if "com vigencia" in r and "nao instalado" in r: return "Com vigência e não instalado"
    if "sem vigencia" in r and "instalado" in r: return "Sem vigência e instalado"
    return "Sem vigência e não instalado"

if "status_do_contrato" in base_df.columns:
    base_df["status_do_contrato"] = base_df["status_do_contrato"].apply(normalize_status)
elif "status do servico/acesorio no cancelamento" in base_df.columns:
    base_df["status_do_contrato"] = base_df["status do servico/acesorio no cancelamento"].apply(normalize_status)
else:
    if "instalado" in base_df.columns:
        def by_flags(r):
            if r["meses_restantes"]>0 and bool(r.get("instalado", True)):  return "Com vigência e instalado"
            if r["meses_restantes"]>0 and not bool(r.get("instalado", False)): return "Com vigência e não instalado"
            if r["meses_restantes"]==0 and bool(r.get("instalado", True)): return "Sem vigência e instalado"
            return "Sem vigência e não instalado"
        base_df["status_do_contrato"] = base_df.apply(by_flags, axis=1)
    else:
        base_df["status_do_contrato"] = np.where(base_df["meses_restantes"]>0, "Com vigência e instalado", "Sem vigência e não instalado")

# Preenche 0 se não vierem na base
for c in ["valor_taxa_cancelamento","valor_multa_nao_devolucao"]:
    if c not in base_df.columns: base_df[c] = 0.0
    base_df[c] = pd.to_numeric(base_df[c], errors="coerce").fillna(0.0)

# ===================== Cálculos finais =====================
def valor_com_devolucao(r):
    stt, m25, taxa = r["status_do_contrato"], r["taxa_multa_25pct"], r["valor_taxa_cancelamento"]
    if stt.startswith("Com vigência"): return float(m25) + float(taxa)
    if stt == "Sem vigência e instalado": return float(taxa)
    return 0.0

def valor_sem_devolucao(r):
    stt, m25, multa = r["status_do_contrato"], r["taxa_multa_25pct"], r["valor_multa_nao_devolucao"]
    if stt.startswith("Com vigência"): return float(m25) + float(multa)
    if stt == "Sem vigência e instalado": return float(multa)
    return 0.0

base_df["valor_cobrar_com_devolucao"] = base_df.apply(valor_com_devolucao, axis=1)
base_df["valor_cobrar_sem_devolucao"]  = base_df.apply(valor_sem_devolucao, axis=1)

# ===================== Filtros =====================
st.subheader("Filtros")

c1, c2, c3 = st.columns(3)
with c1:
    sel_clientes = st.multiselect("Cliente", sorted(base_df["cliente"].astype(str).unique().tolist()))
with c2:
    sel_classes  = st.multiselect("Classe", sorted(base_df["classe"].astype(str).unique().tolist()))
with c3:
    sel_termos   = st.multiselect("Termo", sorted(base_df["termo"].astype(str).unique().tolist()))

c4, c5 = st.columns(2)
with c4:
    sel_servicos = st.multiselect("Serviço/Acessório", sorted(base_df["servico_acessorio"].astype(str).unique().tolist()))
with c5:
    status_opts = [
        "Com vigência e instalado","Com vigência e não instalado",
        "Sem vigência e instalado","Sem vigência e não instalado",
    ]
    sel_status = st.multiselect("Status do contrato", status_opts)

c6, c7 = st.columns(2)
min_cdev, max_cdev = float(base_df["valor_cobrar_com_devolucao"].min()), float(base_df["valor_cobrar_com_devolucao"].max())
min_sdev, max_sdev = float(base_df["valor_cobrar_sem_devolucao"].min()), float(base_df["valor_cobrar_sem_devolucao"].max())
with c6:
    faixa_cdev = st.slider("Faixa de valores (Com Devolução)",
        min_value=float(np.floor(min_cdev)), max_value=float(np.ceil(max_cdev)),
        value=(float(np.floor(min_cdev)), float(np.ceil(max_cdev))), step=1.0)
with c7:
    faixa_sdev = st.slider("Faixa de valores (Sem Devolução)",
        min_value=float(np.floor(min_sdev)), max_value=float(np.ceil(max_sdev)),
        value=(float(np.floor(min_sdev)), float(np.ceil(max_sdev))), step=1.0)

# Aplica filtros
f = base_df.copy()
if sel_clientes: f = f[f["cliente"].astype(str).isin(sel_clientes)]
if sel_classes:  f = f[f["classe"].astype(str).isin(sel_classes)]
if sel_termos:   f = f[f["termo"].astype(str).isin(sel_termos)]
if sel_servicos: f = f[f["servico_acessorio"].astype(str).isin(sel_servicos)]
if sel_status:   f = f[f["status_do_contrato"].isin(sel_status)]
f = f[(f["valor_cobrar_com_devolucao"].between(faixa_cdev[0], faixa_cdev[1])) &
      (f["valor_cobrar_sem_devolucao"].between(faixa_sdev[0], faixa_sdev[1]))]

st.markdown("---")

# ===================== Métricas (formato BRL) =====================
m1, m2, m3, m4 = st.columns(4)
m1.metric("Valor Total dos Contratos com Devolução", brl(f['valor_cobrar_com_devolucao'].sum()))
m2.metric("Valor Total dos Contratos sem Devolução", brl(f['valor_cobrar_sem_devolucao'].sum()))
m3.metric("Quantidade de Contratos", f"{f['termo'].nunique():,}")
m4.metric("Quantidade de Acessórios", f"{len(f):,}")

# ===================== Tabela detalhada (formato BRL) =====================
cols_show = ["classe","termo","servico_acessorio","status_do_contrato",
             "valor_cobrar_com_devolucao","valor_cobrar_sem_devolucao"]
presentes = [c for c in cols_show if c in f.columns]
tbl = f[presentes].sort_values(["classe","termo","servico_acessorio"]).reset_index(drop=True)

styled_tbl = tbl.style.format({
    "valor_cobrar_com_devolucao": brl,
    "valor_cobrar_sem_devolucao": brl,
})
st.dataframe(styled_tbl, use_container_width=True)

# ===================== Resumo (agrupado) =====================
st.subheader("Resumo consolidado (opcional)")
agr_por = st.multiselect("Agrupar por", ["cliente","classe","termo"], default=["cliente"])
if agr_por:
    agg = f.groupby(agr_por, dropna=False, as_index=False).agg(
        contratos=("termo","nunique"),
        acessorios=("servico_acessorio","count"),
        total_com_devolucao=("valor_cobrar_com_devolucao","sum"),
        total_sem_devolucao=("valor_cobrar_sem_devolucao","sum"),
    )
    st.dataframe(
        agg.style.format({
            "total_com_devolucao": brl,
            "total_sem_devolucao": brl,
        }),
        use_container_width=True
    )
else:
    agg = pd.DataFrame()

# ===================== Exportar (mantém números crus) =====================
st.subheader("Exportar resultados")
csv_bytes = f.to_csv(index=False).encode("utf-8-sig")
st.download_button("Baixar CSV (detalhado filtrado)", csv_bytes, file_name="resultado_rescisao.csv", mime="text/csv")

try:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        tbl.to_excel(writer, index=False, sheet_name="detalhado")
        if not agg.empty: agg.to_excel(writer, index=False, sheet_name="resumo")
    st.download_button(
        "Baixar Excel (detalhado + resumo)",
        data=output.getvalue(),
        file_name="resultado_rescisao.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
except Exception:
    st.info("Para exportar em Excel localmente, garanta que a dependência 'XlsxWriter' está instalada.")
