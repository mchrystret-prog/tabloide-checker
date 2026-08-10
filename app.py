import re
import os
import unicodedata
from datetime import datetime
from io import BytesIO

import fitz
import pandas as pd
import streamlit as st
from PIL import Image
from pypdf import PdfReader
from rapidfuzz import fuzz
from streamlit_cookies_manager import EncryptedCookieManager

from ocr_utils import abrir_imagem_jpeg, analisar_jpeg
from planilha_utils import ler_planilha_normalizada


st.set_page_config(
    page_title="Tabloide Checker",
    page_icon="🛒",
    layout="wide"
)

VERSAO = "2.1.1"


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


def obter_usuarios():
    try:
        return dict(st.secrets["usuarios"])
    except Exception:
        return {}


def obter_perfil(usuario):
    try:
        return st.secrets["perfis"].get(usuario, "USUARIO")
    except Exception:
        return "USUARIO"


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

st.session_state.perfil = obter_perfil(st.session_state.usuario)

with st.sidebar:
    st.success(f"✅ Logado como: {st.session_state.usuario}")
    st.caption(f"👤 Perfil: {st.session_state.perfil}")
    st.divider()
    st.caption("Tabloide Checker")
    st.caption(f"Versão {VERSAO}")

    pagina = st.radio(
        "Menu",
        [
            "🏠 Conferência",
            "📋 Histórico"
        ]
    )

    if st.button("Sair"):
        st.session_state.logado = False
        st.session_state.usuario = ""

        try:
            del cookies["usuario"]
            cookies.save()
        except Exception:
            pass

        st.rerun()


st.title("🛒 Tabloide Checker")

if pagina == "🏠 Conferência":
    descricao = (
        "Utilize esta área para validar automaticamente preços e "
        "descrições do tabloide antes da publicação."
    )
else:
    descricao = (
        "Consulte o histórico de conferências realizadas, "
        "acompanhe divergências encontradas e monitore a evolução das validações."
    )

st.markdown(
    f"""
### Bem-vindo, {st.session_state.usuario.capitalize()} 👋

{descricao}
"""
)


if "resultado" not in st.session_state:
    st.session_state.resultado = None

if "ignorados" not in st.session_state:
    st.session_state.ignorados = None

if "metricas" not in st.session_state:
    st.session_state.metricas = None

if "documento_preview" not in st.session_state:
    st.session_state.documento_preview = None

if "ocr_diagnostico" not in st.session_state:
    st.session_state.ocr_diagnostico = None


def formatar_preco(valor):
    if pd.isna(valor):
        return ""
    try:
        return f"{float(valor):.2f}".replace(".", ",")
    except Exception:
        return str(valor).replace(".", ",")


def limpar_texto(texto):
    if pd.isna(texto):
        return ""
    return str(texto).replace("\n", " ").replace("  ", " ").strip().upper()


def texto_comparacao(texto):
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", texto.upper()).strip()


def carregar_xlsx(arquivo):
    df_original, modelo_planilha = ler_planilha_normalizada(arquivo)

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

    tem_preco_regular = pd.to_numeric(df["PREÇO"], errors="coerce").notna()
    tem_coopermais = pd.to_numeric(df["COOPERMAIS"], errors="coerce").notna()
    df = df[tem_preco_regular | tem_coopermais].copy()

    total_antes = len(df)

    ignorados = df[
        (df["Tipo"] != "EXCLUÍDO")
        & df["Descrição"].astype(str).str.upper().str.contains("INTERNO", na=False)
    ].copy()

    df = df[
        ~(
            (df["Tipo"] != "EXCLUÍDO")
            & df["Descrição"].astype(str).str.upper().str.contains("INTERNO", na=False)
        )
    ].copy()

    total_ignorados = len(ignorados)

    df["descricao_limpa"] = df["Descrição"].apply(limpar_texto)
    df["unidade_limpa"] = df["Unid.Medida"].apply(limpar_texto)
    df["embalagem_limpa"] = df["Embalagem"].apply(limpar_texto)

    df["preco_regular_fmt"] = df["PREÇO"].apply(formatar_preco)
    df["coopermais_fmt"] = df["COOPERMAIS"].apply(formatar_preco)

    return df, total_antes, total_ignorados, ignorados, modelo_planilha


def carregar_planilhas(arquivos):
    """Combina uma ou mais grades, preservando o modelo de cada arquivo."""
    partes = []
    ignorados_partes = []
    modelos = []
    total_antes = 0
    total_ignorados = 0

    for arquivo in arquivos:
        df, antes, ignorados_total, ignorados, modelo = carregar_xlsx(arquivo)
        partes.append(df)
        total_antes += antes
        total_ignorados += ignorados_total
        modelos.append(f"{arquivo.name}: {modelo}")
        if ignorados is not None and not ignorados.empty:
            ignorados_partes.append(ignorados)

    combinado = pd.concat(partes, ignore_index=True)
    ignorados = (
        pd.concat(ignorados_partes, ignore_index=True)
        if ignorados_partes
        else pd.DataFrame()
    )
    return combinado, total_antes, total_ignorados, ignorados, modelos


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


def carregar_jpegs(arquivos):
    """Executa OCR e transforma cada JPEG em uma página pesquisável."""
    paginas = []

    for i, arquivo in enumerate(arquivos):
        imagem = abrir_imagem_jpeg(arquivo)
        analise = analisar_jpeg(imagem)
        texto_limpo = limpar_texto(analise["texto"])
        paginas.append({
            "pagina": i + 1,
            "texto": texto_limpo,
            "precos_promocionais": analise["precos_promocionais"],
            "blocos_promocionais": analise["blocos"],
        })

    return paginas


def carregar_documento(arquivos):
    """Lê um PDF ou uma sequência de imagens JPEG."""
    if not arquivos:
        raise ValueError("Nenhum arquivo do tabloide foi enviado.")

    extensoes = [os.path.splitext(arquivo.name)[1].lower() for arquivo in arquivos]
    tem_pdf = any(extensao == ".pdf" for extensao in extensoes)
    tem_jpeg = any(extensao in (".jpg", ".jpeg") for extensao in extensoes)

    if tem_pdf and tem_jpeg:
        raise ValueError("Envie um PDF ou imagens JPEG, sem misturar os formatos.")

    if tem_pdf:
        if len(arquivos) != 1:
            raise ValueError("Envie apenas um PDF por conferência.")
        return carregar_pdf(arquivos[0]), "PDF"

    return carregar_jpegs(arquivos), "JPEG"


def gerar_preview_pagina(pdf_bytes, numero_pagina):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(numero_pagina - 1)

    pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    doc.close()
    return img


def gerar_preview_documento(documento_preview, numero_pagina):
    if documento_preview["tipo"] == "PDF":
        return gerar_preview_pagina(documento_preview["pdf_bytes"], numero_pagina)

    imagem_bytes = documento_preview["imagens_bytes"][numero_pagina - 1]
    return Image.open(BytesIO(imagem_bytes)).convert("RGB")


def preco_na_pagina(preco, texto_pagina):
    if not preco:
        return False

    possibilidades = [
        preco,
        preco.replace(",", ""),
        preco.replace(",", " ")
    ]

    if any(p in texto_pagina for p in possibilidades):
        return True

    partes = preco.split(",")
    if len(partes) == 2:
        padrao = rf"(?<!\d){re.escape(partes[0])}\D{{0,3}}{re.escape(partes[1])}(?!\d)"
        return bool(re.search(padrao, texto_pagina))

    return False


def extrair_precos_da_pagina(texto_pagina):
    precos = re.findall(r"\b\d{1,3},\d{2}\b", texto_pagina)
    return list(dict.fromkeys(precos))


def encontrar_preco_divergente(preco_xlsx, texto_pagina):
    precos_pdf = extrair_precos_da_pagina(texto_pagina)

    if not preco_xlsx:
        return ""

    precos_diferentes = [preco for preco in precos_pdf if preco != preco_xlsx]

    if precos_diferentes:
        return precos_diferentes[0]

    return ""


def encontrar_pagina(descricao, paginas, modo_ocr=False):
    melhor_pagina = "-"
    melhor_score = 0

    for pagina in paginas:
        if modo_ocr:
            score = fuzz.token_set_ratio(
                texto_comparacao(descricao),
                texto_comparacao(pagina["texto"])
            )
        else:
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


def pegar_dados_pagina(numero_pagina, paginas):
    for pagina in paginas:
        if pagina["pagina"] == numero_pagina:
            return pagina
    return {"texto": "", "precos_promocionais": [], "blocos_promocionais": []}


def encontrar_bloco_produto(descricao, dados_pagina):
    """Encontra o card cuja descrição mais se aproxima do item da grade."""
    melhor_bloco = None
    melhor_score = 0
    descricao_normalizada = texto_comparacao(descricao)

    for bloco in dados_pagina.get("blocos_promocionais", []):
        score = fuzz.token_set_ratio(
            descricao_normalizada,
            texto_comparacao(bloco.get("texto", "")),
        )
        if score > melhor_score:
            melhor_score = score
            melhor_bloco = bloco

    return melhor_bloco, melhor_score


def atribuir_blocos_produtos(df, paginas):
    """Faz associação global um-para-um entre itens e cards da arte."""
    possibilidades = []

    for indice_linha, row in df.iterrows():
        if row["Tipo"] == "EXCLUÍDO":
            continue
        descricao = texto_comparacao(row["Descrição"])
        regular = row["preco_regular_fmt"]
        coopermais = row["coopermais_fmt"]

        for dados_pagina in paginas:
            for indice_bloco, bloco in enumerate(
                dados_pagina.get("blocos_promocionais", [])
            ):
                score_texto = fuzz.token_set_ratio(
                    descricao, texto_comparacao(bloco.get("texto", ""))
                )
                tem_preco_lido = bool(
                    bloco.get("precos") or bloco.get("precos_card")
                )
                if not tem_preco_lido and score_texto < 65:
                    continue
                bonus_preco = 0
                if coopermais and coopermais in set(bloco.get("precos", [])):
                    bonus_preco += 12
                if regular and regular in set(bloco.get("precos_card", [])):
                    bonus_preco += 5
                score_total = min(100, score_texto + bonus_preco)
                if score_total >= 40:
                    possibilidades.append(
                        (
                            score_total,
                            score_texto,
                            indice_linha,
                            dados_pagina["pagina"],
                            indice_bloco,
                            bloco,
                        )
                    )

    atribuicoes = {}
    blocos_ocupados = set()
    for _, score_texto, indice_linha, pagina, indice_bloco, bloco in sorted(
        possibilidades, reverse=True, key=lambda item: (item[0], item[1])
    ):
        chave_bloco = (pagina, indice_bloco)
        if indice_linha in atribuicoes or chave_bloco in blocos_ocupados:
            continue
        atribuicoes[indice_linha] = (pagina, bloco, score_texto)
        blocos_ocupados.add(chave_bloco)

    return atribuicoes


def campo_no_card(valor, texto_card, campo=""):
    if not valor:
        return True

    esperado = texto_comparacao(valor)
    texto = texto_comparacao(texto_card)
    tokens = set(texto.split())

    equivalencias = {
        "KG": {"KG", "QUILO"},
        "QUILO": {"KG", "QUILO"},
        "UNIDADE": {"UNIDADE", "UNID"},
        "PACOTE": {"PACOTE", "PCT"},
        "BANDEJA": {"BANDEJA", "BDJ"},
        "CAIXA": {"CAIXA"},
        "POTE": {"POTE"},
        "FRASCO": {"FRASCO"},
        "VIDRO": {"VIDRO"},
        "LATA": {"LATA"},
        "PET": {"PET"},
        "SACHE": {"SACHE"},
        "TABLETE": {"TABLETE"},
    }

    if esperado in equivalencias:
        return bool(equivalencias[esperado] & tokens)

    # Pesos e volumes pequenos sofrem confusões previsíveis entre G/6 e L/1.
    compacto_esperado = esperado.replace(" ", "")
    compacto_texto = texto.replace(" ", "")
    variantes = {
        compacto_esperado,
        compacto_esperado.replace("G", "6"),
        compacto_esperado.replace("L", "1"),
    }
    return any(variante and variante in compacto_texto for variante in variantes)


def classificar_descricao(score, limiar_ok=85):
    if score >= limiar_ok:
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

    if "PREÇO DIVERGENTE" in texto:
        return "Preço divergente no PDF"

    if "PREÇO REGULAR" in texto:
        return "Preço regular não encontrado"

    if "UNIDADE" in texto:
        return "Unidade de medida não encontrada"

    if "EMBALAGEM" in texto:
        return "Embalagem não encontrada"

    if status_descricao == "REVISAR":
        return "Revisar descrição do produto"

    return ""


def conferir(df, paginas, tipo_documento="PDF"):
    resultados = []
    modo_ocr = tipo_documento == "JPEG"
    blocos_usados = set()
    atribuicoes_ocr = atribuir_blocos_produtos(df, paginas) if modo_ocr else {}

    for indice_linha, row in df.iterrows():
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
                "Confiança": "-",
                "Preço reconhecido OCR": "-",
                "Evidências": "Produto excluído da conferência",
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

        pagina, score = encontrar_pagina(descricao, paginas, modo_ocr)
        dados_pagina = pegar_dados_pagina(pagina, paginas)
        texto_pagina = dados_pagina["texto"]

        status_descricao = classificar_descricao(
            score,
            limiar_ok=80 if modo_ocr else 85
        )

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

        preco_divergente_pdf = ""
        if not preco_regular_ok:
            preco_divergente_pdf = encontrar_preco_divergente(preco_regular, texto_pagina)

        apontamentos = []

        if tipo_item == "INCLUÍDO":
            apontamentos.append("Produto incluído")

        if status_descricao == "REVISAR":
            apontamentos.append("Revisar descrição")

        if status_descricao == "DIVERGÊNCIA":
            apontamentos.append(
                "Produto da grade não reconhecido nas imagens JPEG"
                if modo_ocr
                else "Produto da grade não encontrado no PDF"
            )

        confianca = ""
        preco_reconhecido_ocr = ""
        evidencias = []
        status_campo_descricao = status_descricao
        status_campo_unidade = "OK" if unidade_ok and embalagem_ok else "NÃO ENCONTRADO"
        status_preco_regular = "OK" if preco_regular_ok or not preco_regular else "NÃO ENCONTRADO"
        status_preco_coopermais = "OK" if coopermais_ok or not coopermais else "NÃO ENCONTRADO"
        preco_regular_ocr = ""
        preco_coopermais_ocr = ""
        score_card = "-"

        if modo_ocr:
            preco_principal = coopermais if coopermais else preco_regular
            atribuicao = atribuicoes_ocr.get(indice_linha)
            if atribuicao:
                pagina, bloco, score_card_num = atribuicao
                dados_pagina = pegar_dados_pagina(pagina, paginas)
                texto_pagina = dados_pagina["texto"]
            else:
                bloco, score_card_num = None, 0
            score_card = round(score_card_num, 2)

            if bloco is None or score_card_num < 40:
                status_final = "AUSENTE"
                motivo_principal = "Produto da planilha não localizado na arte"
                confianca = "Alta" if score < 45 else "Média"
                status_campo_descricao = "AUSENTE"
                status_campo_unidade = "NÃO APLICÁVEL"
                status_preco_regular = "NÃO APLICÁVEL"
                status_preco_coopermais = "NÃO APLICÁVEL"
                apontamentos.append("Produto da planilha ausente na arte")
            else:
                blocos_usados.add((pagina, id(bloco)))
                texto_card = limpar_texto(bloco.get("texto", ""))
                precos_promocionais = set(bloco.get("precos", []))
                precos_card = set(bloco.get("precos_card", [])) | precos_promocionais
                descricao_ok = score_card_num >= 65
                embalagem_ok_card = campo_no_card(embalagem, texto_card, "embalagem")
                unidade_ok_card = campo_no_card(unidade, texto_card, "unidade")
                unidade_completa_ok = embalagem_ok_card and unidade_ok_card
                coopermais_ok_card = not coopermais or coopermais in precos_promocionais
                regular_ok_card = (
                    not preco_regular
                    or preco_regular in precos_card
                    or (preco_regular == coopermais and coopermais_ok_card)
                )

                status_campo_descricao = "OK" if descricao_ok else "REVISAR"
                status_campo_unidade = "OK" if unidade_completa_ok else "DIVERGENTE"
                status_preco_regular = "OK" if regular_ok_card else "AUSENTE"
                status_preco_coopermais = "OK" if coopermais_ok_card else "DIVERGENTE"
                preco_regular_ocr = ", ".join(
                    sorted(set(bloco.get("precos_regulares", [])))
                )
                preco_coopermais_ocr = ", ".join(sorted(precos_promocionais))

                evidencias.append(f"Descrição do card ({score_card_num:.1f}%)")
                motores = bloco.get("motores", {})
                if motores.get("rapidocr"):
                    evidencias.append("Leitura confirmada por OCR neural local")
                if coopermais_ok_card and coopermais:
                    preco_reconhecido_ocr = coopermais
                    evidencias.append(f"CooperMais exato ({coopermais})")
                if regular_ok_card and preco_regular:
                    evidencias.append(f"Regular exato ({preco_regular})")

                if not descricao_ok:
                    apontamentos.append("Descrição do card com baixa confiança")
                if not unidade_completa_ok:
                    apontamentos.append(
                        f"Unidade/embalagem divergente: esperado {embalagem} {unidade}".strip()
                    )
                if not regular_ok_card and preco_regular:
                    apontamentos.append(f"Preço regular ausente: esperado {preco_regular}")
                if not coopermais_ok_card and coopermais:
                    observado = ", ".join(sorted(precos_promocionais)) or "não reconhecido"
                    apontamentos.append(
                        f"Preço CooperMais divergente: esperado {coopermais} | arte {observado}"
                    )

                if not descricao_ok:
                    status_final = "REVISAR"
                    motivo_principal = "Revisar descrição reconhecida no card"
                    confianca = "Baixa"
                elif not unidade_completa_ok:
                    status_final = "DIVERGÊNCIA"
                    motivo_principal = "Unidade ou embalagem divergente"
                    confianca = "Alta"
                elif not coopermais_ok_card:
                    status_final = "DIVERGÊNCIA" if precos_promocionais else "REVISAR"
                    motivo_principal = (
                        "Preço CooperMais divergente"
                        if precos_promocionais
                        else "Preço CooperMais não reconhecido"
                    )
                    confianca = "Alta" if precos_promocionais else "Baixa"
                elif not regular_ok_card:
                    status_final = "INCOMPLETO"
                    motivo_principal = "Preço regular ausente no card"
                    confianca = "Média"
                else:
                    status_final = "OK"
                    motivo_principal = ""
                    confianca = "Alta"
        else:
            if not unidade_ok:
                apontamentos.append("Unidade de medida não encontrada na página do produto")

            if not embalagem_ok:
                apontamentos.append("Embalagem não encontrada na página do produto")

            if not preco_regular_ok:
                if preco_divergente_pdf:
                    apontamentos.append(
                        f"Preço divergente no PDF: XLSX {preco_regular} | PDF {preco_divergente_pdf}"
                    )
                else:
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
            confianca = "Alta" if status_final == "OK" else "Baixa"
            evidencias.append(f"Descrição reconhecida ({score:.1f}%)")

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
                "Conferência JPEG por OCR"
                if modo_ocr
                else (
                    "Quilo sem CooperMais"
                    if produto_por_quilo_sem_coopermais
                    else ""
                )
            ),
            "Confiança": confianca,
            "Descrição status": status_campo_descricao,
            "Unidade/embalagem status": status_campo_unidade,
            "Preço regular status": status_preco_regular,
            "CooperMais status": status_preco_coopermais,
            "Preço regular OCR": preco_regular_ocr,
            "CooperMais OCR": preco_coopermais_ocr,
            "Preço reconhecido OCR": preco_reconhecido_ocr,
            "Evidências": "; ".join(evidencias),
            "Score card": score_card,
            "Score descrição": round(score, 2),
            "Apontamentos": "; ".join(apontamentos)
        })

    if modo_ocr:
        for dados_pagina in paginas:
            for bloco in dados_pagina.get("blocos_promocionais", []):
                chave = (dados_pagina["pagina"], id(bloco))
                texto_card = limpar_texto(bloco.get("texto", ""))
                palavras = re.findall(r"[A-ZÀ-Ü]{3,}", texto_card)
                if (
                    chave in blocos_usados
                    or not bloco.get("precos")
                    or len(palavras) < 2
                ):
                    continue

                resultados.append({
                    "Status": "SEM BASE",
                    "Motivo principal": "Card encontrado sem correspondência nas planilhas",
                    "Página provável": dados_pagina["pagina"],
                    "Aba": "-",
                    "Tipo": "SEM BASE",
                    "Código": "-",
                    "Descrição": " ".join(palavras[:12]),
                    "Embalagem": "-",
                    "Unid.Medida": "-",
                    "Preço Regular XLSX": "-",
                    "CooperMais XLSX": "-",
                    "Regra especial": "Card adicional detectado por OCR",
                    "Confiança": "Média",
                    "Descrição status": "SEM BASE",
                    "Unidade/embalagem status": "NÃO APLICÁVEL",
                    "Preço regular status": "NÃO APLICÁVEL",
                    "CooperMais status": "NÃO APLICÁVEL",
                    "Preço regular OCR": ", ".join(bloco.get("precos_regulares", [])),
                    "CooperMais OCR": ", ".join(bloco.get("precos", [])),
                    "Preço reconhecido OCR": ", ".join(bloco.get("precos", [])),
                    "Evidências": "Card com descrição e preço, sem item compatível na grade",
                    "Score card": "-",
                    "Score descrição": "-",
                    "Apontamentos": "Confirmar se o produto deveria constar na planilha",
                })

    return pd.DataFrame(resultados)


def destacar_linhas(row):
    if row["Status"] == "DIVERGÊNCIA":
        return ["background-color: #5c1f1f"] * len(row)
    if row["Status"] == "REVISAR":
        return ["background-color: #5c4b1f"] * len(row)
    if row["Status"] == "INCOMPLETO":
        return ["background-color: #59451a"] * len(row)
    if row["Status"] == "AUSENTE":
        return ["background-color: #4d2738"] * len(row)
    if row["Status"] == "SEM BASE":
        return ["background-color: #34305c"] * len(row)
    if row["Status"] == "EXCLUÍDO":
        return ["background-color: #3a3a3a"] * len(row)
    return [""] * len(row)


def gerar_excel(resultado, ignorados, metricas, usuario, somente_alertas=False):
    output = BytesIO()

    if somente_alertas:
        resultado_exportar = resultado[
            resultado["Status"].isin(
                ["REVISAR", "DIVERGÊNCIA", "INCOMPLETO", "AUSENTE", "SEM BASE"]
            )
        ].copy()
    else:
        resultado_exportar = resultado.copy()

    resumo = pd.DataFrame(
        [
            ["Usuário", usuario],
            ["Versão", VERSAO],
            ["Itens na grade", metricas["total_antes"]],
            ["Internos ignorados", metricas["total_ignorados"]],
            ["Conferidos", metricas["total"]],
            ["OK", metricas["ok"]],
            ["Revisar", metricas["revisar"]],
            ["Incompletos", metricas.get("incompletos", 0)],
            ["Ausentes", metricas.get("ausentes", 0)],
            ["Sem base", metricas.get("sem_base", 0)],
            ["Divergências", metricas["divergencias"]],
            ["Excluídos", metricas["excluidos"]],
            ["Incluídos", metricas["incluidos"]],
        ],
        columns=["Indicador", "Valor"]
    )

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        resumo.to_excel(writer, index=False, sheet_name="Resumo")
        resultado_exportar.to_excel(writer, index=False, sheet_name="Conferência")

        if ignorados is not None and not ignorados.empty:
            ignorados.to_excel(writer, index=False, sheet_name="Itens Ignorados")

        workbook = writer.book

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

        worksheet = writer.sheets["Conferência"]

        for col_num, value in enumerate(resultado_exportar.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 24)

        for row_num, status in enumerate(resultado_exportar["Status"], start=1):
            if status == "DIVERGÊNCIA":
                worksheet.set_row(row_num, None, erro_format)
            elif status == "REVISAR":
                worksheet.set_row(row_num, None, revisar_format)
            elif status in ("INCOMPLETO", "AUSENTE"):
                worksheet.set_row(row_num, None, revisar_format)
            elif status == "EXCLUÍDO":
                worksheet.set_row(row_num, None, excluido_format)

        resumo_sheet = writer.sheets["Resumo"]
        resumo_sheet.set_column(0, 0, 25)
        resumo_sheet.set_column(1, 1, 25)

    output.seek(0)
    return output


def salvar_historico(usuario, xlsx_nome, pdf_nome, metricas):
    arquivo = "historico.csv"

    nova_linha = pd.DataFrame(
        [{
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "usuario": usuario,
            "xlsx": xlsx_nome,
            "pdf": pdf_nome,
            "itens_grade": metricas["total_antes"],
            "ok": metricas["ok"],
            "revisar": metricas["revisar"],
            "incompletos": metricas.get("incompletos", 0),
            "ausentes": metricas.get("ausentes", 0),
            "sem_base": metricas.get("sem_base", 0),
            "divergencias": metricas["divergencias"],
            "excluidos": metricas["excluidos"],
            "incluidos": metricas["incluidos"]
        }]
    )

    if os.path.exists(arquivo):
        historico = pd.read_csv(arquivo)
        historico = pd.concat([historico, nova_linha], ignore_index=True)
    else:
        historico = nova_linha

    historico.to_csv(arquivo, index=False)


if pagina == "📋 Histórico":
    st.header("📋 Histórico de Conferências")

    if os.path.exists("historico.csv"):
        historico = pd.read_csv("historico.csv")

        if not historico.empty:
            historico["data_hora"] = pd.to_datetime(
                historico["data_hora"],
                format="%d/%m/%Y %H:%M:%S",
                errors="coerce"
            )

            historico = historico.sort_values(by="data_hora", ascending=False).reset_index(drop=True)

            total_conferencias = len(historico)
            total_divergencias = historico["divergencias"].sum()
            total_revisar = historico["revisar"].sum()
            usuarios_ativos = historico["usuario"].nunique()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Conferências", total_conferencias)
            c2.metric("Divergências", int(total_divergencias))
            c3.metric("Itens Revisar", int(total_revisar))
            c4.metric("Usuários", usuarios_ativos)

            historico_exibir = historico.copy()
            historico_exibir["data_hora"] = (
                historico_exibir["data_hora"]
                .dt.strftime("%d/%m/%Y %H:%M:%S")
            )

            st.dataframe(historico_exibir, use_container_width=True)
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Conferências", 0)
            c2.metric("Divergências", 0)
            c3.metric("Itens Revisar", 0)
            c4.metric("Usuários", 0)
            st.dataframe(historico, use_container_width=True)
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Conferências", 0)
        c2.metric("Divergências", 0)
        c3.metric("Itens Revisar", 0)
        c4.metric("Usuários", 0)
        st.info("Nenhuma conferência registrada ainda.")

    st.stop()


xlsx_files = None
tabloide_files = None

if pagina == "🏠 Conferência":
    xlsx_files = st.file_uploader(
        "Selecione uma ou mais grades de ofertas XLSX",
        type=["xlsx"],
        accept_multiple_files=True,
        help="Você pode combinar as planilhas da frente e do verso na mesma conferência.",
    )
    tabloide_files = st.file_uploader(
        "Selecione o tabloide em PDF ou JPEG",
        type=["pdf", "jpg", "jpeg"],
        accept_multiple_files=True,
        help=(
            "Para PDF, envie um único arquivo. Para JPEG, você pode selecionar "
            "várias imagens; a ordem dos arquivos definirá a numeração das páginas."
        )
    )

    st.caption(
        "Leitura gratuita em duas camadas: Tesseract em português + OCR neural "
        "local. Nenhuma imagem é enviada para uma API paga."
    )

    if st.button("Conferir tabloide"):
        if not xlsx_files or not tabloide_files:
            st.warning("Envie o XLSX e o tabloide em PDF ou JPEG para iniciar a conferência.")
        else:
            try:
                with st.spinner("Lendo XLSX..."):
                    (
                        df,
                        total_antes,
                        total_ignorados,
                        ignorados,
                        modelo_planilha
                    ) = carregar_planilhas(xlsx_files)

                st.success("Planilhas reconhecidas: " + " | ".join(modelo_planilha))

                with st.spinner("Lendo o tabloide e reconhecendo os textos..."):
                    paginas, tipo_documento = carregar_documento(tabloide_files)

                if tipo_documento == "PDF":
                    tabloide_files[0].seek(0)
                    st.session_state.documento_preview = {
                        "tipo": "PDF",
                        "pdf_bytes": tabloide_files[0].read()
                    }
                else:
                    imagens_bytes = []
                    for arquivo in tabloide_files:
                        arquivo.seek(0)
                        imagens_bytes.append(arquivo.read())
                    st.session_state.documento_preview = {
                        "tipo": "JPEG",
                        "imagens_bytes": imagens_bytes
                    }

                with st.spinner("Comparando dados..."):
                    resultado = conferir(df, paginas, tipo_documento)
            except Exception as erro:
                st.error(f"Não foi possível processar os arquivos: {erro}")
                st.stop()

            resultado["Página provável"] = resultado["Página provável"].astype(str)
            resultado["Score descrição"] = resultado["Score descrição"].astype(str)

            total = len(resultado)
            ok = len(resultado[resultado["Status"] == "OK"])
            revisar = len(resultado[resultado["Status"] == "REVISAR"])
            incompletos = len(resultado[resultado["Status"] == "INCOMPLETO"])
            ausentes = len(resultado[resultado["Status"] == "AUSENTE"])
            sem_base = len(resultado[resultado["Status"] == "SEM BASE"])
            divergencias = len(resultado[resultado["Status"] == "DIVERGÊNCIA"])
            excluidos = len(resultado[resultado["Status"] == "EXCLUÍDO"])
            incluidos = len(resultado[resultado["Tipo"] == "INCLUÍDO"])

            st.session_state.resultado = resultado
            st.session_state.ignorados = ignorados
            st.session_state.metricas = {
                "total_antes": total_antes,
                "total_ignorados": total_ignorados,
                "total": total,
                "ok": ok,
                "revisar": revisar,
                "incompletos": incompletos,
                "ausentes": ausentes,
                "sem_base": sem_base,
                "divergencias": divergencias,
                "excluidos": excluidos,
                "incluidos": incluidos
            }

            if tipo_documento == "JPEG":
                precos_unicos = sorted({
                    preco
                    for dados in paginas
                    for preco in dados.get("precos_promocionais", [])
                })
                st.session_state.ocr_diagnostico = {
                    "precos_unicos": len(precos_unicos),
                    "itens_com_preco_exato": int(
                        resultado["Preço reconhecido OCR"].astype(bool).sum()
                    ),
                    "paginas": len(paginas),
                    "cards_ocr_neural": sum(
                        1
                        for dados in paginas
                        for bloco in dados.get("blocos_promocionais", [])
                        if bloco.get("motores", {}).get("rapidocr")
                    ),
                }
            else:
                st.session_state.ocr_diagnostico = None

            salvar_historico(
                st.session_state.usuario,
                ", ".join(arquivo.name for arquivo in xlsx_files),
                ", ".join(arquivo.name for arquivo in tabloide_files),
                st.session_state.metricas
            )


if pagina == "🏠 Conferência" and st.session_state.resultado is not None:
    resultado = st.session_state.resultado
    ignorados = st.session_state.ignorados
    metricas = st.session_state.metricas

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col7, col8, col9, col10, col11 = st.columns(5)

    col1.metric("Itens na grade", metricas["total_antes"])
    col2.metric("Internos ignorados", metricas["total_ignorados"])
    col3.metric("Conferidos", metricas["total"])
    col4.metric("OK", metricas["ok"])
    col5.metric("Revisar", metricas["revisar"])
    col6.metric("Incompletos", metricas.get("incompletos", 0))
    col7.metric("Ausentes", metricas.get("ausentes", 0))
    col8.metric("Sem base", metricas.get("sem_base", 0))
    col9.metric("Divergências", metricas["divergencias"])
    col10.metric("Excluídos", metricas["excluidos"])
    col11.metric("Incluídos", metricas["incluidos"])

    if st.session_state.ocr_diagnostico is not None:
        diagnostico = st.session_state.ocr_diagnostico
        cobertura = (
            diagnostico["itens_com_preco_exato"] / metricas["total"]
            if metricas["total"]
            else 0
        )
        st.caption(
            "Diagnóstico da leitura gratuita: "
            f"{diagnostico['precos_unicos']} preços distintos identificados em "
            f"{diagnostico['paginas']} página(s); "
            f"{diagnostico['itens_com_preco_exato']} item(ns) com preço exato confirmado; "
            f"{diagnostico.get('cards_ocr_neural', 0)} card(s) receberam a segunda leitura neural."
        )
        if diagnostico.get("cards_ocr_neural", 0) == 0:
            st.warning(
                "O segundo motor local não iniciou. A conferência foi concluída "
                "somente com o Tesseract e, por segurança, poderá deixar mais itens "
                "em Revisar. Confira o log de instalação do RapidOCR no Streamlit."
            )
        if metricas["total"] >= 10 and cobertura < 0.25:
            st.warning(
                "A leitura de preços ficou abaixo do nível mínimo esperado. "
                "O resultado foi mantido como REVISAR e não deve ser tratado "
                "como divergência confirmada. Confira a resolução das imagens "
                "ou execute novamente antes de aprovar o tabloide."
            )

    st.subheader("Resultado da conferência")

    modo_visualizacao = st.radio(
        "Visualização",
        [
            "Somente divergências",
            "Todos os pontos de atenção",
            "Excluídos",
            "Incluídos",
            "Todos os produtos"
        ],
        horizontal=True
    )

    if modo_visualizacao == "Somente divergências":
        tabela = resultado[resultado["Status"] == "DIVERGÊNCIA"]
    elif modo_visualizacao == "Todos os pontos de atenção":
        tabela = resultado[
            resultado["Status"].isin(
                ["REVISAR", "DIVERGÊNCIA", "INCOMPLETO", "AUSENTE", "SEM BASE"]
            )
        ]
    elif modo_visualizacao == "Excluídos":
        tabela = resultado[resultado["Status"] == "EXCLUÍDO"]
    elif modo_visualizacao == "Incluídos":
        tabela = resultado[resultado["Tipo"] == "INCLUÍDO"]
    else:
        tabela = resultado

    tabela = tabela.copy()
    tabela["Página provável"] = tabela["Página provável"].astype(str)

    st.dataframe(
        tabela.style.apply(destacar_linhas, axis=1),
        use_container_width=True
    )

    if st.session_state.documento_preview is not None:
        paginas_disponiveis = []

        for p in tabela["Página provável"].dropna().unique():
            try:
                paginas_disponiveis.append(int(p))
            except Exception:
                pass

        paginas_disponiveis = sorted(set(paginas_disponiveis))

        if paginas_disponiveis:
            st.subheader("Visualizar página do tabloide")

            pagina_escolhida = st.selectbox("Selecione a página", paginas_disponiveis)

            with st.spinner("Carregando página do tabloide..."):
                imagem_pagina = gerar_preview_documento(
                    st.session_state.documento_preview,
                    pagina_escolhida
                )

            st.image(
                imagem_pagina,
                caption=f"Página {pagina_escolhida}",
                use_container_width=True
            )

    arquivo_excel_completo = gerar_excel(
        resultado,
        ignorados,
        metricas,
        st.session_state.usuario
    )

    arquivo_excel_alertas = gerar_excel(
        resultado,
        ignorados,
        metricas,
        st.session_state.usuario,
        somente_alertas=True
    )

    col_a, col_b = st.columns(2)

    with col_a:
        st.download_button(
            label="📥 Baixar relatório completo",
            data=arquivo_excel_completo,
            file_name="relatorio_completo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with col_b:
        st.download_button(
            label="⚠️ Baixar pontos de atenção",
            data=arquivo_excel_alertas,
            file_name="relatorio_divergencias.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
