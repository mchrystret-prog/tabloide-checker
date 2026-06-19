import streamlit as st
import pandas as pd
from pypdf import PdfReader
from rapidfuzz import fuzz
from io import BytesIO
from streamlit_cookies_manager import EncryptedCookieManager
import unicodedata
import fitz
from PIL import Image

st.set_page_config(
    page_title="Tabloide Checker",
    page_icon="🛒",
    layout="wide"
)

VERSAO = "1.2.0"


# =========================
# COOKIES
# =========================

def obter_senha_cookie():
    try:
        return st.secrets["cookie"]["senha"]
    except Exception:
        return None


senha_cookie = obter_senha_cookie()

if not senha_cookie:
    st.error("Configure a chave de cookie nos Secrets do Streamlit.")
    st.stop()

cookies = EncryptedCookieManager(
    prefix="tabloide_checker_",
    password=senha_cookie
)

if not cookies.ready():
    st.stop()


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

            cookies["usuario"] = usuario
            cookies.save()

            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")


usuarios = obter_usuarios()

if "logado" not in st.session_state:
    st.session_state.logado = False

if "usuario" not in st.session_state:
    st.session_state.usuario = ""

usuario_cookie = cookies.get("usuario")

if usuario_cookie in usuarios and not st.session_state.logado:
    st.session_state.logado = True
    st.session_state.usuario = usuario_cookie

if not st.session_state.logado:
    tela_login()
    st.stop()


# =========================
# APP PRINCIPAL
# =========================

st.title("🛒 Tabloide Checker")

st.markdown(
    f"""
### 👋 Bem-vindo, {st.session_state.usuario.capitalize()}!

Utilize o sistema para validar automaticamente preços, descrições e ofertas do tabloide antes da publicação.
"""
)

with st.sidebar:
    st.success(f"✅ Logado como: {st.session_state.usuario}")

    st.divider()

    st.caption("Tabloide Checker")
    st.caption(f"Versão {VERSAO}")

    if st.button("Sair"):
        st.session_state.logado = False
        st.session_state.usuario = ""

        try:
            del cookies["usuario"]
            cookies.save()
        except Exception:
            pass

        st.rerun()


if "resultado" not in st.session_state:
    st.session_state.resultado = None

if "ignorados" not in st.session_state:
    st.session_state.ignorados = None

if "metricas" not in st.session_state:
    st.session_state.metricas = None

if "previews_pdf" not in st.session_state:
    st.session_state.previews_pdf = None


xlsx_file = st.file_uploader("Selecione a grade de ofertas XLSX", type=["xlsx"])
pdf_file = st.file_uploader("Selecione o PDF exportado do InDesign", type=["pdf"])


def remover_acentos(texto):
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def texto_busca(texto):
    if pd.isna(texto):
        return ""

    return remover_acentos(str(texto)).upper().strip()


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


def aplicar_tipo_blocos(df):
    tipo_atual = "NORMAL"
    tipos = []

    for _, row in df.iterrows():
        texto_linha = texto_busca(" ".join([str(v) for v in row.values if not pd.isna(v)]))

        if "EXCLUID" in texto_linha:
            tipo_atual = "EXCLUÍDO"
            tipos.append("SEPARADOR")
            continue

        if "INCLUID" in texto_linha:
            tipo_atual = "INCLUÍDO"
            tipos.append("SEPARADOR")
            continue

        if "BOX" in texto_linha and "EXCLUID" not in texto_linha and "INCLUID" not in texto_linha:
            tipo_atual = "NORMAL"
            tipos.append("SEPARADOR")
            continue

        tipos.append(tipo_atual)

    df["Tipo"] = tipos
    return df


def ler_aba_agencia(arquivo):
    df = pd.read_excel(
        arquivo,
        sheet_name="Agência",
        header=2
    )

    df["Aba"] = "Agência"
    df = aplicar_tipo_blocos(df)

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

    df = aplicar_tipo_blocos(df)

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
        "Tipo",
        "Código",
        "Descrição",
        "Embalagem",
        "Unid.Medida",
        "PREÇO",
        "COOPERMAIS"
    ]

    df = df_original[colunas].copy()
    df = df.dropna(subset=["Descrição"])

    df = df[df["Tipo"] != "SEPARADOR"].copy()

    df = df[
        pd.to_numeric(df["PREÇO"], errors="coerce").notna()
    ].copy()

    total_antes = len(df)

    ignorados = df[
        (df["Tipo"] != "EXCLUÍDO")
        & (
            df["Descrição"]
            .astype(str)
            .str.upper()
            .str.contains("INTERNO", na=False)
        )
    ].copy()

    df = df[
        ~(
            (df["Tipo"] != "EXCLUÍDO")
            & (
                df["Descrição"]
                .astype(str)
                .str.upper()
                .str.contains("INTERNO", na=False)
            )
        )
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


def gerar_preview_paginas(pdf_file):
    pdf_file.seek(0)
    pdf_bytes = pdf_file.read()
    pdf_file.seek(0)

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    previews = {}

    for pagina_num in range(len(doc)):
        page = doc.load_page(pagina_num)

        pix = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False
        )

        img = Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

        previews[pagina_num + 1] = img

    doc.close()

    return previews


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
        tipo_item = row["Tipo"]

        if tipo_item == "EXCLUÍDO":
            resultados.append({
                "Status": "EXCLUÍDO",
                "Motivo principal": "Produto excluído",
                "Página provável": "-",
                "Aba": row["Aba"],
                "Tipo": tipo_item,
                "Código": row["Código"],
                "Descrição": row["Descrição"],
                "Embalagem": row["Embalagem"],
                "Unid.Medida": row["Unid.Medida"],
                "Preço Regular XLSX": row["preco_regular_fmt"],
                "CooperMais XLSX": row["coopermais_fmt"],
                "Regra especial": "Produto listado no bloco EXCLUÍDOS",
                "Score descrição": "-",
                "Apontamentos": "Produto excluído"
            })
            continue

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

        if tipo_item == "INCLUÍDO":
            apontamentos.append("Produto incluído")

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
        elif status_descricao == "REVISAR":
            status_final = "REVISAR"
        else:
            status_final = "OK"

        motivo_principal = definir_motivo_principal(
            score,
            status_descricao,
            apontamentos
        )

        if tipo_item == "INCLUÍDO" and status_final == "OK":
            motivo_principal = "Produto incluído conferido"

        resultados.append({
            "Status": status_final,
            "Motivo principal": motivo_principal,
            "Página provável": pagina,
            "Aba": row["Aba"],
            "Tipo": tipo_item,
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

    if row["Status"] == "EXCLUÍDO":
        return ["background-color: #3a3a3a"] * len(row)

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

        excluido_format = workbook.add_format({
            "bg_color": "#D9D9D9",
            "font_color": "#595959"
        })

        for col_num, value in enumerate(resultado.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 24)

        for row_num, status in enumerate(resultado["Status"], start=1):
            if status == "DIVERGÊNCIA":
                worksheet.set_row(row_num, None, erro_format)

            if status == "REVISAR":
                worksheet.set_row(row_num, None, revisar_format)

            if status == "EXCLUÍDO":
                worksheet.set_row(row_num, None, excluido_format)

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

        with st.spinner("Gerando pré-visualizações..."):
            previews_pdf = gerar_preview_paginas(pdf_file)

        with st.spinner("Comparando dados..."):
            resultado = conferir(df, paginas)

        total = len(resultado)
        ok = len(resultado[resultado["Status"] == "OK"])
        revisar = len(resultado[resultado["Status"] == "REVISAR"])
        divergencias = len(resultado[resultado["Status"] == "DIVERGÊNCIA"])
        excluidos = len(resultado[resultado["Status"] == "EXCLUÍDO"])
        incluidos = len(resultado[resultado["Tipo"] == "INCLUÍDO"])

        st.session_state.resultado = resultado
        st.session_state.previews_pdf = previews_pdf
        st.session_state.ignorados = ignorados
        st.session_state.metricas = {
            "total_antes": total_antes,
            "total_ignorados": total_ignorados,
            "total": total,
            "ok": ok,
            "revisar": revisar,
            "divergencias": divergencias,
            "excluidos": excluidos,
            "incluidos": incluidos
        }


if st.session_state.resultado is not None:
    resultado = st.session_state.resultado
    ignorados = st.session_state.ignorados
    metricas = st.session_state.metricas

    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)

    col1.metric("Itens na grade", metricas["total_antes"])
    col2.metric("Internos ignorados", metricas["total_ignorados"])
    col3.metric("Conferidos", metricas["total"])
    col4.metric("OK", metricas["ok"])
    col5.metric("Revisar", metricas["revisar"])
    col6.metric("Divergências", metricas["divergencias"])
    col7.metric("Excluídos", metricas["excluidos"])
    col8.metric("Incluídos", metricas["incluidos"])

    st.subheader("Resultado da conferência")

    modo_visualizacao = st.radio(
        "Visualização",
        [
            "Somente divergências",
            "Revisar + divergências",
            "Excluídos",
            "Incluídos",
            "Todos os produtos"
        ],
        horizontal=True
    )

    if modo_visualizacao == "Somente divergências":
        tabela = resultado[resultado["Status"] == "DIVERGÊNCIA"]
    elif modo_visualizacao == "Revisar + divergências":
        tabela = resultado[resultado["Status"].isin(["REVISAR", "DIVERGÊNCIA"])]
    elif modo_visualizacao == "Excluídos":
        tabela = resultado[resultado["Status"] == "EXCLUÍDO"]
    elif modo_visualizacao == "Incluídos":
        tabela = resultado[resultado["Tipo"] == "INCLUÍDO"]
    else:
        tabela = resultado

    st.dataframe(
        tabela.style.apply(destacar_linhas, axis=1),
        use_container_width=True
    )

    if st.session_state.previews_pdf is not None:
        paginas_disponiveis = sorted(
            tabela["Página provável"]
            .dropna()
            .unique()
        )

        paginas_disponiveis = [
            int(p) for p in paginas_disponiveis
            if str(p).isdigit()
        ]

        if paginas_disponiveis:
            st.subheader("Visualizar página do PDF")

            pagina_escolhida = st.selectbox(
                "Selecione a página",
                paginas_disponiveis
            )

            if pagina_escolhida in st.session_state.previews_pdf:
                st.image(
                    st.session_state.previews_pdf[pagina_escolhida],
                    caption=f"Página {pagina_escolhida}",
                    use_container_width=True
                )

    arquivo_excel = gerar_excel(resultado, ignorados)

    st.download_button(
        label="Baixar relatório Excel",
        data=arquivo_excel,
        file_name="relatorio_conferencia_tabloide.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )