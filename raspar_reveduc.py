#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspa a Revista Eletrônica de Educação (Reveduc/UFSCar) e extrai os autores
de cada artigo (método de Castanha, 2024 — classe CSS ".authors" do OJS).

Adaptações em relação ao método original:
  * o arquivo tem 2 páginas (42 números, 25 por página) — percorre a paginação;
  * os autores aparecem em <div class="authors"> como texto separado por
    vírgulas (sem <span class="name">), então a extração é por split de vírgula;
  * filtro de "títulos acadêmicos" (ex.: "Profa. Dra.") que aparecem como nome
    de autor por erro de cadastro no OJS.

Saída: JSON {"artigos": [[autor, ...], ...]} consumido por gerar_rede.py.
"""

import json
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.reveduc.ufscar.br/index.php/reveduc"
ARCHIVE = BASE + "/issue/archive"
OUT = "reveduc_dados_coautoria.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Títulos acadêmicos que podem aparecer como "autor" (erro de cadastro no OJS)
TITLE_RE = re.compile(
    r"^(prof\.?\s*ª?\.?|professor\.?a?|doutor\.?a?|dr\.?\s*ª?\.?|"
    r"mestre\.?|mestra\.?|me\.?|ma\.?|esp\.?|msc\.?|phd\.?|"
    r"m\.?\s*sc\.?|d\.?\s*sc\.?)"
    r"(\s+(dr\.?|dra\.?|sc\.?))?\.?$",
    re.IGNORECASE,
)

session = requests.Session()
session.headers.update(HEADERS)


def get(url, retries=3):
    for attempt in range(retries):
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            return r
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Falha em {url} (status {r.status_code})")


def collect_issue_links():
    """Percorre as páginas do arquivo e junta os links dos números."""
    links = []
    url = ARCHIVE
    while url:
        html = BeautifulSoup(get(url).text, "html.parser")
        for a in html.select("a.title"):
            href = a.get("href", "")
            if "/issue/view/" in href:
                links.append(urljoin(BASE, href))
        nxt = html.select_one(".cmp_pagination a.next")
        url = nxt.get("href") if nxt else None
        if url:
            url = urljoin(BASE, url)
    # ordena e deduplica
    links = sorted(set(links), key=lambda u: int(re.search(r"/view/(\d+)", u).group(1)))
    return links


def limpar_nomes(texto):
    """Divide o texto de '.authors' em nomes e remove títulos acadêmicos."""
    nomes = []
    for parte in texto.split(","):
        nome = re.sub(r"\s+", " ", parte.replace("\xa0", " ")).strip()
        if not nome:
            continue
        if TITLE_RE.match(nome):
            continue  # descarta "Profa. Dra.", "Dr.", etc.
        nomes.append(nome)
    # remove duplicados preservando a ordem
    return list(dict.fromkeys(nomes))


def main():
    print("Coletando números (páginas do arquivo)...")
    issues = collect_issue_links()
    print(f"  -> {len(issues)} números encontrados.")

    artigos = []   # lista de listas de autores
    por_issue = {}

    for n, link in enumerate(issues, 1):
        issue_id = re.search(r"/view/(\d+)", link).group(1)
        html = BeautifulSoup(get(link).text, "html.parser")
        count = 0
        for bloco in html.select("div.authors"):
            nomes = limpar_nomes(bloco.get_text(" ", strip=True))
            if nomes:
                artigos.append(nomes)
                count += 1
        por_issue[issue_id] = count
        print(f"  [{n:2d}/{len(issues)}] número {issue_id}: {count} artigos")
        time.sleep(0.3)

    print(f"\nTotal de artigos: {len(artigos)}")
    autores = set(a for art in artigos for a in art)
    print(f"Total de autores distintos: {len(autores)}")

    dados = {
        "revista": "Revista Eletrônica de Educação (Reveduc/UFSCar)",
        "artigos": artigos,
        "artigos_por_issue": por_issue,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"Salvo em {OUT}")

    # checagem de resíduos de títulos
    residuos = [a for a in autores if TITLE_RE.match(a)]
    if residuos:
        print(f"AVISO: {len(residuos)} possíveis títulos restantes:", residuos[:10])


if __name__ == "__main__":
    sys.exit(main())
