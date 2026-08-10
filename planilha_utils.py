import unicodedata

import pandas as pd


COLUNAS_NORMALIZADAS = [
    "Aba",
    "Tipo",
    "Código",
    "Descrição",
    "Embalagem",
    "Unid.Medida",
    "PREÇO",
    "COOPERMAIS",
]


def normalizar_nome(valor):
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def aplicar_tipo_blocos(df):
    tipo_atual = "NORMAL"
    tipos = []

    for _, row in df.iterrows():
        texto_linha = normalizar_nome(
            " ".join(str(v) for v in row.values if not pd.isna(v))
        )

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


def encontrar_aba_por_nome(excel, nome_procurado):
    nome_normalizado = normalizar_nome(nome_procurado)
    for nome in excel.sheet_names:
        if normalizar_nome(nome) == nome_normalizado:
            return nome
    return None


def encontrar_aba_tabaloide_digital(excel):
    aba = encontrar_aba_por_nome(excel, "Tabloide Digital")
    if aba:
        return aba

    for nome in excel.sheet_names:
        cabecalho = pd.read_excel(excel, sheet_name=nome, nrows=0)
        colunas = {normalizar_nome(coluna) for coluna in cabecalho.columns}
        obrigatorias = {"CODIGO", "PRECO", "OFERTA"}
        tem_descricao = bool(
            {"DESCRITIVO MARKETING", "DESCRICAO CADASTRO"} & colunas
        )
        if obrigatorias.issubset(colunas) and tem_descricao:
            return nome

    return None


def obter_coluna(df, nome, valor_padrao=None):
    alvo = normalizar_nome(nome)
    for coluna in df.columns:
        if normalizar_nome(coluna) == alvo:
            return df[coluna]
    return pd.Series([valor_padrao] * len(df), index=df.index)


def tem_coluna(df, nome):
    alvo = normalizar_nome(nome)
    return any(normalizar_nome(coluna) == alvo for coluna in df.columns)


def ler_modelo_tabaloide_digital(excel, aba):
    origem = pd.read_excel(excel, sheet_name=aba, header=0)

    if tem_coluna(origem, "Principal"):
        principal = obter_coluna(origem, "Principal")
        mascara_principal = principal.apply(
            lambda valor: valor is True
            or str(valor).strip().upper() in {"TRUE", "1", "SIM", "YES"}
        )
        if mascara_principal.any():
            origem = origem[mascara_principal].copy()

    descricao_marketing = obter_coluna(origem, "Descritivo Marketing")
    descricao_cadastro = obter_coluna(origem, "Descrição Cadastro")
    descricao = descricao_marketing.where(
        descricao_marketing.notna()
        & descricao_marketing.astype(str).str.strip().ne(""),
        descricao_cadastro,
    )

    df = pd.DataFrame(index=origem.index)
    df["Aba"] = aba
    df["Tipo"] = "NORMAL"
    df["Código"] = obter_coluna(origem, "Código")
    df["Descrição"] = descricao
    df["Embalagem"] = obter_coluna(origem, "Embalagem")
    df["Unid.Medida"] = obter_coluna(origem, "Unidade")
    df["PREÇO"] = obter_coluna(origem, "Preço")
    df["COOPERMAIS"] = obter_coluna(origem, "Oferta")
    return df[COLUNAS_NORMALIZADAS]


def ler_modelo_tabaloide_marketing(excel, aba):
    """Lê a lista simples, sem cabeçalho, usada no verso do tabloide."""
    origem = pd.read_excel(excel, sheet_name=aba, header=None)
    origem = origem[origem.iloc[:, 0].apply(lambda valor: str(valor).strip().isdigit())]

    df = pd.DataFrame(index=origem.index)
    df["Aba"] = aba
    df["Tipo"] = "NORMAL"
    df["Código"] = origem.iloc[:, 0]
    df["Descrição"] = origem.iloc[:, 1]
    df["Embalagem"] = origem.iloc[:, 2]
    df["Unid.Medida"] = origem.iloc[:, 3]
    df["PREÇO"] = origem.iloc[:, 4]
    df["COOPERMAIS"] = origem.iloc[:, 5]
    return df[COLUNAS_NORMALIZADAS]


def ler_modelo_lista_ofertas(excel, aba):
    """Lê a lista FLV cujo cabeçalho começa em 'Cód. Produto'."""
    origem = pd.read_excel(excel, sheet_name=aba, header=None)
    linha_cabecalho = None

    for indice, valor in origem.iloc[:, 0].items():
        if "COD. PRODUTO" in normalizar_nome(valor):
            linha_cabecalho = indice
            break

    if linha_cabecalho is None:
        raise ValueError("Cabeçalho da Lista de Ofertas não encontrado.")

    dados = origem.iloc[linha_cabecalho + 1 :].copy()
    dados = dados[dados.iloc[:, 0].apply(lambda valor: str(valor).strip().isdigit())]

    df = pd.DataFrame(index=dados.index)
    df["Aba"] = aba
    df["Tipo"] = "NORMAL"
    df["Código"] = dados.iloc[:, 0]
    # A terceira coluna contém o descritivo já preparado para a comunicação.
    df["Descrição"] = dados.iloc[:, 2].where(dados.iloc[:, 2].notna(), dados.iloc[:, 1])
    df["Embalagem"] = dados.iloc[:, 3]
    df["Unid.Medida"] = dados.iloc[:, 4]
    df["PREÇO"] = dados.iloc[:, 5]
    df["COOPERMAIS"] = dados.iloc[:, 6]
    return df[COLUNAS_NORMALIZADAS]


def ler_modelo_legado(excel):
    dataframes = []
    aba_agencia = encontrar_aba_por_nome(excel, "Agência")
    aba_flv = encontrar_aba_por_nome(excel, "FLV")

    if aba_agencia:
        df_agencia = pd.read_excel(excel, sheet_name=aba_agencia, header=2)
        df_agencia["Aba"] = "Agência"
        dataframes.append(aplicar_tipo_blocos(df_agencia))

    if aba_flv:
        df_raw = pd.read_excel(excel, sheet_name=aba_flv, header=None)
        if df_raw.shape[1] < 6:
            raise ValueError("A aba FLV precisa ter pelo menos seis colunas.")

        df_flv = pd.DataFrame(index=df_raw.index)
        df_flv["Código"] = df_raw.iloc[:, 0]
        df_flv["Descrição"] = df_raw.iloc[:, 1]
        df_flv["Embalagem"] = df_raw.iloc[:, 2]
        df_flv["Unid.Medida"] = df_raw.iloc[:, 3]
        df_flv["PREÇO"] = df_raw.iloc[:, 4]
        df_flv["COOPERMAIS"] = df_raw.iloc[:, 5]
        df_flv["Aba"] = "FLV"
        dataframes.append(aplicar_tipo_blocos(df_flv))

    if not dataframes:
        raise ValueError(
            "Modelo de planilha não reconhecido. Envie o modelo Agência/FLV "
            "ou o modelo Tabloide Digital."
        )

    df = pd.concat(dataframes, ignore_index=True)
    return df[COLUNAS_NORMALIZADAS]


def ler_planilha_normalizada(arquivo):
    arquivo.seek(0)
    excel = pd.ExcelFile(arquivo)
    aba_digital = encontrar_aba_tabaloide_digital(excel)

    if aba_digital:
        return (
            ler_modelo_tabaloide_digital(excel, aba_digital),
            "Tabloide Digital",
        )

    for aba in excel.sheet_names:
        amostra = pd.read_excel(excel, sheet_name=aba, header=None, nrows=5)
        primeira_coluna = " ".join(normalizar_nome(valor) for valor in amostra.iloc[:, 0])

        if "COD. PRODUTO" in primeira_coluna:
            return ler_modelo_lista_ofertas(excel, aba), "Lista de Ofertas FLV"

        if normalizar_nome(aba) == "TABLOIDE MARKETING" and amostra.shape[1] >= 6:
            return ler_modelo_tabaloide_marketing(excel, aba), "Tabloide Marketing"

    return ler_modelo_legado(excel), "Agência/FLV"
