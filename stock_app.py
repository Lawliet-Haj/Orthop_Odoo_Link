from flask import Flask, render_template_string, request, jsonify
import os
import sys
import json
import datetime as dt
import requests
import xml.etree.ElementTree as ET
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

# Charge le fichier .env s'il existe (python-dotenv optionnel ; sinon on se base
# uniquement sur les variables d'environnement du système).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

urllib3.disable_warnings()

app = Flask(__name__)

# ─── Configuration Orthop (via variables d'environnement / fichier .env) ──────
URL             = os.environ.get("ORTHOP_URL", "")
ORTHOP_ORIGINE  = os.environ.get("ORTHOP_ORIGINE", "")
ORTHOP_USERNAME = os.environ.get("ORTHOP_USERNAME", "")
ORTHOP_PASSWORD = os.environ.get("ORTHOP_PASSWORD", "")

if not (URL and ORTHOP_USERNAME and ORTHOP_PASSWORD):
    print("⚠️  Identifiants Orthop manquants — créez un fichier .env "
          "(voir .env.example).")

NS_ART = 'http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles'

AUTH = f"""
<par:Authentification i:nil="true"/>
<par:Origine>{ORTHOP_ORIGINE}</par:Origine>
<par:Password>{ORTHOP_PASSWORD}</par:Password>
<par:Username>{ORTHOP_USERNAME}</par:Username>
"""

# ─── Cache ───────────────────────────────────────────────────────
_cache = {'lieux': None, 'articles': None}

# ─── HTML ────────────────────────────────────────────────────────
HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Stock TLE - Par lieu de stockage</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #f0f2f5; }
    .header { background: #1a3c6e; color: white; padding: 20px 30px; }
    .header h1 { font-size: 22px; }
    .header p { font-size: 13px; opacity: 0.7; margin-top: 4px; }
    .container { padding: 30px; max-width: 1400px; margin: auto; }
    .card { background: white; border-radius: 8px; padding: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; }
    .form-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
    label { font-size: 13px; font-weight: bold; color: #444; display: block; margin-bottom: 6px; }
    select, input { padding: 10px 14px; border: 1px solid #ddd;
                    border-radius: 6px; font-size: 14px; min-width: 220px; }
    button { padding: 10px 24px; background: #1a3c6e; color: white;
             border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
    button:hover { background: #2a5298; }
    button:disabled { background: #aaa; cursor: not-allowed; }
    .stats { display: flex; gap: 16px; margin-top: 16px; flex-wrap: wrap; }
    .stat { background: #f8f9fa; border-left: 4px solid #1a3c6e;
            padding: 12px 16px; border-radius: 4px; flex: 1; min-width: 150px; }
    .stat-val { font-size: 24px; font-weight: bold; color: #1a3c6e; }
    .stat-label { font-size: 12px; color: #888; margin-top: 2px; }
    .spinner { display: none; text-align: center; padding: 40px; color: #888; font-size: 16px; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }
    th { background: #1a3c6e; color: white; padding: 10px 14px;
         text-align: left; cursor: pointer; }
    th:hover { background: #2a5298; }
    td { padding: 9px 14px; border-bottom: 1px solid #f0f0f0; }
    tr:hover td { background: #f5f8ff; }
    .qte { font-weight: bold; color: #1a3c6e; text-align: right; }
    .qte-zero { color: #aaa; text-align: right; }
    .ref { font-family: monospace; color: #555; }
    .search-bar { margin-bottom: 12px; }
    .search-bar input { width: 100%; padding: 8px 12px; }
    .export-btn { padding: 8px 18px; background: #28a745; color: white;
                  border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
    .export-btn:hover { background: #218838; }
    .badge { display: inline-block; background: #e3f0ff; color: #1a3c6e;
             border-radius: 12px; padding: 2px 10px; font-size: 12px; margin-left: 8px; }
    .table-wrap { max-height: 600px; overflow-y: auto; }
  </style>
</head>
<body>

<div class="header">
  <h1>📦 Stock Tire-Lait Express</h1>
  <p>Consultation du stock en temps réel par lieu de stockage</p>
</div>

<div class="container">
  <div class="card">
    <div class="form-row">
      <div>
        <label>Lieu de stockage</label>
        <select id="lieu">
          <option value="">-- Chargement... --</option>
        </select>
      </div>
      <div>
        <label>Filtre stock</label>
        <select id="filtre">
          <option value="positif">Stock > 0 seulement</option>
          <option value="tous">Tous les articles</option>
        </select>
      </div>
      <div>
        <label>&nbsp;</label>
        <button onclick="chargerStock()" id="btnCharger">🔍 Charger le stock</button>
      </div>
    </div>

    <div class="stats" id="stats" style="display:none">
      <div class="stat">
        <div class="stat-val" id="nb-articles">0</div>
        <div class="stat-label">Articles</div>
      </div>
      <div class="stat">
        <div class="stat-val" id="total-stock">0</div>
        <div class="stat-label">Stock total</div>
      </div>
      <div class="stat">
        <div class="stat-val" id="lieu-nom">-</div>
        <div class="stat-label">Lieu sélectionné</div>
      </div>
    </div>
  </div>

  <div class="spinner" id="spinner">⏳ Chargement en cours...</div>

  <div class="card" id="tableau-card" style="display:none">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <strong>Résultats <span class="badge" id="count-badge">0</span></strong>
      <button class="export-btn" onclick="exportCSV()">⬇ Exporter CSV</button>
    </div>
    <div class="search-bar" style="margin-top:12px;">
      <input type="text" id="search"
             placeholder="🔎 Rechercher un article..."
             oninput="filtrerTableau()">
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th onclick="sortTable('reference')">Référence ↕</th>
            <th onclick="sortTable('libelle')">Article ↕</th>
            <th onclick="sortTable('code')">Code Article ↕</th>
            <th onclick="sortTable('code_lieu')">Code Lieu ↕</th>
            <th onclick="sortTable('nom_partenaire')">Partenaire ↕</th>
            <th onclick="sortTable('quantite')" style="text-align:right">Stock ↕</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
let allData = [];
let sortCol = '';
let sortAsc = true;

// Charger les lieux au démarrage
fetch('/lieux')
  .then(r => r.json())
  .then(lieux => {
    const sel = document.getElementById('lieu');
    sel.innerHTML = '<option value="">-- Choisir un lieu --</option>';
    lieux.forEach(item => {
      if (!item[0] || !item[0].trim()) return;
      const opt = document.createElement('option');
      opt.value = item[0];
      opt.textContent = item[1] ? item[0] + ' — ' + item[1] : item[0];
      sel.appendChild(opt);
    });
  })
  .catch(err => {
    console.error('Erreur:', err);
    document.getElementById('lieu').innerHTML =
      '<option value="">Erreur de chargement</option>';
  });

function chargerStock() {
  const lieu = document.getElementById('lieu').value;
  if (!lieu) { alert('Choisissez un lieu de stockage'); return; }

  document.getElementById('spinner').style.display = 'block';
  document.getElementById('tableau-card').style.display = 'none';
  document.getElementById('stats').style.display = 'none';
  document.getElementById('btnCharger').disabled = true;

  const filtre = document.getElementById('filtre').value;
  fetch('/stock?lieu=' + encodeURIComponent(lieu) + '&filtre=' + filtre)
    .then(r => r.json())
    .then(data => {
      allData = data;
      afficherTableau(data);
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('tableau-card').style.display = 'block';
      document.getElementById('stats').style.display = 'flex';
      document.getElementById('nb-articles').textContent = data.length;
      document.getElementById('total-stock').textContent =
        data.reduce((s, r) => s + r.quantite, 0);
      document.getElementById('lieu-nom').textContent = lieu;
      document.getElementById('btnCharger').disabled = false;
    })
    .catch(err => {
      console.error(err);
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('btnCharger').disabled = false;
      alert('Erreur lors du chargement');
    });
}

function afficherTableau(data) {
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  document.getElementById('count-badge').textContent = data.length;

  if (data.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align:center;padding:20px;color:#888">' +
      'Aucun résultat</td></tr>';
    return;
  }

  data.forEach(r => {
    const tr = document.createElement('tr');
    const qteClass = r.quantite > 0 ? 'qte' : 'qte-zero';
    tr.innerHTML =
      '<td class="ref">' + (r.reference      || '') + '</td>' +
      '<td>'             + (r.libelle         || '') + '</td>' +
      '<td>'             + (r.code            || '') + '</td>' +
      '<td>'             + (r.code_lieu       || '') + '</td>' +
      '<td>'             + (r.nom_partenaire  || '') + '</td>' +
      '<td class="' + qteClass + '">' + r.quantite + '</td>';
    tbody.appendChild(tr);
  });
}

function filtrerTableau() {
  const q = document.getElementById('search').value.toLowerCase();
  const filtered = allData.filter(r =>
    (r.libelle        || '').toLowerCase().includes(q) ||
    (r.reference      || '').toLowerCase().includes(q) ||
    (r.nom_partenaire || '').toLowerCase().includes(q) ||
    (r.code_lieu      || '').toLowerCase().includes(q)
  );
  afficherTableau(filtered);
}

function sortTable(col) {
  if (sortCol === col) sortAsc = !sortAsc;
  else { sortCol = col; sortAsc = true; }
  const sorted = [...allData].sort((a, b) => {
    const va = a[col], vb = b[col];
    if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
    return sortAsc
      ? String(va || '').localeCompare(String(vb || ''))
      : String(vb || '').localeCompare(String(va || ''));
  });
  afficherTableau(sorted);
}

function exportCSV() {
  const lieu = document.getElementById('lieu').value;
  const rows = [['Ref_Produit','Libelle','CodeArticle',
                 'Code_Lieu','Nom_Partenaire','Stock_reel']];
  allData.forEach(r => rows.push([
    r.reference, r.libelle, r.code,
    r.code_lieu, r.nom_partenaire, r.quantite
  ]));
  const csv = rows.map(r => r.join(';')).join('\\n');
  const blob = new Blob(['\\uFEFF' + csv], {type: 'text/csv;charset=utf-8;'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'stock_' + lieu + '_' +
               new Date().toISOString().slice(0,10) + '.csv';
  a.click();
}
</script>
</body>
</html>
"""

# ─── SOAP ────────────────────────────────────────────────────────
def post_soap(action, body):
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"http://tempuri.org/ISWOM_Articles/{action}"'
    }
    resp = requests.post(URL, data=body.encode("utf-8"),
                         headers=headers, verify=False, timeout=30)
    return ET.fromstring(resp.text)

# ─── LIEUX ───────────────────────────────────────────────────────
def get_lieux():
    if _cache['lieux']:
        return _cache['lieux']
    body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/>
      <soapenv:Body>
        <tem:GetLieuxStock>
          <tem:paramGetLieuxStock>{AUTH}</tem:paramGetLieuxStock>
        </tem:GetLieuxStock>
      </soapenv:Body>
    </soapenv:Envelope>"""
    root = post_soap("GetLieuxStock", body)
    lieux = {}
    for l in root.iter(f'{{{NS_ART}}}LieuStockage'):
        code = l.findtext(f'{{{NS_ART}}}Code') or ''
        lib  = l.findtext(f'{{{NS_ART}}}Libelle') or ''
        if code.strip():
            lieux[code] = lib
    _cache['lieux'] = lieux
    return lieux

# ─── ARTICLES ────────────────────────────────────────────────────
def get_articles():
    if _cache['articles']:
        return _cache['articles']
    body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:art="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/>
      <soapenv:Body>
        <tem:FindArticle>
          <tem:paramFindArticle>
            {AUTH}
            <mob:ControleMax>false</mob:ControleMax>
            <mob:Recherche>
              <art:Etat>0</art:Etat>
            </mob:Recherche>
          </tem:paramFindArticle>
        </tem:FindArticle>
      </soapenv:Body>
    </soapenv:Envelope>"""
    root = post_soap("FindArticle", body)
    articles = []
    for art in root.iter(f'{{{NS_ART}}}Article'):
        code = art.findtext(f'{{{NS_ART}}}Code') or ''
        lib  = art.findtext(f'{{{NS_ART}}}Libelle') or ''
        ref  = art.findtext(f'{{{NS_ART}}}ManufacturerRef') or ''
        decl = art.findtext(f'{{{NS_ART}}}CodeDeclinaisonDefaut')
        if not ref.strip():
            ref = f"ART-{code}"
        if code and decl:
            articles.append({
                'code':     code,
                'libelle':  lib,
                'reference': ref,
                'decl':     decl
            })
    _cache['articles'] = articles
    return articles

# ─── STOCK D'UNE DÉCLINAISON (tous lieux) ────────────────────────
def _stock_declinaison_root(decl):
    """Appelle FindStockDeclinaison pour une déclinaison ; renvoie le XML parsé.
    La réponse contient le stock de TOUS les lieux pour cette déclinaison."""
    body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:art="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/>
      <soapenv:Body>
        <tem:FindStockDeclinaison>
          <tem:paramFindStockDeclinaison>
            {AUTH}
            <mob:Recherche>
              <art:CodeDeclinaison>{decl}</art:CodeDeclinaison>
            </mob:Recherche>
          </tem:paramFindStockDeclinaison>
        </tem:FindStockDeclinaison>
      </soapenv:Body>
    </soapenv:Envelope>"""
    return post_soap("FindStockDeclinaison", body)


# ─── STOCK UN ARTICLE (pour un lieu donné) ───────────────────────
def get_stock_article(art, lieu, filtre, lieux_libelles):
    root = _stock_declinaison_root(art['decl'])
    for sd in root.iter(f'{{{NS_ART}}}StockDeclinaison'):
        l   = sd.findtext(f'{{{NS_ART}}}CodeLieuStockage') or ''
        qte = float(sd.findtext(f'{{{NS_ART}}}QteUtilPourDecl') or '0')
        if l == lieu:
            if filtre == 'tous' or qte > 0:
                return {
                    'reference':      art['reference'],
                    'libelle':        art['libelle'],
                    'code':           art['code'],
                    'code_lieu':      l,
                    'nom_partenaire': lieux_libelles.get(l, l),
                    'quantite':       int(qte)
                }
    # filtre=tous → retourner qte=0
    if filtre == 'tous':
        return {
            'reference':      art['reference'],
            'libelle':        art['libelle'],
            'code':           art['code'],
            'code_lieu':      lieu,
            'nom_partenaire': lieux_libelles.get(lieu, lieu),
            'quantite':       0
        }
    return None

# ─── TOUT LE STOCK (tous lieux, un appel par article) ────────────
def get_all_stock(filtre='positif'):
    """Récupère le stock de TOUS les lieux en un seul passage.

    FindStockDeclinaison renvoie déjà tous les lieux pour une déclinaison : on
    n'appelle donc Orthop qu'UNE fois par article (≈ N appels, et non N×lieux).
    Renvoie {rows, articles_total, articles_failed} — articles_failed permet de
    savoir si le snapshot est complet (cf. synchro autoritaire)."""
    articles       = get_articles()
    lieux_libelles = get_lieux()
    rows = []
    failed = 0

    def traiter(art):
        out = []
        root = _stock_declinaison_root(art['decl'])
        for sd in root.iter(f'{{{NS_ART}}}StockDeclinaison'):
            l = sd.findtext(f'{{{NS_ART}}}CodeLieuStockage') or ''
            if not l.strip():
                continue
            qte = float(sd.findtext(f'{{{NS_ART}}}QteUtilPourDecl') or '0')
            if filtre == 'positif' and qte <= 0:
                continue
            out.append({
                'reference':      art['reference'],
                'libelle':        art['libelle'],
                'code':           art['code'],
                'code_lieu':      l,
                'nom_partenaire': lieux_libelles.get(l, l),
                'quantite':       int(qte),
            })
        return out

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(traiter, art) for art in articles]
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                failed += 1

    return {'rows': rows, 'articles_total': len(articles), 'articles_failed': failed}


# ─── PARC (machines sérialisées : numéros de parc) ───────────────
# États Orthop exclus de la synchro (machines définitivement sorties).
PARC_ETATS_EXCLUS = {'2', '3', '7', '9'}  # Vendu, Détruit, Retour Fournisseur, Perdu


def get_all_parc():
    """Récupère le parc « vivant » (machines sérialisées) via FindParc.

    Un seul appel renvoie tout le parc. On exclut les états définitivement
    sortis (PARC_ETATS_EXCLUS). Chaque machine : Numero, CodeArticle, lieu,
    état, disponible, réservé — enrichie du libellé/référence article et du nom
    du lieu. Renvoie {rows, total, kept}."""
    articles = get_articles()
    lieux_libelles = get_lieux()
    # Map CodeArticle (str) → (libellé, référence) pour enrichir le parc
    art_map = {a['code']: (a['libelle'], a['reference']) for a in articles}

    body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:art="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/>
      <soapenv:Body>
        <tem:FindParc>
          <tem:paramFindParc>
            {AUTH}
            <mob:ControleMax>false</mob:ControleMax>
            <mob:Recherche></mob:Recherche>
          </tem:paramFindParc>
        </tem:FindParc>
      </soapenv:Body>
    </soapenv:Envelope>"""
    root = post_soap("FindParc", body)

    rows = []
    total = 0
    for p in root.iter(f'{{{NS_ART}}}Parc'):
        total += 1
        etat = (p.findtext(f'{{{NS_ART}}}Etat') or '').strip()
        if etat in PARC_ETATS_EXCLUS:
            continue
        numero = (p.findtext(f'{{{NS_ART}}}Numero') or '').strip()
        if not numero:
            continue
        code = (p.findtext(f'{{{NS_ART}}}CodeArticle') or '').strip()
        lieu = (p.findtext(f'{{{NS_ART}}}LieuStockage') or '').strip()
        libelle, reference = art_map.get(code, ('', ''))
        rows.append({
            'numero':         numero,
            'code_article':   code,
            'ref_produit':    reference,
            'libelle':        libelle,
            'code_lieu':      lieu,
            'nom_partenaire': lieux_libelles.get(lieu, lieu),
            'etat':           etat,
            'disponible':     (p.findtext(f'{{{NS_ART}}}Disponible') or '').strip().lower() == 'true',
            'reserve':        (p.findtext(f'{{{NS_ART}}}Reserve') or '').strip().lower() == 'true',
        })
    return {'rows': rows, 'total': total, 'kept': len(rows)}


def sync_parc_to_odoo():
    """Récupère le parc vivant et le pousse vers Odoo (/api/parc/sync)."""
    base = os.environ.get('ODOO_SYNC_URL', '')
    key  = os.environ.get('ODOO_STOCK_API_KEY', '')
    if not base or not key:
        return {'error': 'ODOO_SYNC_URL ou ODOO_STOCK_API_KEY manquant (voir .env)'}
    url = base.replace('/stock/sync', '/parc/sync')

    snap = get_all_parc()
    resp = requests.post(
        url,
        json={'rows': snap['rows'], 'full_sync': True},
        headers={'X-API-Key': key},
        timeout=600,
    )
    resp.raise_for_status()
    result = resp.json()
    result.update({
        'rows_sent':   len(snap['rows']),
        'parc_total':  snap['total'],
        'parc_kept':   snap['kept'],
    })
    return result


# ─── CATALOGUE (articles + référence commerciale Type=1) ─────────
def _local(tag):
    return tag.split('}')[-1]


def get_catalog():
    """Catalogue Orthop : code, libellé, famille (FindArticle) + référence
    commerciale Type=1 (FindDeclinaison). Renvoie une liste de dicts."""
    # 1. Articles
    body_a = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:art="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/><soapenv:Body><tem:FindArticle><tem:paramFindArticle>
        {AUTH}<mob:ControleMax>false</mob:ControleMax>
        <mob:Recherche><art:Etat>0</art:Etat></mob:Recherche>
      </tem:paramFindArticle></tem:FindArticle></soapenv:Body></soapenv:Envelope>"""
    root_a = post_soap("FindArticle", body_a)
    arts = {}
    for a in root_a.iter(f'{{{NS_ART}}}Article'):
        code = (a.findtext(f'{{{NS_ART}}}Code') or '').strip()
        if not code:
            continue
        arts[code] = {
            'code': code,
            'libelle': (a.findtext(f'{{{NS_ART}}}Libelle') or '').strip(),
            'code_famille': (a.findtext(f'{{{NS_ART}}}CodeFamille') or '').strip(),
            'manufacturerref': (a.findtext(f'{{{NS_ART}}}ManufacturerRef') or '').strip(),
        }

    # 2. Déclinaisons (toutes) → référence Type=1 par CodeArticle
    body_d = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:tem="http://tempuri.org/"
        xmlns:mob="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour.Articles"
        xmlns:art="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.Articles"
        xmlns:par="http://schemas.datacontract.org/2004/07/Mobilog.Serveur.API.DTO.ParamRetour"
        xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
      <soapenv:Header/><soapenv:Body><tem:FindDeclinaison><tem:paramFindDeclinaison>
        {AUTH}<mob:ControleMax>false</mob:ControleMax><mob:Recherche></mob:Recherche>
      </tem:paramFindDeclinaison></tem:FindDeclinaison></soapenv:Body></soapenv:Envelope>"""
    refs = {}
    try:
        root_d = post_soap("FindDeclinaison", body_d)
        for decl in root_d.iter():
            if _local(decl.tag) != 'Declinaison':
                continue
            ca = ''
            for ch in decl:
                if _local(ch.tag) == 'CodeArticle':
                    ca = (ch.text or '').strip()
                    break
            if not ca or ca in refs:
                continue
            for ra in decl.iter():
                if _local(ra.tag) != 'Reference_Article':
                    continue
                rtype = rval = ''
                for f in ra:
                    ln = _local(f.tag)
                    if ln == 'Type':
                        rtype = (f.text or '').strip()
                    elif ln == 'Reference':
                        rval = (f.text or '').strip()
                if rval and rtype == '1':
                    refs[ca] = rval
                    break
    except Exception:
        pass

    return [
        {
            'code':         a['code'],
            'libelle':      a['libelle'],
            'reference':    refs.get(a['code']) or a['manufacturerref'] or '',
            'code_famille': a['code_famille'],
        }
        for a in arts.values()
    ]


def sync_catalog_to_odoo():
    """Pousse le catalogue Orthop vers Odoo (/api/catalog/sync)."""
    base = os.environ.get('ODOO_SYNC_URL', '')
    key  = os.environ.get('ODOO_STOCK_API_KEY', '')
    if not base or not key:
        return {'error': 'ODOO_SYNC_URL ou ODOO_STOCK_API_KEY manquant (voir .env)'}
    url = base.replace('/stock/sync', '/catalog/sync')
    rows = get_catalog()
    resp = requests.post(url, json={'rows': rows}, headers={'X-API-Key': key}, timeout=300)
    resp.raise_for_status()
    result = resp.json()
    result['rows_sent'] = len(rows)
    return result


# ─── CONSOMMATION (sorties de stock, via FindMouvementStock) ─────
# FindMouvementStock vit dans le service Articles mais utilise les namespaces
# « Must.Server.API.Models.*.Products » (et NON les vieux Mobilog.*.DTO).
# Le WSDL annonce un hôte interne : on force l'URL publique via create_service.
_NS_MVT_PARAM = 'http://schemas.datacontract.org/2004/07/Must.Server.API.Models.ParamsReturns.Products'
_NS_MVT_RECH = 'http://schemas.datacontract.org/2004/07/Must.Server.API.Models.Business.Products'


def _mvt_service():
    """Construit (et met en cache) un service zeep pour FindMouvementStock,
    en forçant l'URL publique (le WSDL annonce un hôte interne non résolvable)."""
    if _cache.get('mvt_service'):
        return _cache['mvt_service']
    from zeep import Client, Settings
    from zeep.transports import Transport
    sess = requests.Session()
    sess.verify = False
    client = Client(URL + '?singleWsdl',
                    settings=Settings(strict=False, xml_huge_tree=True),
                    transport=Transport(session=sess, timeout=300, operation_timeout=300))
    binding = None
    for svc in client.wsdl.services.values():
        for port in svc.ports.values():
            binding = port.binding.name
            break
        if binding:
            break
    service = client.create_service(binding, URL)
    _cache['mvt_client'] = client
    _cache['mvt_service'] = service
    return service


def get_all_conso(days=90):
    """Consommation (SORTIES de stock) par (lieu, article) sur `days` jours.

    Un seul appel FindMouvementStock (tous lieux) sur la période. Une sortie =
    mouvement à quantité NÉGATIVE (TypeMouvement 'MV', « Sortie … ») ; on somme
    leur valeur absolue. Les entrées (réappros, +) sont ignorées.
    Renvoie {rows, total_mouvements, sorties, periode}."""
    from collections import defaultdict
    service = _mvt_service()
    client = _cache['mvt_client']
    ParamT = client.get_type('{%s}ParamFindMouvementStock' % _NS_MVT_PARAM)
    RechT = client.get_type('{%s}FindMouvementStock' % _NS_MVT_RECH)

    fin = dt.datetime.now()
    debut = fin - dt.timedelta(days=days)
    rech = RechT(
        DebutDateMouvement=debut.strftime('%Y-%m-%dT00:00:00'),
        FinDateMouvement=fin.strftime('%Y-%m-%dT23:59:59'),
    )
    param = ParamT(Origine=ORTHOP_ORIGINE, Password=ORTHOP_PASSWORD,
                   Username=ORTHOP_USERNAME, Recherche=rech)
    ret = service.FindMouvementStock(param)
    arr = getattr(ret, 'MouvementsStock', None)
    items = []
    if arr is not None:
        sub = getattr(arr, 'MvtStock', None)
        items = sub if isinstance(sub, list) else ([sub] if sub else [])

    lieux_libelles = get_lieux()
    art_map = {a['code']: (a['libelle'], a['reference']) for a in get_articles()}

    agg = defaultdict(float)        # (code_lieu, code_article) -> conso (positive)
    sorties = 0
    for mv in items:
        try:
            q = float(getattr(mv, 'Quantite', 0) or 0)
        except (TypeError, ValueError):
            q = 0.0
        if q >= 0:
            continue                # on ne garde que les sorties (quantité < 0)
        lieu = (getattr(mv, 'LieuStockage', '') or '').strip()
        code = str(getattr(mv, 'Article', '') or '').strip()
        if not lieu or not code:
            continue
        agg[(lieu, code)] += -q
        sorties += 1

    periode = '%s → %s' % (debut.strftime('%Y-%m-%d'), fin.strftime('%Y-%m-%d'))
    rows = []
    for (lieu, code), qte in agg.items():
        libelle, _ref = art_map.get(code, ('', ''))
        rows.append({
            'code_lieu': lieu,
            'code_article': code,
            'nom': lieux_libelles.get(lieu, lieu),
            'libelle': libelle,
            'qte': qte,
            'periode': periode,
        })
    return {'rows': rows, 'total_mouvements': len(items),
            'sorties': sorties, 'periode': periode}


# ─── CONSOMMATION PARC (tire-lait : sorties = mises en location) ──
# Les tire-lait ne « sortent » pas du stock mais du PARC : une sortie = une mise
# en location (DeliveryDate) dans GetHistoParc (sphère Clients). On rattache au
# lieu via le n° de parc (présent dans FindParc, déjà synchronisé).
_NS_HISTO_PARAM = 'http://schemas.datacontract.org/2004/07/Must.Server.API.Models.ParamsReturns.Clients'


def _clients_service():
    """Service zeep SWOM_Clients.svc (URL publique forcée)."""
    if _cache.get('clients_service'):
        return _cache['clients_service']
    from zeep import Client, Settings
    from zeep.transports import Transport
    clients_url = URL.rsplit('/', 1)[0] + '/SWOM_Clients.svc'
    sess = requests.Session()
    sess.verify = False
    client = Client(clients_url + '?singleWsdl',
                    settings=Settings(strict=False, xml_huge_tree=True),
                    transport=Transport(session=sess, timeout=400, operation_timeout=600))
    binding = None
    for svc in client.wsdl.services.values():
        for port in svc.ports.values():
            binding = port.binding.name
            break
        if binding:
            break
    service = client.create_service(binding, clients_url)
    _cache['clients_client'] = client
    _cache['clients_service'] = service
    return service


def get_all_conso_parc(days=90):
    """Consommation des tire-lait = nombre de SORTIES parc (mises en location)
    sur `days` jours, par (lieu, CodeArticle).

    GetHistoParc (sans filtre client) renvoie tout l'historique de location ;
    on garde les DeliveryDate récentes et on rattache chaque machine à son lieu
    via le n° de parc (FindParc). Renvoie {rows, deliveries, joined, periode}."""
    from collections import defaultdict
    service = _clients_service()
    client = _cache['clients_client']
    ParamT = client.get_type('{%s}ParamGetHistoParc' % _NS_HISTO_PARAM)

    # Cartes depuis le parc courant : n° -> (lieu, code) ; (lieu, code) -> libellé
    parc = get_all_parc()['rows']
    pmap = {}
    model_lib = {}
    for p in parc:
        num = p.get('numero')
        if num:
            pmap[num] = (p['code_lieu'], p['code_article'])
        model_lib.setdefault((p['code_lieu'], p['code_article']), p.get('libelle') or '')
    lieux_libelles = get_lieux()

    ret = service.GetHistoParc(ParamT(
        Origine=ORTHOP_ORIGINE, Password=ORTHOP_PASSWORD, Username=ORTHOP_USERNAME,
        ListCodesClients={'int': []}))
    arr = getattr(ret, 'ListHistoParc', None)
    items = getattr(arr, 'HistoParc', None) if arr is not None else None
    items = items if isinstance(items, list) else ([items] if items else [])

    fin = dt.datetime.now()
    debut = fin - dt.timedelta(days=days)
    agg = defaultdict(int)
    deliveries = joined = 0
    for h in items:
        d = getattr(h, 'DeliveryDate', None)
        if not d:
            continue
        try:
            d = d.replace(tzinfo=None)
        except (TypeError, ValueError, AttributeError):
            continue
        if d < debut or d > fin:
            continue
        deliveries += 1
        info = pmap.get((getattr(h, 'ParcCode', '') or '').strip())
        if not info:
            continue
        joined += 1
        lieu, code = info
        if lieu and code:
            agg[(lieu, code)] += 1

    periode = '%s → %s' % (debut.strftime('%Y-%m-%d'), fin.strftime('%Y-%m-%d'))
    rows = []
    for (lieu, code), n in agg.items():
        rows.append({
            'code_lieu': lieu,
            'code_article': code,
            'nom': lieux_libelles.get(lieu, lieu),
            'libelle': model_lib.get((lieu, code), ''),
            'qte': float(n),
            'periode': periode,
        })
    return {'rows': rows, 'deliveries': deliveries, 'joined': joined, 'periode': periode}


def sync_conso_to_odoo(days=90):
    """Récupère la consommation (`days` jours) et la pousse vers Odoo
    (/api/conso/sync). Fusionne DEUX sources par (lieu, CodeArticle) :
      - consommables : sorties de stock (FindMouvementStock) ;
      - tire-lait : sorties de parc / mises en location (GetHistoParc).
    À lancer une fois par mois (fin de mois)."""
    base = os.environ.get('ODOO_SYNC_URL', '')
    key = os.environ.get('ODOO_STOCK_API_KEY', '')
    if not base or not key:
        return {'error': 'ODOO_SYNC_URL ou ODOO_STOCK_API_KEY manquant (voir .env)'}
    url = base.replace('/stock/sync', '/conso/sync')

    conso = get_all_conso(days)            # consommables (sorties stock)
    parc = get_all_conso_parc(days)        # tire-lait (sorties parc)

    # Fusion par (code_lieu, code_article) — les codes consommables et machines
    # sont disjoints, mais on somme par sécurité.
    merged = {}
    for r in conso['rows'] + parc['rows']:
        k = (r['code_lieu'], r['code_article'])
        if k in merged:
            merged[k]['qte'] += r['qte']
            if not merged[k].get('libelle'):
                merged[k]['libelle'] = r.get('libelle') or ''
        else:
            merged[k] = dict(r)
    rows = list(merged.values())

    resp = requests.post(
        url,
        json={'rows': rows, 'full_sync': True},
        headers={'X-API-Key': key},
        timeout=600,
    )
    resp.raise_for_status()
    result = resp.json()
    result.update({
        'rows_sent': len(rows),
        'conso_stock_rows': len(conso['rows']),
        'conso_parc_rows': len(parc['rows']),
        'sorties_stock': conso['sorties'],
        'sorties_parc': parc['joined'],
        'periode': conso['periode'],
    })
    return result


# ─── SYNCHRONISATION VERS ODOO ───────────────────────────────────
def sync_to_odoo(filtre='positif'):
    """Récupère tout le stock et le pousse vers l'endpoint Odoo /api/stock/sync.

    La synchro est « autoritaire » (full_sync) UNIQUEMENT si le snapshot est
    complet (aucun article en échec) : Odoo remet alors à 0 les lignes non
    reçues. En cas d'échec partiel, full_sync=False (on évite d'effacer du stock
    à tort) — les articles non récupérés gardent leur valeur précédente."""
    url = os.environ.get('ODOO_SYNC_URL', '')
    key = os.environ.get('ODOO_STOCK_API_KEY', '')
    if not url or not key:
        return {'error': 'ODOO_SYNC_URL ou ODOO_STOCK_API_KEY manquant (voir .env)'}

    snap = get_all_stock(filtre)
    rows = [{
        'code_lieu':    r['code_lieu'],
        'code_article': r['code'],
        'ref_produit':  r['reference'],
        'nom':          r['nom_partenaire'],
        'libelle':      r['libelle'],
        'qte':          r['quantite'],
    } for r in snap['rows']]

    full_sync = (snap['articles_failed'] == 0)

    resp = requests.post(
        url,
        json={'rows': rows, 'full_sync': full_sync},
        headers={'X-API-Key': key},
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()
    result.update({
        'rows_sent':       len(rows),
        'articles_total':  snap['articles_total'],
        'articles_failed': snap['articles_failed'],
        'full_sync':       full_sync,
    })
    return result


# ─── ROUTES ──────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/stock_all')
def route_stock_all():
    filtre = request.args.get('filtre', 'positif')
    return jsonify(get_all_stock(filtre)['rows'])

@app.route('/sync')
def route_sync():
    filtre = request.args.get('filtre', 'positif')
    return jsonify(sync_to_odoo(filtre))

@app.route('/parc_all')
def route_parc_all():
    return jsonify(get_all_parc()['rows'])

@app.route('/sync_parc')
def route_sync_parc():
    return jsonify(sync_parc_to_odoo())

@app.route('/catalog')
def route_catalog():
    return jsonify(get_catalog())

@app.route('/sync_catalog')
def route_sync_catalog():
    return jsonify(sync_catalog_to_odoo())

@app.route('/conso_all')
def route_conso_all():
    return jsonify(get_all_conso(int(request.args.get('days', 90)))['rows'])

@app.route('/sync_conso')
def route_sync_conso():
    return jsonify(sync_conso_to_odoo(int(request.args.get('days', 90))))

@app.route('/lieux')
def route_lieux():
    lieux = get_lieux()
    result = sorted([[k, v] for k, v in lieux.items()], key=lambda x: x[0])
    return jsonify(result)

@app.route('/stock')
def route_stock():
    lieu           = request.args.get('lieu', '')
    filtre         = request.args.get('filtre', 'positif')
    articles       = get_articles()
    lieux_libelles = get_lieux()
    results        = []

    def traiter(art):
        return get_stock_article(art, lieu, filtre, lieux_libelles)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(traiter, art) for art in articles]
        for future in as_completed(futures):
            try:
                r = future.result()
                if r is not None:
                    results.append(r)
            except:
                pass

    results.sort(key=lambda x: x['reference'])
    return jsonify(results)

# ─── MAIN ────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Sortie en UTF-8 (sinon la console Windows cp1252 plante sur les accents/emojis)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Mode synchro (pour cron / tâche planifiée)
    if '--sync' in sys.argv:
        print("Synchronisation du stock vers Odoo...")
        res = sync_to_odoo()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get('status') == 'ok' else 1)

    if '--sync-parc' in sys.argv:
        print("Synchronisation du parc (machines) vers Odoo...")
        res = sync_parc_to_odoo()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get('status') == 'ok' else 1)

    if '--sync-catalog' in sys.argv:
        print("Synchronisation du catalogue Orthop vers Odoo...")
        res = sync_catalog_to_odoo()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get('status') == 'ok' else 1)

    if '--sync-conso' in sys.argv:
        print("Synchronisation de la consommation (sorties, 90 j) vers Odoo...")
        res = sync_conso_to_odoo()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get('status') == 'ok' else 1)

    print("=" * 50)
    print("  STOCK TLE — Application locale")
    print("=" * 50)

    print("\n⏳ Chargement des lieux...")
    get_lieux()
    print(f"  ✓ {len(_cache['lieux'])} lieux chargés")

    print("\n⏳ Chargement des articles...")
    get_articles()
    print(f"  ✓ {len(_cache['articles'])} articles chargés")

    print("\n  → Ouvre http://localhost:5000 dans ton navigateur")
    print("=" * 50 + "\n")

    app.run(debug=False, port=5000)