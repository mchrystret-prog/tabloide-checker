# Tabloide Checker 2.0

Conferência de grades de ofertas XLSX com tabloides em PDF ou imagens
JPEG/JPG. Para JPEG, a versão 2.0 oferece um modo híbrido que combina OCR local
e leitura visual estruturada.

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

## Modos para JPEG

### Híbrido confiável (recomendado)

Faz uma leitura estruturada da página inteira por visão e mantém o OCR local
como apoio. A planilha é fornecida ao leitor visual somente para associar o
card ao código correto: preço, descrição e unidade precisam ser lidos na
imagem, e campos ilegíveis ou ausentes retornam vazios.

Esse modo usa a API da OpenAI e gera consumo na conta correspondente. Configure
os Secrets do Streamlit:

```toml
[openai]
api_key = "sk-..."
modelo = "gpt-5.6"
```

Também é possível usar as variáveis `OPENAI_API_KEY` e
`OPENAI_VISION_MODEL`.

### Somente OCR local

Não usa API externa. É útil como alternativa, mas textos e preços pequenos em
artes densas podem permanecer como `REVISAR`. O Tesseract precisa estar no
`PATH`, com português e inglês. No Streamlit Community Cloud, o
`packages.txt` instala os pacotes necessários.

## Configuração do acesso

Além da seção `openai`, mantenha nos Secrets as configurações já usadas pelo
aplicativo:

```toml
[cookie]
senha = "uma-chave-longa-e-secreta"

[usuarios]
usuario = "senha"

[perfis]
usuario = "ADMIN"
```

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```

O relatório pode ser filtrado na tela e exportado para XLSX com o status e a
evidência de cada campo.
