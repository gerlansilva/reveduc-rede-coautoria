#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspa as afiliações (instituições) dos autores da Reveduc/UFSCar.

Fonte: meta tags `citation_author` e `citation_author_institution` da página de
cada artigo (OJS), que vêm em pares e em ordem. Extrai nome -> instituição.

Saída: reveduc_afiliacoes.json = {"afiliacoes": {nome: instituicao}} (a mais
frequente por autor). Consumido por gerar_rede.py.
"""

import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.reveduc.ufscar.br/index.php/reveduc"
ARCHIVE = BASE + "/issue/archive"
OUT = "reveduc_afiliacoes.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

LINK_RE = re.compile(r"/article/view/(\d+)$")


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def collect_article_links():
    s = _session()
    links = []
    url = ARCHIVE
    while url:
        html = BeautifulSoup(s.get(url, timeout=30).text, "html.parser")
        for a in html.select("a.title"):
            href = a.get("href", "")
            if "/issue/view/" in href:
                links.append(urljoin(BASE, href))
        nxt = html.select_one(".cmp_pagination a.next")
        url = urljoin(BASE, nxt["href"]) if nxt else None
    issues = sorted(set(links), key=lambda u: int(re.search(r"/view/(\d+)", u).group(1)))

    arts = []
    for iss in issues:
        html = BeautifulSoup(s.get(iss, timeout=30).text, "html.parser")
        for a in html.select("a"):
            href = a.get("href", "")
            if LINK_RE.search(href):
                arts.append(urljoin(BASE, href))
        time.sleep(0.2)
    return sorted(set(arts))


def scrape_article(art_url):
    """Retorna lista de pares (nome, instituicao) de um artigo, ou [] em erro."""
    s = _session()
    try:
        html = BeautifulSoup(s.get(art_url, timeout=30).text, "html.parser")
    except Exception:
        return []
    autores = []
    insts = []
    for m in html.find_all("meta"):
        name = m.get("name", "")
        if name == "citation_author":
            autores.append(m.get("content", "").strip())
        elif name == "citation_author_institution":
            insts.append(m.get("content", "").strip())
    # pares em ordem (nem todo autor tem instituição)
    pares = []
    for i, nome in enumerate(autores):
        inst = insts[i] if i < len(insts) else ""
        if nome:
            pares.append((nome, inst))
    return pares


def main():
    print("Coletando links de artigos...")
    arts = collect_article_links()
    print(f"  -> {len(arts)} artigos.")

    por_autor = defaultdict(Counter)
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut = {ex.submit(scrape_article, a): a for a in arts}
        done = 0
        for f in as_completed(fut):
            done += 1
            for nome, inst in f.result():
                if inst:
                    por_autor[nome][inst] += 1
            if done % 200 == 0:
                print(f"  ... {done}/{len(arts)} artigos processados")

    afiliacoes = {nome: c.most_common(1)[0][0] for nome, c in por_autor.items()}
    com_aff = sum(1 for v in afiliacoes.values() if v)
    print(f"\nAutores distintos: {len(afiliacoes)} | com afiliação: {com_aff}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"afiliacoes": afiliacoes}, f, ensure_ascii=False, indent=2)
    print(f"Salvo em {OUT}")


if __name__ == "__main__":
    sys.exit(main())
