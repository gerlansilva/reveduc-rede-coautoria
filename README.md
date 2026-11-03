# Rede de coautoria — Revista Eletrônica de Educação (Reveduc/UFSCar)

Visualização interativa da rede de coautoria da
[Revista Eletrônica de Educação](https://www.reveduc.ufscar.br/index.php/reveduc/index)
(Reveduc/UFSCar), reimplementando em Python o método de **Rafael Gutierres
Castanha** (2024) — *Visualização de redes de coautoria como insumo bibliométrico
às revistas científicas* (DOI: [10.5007/1518-2924.2024.e96589](https://doi.org/10.5007/1518-2924.2024.e96589)).

## Demonstração

A rede interativa está publicada em:
**https://coautoriareveduc.pages.dev**

## Funcionalidades

- **Raspagem** do portal OJS da revista (42 números, 1330 artigos, 2370 autores).
- **Busca por nome** com destaque da sub-rede do autor (e seus coautores).
- **Métricas** de análise de redes sociais, colorizáveis por autor:
  produção (artigos), grau, intermediação (betweenness), proximidade (closeness),
  autovetor (eigenvector) e agrupamento (clustering).
- **Detecção de comunidades** (Louvain) com destaque por comunidade.
- **Tabela dinâmica** dos 20 autores mais bem posicionados na métrica escolhida.
- Rede **self-contained**: a biblioteca vis-network está incluída no repositório
  (sem dependência de CDN externo).

## Estrutura

```
raspar_reveduc.py           # raspagem OJS da Reveduc (requests + BeautifulSoup)
gerar_rede.py               # métricas, comunidades e geração do HTML (genérico)
reveduc_dados_coautoria.json# dados raspados (artigos)
site/
  index.html                # rede interativa (self-contained)
  vis-network.min.js        # biblioteca vis-network (visjs)
```

## Como reproduzir

Requisitos: Python 3.10+ e as libs `requests`, `beautifulsoup4`, `networkx`.

```bash
pip install requests beautifulsoup4 networkx

# 1. raspa a revista e gera reveduc_dados_coautoria.json
python raspar_reveduc.py

# 2. calcula métricas/comunidades e gera site/index.html
python gerar_rede.py --input reveduc_dados_coautoria.json \
    --outdir site --titulo "Revista Eletrônica de Educação (Reveduc/UFSCar)" \
    --rotulo "Reveduc/UFSCar"
```

O gerador (`gerar_rede.py`) é genérico e pode ser reutilizado para qualquer
revista OJS: basta fornecer o JSON com a chave `artigos` (lista de listas de
autores).

## Particularidades da Reveduc

- O arquivo tem **2 páginas** (42 números, 25 por página) — o raspador percorre a
  paginação (`a.next` em `.cmp_pagination`).
- A partir do v. 14 a revista adota **publicação contínua**, então alguns volumes
  concentram muitos artigos (ex.: v. 18 n. 1 (2024) com 253 artigos).
- Os autores aparecem em `<div class="authors">` como texto separado por vírgulas
  (sem `<span class="name">`); a extração usa split de vírgula e um filtro para
  descartar **títulos acadêmicos** cadastrados como autor por engano (ex.:
  "Profa. Dra.").

## Publicação (Cloudflare Pages)

A pasta `site/` é um site estático: qualquer host serve. O deploy usa o Cloudflare
Pages clássico (que fornece o domínio `*.pages.dev`):

```bash
npx wrangler@3 pages deploy site --project-name coautoriareveduc
```

## Licença

Conteúdo da revista sob a licença do periódico (Reveduc/UFSCar). Código deste
repositório disponível para reuso acadêmico; cite o artigo original de Castanha
(2024) e este repositório.
