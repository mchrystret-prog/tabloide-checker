# Tabloide Checker 2.1.1

Conferência gratuita de grades de ofertas XLSX com tabloides em PDF ou imagens
JPEG/JPG. Todo o processamento acontece no próprio servidor da aplicação: não
há API paga, chave externa nem cobrança por página.

## O que é validado

Cada card é conferido campo a campo:

- descrição do produto;
- unidade de medida e embalagem;
- preço regular;
- preço CooperMais.

O sistema também aponta produtos da planilha ausentes na arte e cards da arte
sem correspondência nas planilhas.

Os resultados possíveis são:

- `OK`: todos os campos exigidos foram confirmados;
- `DIVERGÊNCIA`: existe um valor visível diferente da planilha;
- `INCOMPLETO`: um campo exigido pela planilha não aparece na arte;
- `REVISAR`: a leitura não teve confiança suficiente para aprovação automática;
- `AUSENTE`: o produto da planilha não foi localizado;
- `SEM BASE`: existe um card na arte que não está nas planilhas;
- `EXCLUÍDO`: item marcado como excluído no modelo legado.

## Planilhas aceitas

É possível enviar uma ou mais planilhas na mesma conferência. Os modelos são
identificados automaticamente:

- tradicional, com abas `Agência` e/ou `FLV`;
- `Tabloide Digital`;
- lista simples `Tabloide Marketing`, sem cabeçalho;
- `Lista de Ofertas`, com cabeçalho iniciado por `Cód. Produto`.

No modelo `Tabloide Digital`, o descritivo de marketing é usado como descrição
principal. Quando a coluna `Principal` existe, somente os registros marcados
como principais entram na conferência.

## Leitura gratuita em duas camadas

As imagens JPEG passam por dois motores locais:

1. Tesseract com modelos em português e inglês, múltiplos tratamentos de
   contraste e diferentes modos de segmentação;
2. RapidOCR com ONNX Runtime, usado como uma segunda leitura neural dos cards e
   dos preços.

Os cards são recortados antes da leitura e associados aos itens da planilha de
forma global e exclusiva. Um mesmo card não pode aprovar dois produtos. A
descrição, a unidade e cada preço mantêm evidências independentes.

O segundo motor é carregado uma única vez pelo servidor. A primeira conferência
depois que o aplicativo reinicia pode demorar mais; as seguintes reutilizam o
modelo em memória.

## Configuração do acesso

Configure os Secrets do Streamlit:

```toml
[cookie]
senha = "uma-chave-longa-e-secreta"

[usuarios]
usuario = "senha"

[perfis]
usuario = "ADMIN"
```

## Execução local

O Tesseract precisa estar no `PATH`. No Streamlit Community Cloud, o
`packages.txt` instala os idiomas necessários.

```bash
pip install -r requirements.txt
streamlit run app.py
```

O relatório pode ser filtrado na tela e exportado para XLSX com o status e a
evidência de cada campo.
