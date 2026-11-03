#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rede interativa de coautoria (ferramentas avançadas) — genérico
---------------------------------------------------------------
Complementa o método de Castanha (2024) com:
  * detecção de comunidades (Louvain);
  * métricas de análise de redes sociais (grau, intermediação, proximidade,
    autovetor, agrupamento);
  * busca por nome com destaque da sub-rede do autor;
  * tabela dinâmica de top autores por métrica.

Lê os dados já raspados (JSON com chave "artigos": lista de listas de autores)
e gera um HTML único e interativo (self-contained: usa vis-network.min.js do
mesmo diretório).

Uso:
    python gerar_rede.py --input dados.json --outdir site \
        --titulo "Revista X" --rotulo "X"
"""

import argparse
import json
import os
import unicodedata
import warnings
from collections import Counter, defaultdict

import networkx as nx

warnings.filterwarnings("ignore")

ap = argparse.ArgumentParser(description="Gera a rede interativa de coautoria.")
ap.add_argument("--input", required=True, help="JSON com a chave 'artigos'")
ap.add_argument("--outdir", required=True, help="Diretório de saída (index.html)")
ap.add_argument("--titulo", required=True, help="Título completo para o <h1>")
ap.add_argument("--rotulo", required=True, help="Rótulo curto para o <title>")
args = ap.parse_args()

JSON_IN = args.input
HTML_OUT = os.path.join(args.outdir, "index.html")

# ---------------------------------------------------------------------------
# 1. Carrega dados raspados, normaliza os nomes e reconstrói o grafo
# ---------------------------------------------------------------------------
with open(JSON_IN, encoding="utf-8") as f:
    dados = json.load(f)

artigos_brutos = dados["artigos"]


CONN_LOWER = {"de", "da", "do", "das", "dos", "e", "y", "d'", "&"}
SUFIXO_LOWER = {"junior", "filho", "filha", "neto", "neta", "sobrinho", "sobrinha",
                "segundo", "terceiro", "ii", "iii", "iv"}


def _strip_accents(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _has_accent(s):
    return any(ord(c) > 127 for c in s)


def _tokens(nome):
    """Tokens significativos: sem acento, minúsculos, sem conectores.

    Iniciais ("D.", "J.") viram token de uma letra (perdem o ponto) para que
    possam ser expandidas (ex.: "Timothy D." ~ "Timothy Denis"); conectores
    ("de", "da", "e", "d'") são descartados. Isso também evita confundir a
    inicial "D." com o conector "da" ("Maria D. Silva" != "Maria da Silva").
    """
    out = []
    for t in nome.split():
        tn = _strip_accents(t).lower()
        if not tn:
            continue
        if tn.endswith("."):            # inicial: "D." -> "d"
            tn = tn.rstrip(".")
            if tn:
                out.append(tn)
            continue
        if tn in CONN_LOWER:
            continue
        out.append(tn)
    return out


def _edit_distance(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


# variantes conhecidas de prenome (sempre a mesma pessoa)
VARIANTES = {"luis": "luiz", "luís": "luiz"}


def _mesma_pessoa(t1, t2):
    """Heurísticas conservadoras: os dois nomes são a mesma pessoa?

    Evita o falso-positivo clássico de juntar prenomes curtos que diferem por
    uma letra (ex.: "Lara" vs "Sara" são pessoas diferentes). A regra de
    edição mínima só vale para tokens "longos" (>= 6 letras), onde um erro de
    digitação é muito mais provável que uma troca de pessoa.
    """
    a = [VARIANTES.get(x, x) for x in t1]
    b = [VARIANTES.get(x, x) for x in t2]
    if a == b:
        return True
    if len(a) != len(b):
        return False
    # 1) iniciais expandidas: "Timothy D." ~ "Timothy Denis"
    diffs = 0
    for x, y in zip(a, b):
        if x == y:
            continue
        if (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)):
            diffs += 1
            continue
        break
    else:
        if diffs > 0:
            return True
    # 2) um único token divergente, apenas se longo (>= 6 letras)
    pos = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(pos) == 1:
        x, y = a[pos[0]], b[pos[0]]
        if len(x) >= 6 and len(y) >= 6:
            return _edit_distance(x, y) <= 1
    # 3) mesmos tokens, ordem trocada
    return Counter(a) == Counter(b)


def _agrupar_nomes(nomes):
    """Agrupa nomes transitivamente (union-find), comparando por sobrenome."""
    parent = {n: n for n in nomes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    buckets = defaultdict(list)
    for n in nomes:
        tk = _tokens(n)
        if tk:
            buckets[tk[-1]].append(n)
            if tk[-1] in SUFIXO_LOWER and len(tk) > 1:
                buckets[tk[-2]].append(n)

    for items in buckets.values():
        m = len(items)
        for i in range(m):
            t1 = _tokens(items[i])
            for j in range(i + 1, m):
                if _mesma_pessoa(t1, _tokens(items[j])):
                    union(items[i], items[j])

    grupos = defaultdict(list)
    for n in nomes:
        grupos[find(n)].append(n)
    return list(grupos.values())


def normalize_artigos(artigos):
    """Agrupa variantes do MESMO pesquisador e devolve nomes canônicos.

    Devolve (artigos_normalizados, log). O nome canônico é a grafia mais
    frequente (desempate: com acento e mais longa). Nomes genuinamente
    diferentes não são mesclados — só variações de grafia do mesmo nome.
    """
    nomes = sorted({nome for art in artigos for nome in art})
    grupos = _agrupar_nomes(nomes)

    freq = Counter(nome for art in artigos for nome in art)
    canone = {}
    log = []
    for g in grupos:
        if len(g) == 1:
            canone[g[0]] = g[0]
            continue
        c = sorted(g, key=lambda n: (-freq[n], -_has_accent(n), -len(n)))[0]
        for n in g:
            canone[n] = c
        log.append((c, sorted(g)))
    return canone, log


n_bruto = len({nome for art in artigos_brutos for nome in art})
canone, log_normalizacao = normalize_artigos(artigos_brutos)

artigos = []
for art in artigos_brutos:
    norm, seen = [], set()
    for nome in art:
        cn = canone[nome]
        if cn not in seen:
            norm.append(cn)
            seen.add(cn)
    if norm:
        artigos.append(norm)

n_canon = len({nome for art in artigos for nome in art})
if n_bruto != n_canon:
    print(f"Normalização de nomes: {n_bruto} grafias -> {n_canon} autores "
          f"({n_bruto - n_canon} variantes agrupadas).")
    for c, variantes in log_normalizacao:
        outros = " | ".join(v for v in variantes if v != c)
        print(f"  · {c}  <=  {outros}")

G = nx.Graph()
for art in artigos:
    nomes = sorted(set(art))
    for nome in nomes:
        if nome not in G:
            G.add_node(nome)
    for i in range(len(nomes)):
        for j in range(i + 1, len(nomes)):
            a, b = nomes[i], nomes[j]
            G.add_edge(a, b, weight=G[a][b]["weight"] + 1 if G.has_edge(a, b) else 1)

n_nodes = G.number_of_nodes()
n_edges = G.number_of_edges()

# ---------------------------------------------------------------------------
# 2. Métricas de análise de redes sociais
# ---------------------------------------------------------------------------
print("Calculando métricas...")

producao = {n: len([1 for a in artigos if n in a]) for n in G.nodes()}
grau = dict(G.degree())                                   # nº de coautores distintos
central_grau = nx.degree_centrality(G)
central_inter = nx.betweenness_centrality(G)
central_prox = nx.closeness_centrality(G)
central_eigen = nx.eigenvector_centrality(G, max_iter=1000)
clustering = nx.clustering(G)                             # coeficiente de agrupamento

# ---------------------------------------------------------------------------
# 3. Comunidades (Louvain)
# ---------------------------------------------------------------------------
print("Detectando comunidades (Louvain)...")
particao = nx.community.louvain_communities(G, weight="weight", seed=42)
comunidade = {}          # autor -> id da comunidade
com_sizes = []           # (id, tamanho)
for cid, membros in enumerate(sorted(particao, key=len, reverse=True)):
    for m in membros:
        comunidade[m] = cid
    com_sizes.append((cid, len(membros)))

modularidade = nx.community.modularity(G, particao)

# Métricas globais
maior = max(nx.connected_components(G), key=len)
H = G.subgraph(maior)
diametro = nx.diameter(H)
cam_medio = nx.average_shortest_path_length(H)
cluster_medio = nx.average_clustering(G)

print(f"  nós={n_nodes}  arestas={n_edges}  comunidades={len(particao)}")
print(f"  modularidade={modularidade:.3f}  diâmetro(maior comp.)={diametro}")
print(f"  caminho médio={cam_medio:.3f}  agrupamento médio={cluster_medio:.3f}")

# ---------------------------------------------------------------------------
# 4. Prepara dados para o HTML (nós e arestas)
# ---------------------------------------------------------------------------
CONN = {"de", "da", "do", "das", "dos", "e", "d", "d'", "y", "&"}
SUFIXO = {"junior", "júnior", "filho", "filha", "neto", "neta",
          "sobrinho", "sobrinha", "segundo", "terceiro", "ii", "iii", "iv"}


def _norm(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def parse_nome(nome):
    """Separa sobrenome e prenomes de um nome completo.

    'João dos Reis Silva Júnior' -> ('Silva Júnior', ['João', 'Reis'])
    (conectores "de/da/dos" são ignorados; sufixos Júnior/Filho ficam no sobrenome)
    """
    toks = nome.split()
    if len(toks) <= 1:
        return nome, []
    low = [_norm(t) for t in toks]
    n = len(toks)
    j = n - 1
    sobrenome = [toks[j]]
    if low[j] in SUFIXO and j > 0:            # "Silva Júnior"
        j -= 1
        sobrenome.insert(0, toks[j])
    if j > 0 and low[j - 1] in CONN:          # "da Silva"
        sobrenome.insert(0, toks[j - 1])
        j -= 1
    prenomes = [toks[k] for k in range(j) if low[k] not in CONN]
    return " ".join(sobrenome), prenomes


def _iniciais(prenomes):
    return " ".join(p[0].upper() + "." for p in prenomes)


def make_short_labels(nomes):
    """Abrevia mantendo cada nome completo como identidade (sem mesclar).

    Começa pelo formato mais curto — "Sobrenome, Iniciais" — e só desfaz a
    abreviação quando dois pesquisadores DIFERENTES colidem: revela o primeiro
    prenome, depois o segundo, e assim por diante, até os rótulos ficarem
    únicos. Nunca usa números: o último recurso é o nome completo.
    """
    parsed = {nome: parse_nome(nome) for nome in nomes}

    def build(nome, k):
        """k = quantos prenomes ficam por extenso (0 = só iniciais)."""
        sob, pre = parsed[nome]
        if not pre:
            return sob
        if k == 0:
            return f"{sob}, {_iniciais(pre)}"
        ext = " ".join(pre[:k])
        ini = _iniciais(pre[k:])
        return f"{sob}, {ext} {ini}".strip() if ini else f"{sob}, {ext}"

    short = {}
    pendentes = set(nomes)
    k = 0
    while pendentes and k <= len(nomes):
        cand = {nome: build(nome, k) for nome in pendentes}
        cnt = Counter(cand.values())
        resolvidos = [nome for nome in pendentes if cnt[cand[nome]] == 1]
        for nome in resolvidos:
            short[nome] = cand[nome]
            pendentes.discard(nome)
        k += 1
    for nome in pendentes:            # homônimos exatos (não deve ocorrer)
        short[nome] = nome
    return short


nomes_ordenados = sorted(G.nodes())
short_map = make_short_labels(nomes_ordenados)

nodes = []
name_to_id = {}
for i, nome in enumerate(nomes_ordenados):
    name_to_id[nome] = i
    nodes.append({
        "id": i,
        "label": nome,
        "short": short_map[nome],
        "title": f"{nome}<br>Artigos: {producao[nome]} · Coautores: {grau[nome]}",
        "value": producao[nome],
        "community": comunidade[nome],
        "m": {
            "artigos": producao[nome],
            "grau": grau[nome],
            "betweenness": round(central_inter[nome], 6),
            "closeness": round(central_prox[nome], 6),
            "eigenvector": round(central_eigen[nome], 6),
            "clustering": round(clustering[nome], 4),
        },
    })

edges = [
    {"id": i, "from": name_to_id[a], "to": name_to_id[b], "value": w, "width": w}
    for i, (a, b, w) in enumerate(G.edges(data="weight"))
]

comunidades_js = [{"id": cid, "tamanho": t} for cid, t in com_sizes]

payload = {
    "nodes": nodes,
    "edges": edges,
    "communities": comunidades_js,
    "stats": {
        "artigos": len(artigos),
        "autores": n_nodes,
        "arestas": n_edges,
        "comunidades": len(particao),
        "modularidade": round(modularidade, 3),
        "densidade": round(nx.density(G), 5),
        "componentes": nx.number_connected_components(G),
        "diametro": diametro,
        "cam_medio": round(cam_medio, 3),
        "cluster_medio": round(cluster_medio, 3),
    },
}

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rede de coautoria — __ROTULO__</title>
<script type="text/javascript" src="vis-network.min.js"></script>
<style>
  :root { --border:#e2e2e2; --accent:#0d47a1; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color:#222; }
  header { padding:14px 20px; border-bottom:1px solid var(--border); background:#fafafa; }
  header h1 { margin:0 0 4px; font-size:1.15rem; }
  header p { margin:0; color:#666; font-size:.85rem; }
  #layout { display:flex; height:calc(100vh - 78px); }
  #main { flex:1; position:relative; }
  #network { width:100%; height:100%; }
  aside { width:340px; border-left:1px solid var(--border); display:flex; flex-direction:column; overflow:hidden; background:#fff; }
  .panel { padding:12px 16px; border-bottom:1px solid var(--border); }
  .panel h2 { margin:0 0 8px; font-size:.85rem; text-transform:uppercase; letter-spacing:.04em; color:#555; }
  .row { display:flex; gap:8px; margin-bottom:8px; }
  .row label { font-size:.78rem; color:#555; display:block; margin-bottom:2px; }
  .row select, .row input { width:100%; padding:6px 8px; font-size:.85rem; border:1px solid #ccc; border-radius:6px; }
  button { padding:7px 12px; font-size:.85rem; border:1px solid #ccc; border-radius:6px; background:#fff; cursor:pointer; }
  button:hover { background:#f0f0f0; }
  #tablewrap { flex:1; overflow-y:auto; }
  table { width:100%; border-collapse:collapse; font-size:.82rem; }
  th, td { text-align:left; padding:6px 12px; border-bottom:1px solid #f0f0f0; }
  th { position:sticky; top:0; background:#fff; color:#555; font-size:.75rem; text-transform:uppercase; }
  tbody tr { cursor:pointer; }
  tbody tr:hover { background:#eef5ff; }
  .num { text-align:right; font-variant-numeric:tabular-nums; color:#444; }
  #hint { position:absolute; top:10px; left:10px; background:rgba(255,255,255,.92); border:1px solid var(--border); border-radius:8px; padding:8px 12px; font-size:.78rem; color:#444; max-width:320px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
</style></head><body>
<header>
  <h1>Rede de coautoria — __TITULO__</h1>
  <p id="statsline"></p>
</header>
<div id="layout">
  <div id="main">
    <div id="network"></div>
    <div id="hint">Digite um nome para buscar, ou clique em um autor na tabela ao lado para destacar sua sub-rede.</div>
  </div>
  <aside>
    <div class="panel">
      <h2>Buscar autor</h2>
      <input id="search" list="authors" placeholder="Digite o nome..." autocomplete="off">
      <datalist id="authors"></datalist>
      <div class="row" style="margin-top:8px; align-items:center;">
        <label style="margin:0; display:flex; align-items:center; gap:6px; cursor:pointer; font-size:.8rem; white-space:nowrap;">
          <input type="checkbox" id="abrev"> Abreviar nomes
        </label>
        <button id="reset">Redefinir</button>
      </div>
    </div>
    <div class="panel">
      <h2>Colorir por</h2>
      <div class="row">
        <select id="metric">
          <option value="artigos">Nº de artigos (produção)</option>
          <option value="grau">Grau (nº de coautores)</option>
          <option value="betweenness">Intermediação (betweenness)</option>
          <option value="closeness">Proximidade (closeness)</option>
          <option value="eigenvector">Autovetor (eigenvector)</option>
          <option value="clustering">Agrupamento (clustering)</option>
          <option value="community">Comunidade (Louvain)</option>
        </select>
      </div>
    </div>
    <div class="panel">
      <h2>Destacar comunidade</h2>
      <div class="row">
        <select id="community"><option value="">— todas —</option></select>
      </div>
    </div>
    <div class="panel" style="border-bottom:none;">
      <h2>Top 20 por métrica</h2>
    </div>
    <div id="tablewrap"><table><thead><tr><th>Autor</th><th class="num">Valor</th></tr></thead><tbody id="tablebody"></tbody></table></div>
  </aside>
</div>
<script>
const DATA = __DATA__;
const PALETTE = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf","#aec7e8","#ffbb78","#98df8a","#ff9896","#c5b0d5","#c49c94","#f7b6d2","#dbdb8d","#9edae5","#ad494a"];

const nodesArr = DATA.nodes;
const edgesArr = DATA.edges;
const nodes = new vis.DataSet(nodesArr);
const edges = new vis.DataSet(edgesArr);
const container = document.getElementById('network');
const network = new vis.Network(container, {nodes, edges}, {
  nodes: { shape:'dot', scaling:{min:6,max:40}, font:{size:13, color:'#333'} },
  edges: { color:{color:'#999', highlight:'#d62728'}, scaling:{min:1,max:6}, smooth:{type:'continuous'} },
  physics: { barnesHut:{gravitationalConstant:-6000, springLength:150, springConstant:0.04, damping:0.25} },
  interaction: { hover:true, tooltipDelay:80, navigationButtons:true, keyboard:true }
});

// ----- helpers de cor -----
function lerp(a,b,t){ return a+(b-a)*t; }
function hexToRgb(h){ h=h.replace('#',''); return [parseInt(h.substr(0,2),16),parseInt(h.substr(2,2),16),parseInt(h.substr(4,2),16)]; }
function rgbToHex(c){ return '#'+c.map(v=>Math.round(v).toString(16).padStart(2,'0')).join(''); }
function valueToColor(v, min, max){
  const lo=[227,242,253], hi=[13,71,161]; // azul claro -> azul escuro
  if (max===min) return rgbToHex(lo);
  const t=(v-min)/(max-min);
  return rgbToHex([lerp(lo[0],hi[0],t), lerp(lo[1],hi[1],t), lerp(lo[2],hi[2],t)]);
}
let nodeColors = {}; // id -> cor base atual
function colorByCommunity(){
  const upd = nodesArr.map(n => ({id:n.id, color:PALETTE[n.community % PALETTE.length]}));
  upd.forEach(o => nodeColors[o.id] = o.color);
  nodes.update(upd);
}
function colorByMetric(field){
  const vals = nodesArr.map(n => n.m[field]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const upd = nodesArr.map(n => ({id:n.id, color:valueToColor(n.m[field], min, max)}));
  upd.forEach(o => nodeColors[o.id] = o.color);
  nodes.update(upd);
}
function resetColors(){
  const field = document.getElementById('metric').value;
  if (field === 'community') colorByCommunity(); else colorByMetric(field);
  resetHighlight();
}

// ----- destaque de sub-rede -----
function resetHighlight(){
  nodes.update(nodesArr.map(n => ({id:n.id, color:nodeColors[n.id], borderWidth:0, borderColor:'rgba(0,0,0,0)', font:{color:'#333'}})));
  edges.update(edgesArr.map(e => ({id:e.id, color:{color:'#999'}, width:e.width, dashes:false})));
  document.getElementById('hint').innerHTML = 'Digite um nome para buscar, ou clique em um autor na tabela ao lado para destacar sua sub-rede.';
}
function highlightAuthor(id){
  const neigh = network.getConnectedNodes(id, 'both');
  const highlightSet = new Set([id, ...neigh]);
  const edgeSel = new Set();
  edgesArr.forEach((e,i)=>{ if(highlightSet.has(e.from) && highlightSet.has(e.to)) edgeSel.add(i); });
  nodes.update(nodesArr.map(n => {
    if (n.id === id) return {id:n.id, color:'#d62728', borderWidth:3, borderColor:'#7f0c16', font:{color:'#fff'}};
    if (highlightSet.has(n.id)) return {id:n.id, color:nodeColors[n.id], borderWidth:2, borderColor:'#d62728', font:{color:'#000'}};
    return {id:n.id, color:'#ececec', borderWidth:0, font:{color:'#bbb'}};
  }));
  edges.update(edgesArr.map((e,i) => {
    if (edgeSel.has(i)) return {id:e.id, color:{color:'#d62728'}, width:Math.max(1.5, e.width*2)};
    return {id:e.id, color:{color:'#efefef'}, width:0.5};
  }));
  network.focus(id, {scale:1.1, animation:{duration:500, easingFunction:'easeInOutQuad'}});
  const n = nodesArr[id];
  document.getElementById('hint').innerHTML = '<b>'+n.label+'</b><br>Artigos: '+n.m.artigos+' · Coautores: '+n.m.grau+' · Comunidade '+n.community;
}

// ----- rótulos (completo / abreviado) -----
let shortMode = false;
function labelOf(n){ return shortMode ? n.short : n.label; }
function applyLabels(){
  nodes.update(nodesArr.map(n => ({id:n.id, label:labelOf(n)})));
  rebuildDatalist();
  renderTable();
}

// ----- busca por nome -----
const datalist = document.getElementById('authors');
function rebuildDatalist(){
  datalist.innerHTML = '';
  nodesArr.forEach(n => { const o=document.createElement('option'); o.value=labelOf(n); datalist.appendChild(o); });
}
const byName = {};
nodesArr.forEach(n => { byName[n.label.toLowerCase()] = n.id; byName[n.short.toLowerCase()] = n.id; });
const search = document.getElementById('search');
function doSearch(){
  const q = search.value.trim().toLowerCase();
  if (!q){ resetHighlight(); return; }
  const id = byName[q];
  if (id !== undefined){ highlightAuthor(id); return; }
  const found = nodesArr.find(n => n.label.toLowerCase().includes(q) || n.short.toLowerCase().includes(q));
  if (found) highlightAuthor(found.id);
}
search.addEventListener('input', doSearch);
search.addEventListener('keydown', e => { if (e.key==='Enter') doSearch(); });
document.getElementById('abrev').addEventListener('change', e => { shortMode = e.target.checked; applyLabels(); });

// ----- colorir por métrica -----
const metricSel = document.getElementById('metric');
metricSel.addEventListener('change', resetColors);

// ----- destacar comunidade -----
const comSel = document.getElementById('community');
DATA.communities.forEach(c => {
  const o=document.createElement('option'); o.value=c.id; o.textContent='Comunidade '+c.id+' ('+c.tamanho+' autores)';
  comSel.appendChild(o);
});
comSel.addEventListener('change', () => {
  const v = comSel.value;
  if (v===''){ resetColors(); return; }
  const cid = +v;
  const inCom = new Set(nodesArr.filter(n=>n.community===cid).map(n=>n.id));
  const edgeSel = new Set();
  edgesArr.forEach((e,i)=>{ if(inCom.has(e.from) && inCom.has(e.to)) edgeSel.add(i); });
  nodes.update(nodesArr.map(n => inCom.has(n.id) ? {id:n.id, color:nodeColors[n.id], borderWidth:2, borderColor:'#111', font:{color:'#000'}} : {id:n.id, color:'#ececec', borderWidth:0, font:{color:'#bbb'}}));
  edges.update(edgesArr.map((e,i)=> edgeSel.has(i) ? {id:e.id, color:{color:'#111'}, width:Math.max(1.5, e.width*2)} : {id:e.id, color:{color:'#efefef'}, width:0.5}));
  network.fit({nodes:[...inCom], animation:{duration:500}});
  document.getElementById('hint').innerHTML = 'Comunidade '+cid+' ('+inCom.size+' autores) em destaque.';
});

// ----- tabela top 20 -----
const tbody = document.getElementById('tablebody');
function renderTable(){
  const field = metricSel.value;
  const list = field==='community' ? [] : nodesArr.slice().sort((a,b)=> b.m[field]-a.m[field]).slice(0,20);
  tbody.innerHTML = '';
  if (field==='community'){
    DATA.communities.slice(0,20).forEach(c => {
      const tr=document.createElement('tr');
      tr.innerHTML = '<td>Comunidade '+c.id+'</td><td class="num">'+c.tamanho+'</td>';
      tr.onclick = ()=>{ comSel.value = c.id; comSel.dispatchEvent(new Event('change')); };
      tbody.appendChild(tr);
    });
    return;
  }
  list.forEach(n => {
    const tr=document.createElement('tr');
    tr.innerHTML = '<td>'+labelOf(n)+'</td><td class="num">'+n.m[field]+'</td>';
    tr.onclick = ()=>highlightAuthor(n.id);
    tbody.appendChild(tr);
  });
}
metricSel.addEventListener('change', renderTable);

// ----- stats -----
const s = DATA.stats;
document.getElementById('statsline').textContent =
  s.artigos+' artigos · '+s.autores+' autores · '+s.arestas+' laços · '+s.comunidades+' comunidades (Louvain) · modularidade '+s.modularidade+' · diâmetro '+s.diametro+' · caminho médio '+s.cam_medio+' · agrupamento '+s.cluster_medio;

// ----- inicial -----
colorByMetric('artigos');
rebuildDatalist();
renderTable();
network.on('click', p => { if (p.nodes.length) highlightAuthor(p.nodes[0]); });
</script></body></html>
"""


print(f"Escrevendo {HTML_OUT} ...")
os.makedirs(os.path.dirname(HTML_OUT), exist_ok=True)
html = (HTML_TEMPLATE
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        .replace("__TITULO__", args.titulo)
        .replace("__ROTULO__", args.rotulo))
with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)

print("Concluído.")
