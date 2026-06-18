import streamlit as st
import pandas as pd
from pypdf import PdfReader
from rapidfuzz import fuzz
from io import BytesIO

st.set_page_config(
    page_title="Tabloide Checker",
    page_icon="🛒",
    layout="wide"
)

# =========================
# LOGIN
# =========================

def obter_usuarios():
    try:
        return dict(st.secrets["usuarios"])
    except Exception:
        return {}


def tela_login():
    st.title("🛒 Tabloide Checker")
    st.write("Acesso restrito")

    usuarios = obter_usuarios()

    if not usuarios:
        st.error("Nenhum usuário configurado. Configure os usuários no Secrets do Streamlit.")
        st.stop()

    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        if usuario in usuarios and senha == usuarios[usuario]:
            st.session_state.logado = True
            st.session_state.usuario = usuario
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")


if "logado" not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    tela_login()
    st.stop()


# =========================
# APP PRINCIPAL
# =========================

st.title("🛒 Tabloide Checker")
st.write("Conferência automática de tabloide: XLSX x PDF")

with st.sidebar:
    st.write(f"Usuário: **{st.session_state.usuario}**")
    if st.button("Sair"):
        st.session_state.logado = False
        st.session_state.usuario = ""
        st.rerun()


if "resultado" not in st.session_state:
    st.session_state.resultado = None

if "ignorados" not in st.session_state:
    st.session_state.ignorados = None

if "metricas" not in st.session_state:
    st.session_state.metricas = None


xlsx_file = st.file_uploader("Selecione a grade de ofertas XLSX", type=["xlsx"])
pdf_file = st.file_uploader("Selecione o PDF exportado do InDesign", type=["pdf"])


def formatar_preco(valor):
    if pd.isna(valor):
        return ""

    try:
        return f"{float(valor):.2f}".replace(".", ",")
    except:
        return str(valor).replace(".", ",")


def limpar_texto(texto):
    if pd.isna(texto):
        return ""

    return (
        str(texto)
        .replace("\n", " ")
        .replace("  ", " ")
        .strip()
        .upper()
    )


def ler_aba_agencia(arquivo):
    df = pd.read_excel(
        arquivo,
        sheet_name="Agência",
        header=2
    )

    df["Aba"] = "Agência"
    return df


def ler_aba_flv(arquivo):
    df_raw = pd.read_excel(
        arquivo,
        sheet_name="FLV",
        header=None
    )

    df = pd.DataFrame()

    df["Código"] = df_raw.iloc[:, 0]
    df["Descrição"] = df_raw.iloc[:, 1]
    df["Embalagem"] = df_raw.iloc[:, 2]
    df["Unid.Medida"] = df_raw.iloc[:, 3]
    df["PREÇO"] = df_raw.iloc[:, 4]
    df["COOPERMAIS"] = df_raw.iloc[:, 5]
    df["Aba"] = "FLV"

    return df


def carregar_xlsx(arquivo):
    dataframes = []

    try:
        df_agencia = ler_aba_agencia(arquivo)
        dataframes.append(df_agencia)
    except Exception as erro:
        st.warning(f"Aba Agência não foi lida: {erro}")

    try:
        df_flv = ler_aba_flv(arquivo)
        dataframes.append(df_flv)
    except Exception as erro:
        st.warning(f"Aba FLV não foi lida: {erro}")

    if len(dataframes) == 0:
        raise Exception("Nenhuma das abas esperadas foi encontrada.")

    df_original = pd.concat(dataframes, ignore_index=True)

    colunas = [
        "Aba",
        "Código",
        "Descrição",
        "Embalagem",
        "Unid.Medida",
        "PREÇO",
        "COOPERMAIS"
    ]

    df = df_original[colunas].copy()
    df = df.dropna(subset=["Descrição"])

    df = df[
        pd.to_numeric(df["PREÇO"], errors="coerce").notna()
    ].copy()

    total_antes = len(df)

    ignorados = df[
        df["Descrição"]
        .astype(str)
        .str.upper()
        .str.contains("INTERNO", na=False)
    ].copy()

    df = df[
        ~df["Descrição"]
        .astype(str)
        .str.upper()
        .str.contains("INTERNO", na=False)
    ].copy()

    total_ignorados = len(ignorados)

    df["descricao_limpa"] = df["Descrição"].apply(limpar_texto)
    df["unidade_limpa"] = df["Unid.Medida"].apply(limpar_texto)
    df["embalagem_limpa"] = df["Embalagem"].apply(limpar_texto)

    df["preco_regular_fmt"] = df["PREÇO"].apply(formatar_preco)
    df["coopermais_fmt"] = df["COOPERMAIS"].apply(formatar_preco)

    return df, total_antes, total_ignorados, ignorados


def carregar_pdf(arquivo):
    reader = PdfReader(arquivo)
    paginas = []

    for i, page in enumerate(reader.pages):
        texto = page.extract_text() or ""
        texto_limpo = limpar_texto(texto)

        paginas.append({
            "pagina": i + 1,
            "texto": texto_limpo
        })

    return paginas


def preco_na_pagina(preco, texto_pagina):
    if not preco:
        return False

    possibilidades = [
        preco,
        preco.replace(",", ""),
        preco.replace(",", " ")
    ]

    return any(p in texto_pagina for p in possibilidades)


def encontrar_pagina(descricao, paginas):
    melhor_pagina = "-"
    melhor_score = 0

    for pagina in paginas:
        score = fuzz.partial_ratio(descricao, pagina["texto"])

        if score > melhor_score:
            melhor_score = score
            melhor_pagina = pagina["pagina"]

    return melhor_pagina, melhor_score


def pegar_texto_pagina(numero_pagina, paginas):
    for pagina in paginas:
        if pagina["pagina"] == numero_pagina:
            return pagina["texto"]

    return ""


def classificar_descricao(score):
    if score >= 85:
        return "OK"

    if score >= 60:
        return "REVISAR"

    return "DIVERGÊNCIA"


def definir_motivo_principal(score, status_descricao, apontamentos):
    texto = " ".join(apontamentos).upper()

    if score < 60:
        return "Produto da grade provavelmente não está no PDF"

    if status_descricao == "DIVERGÊNCIA":
        return "Produto da grade não encontrado no PDF"

    if "PREÇO COOPERMAIS" in texto:
        return "Preço CooperMais não encontrado"

    if "PREÇO REGULAR" in texto:
        return "Preço regular não encontrado"

    if "UNIDADE" in texto:
        return "Unidade de medida não encontrada"

    if "EMBALAGEM" in texto:
        return "Embalagem não encontrada"

    if status_descricao == "REVISAR":
        return "Revisar descrição do produto"

    return ""


def conferir(df, paginas):
    resultados = []

    for _, row in df.iterrows():
        descricao = row["descricao_limpa"]
        unidade = row["unidade_limpa"]
        embalagem = row["embalagem_limpa"]
        preco_regular = row["preco_regular_fmt"]
        coopermais = row["coopermais_fmt"]

        produto_por_quilo_sem_coopermais = (
            embalagem == "QUILO"
            and not unidade
            and not coopermais
        )

        pagina, score = encontrar_pagina(descricao, paginas)
        texto_pagina = pegar_texto_pagina(pagina, paginas)

        status_descricao = classificar_descricao(score)

        if produto_por_quilo_sem_coopermais:
            unidade_ok = True
            coopermais_ok = True
        else:
            unidade_ok = True
            if unidade:
                unidade_ok = unidade in texto_pagina

            coopermais_ok = True
            if coopermais:
                coopermais_ok = preco_na_pagina(coopermais, texto_pagina)

        embalagem_ok = True
        if embalagem:
            embalagem_ok = embalagem in texto_pagina

        preco_regular_ok = preco_na_pagina(preco_regular, texto_pagina)

        apontamentos = []

        if status_descricao == "REVISAR":
            apontamentos.append("Revisar descrição")

        if status_descricao == "DIVERGÊNCIA":
            apontamentos.append("Produto da grade não encontrado no PDF")

        if not unidade_ok:
            apontamentos.append("Unidade de medida não encontrada na página do produto")

        if not embalagem_ok:
            apontamentos.append("Embalagem não encontrada na página do produto")

        if not preco_regular_ok:
            apontamentos.append("Preço regular não encontrado na página do produto")

        if not coopermais_ok:
            apontamentos.append("Preço CooperMais não encontrado na página do produto")

        if any("não encontrada" in item or "não encontrado" in item for item in apontamentos):
            status_final = "DIVERGÊNCIA"
        elif apontamentos:
            status_final = "REVISAR"
        else:
            status_final = "OK"

        motivo_principal = definir_motivo_principal(
            score,
            status_descricao,
            apontamentos
        )

        resultados.append({
            "Status": status_final,
            "Motivo principal": motivo_principal,
            "Página provável": pagina,
            "Aba": row["Aba"],
            "Código": row["Código"],
            "Descrição": row["Descrição"],
            "Embalagem": row["Embalagem"],
            "Unid.Medida": row["Unid.Medida"],
            "Preço Regular XLSX": preco_regular,
            "CooperMais XLSX": coopermais,
            "Regra especial": (
                "Quilo sem CooperMais"
                if produto_por_quilo_sem_coopermais
                else ""
            ),
            "Score descrição": round(score, 2),
            "Apontamentos": "; ".join(apontamentos)
        })

    return pd.DataFrame(resultados)


def destacar_linhas(row):
    if row["Status"] == "DIVERGÊNCIA":
        return ["background-color: #5c1f1f"] * len(row)

    if row["Status"] == "REVISAR":
        return ["background-color: #5c4b1f"] * len(row)

    return [""] * len(row)


def gerar_excel(resultado, ignorados):
    output = BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        resultado.to_excel(writer, index=False, sheet_name="Conferência")

        if ignorados is not None and not ignorados.empty:
            ignorados.to_excel(writer, index=False, sheet_name="Itens Ignorados")

        workbook = writer.book
        worksheet = writer.sheets["Conferência"]

        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#245E2B",
            "font_color": "white"
        })

        erro_format = workbook.add_format({
            "bg_color": "#FFC7CE",
            "font_color": "#9C0006"
        })

        revisar_format = workbook.add_format({
            "bg_color": "#FFEB9C",
            "font_color": "#9C6500"
        })

        for col_num, value in enumerate(resultado.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 24)

        for row_num, status in enumerate(resultado["Status"], start=1):
            if status == "DIVERGÊNCIA":
                worksheet.set_row(row_num, None, erro_format)

            if status == "REVISAR":
                worksheet.set_row(row_num, None, revisar_format)

    output.seek(0)
    return output


if st.button("Conferir tabloide"):
    if not xlsx_file or not pdf_file:
        st.warning("Envie o XLSX e o PDF para iniciar a conferência.")
    else:
        with st.spinner("Lendo XLSX..."):
            df, total_antes, total_ignorados, ignorados = carregar_xlsx(xlsx_file)

        with st.spinner("Lendo PDF..."):
            paginas = carregar_pdf(pdf_file)

        with st.spinner("Comparando dados..."):
            resultado = conferir(df, paginas)

        total = len(resultado)
        ok = len(resultado[resultado["Status"] == "OK"])
        revisar = len(resultado[resultado["Status"] == "REVISAR"])
        divergencias = len(resultado[resultado["Status"] == "DIVERGÊNCIA"])

        st.session_state.resultado = resultado
        st.session_state.ignorados = ignorados
        st.session_state.metricas = {
            "total_antes": total_antes,
            "total_ignorados": total_ignorados,
            "total": total,
            "ok": ok,
            "revisar": revisar,
            "divergencias": divergencias
        }


if st.session_state.resultado is not None:
    resultado = st.session_state.resultado
    ignorados = st.session_state.ignorados
    metricas = st.session_state.metricas

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("Itens válidos na grade", metricas["total_antes"])
    col2.metric("Itens internos ignorados", metricas["total_ignorados"])
    col3.metric("Produtos conferidos", metricas["total"])
    col4.metric("Produtos OK", metricas["ok"])
    col5.metric("Revisar", metricas["revisar"])
    col6.metric("Divergências", metricas["divergencias"])

    st.subheader("Resultado da conferência")

    modo_visualizacao = st.radio(
        "Visualização",
        ["Somente divergências", "Revisar + divergências", "Todos os produtos"],
        horizontal=True
    )

    if modo_visualizacao == "Somente divergências":
        tabela = resultado[resultado["Status"] == "DIVERGÊNCIA"]
    elif modo_visualizacao == "Revisar + divergências":
        tabela = resultado[resultado["Status"].isin(["REVISAR", "DIVERGÊNCIA"])]
    else:
        tabela = resultado

    st.dataframe(
        tabela.style.apply(destacar_linhas, axis=1),
        use_container_width=True
    )

    arquivo_excel = gerar_excel(resultado, ignorados)

    st.download_button(
        label="Baixar relatório Excel",
        data=arquivo_excel,
        file_name="relatorio_conferencia_tabloide.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )