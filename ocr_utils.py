import re
from collections import Counter

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps


def abrir_imagem_jpeg(arquivo):
    """Abre um JPEG, corrige sua orientação e garante o modo RGB."""
    arquivo.seek(0)
    imagem = Image.open(arquivo)
    return ImageOps.exif_transpose(imagem).convert("RGB")


def redimensionar_para_ocr(imagem, maior_alvo=4000, escala_maxima=2.5):
    largura, altura = imagem.size
    maior_dimensao = max(largura, altura)

    if maior_dimensao < maior_alvo:
        escala = min(escala_maxima, maior_alvo / maior_dimensao)
        imagem = imagem.resize(
            (int(largura * escala), int(altura * escala)),
            Image.Resampling.LANCZOS,
        )

    return imagem


def preparar_imagem_ocr(imagem):
    """Melhora contraste e definição para textos pequenos de tabloides."""
    imagem = redimensionar_para_ocr(imagem)
    imagem = ImageOps.grayscale(imagem)
    imagem = ImageOps.autocontrast(imagem)
    return imagem.filter(ImageFilter.SHARPEN)


def executar_ocr_texto(imagem, configuracao="--oem 3 --psm 11"):
    try:
        return pytesseract.image_to_string(
            imagem,
            lang="por+eng",
            config=configuracao,
            timeout=120,
        )
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(
            imagem,
            lang="eng",
            config=configuracao,
            timeout=120,
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


def _normalizar_preco(inteiro, centavos):
    inteiro = inteiro.lstrip("0") or "0"
    if not 1 <= len(inteiro) <= 3 or len(centavos) != 2:
        return None

    valor = int(inteiro) + int(centavos) / 100
    if valor <= 0 or valor > 999.99:
        return None
    return f"{inteiro},{centavos}"


def _precos_do_texto(texto, aceitar_sem_separador=True):
    """Converte somente sequências coerentes em preços, sem combinar OCRs."""
    texto = str(texto).replace("\n", " ")
    encontrados = set()

    for inteiro, centavos in re.findall(r"(?<!\d)(\d{1,3})\s*[,.;:]\s*(\d{2})(?!\d)", texto):
        preco = _normalizar_preco(inteiro, centavos)
        if preco:
            encontrados.add(preco)

    if aceitar_sem_separador:
        for sequencia in re.findall(
            r"(?<!\d)\d{3,5}(?!\d)(?!\s*[,.;:]\s*\d{2})", texto
        ):
            preco = _normalizar_preco(sequencia[:-2], sequencia[-2:])
            if preco:
                encontrados.add(preco)

    return encontrados


def _mascaras_digitos(recorte_rgb):
    """Gera versões binárias dos algarismos claros sobre o fundo colorido."""
    array = np.asarray(recorte_rgb)
    cinza = (
        array[:, :, 0].astype(np.float32) * 0.299
        + array[:, :, 1].astype(np.float32) * 0.587
        + array[:, :, 2].astype(np.float32) * 0.114
    ).astype("uint8")

    claro_neutro = (
        (array[:, :, 0] > 155)
        & (array[:, :, 1] > 155)
        & (array[:, :, 2] > 135)
        & ((array.max(axis=2) - array.min(axis=2)) < 90)
    )
    mascara_clara = np.where(claro_neutro, 0, 255).astype("uint8")

    # A segunda versão tolera letras brancas comprimidas pelo JPEG.
    amplitude = array.max(axis=2).astype(np.int16) - array.min(axis=2).astype(np.int16)
    mascara_valor = np.where(
        (array.max(axis=2) > 155) & (amplitude < 135), 0, 255
    ).astype("uint8")

    histograma = np.bincount(cinza.ravel(), minlength=256).astype(np.float64)
    probabilidades = histograma / max(histograma.sum(), 1)
    omega = np.cumsum(probabilidades)
    media = np.cumsum(probabilidades * np.arange(256))
    media_total = media[-1]
    variancia = (media_total * omega - media) ** 2 / (
        omega * (1 - omega) + 1e-12
    )
    limiar = int(np.nanargmax(variancia))
    otsu = np.where(cinza > limiar, 0, 255).astype("uint8")

    return [mascara_clara, mascara_valor, otsu]


def _ocr_preco_binario(binaria, psm):
    altura, largura = binaria.shape
    escala = max(3, min(6, int(260 / max(altura, 1))))
    ampliada = Image.fromarray(binaria).resize(
        (largura * escala, altura * escala), Image.Resampling.BICUBIC
    )
    ampliada = ImageOps.expand(ampliada, border=24, fill=255)
    return pytesseract.image_to_string(
        ampliada,
        lang="eng",
        config=(
            f"--oem 3 --psm {psm} "
            "-c tessedit_char_whitelist=0123456789,."
        ),
        timeout=60,
    )


def _reconhecer_preco_recorte(recorte):
    precos_com_separador = set()
    votos = Counter()
    for binaria in _mascaras_digitos(recorte)[:2]:
        for psm in (7, 11):
            texto = _ocr_preco_binario(binaria, psm)
            precos_com_separador.update(
                _precos_do_texto(texto, aceitar_sem_separador=False)
            )
            votos.update(_precos_do_texto(texto))

    # Fallback geométrico para layouts em que reais e centavos usam tamanhos
    # muito diferentes e o Tesseract não os agrupa na mesma linha.
    largura, altura = recorte.size
    inteiros = Counter()
    for limite in (0.60, 0.68):
        parte = recorte.crop((int(0.04 * largura), 0, int(limite * largura), altura))
        binaria = _mascaras_digitos(parte)[0]
        digitos = re.sub(r"\D", "", _ocr_preco_binario(binaria, 7))
        if 1 <= len(digitos) <= 3:
            inteiros[digitos] += 1

    centavos_encontrados = Counter()
    for inicio in (0.50, 0.57):
        parte_centavos = recorte.crop(
            (int(inicio * largura), 0, largura, int(0.82 * altura))
        )
        binaria = _mascaras_digitos(parte_centavos)[0]
        digitos = re.sub(r"\D", "", _ocr_preco_binario(binaria, 13))
        if len(digitos) >= 2:
            centavos_encontrados[digitos[-2:]] += 1

    for inteiro, votos_inteiro in inteiros.items():
        for centavos, votos_centavos in centavos_encontrados.items():
            preco = _normalizar_preco(inteiro, centavos)
            if preco:
                votos[preco] += min(votos_inteiro, votos_centavos)

    # Um separador decimal legível é evidência forte. Quando o JPEG apaga a
    # vírgula, o mesmo valor precisa aparecer em pelo menos dois tratamentos.
    confirmados = precos_com_separador | {
        preco for preco, quantidade in votos.items() if quantidade >= 2
    }
    return sorted(confirmados)


def _detectar_faixas_verdes(imagem):
    """Localiza faixas promocionais mesmo quando ocupam pouco da página."""
    array = np.asarray(imagem)
    altura_pagina, largura_pagina = array.shape[:2]
    dominante = (
        (array[:, :, 1].astype(np.int16) > array[:, :, 0].astype(np.int16) + 8)
        & (array[:, :, 1].astype(np.int16) > array[:, :, 2].astype(np.int16) + 8)
    )
    amplitude = array.max(axis=2).astype(np.int16) - array.min(axis=2).astype(np.int16)
    verde_valido = (
        (array[:, :, 1] > 45)
        & (amplitude > 20)
    )
    mascara = (dominante & verde_valido).astype("uint8")

    # O limite anterior exigia verde em 20% da largura. Em alguns tabloides,
    # uma faixa individual ocupa menos que isso; 2% encontra a linha e os
    # filtros geométricos abaixo removem elementos decorativos.
    linhas = agrupar_intervalos(
        mascara.sum(axis=1) > largura_pagina * 0.02,
        max(12, int(altura_pagina * 0.006)),
    )

    caixas = []
    for y1, y2 in linhas:
        altura = y2 - y1
        if altura < altura_pagina * 0.006 or altura > altura_pagina * 0.13:
            continue

        colunas = agrupar_intervalos(
            mascara[y1:y2].sum(axis=0) > max(2, altura * 0.035),
            max(45, int(largura_pagina * 0.035)),
        )
        for x1, x2 in colunas:
            largura = x2 - x1
            densidade = mascara[y1:y2, x1:x2].mean()
            if largura < largura_pagina * 0.035 or densidade < 0.12:
                continue

            margem_x = max(3, int(largura * 0.03))
            margem_y = max(2, int(altura * 0.08))
            caixas.append(
                (
                    max(0, x1 - margem_x),
                    max(0, y1 - margem_y),
                    min(largura_pagina, x2 + margem_x),
                    min(altura_pagina, y2 + margem_y),
                )
            )

    return caixas


def extrair_blocos_promocionais(imagem):
    """Retorna cada faixa verde e os preços reconhecidos nela."""
    imagem_ocr = redimensionar_para_ocr(imagem, maior_alvo=3200, escala_maxima=2.0)
    blocos = []

    for caixa in _detectar_faixas_verdes(imagem_ocr):
        recorte = imagem_ocr.crop(caixa)
        precos = _reconhecer_preco_recorte(recorte)
        if precos:
            blocos.append({"caixa": caixa, "precos": precos})

    return blocos


def extrair_precos_promocionais(imagem):
    precos = set()
    for bloco in extrair_blocos_promocionais(imagem):
        precos.update(bloco["precos"])
    return sorted(precos)


def analisar_jpeg(imagem):
    """Executa uma vez o OCR geral e a leitura dedicada dos preços."""
    imagem_texto = redimensionar_para_ocr(imagem)
    texto_colorido = executar_ocr_texto(imagem_texto)
    texto_tratado = executar_ocr_texto(preparar_imagem_ocr(imagem))
    blocos = extrair_blocos_promocionais(imagem)
    precos = sorted({preco for bloco in blocos for preco in bloco["precos"]})

    texto = "\n".join(
        [
            texto_colorido,
            texto_tratado,
            "PREÇOS PROMOCIONAIS: " + " ".join(precos),
        ]
    )
    return {"texto": texto, "precos_promocionais": precos, "blocos": blocos}


def extrair_texto_jpeg(imagem):
    """Compatibilidade com integrações que esperam somente o texto."""
    return analisar_jpeg(imagem)["texto"]
