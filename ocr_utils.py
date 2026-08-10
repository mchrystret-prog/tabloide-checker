import pytesseract
from PIL import Image, ImageFilter, ImageOps


def abrir_imagem_jpeg(arquivo):
    """Abre um JPEG, corrige sua orientação e garante o modo RGB."""
    arquivo.seek(0)
    imagem = Image.open(arquivo)
    return ImageOps.exif_transpose(imagem).convert("RGB")


def preparar_imagem_ocr(imagem):
    """Melhora contraste e definição para textos pequenos de tabloides."""
    largura, altura = imagem.size
    maior_dimensao = max(largura, altura)

    if maior_dimensao < 3000:
        escala = min(2.0, 3000 / maior_dimensao)
        novo_tamanho = (int(largura * escala), int(altura * escala))
        imagem = imagem.resize(novo_tamanho, Image.Resampling.LANCZOS)

    imagem = ImageOps.grayscale(imagem)
    imagem = ImageOps.autocontrast(imagem)
    return imagem.filter(ImageFilter.SHARPEN)


def extrair_texto_jpeg(imagem):
    """Extrai textos dispersos em uma página publicitária."""
    imagem_ocr = preparar_imagem_ocr(imagem)
    configuracao = "--oem 3 --psm 11"

    try:
        return pytesseract.image_to_string(
            imagem_ocr,
            lang="por+eng",
            config=configuracao,
            timeout=120
        )
    except pytesseract.TesseractError:
        # Mantém a leitura disponível quando o pacote local não possui português.
        return pytesseract.image_to_string(
            imagem_ocr,
            lang="eng",
            config=configuracao,
            timeout=120
        )
