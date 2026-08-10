# Tabloide Checker

Conferência automática de uma grade de ofertas XLSX com tabloides em PDF ou
imagens JPEG/JPG.

## Formatos aceitos

- Grade de ofertas: `.xlsx`
- Tabloide: um arquivo `.pdf` ou uma ou mais imagens `.jpg`/`.jpeg`

Ao enviar várias imagens JPEG, cada arquivo é tratado como uma página. A ordem
de seleção dos arquivos define a numeração utilizada no relatório e na prévia.

As imagens JPEG são lidas por OCR. Em uma instalação local, o Tesseract OCR
precisa estar instalado no sistema e disponível no `PATH`, com os idiomas
português e inglês. No Streamlit Community Cloud, o arquivo `packages.txt`
incluído no projeto instala esses componentes automaticamente.
