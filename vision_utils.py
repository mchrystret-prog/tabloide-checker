"""Leitura visual estruturada de tabloides JPEG pela API da OpenAI."""

import base64
import json
import os
from io import BytesIO
from typing import Optional

from PIL import Image
from pydantic import BaseModel, Field


class CardVisual(BaseModel):
    codigo_planilha: Optional[str] = Field(
        description="Código do item correspondente na planilha, ou null se não houver."
    )
    descricao_arte: str = Field(description="Descrição exatamente como aparece no card.")
    embalagem_arte: Optional[str]
    unidade_arte: Optional[str]
    preco_regular_arte: Optional[str] = Field(
        description="Preço regular visível, no formato 0,00."
    )
    preco_coopermais_arte: Optional[str] = Field(
        description="Preço CooperMais visível, no formato 0,00."
    )
    tem_selo_coopermais: bool
    confianca: float = Field(ge=0, le=1)


class AnalisePagina(BaseModel):
    cards: list[CardVisual]


def _imagem_data_url(imagem):
    buffer = BytesIO()
    imagem.convert("RGB").save(buffer, format="JPEG", quality=95)
    conteudo = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{conteudo}"


def _itens_referencia(df):
    itens = []
    for _, row in df.iterrows():
        itens.append(
            {
                "codigo": str(row["Código"]),
                "descricao": str(row["Descrição"]),
                "embalagem": "" if row["embalagem_limpa"] == "" else str(row["Embalagem"]),
                "unidade": "" if row["unidade_limpa"] == "" else str(row["Unid.Medida"]),
                "preco_regular": row["preco_regular_fmt"],
                "preco_coopermais": row["coopermais_fmt"],
            }
        )
    return itens


def obter_configuracao_openai():
    """Obtém chave/modelo dos Secrets do Streamlit ou do ambiente."""
    chave = os.environ.get("OPENAI_API_KEY", "")
    modelo = os.environ.get("OPENAI_VISION_MODEL", "gpt-5.6")

    try:
        import streamlit as st

        bloco = st.secrets.get("openai", {})
        chave = bloco.get("api_key", chave)
        modelo = bloco.get("modelo", modelo)
    except Exception:
        pass

    return chave, modelo


def analisar_pagina_com_visao(imagem: Image.Image, df, numero_pagina: int):
    """Transcreve todos os cards visíveis sem preencher dados por inferência."""
    chave, modelo = obter_configuracao_openai()
    if not chave:
        raise ValueError(
            "O modo híbrido requer [openai] api_key nos Secrets do Streamlit."
        )

    try:
        from openai import OpenAI
    except ImportError as erro:
        raise RuntimeError("A dependência 'openai' não está instalada.") from erro

    referencia = json.dumps(_itens_referencia(df), ensure_ascii=False)
    instrucao = f"""
Você confere uma página de tabloide brasileiro. Extraia TODOS os cards de
produto visíveis na página {numero_pagina}. Para cada card, transcreva de forma
independente: descrição, embalagem/unidade, preço regular e preço CooperMais.

Regras obrigatórias:
- Leia os valores somente da imagem. A referência serve apenas para vincular o
  card a um código; nunca copie dela um texto ou preço ilegível/ausente na arte.
- Use null quando um campo não estiver claramente impresso.
- Não confunda preço regular riscado/menor com o preço CooperMais em destaque.
- Preserve quantidades como 100g, 500ml, kg, unidade, bandeja e pacote.
- Se nenhum item da referência corresponder, use codigo_planilha=null.
- Retorne um registro por card, inclusive cards sem correspondência.

Itens possíveis nas planilhas:
{referencia}
""".strip()

    cliente = OpenAI(api_key=chave)
    resposta = cliente.responses.parse(
        model=modelo,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": instrucao},
                    {
                        "type": "input_image",
                        "image_url": _imagem_data_url(imagem),
                        "detail": "high",
                    },
                ],
            }
        ],
        text_format=AnalisePagina,
    )
    if resposta.output_parsed is None:
        raise RuntimeError("A leitura visual não retornou dados estruturados.")
    return [card.model_dump() for card in resposta.output_parsed.cards]
