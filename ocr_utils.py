import re

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps


def abrir_imagem_jpeg(arquivo):
    """Abre um JPEG, corrige sua orientação e garante o modo RGB."""
    arquivo.seek(0)
    imagem = Image.open(arquivo)
    return ImageOps.exif_transpose(imagem).convert("RGB")


def redimensionar_para_ocr(imagem):
    largura, altura = imagem.size
    maior_dimensao = max(largura, altura)

    if maior_dimensao < 4000:
        escala = min(2.0, 4000 / maior_dimensao)
        novo_tamanho = (int(largura * escala), int(altura * escala))
        imagem = imagem.resize(novo_tamanho, Image.Resampling.LANCZOS)

    return imagem


def preparar_imagem_ocr(imagem):
    """Melhora contraste e definição para textos pequenos de tabloides."""
    imagem = redimensionar_para_ocr(imagem)

    imagem = ImageOps.grayscale(imagem)
    imagem = ImageOps.autocontrast(imagem)
    return imagem.filter(ImageFilter.SHARPEN)


def executar_ocr_texto(imagem):
    configuracao = "--oem 3 --psm 11"

    try:
        return pytesseract.image_to_string(
            imagem,
            lang="por+eng",
            config=configuracao,
            timeout=120
        )
    except pytesseract.TesseractError:
        # Mantém a leitura disponível quando o pacote local não possui português.
        return pytesseract.image_to_string(
            imagem,
            lang="eng",
            config=configuracao,
            timeout=120
        )


def agrupar_intervalos(mascara, tamanho_minimo):
    valores = np.flatnonzero(mascara)
    intervalos = []

    if len(valores) == 0:
        return intervalos

    inicio = anterior = valores[0]
    for valor in valores[1:]:
        if valor > anterior + 1:
            if anterior - inicio + 1 >= tamanho_minimo:
                intervalos.append((int(inicio), int(anterior + 1)))
            inicio = valor
        anterior = valor

    if anterior - inicio + 1 >= tamanho_minimo:
        intervalos.append((int(inicio), int(anterior + 1)))

    return intervalos


def reconhecer_digitos_faixa(imagem, psm):
    imagem = imagem.resize(
        (imagem.width * 4, imagem.height * 4),
        Image.Resampling.LANCZOS
    )
    array = np.asarray(imagem)
    pixels_claros = (
        (array[:, :, 0] > 190)
        & (array[:, :, 1] > 190)
        & (array[:, :, 2] > 170)
    )
    binaria = Image.fromarray(
        np.where(pixels_claros, 0, 255).astype("uint8")
    )
    binaria = ImageOps.expand(binaria, border=16, fill=255)
    texto = pytesseract.image_to_string(
        binaria,
        lang="eng",
        config=(
            f"--oem 3 --psm {psm} "
            "-c tessedit_char_whitelist=0123456789"
        ),
        timeout=120
    )
    return "".join(re.findall(r"\d", texto))


def extrair_precos_promocionais(imagem):
    """Lê números brancos posicionados sobre faixas verdes do tabloide."""
    array = np.asarray(imagem).astype(np.int16)
    vermelho = array[:, :, 0]
    verde = array[:, :, 1]
    azul = array[:, :, 2]
    mascara_verde = (
        (verde > vermelho + 10)
        & (verde > azul + 10)
        & (verde > 55)
    )

    precos = set()
    linhas = agrupar_intervalos(
        mascara_verde.sum(axis=1) > array.shape[1] * 0.2,
        20
    )

    for y1, y2 in linhas:
        altura = y2 - y1
        if altura < 25 or altura > 130:
            continue

        colunas = agrupar_intervalos(
            mascara_verde[y1:y2].sum(axis=0) > altura * 0.05,
            80
        )

        for x1, x2 in colunas:
            largura = x2 - x1
            inteiros = set()
            centavos_encontrados = set()

            for limite in (0.60, 0.62, 0.65):
                recorte = imagem.crop((
                    x1 + int(0.10 * largura),
                    y1,
                    x1 + int(limite * largura),
                    y2 + int(0.10 * altura)
                ))
                inteiros.add(reconhecer_digitos_faixa(recorte, 10))

            for inicio in (0.53, 0.55, 0.57):
                recorte = imagem.crop((
                    x1 + int(inicio * largura),
                    y1,
                    x1 + int(0.94 * largura),
                    y1 + int(0.74 * altura)
                ))
                centavos_encontrados.add(
                    reconhecer_digitos_faixa(recorte, 13)
                )

            for inteiro in inteiros:
                for centavos in centavos_encontrados:
                    if len(centavos) < 2:
                        continue
                    centavos = centavos[-2:]
                    possibilidades = [inteiro]
                    if len(inteiro) > 1:
                        possibilidades.append(inteiro[:-1])

                    for possibilidade in possibilidades:
                        if 1 <= len(possibilidade) <= 3:
                            precos.add(f"{possibilidade},{centavos}")

    return sorted(precos)


def extrair_texto_jpeg(imagem):
    """Extrai descrições, textos gerais e preços de uma página publicitária."""
    texto_colorido = executar_ocr_texto(redimensionar_para_ocr(imagem))
    texto_tratado = executar_ocr_texto(preparar_imagem_ocr(imagem))
    precos = extrair_precos_promocionais(imagem)
    return "\n".join([
        texto_colorido,
        texto_tratado,
        "PREÇOS PROMOCIONAIS: " + " ".join(precos)
    ])
