import re
from collections import Counter
from functools import lru_cache

import numpy as np
import pytesseract
from PIL import Image, ImageFilter, ImageOps


@lru_cache(maxsize=1)
def _motor_rapidocr():
    """Carrega uma única instância do OCR neural gratuito por processo."""
    try:
        from rapidocr import RapidOCR

        return RapidOCR()
    except Exception:
        return None


def executar_rapidocr(imagem):
    """Normaliza as saídas das versões atuais e legadas do RapidOCR."""
    motor = _motor_rapidocr()
    if motor is None:
        return []

    try:
        saida = motor(np.asarray(imagem.convert("RGB")))
        resultado = saida[0] if isinstance(saida, tuple) else saida
        linhas = []

        if hasattr(resultado, "txts"):
            textos_brutos = getattr(resultado, "txts", None)
            scores_brutos = getattr(resultado, "scores", None)
            textos = list(textos_brutos) if textos_brutos is not None else []
            scores = list(scores_brutos) if scores_brutos is not None else []
            for indice, texto in enumerate(textos):
                score = float(scores[indice]) if indice < len(scores) else 0.5
                linhas.append((str(texto), score))
            return linhas

        for item in resultado or []:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                linhas.append((str(item[1]), float(item[2])))
        return linhas
    except Exception:
        # O Tesseract permanece disponível caso o segundo motor falhe.
        return []


def _texto_e_precos_rapidocr(imagem, confianca_minima=0.58):
    linhas = executar_rapidocr(imagem)
    textos = [texto for texto, score in linhas if score >= confianca_minima]
    precos = {
        preco
        for texto, score in linhas
        if score >= max(0.68, confianca_minima)
        for preco in _precos_do_texto(texto)
    }
    confianca = (
        sum(score for _, score in linhas) / len(linhas)
        if linhas
        else 0.0
    )
    return "\n".join(textos), precos, confianca


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


def _componentes_conectados(binaria):
    """Retorna caixas dos elementos pretos sem exigir OpenCV/SciPy."""
    primeiro_plano = binaria < 128
    altura, largura = primeiro_plano.shape
    visitado = np.zeros_like(primeiro_plano, dtype=bool)
    componentes = []

    for y in range(altura):
        for x in range(largura):
            if not primeiro_plano[y, x] or visitado[y, x]:
                continue
            pilha = [(x, y)]
            visitado[y, x] = True
            minimo_x = maximo_x = x
            minimo_y = maximo_y = y
            area = 0

            while pilha:
                atual_x, atual_y = pilha.pop()
                area += 1
                minimo_x = min(minimo_x, atual_x)
                maximo_x = max(maximo_x, atual_x)
                minimo_y = min(minimo_y, atual_y)
                maximo_y = max(maximo_y, atual_y)

                for proximo_x, proximo_y in (
                    (atual_x - 1, atual_y),
                    (atual_x + 1, atual_y),
                    (atual_x, atual_y - 1),
                    (atual_x, atual_y + 1),
                ):
                    if (
                        0 <= proximo_x < largura
                        and 0 <= proximo_y < altura
                        and primeiro_plano[proximo_y, proximo_x]
                        and not visitado[proximo_y, proximo_x]
                    ):
                        visitado[proximo_y, proximo_x] = True
                        pilha.append((proximo_x, proximo_y))

            if area >= 8:
                componentes.append(
                    (minimo_x, minimo_y, maximo_x + 1, maximo_y + 1, area)
                )

    return componentes


def _preco_por_componentes(recorte):
    """Separa reais e centavos pela diferença de tamanho tipográfico."""
    binaria = _mascaras_digitos(recorte)[0]
    altura, largura = binaria.shape
    componentes = [
        componente
        for componente in _componentes_conectados(binaria)
        if componente[0] > largura * 0.12
        and componente[4] >= max(12, altura * largura * 0.0003)
    ]
    if not componentes:
        return set()

    maior_altura = max(y2 - y1 for _, y1, _, y2, _ in componentes)
    grandes = [
        componente
        for componente in componentes
        if componente[3] - componente[1] >= maior_altura * 0.68
    ]
    if not grandes:
        return set()

    grandes.sort(key=lambda item: item[0])
    # Mantém a sequência de algarismos grandes mais à direita, descartando R$.
    ultimo_x = grandes[-1][2]
    sequencia = [c for c in grandes if c[0] >= grandes[-1][0] - largura * 0.42]
    x1 = min(c[0] for c in sequencia)
    y1 = min(c[1] for c in sequencia)
    x2 = max(c[2] for c in sequencia)
    y2 = max(c[3] for c in sequencia)

    menores = [
        componente
        for componente in componentes
        if componente[0] >= ultimo_x - 2
        and maior_altura * 0.25 <= componente[3] - componente[1] <= maior_altura * 0.67
    ]
    menores = sorted(menores, key=lambda item: (-item[4], item[0]))[:2]
    if len(menores) < 2:
        return set()
    menores.sort(key=lambda item: item[0])

    margem = max(3, int(altura * 0.06))
    inteiro_img = binaria[
        max(0, y1 - margem) : min(altura, y2 + margem),
        max(0, x1 - margem) : min(largura, x2 + margem),
    ]
    cx1 = min(c[0] for c in menores)
    cy1 = min(c[1] for c in menores)
    cx2 = max(c[2] for c in menores)
    cy2 = max(c[3] for c in menores)
    centavos_img = binaria[
        max(0, cy1 - margem) : min(altura, cy2 + margem),
        max(0, cx1 - margem) : min(largura, cx2 + margem),
    ]

    inteiro = re.sub(r"\D", "", _ocr_preco_binario(inteiro_img, 7))
    centavos = re.sub(r"\D", "", _ocr_preco_binario(centavos_img, 7))
    if not (1 <= len(inteiro) <= 3 and len(centavos) >= 2):
        return set()
    preco = _normalizar_preco(inteiro, centavos[-2:])
    return {preco} if preco else set()


def _reconhecer_precos_regulares(imagem, caixa_preco):
    """Lê a linha pequena posicionada logo abaixo da faixa promocional."""
    x1, _, x2, y2 = caixa_preco
    altura_pagina = imagem.height
    base = min(altura_pagina, y2 + int(altura_pagina * 0.048))
    if base <= y2:
        return []

    recorte = imagem.crop((x1, y2, x2, base))
    tratado = ImageOps.autocontrast(ImageOps.grayscale(recorte))
    textos = []
    for psm in (7, 11):
        textos.append(
            pytesseract.image_to_string(
                tratado.resize(
                    (tratado.width * 4, tratado.height * 4),
                    Image.Resampling.LANCZOS,
                ),
                lang="eng",
                config=(
                    f"--oem 3 --psm {psm} "
                    "-c tessedit_char_whitelist=0123456789,."
                ),
                timeout=60,
            )
        )
    return sorted({preco for texto in textos for preco in _precos_do_texto(texto)})


def _reconhecer_preco_recorte(recorte):
    precos_com_separador = set()
    votos = Counter()
    precos_com_separador.update(_preco_por_componentes(recorte))
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
    # Logos e o símbolo R$ podem grudar um algarismo espúrio à esquerda.
    # Mantemos também os dois últimos algarismos da parte inteira nesses casos;
    # a etapa de comparação ainda exige igualdade exata com a planilha.
    reduzidos = set()
    for preco in confirmados:
        inteiro, centavos = preco.split(",")
        if len(inteiro) == 3 and int(inteiro) >= 300:
            reduzido = _normalizar_preco(inteiro[-2:], centavos)
            if reduzido:
                reduzidos.add(reduzido)
    confirmados.update(reduzidos)
    return sorted(confirmados)


def _detectar_faixas_verdes(imagem):
    """Localiza faixas claras e caixas escuras de preço promocional."""
    array = np.asarray(imagem).astype(np.int16)
    altura_pagina, largura_pagina = array.shape[:2]
    vermelho = array[:, :, 0]
    verde = array[:, :, 1]
    azul = array[:, :, 2]
    amplitude = array.max(axis=2) - array.min(axis=2)

    mascaras = [
        # Verde-limão usado nas grades de CooperMais.
        (verde > 125)
        & (verde > vermelho + 18)
        & (verde > azul + 35)
        & (vermelho > 35),
        # Verde escuro usado nos cards de carnes e nos destaques grandes.
        (verde > 42)
        & (verde < 145)
        & (verde > vermelho + 6)
        & (verde > azul + 6)
        & (amplitude > 18),
    ]

    caixas = []
    for mascara in mascaras:
        # Fundos verdes nas bordas não podem unir todas as linhas da página.
        mascara[:, : int(largura_pagina * 0.03)] = False
        mascara[:, int(largura_pagina * 0.97) :] = False

        linhas = agrupar_intervalos(
            mascara.sum(axis=1) > largura_pagina * 0.015,
            max(10, int(altura_pagina * 0.004)),
        )

        for y1, y2 in linhas:
            altura = y2 - y1
            if altura < altura_pagina * 0.004 or altura > altura_pagina * 0.12:
                continue

            colunas = agrupar_intervalos(
                mascara[y1:y2].sum(axis=0) > max(2, altura * 0.04),
                max(40, int(largura_pagina * 0.025)),
            )
            for x1, x2 in colunas:
                largura = x2 - x1
                densidade = mascara[y1:y2, x1:x2].mean()
                proporcao = largura / max(altura, 1)
                if (
                    largura < largura_pagina * 0.025
                    or largura > largura_pagina * 0.50
                    or densidade < 0.10
                    or proporcao < 2.0
                ):
                    continue
                caixas.append((int(x1), int(y1), int(x2), int(y2)))

    # Remove detecções duplicadas do mesmo bloco feitas pelas duas máscaras.
    unicas = []
    por_area = sorted(
        caixas,
        key=lambda item: (item[2] - item[0]) * (item[3] - item[1]),
        reverse=True,
    )
    for caixa in por_area:
        x1, y1, x2, y2 = caixa
        duplicada = False
        for ux1, uy1, ux2, uy2 in unicas:
            inter_x = max(0, min(x2, ux2) - max(x1, ux1))
            inter_y = max(0, min(y2, uy2) - max(y1, uy1))
            intersecao = inter_x * inter_y
            menor_area = min((x2 - x1) * (y2 - y1), (ux2 - ux1) * (uy2 - uy1))
            if menor_area and intersecao / menor_area > 0.55:
                duplicada = True
                break
        if not duplicada:
            unicas.append(caixa)

    return sorted(unicas, key=lambda item: (item[1], item[0]))


def _caixa_card(caixa_preco, tamanho_pagina):
    """Expande a faixa para incluir descrição, unidade e preço regular."""
    largura_pagina, altura_pagina = tamanho_pagina
    x1, y1, x2, y2 = caixa_preco
    largura = x2 - x1

    margem_x = max(int(largura * 0.16), int(largura_pagina * 0.012))
    topo = max(0, y1 - int(altura_pagina * 0.145))
    base = min(altura_pagina, y2 + int(altura_pagina * 0.045))
    return (
        max(0, x1 - margem_x),
        topo,
        min(largura_pagina, x2 + margem_x),
        base,
    )


def extrair_blocos_promocionais(imagem):
    """Retorna evidências espacialmente vinculadas a cada card."""
    imagem_ocr = redimensionar_para_ocr(imagem, maior_alvo=3200, escala_maxima=2.0)
    blocos = []

    for caixa in _detectar_faixas_verdes(imagem_ocr):
        recorte = imagem_ocr.crop(caixa)
        precos = _reconhecer_preco_recorte(recorte)
        texto_preco_neural, precos_neurais, confianca_preco_neural = (
            _texto_e_precos_rapidocr(recorte, confianca_minima=0.62)
        )
        precos = sorted(set(precos) | set(precos_neurais))
        caixa_card = _caixa_card(caixa, imagem_ocr.size)
        recorte_card = imagem_ocr.crop(caixa_card)
        texto_card_colorido = executar_ocr_texto(
            recorte_card,
            configuracao="--oem 3 --psm 11",
        )
        texto_card_tratado = executar_ocr_texto(
            preparar_imagem_ocr(recorte_card),
            configuracao="--oem 3 --psm 6",
        )
        texto_card_neural, precos_card_neurais, confianca_card_neural = (
            _texto_e_precos_rapidocr(recorte_card)
        )
        texto_card = "\n".join(
            [texto_card_colorido, texto_card_tratado, texto_card_neural]
        )
        precos_regulares = _reconhecer_precos_regulares(imagem_ocr, caixa)
        precos_card = sorted(
            set(_precos_do_texto(texto_card))
            | set(precos_regulares)
            | set(precos_card_neurais)
        )
        blocos.append({
            "caixa": caixa,
            "caixa_card": caixa_card,
            "texto": texto_card,
            "precos": precos,
            "precos_card": precos_card,
            "precos_regulares": precos_regulares,
            "motores": {
                "tesseract": True,
                "rapidocr": bool(texto_card_neural or texto_preco_neural),
            },
            "confianca_neural": round(
                max(confianca_card_neural, confianca_preco_neural), 3
            ),
        })

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
