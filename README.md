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

Quando a coluna `Principal` estiver presente, somente os registros marcados
como principais serão conferidos. As demais linhas são tratadas como variações
internas do mesmo produto e não entram individualmente no relatório.

## Formatos aceitos

- Grade de ofertas: `.xlsx`
- Tabloide: um arquivo `.pdf` ou uma ou mais imagens `.jpg`/`.jpeg`

Ao enviar várias imagens JPEG, cada arquivo é tratado como uma página. A ordem
de seleção dos arquivos define a numeração utilizada no relatório e na prévia.

As imagens JPEG são lidas por OCR. Em uma instalação local, o Tesseract OCR
precisa estar instalado no sistema e disponível no `PATH`, com os idiomas
português e inglês. No Streamlit Community Cloud, o arquivo `packages.txt`
incluído no projeto instala esses componentes automaticamente.

A leitura de JPEG combina OCR de descrições com uma etapa dedicada às faixas
verdes de preço. Por ser reconhecimento de imagem, casos de baixa confiança são
marcados como `REVISAR` em vez de serem classificados automaticamente como uma
divergência confirmada.
