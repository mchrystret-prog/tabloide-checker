# Tabloide Checker

Conferência automática de uma grade de ofertas XLSX com tabloides em PDF ou
imagens JPEG/JPG.

## Modelos de planilha aceitos

- Modelo tradicional, com as abas `Agência` e/ou `FLV`
- Modelo `Tabloide Digital`, com os campos `Descritivo Marketing`, `Preço` e
  `Oferta`

O modelo é identificado automaticamente no envio. No formato Tabloide Digital,
o descritivo de marketing é usado como descrição principal, com a descrição de
cadastro como alternativa quando o primeiro estiver vazio.

## Formatos aceitos

- Grade de ofertas: `.xlsx`
- Tabloide: um arquivo `.pdf` ou uma ou mais imagens `.jpg`/`.jpeg`

Ao enviar várias imagens JPEG, cada arquivo é tratado como uma página. A ordem
de seleção dos arquivos define a numeração utilizada no relatório e na prévia.

As imagens JPEG são lidas por OCR. Em uma instalação local, o Tesseract OCR
precisa estar instalado no sistema e disponível no `PATH`, com os idiomas
português e inglês. No Streamlit Community Cloud, o arquivo `packages.txt`
incluído no projeto instala esses componentes automaticamente.
