# suivi_stock

Application de consultation du stock Tire-Lait Express (API Orthop / Mobilog).

## 1. Python

Vérifiez que Python est installé : `python --version`
Sinon → https://www.python.org/downloads/

## 2. Installation des dépendances

```
pip install -r requirements.txt
```

## 3. Configuration (identifiants)

Les identifiants Orthop ne sont **plus dans le code** : ils se mettent dans un
fichier `.env` (non versionné).

1. Copiez le modèle : `copy .env.example .env` (Windows) ou `cp .env.example .env`
2. Ouvrez `.env` et renseignez vos identifiants Orthop réels.

> ⚠️ Ne committez jamais `.env` (déjà exclu par `.gitignore`).

## 4. Lancer l'app (consultation)

```
python stock_app.py
```
→ ouvrez http://localhost:5000

## 5. Synchronisation vers Odoo

Pousse **tout le stock** (tous lieux) vers Odoo (`/api/stock/sync`).
Renseignez d'abord dans `.env` :

```
ODOO_SYNC_URL=https://mcm-call-support.odoo.com/api/stock/sync
ODOO_STOCK_API_KEY=<la clé définie dans Odoo : Commandes Matériel → Configuration>
```

Deux façons de déclencher :

- **En ligne de commande** (idéal pour une tâche planifiée / cron) :
  ```
  python stock_app.py --sync
  ```
- **Par HTTP** (idéal pour n8n « Schedule → HTTP GET ») : l'app étant lancée,
  appelez `GET /sync` → renvoie un récapitulatif JSON
  (`created`, `updated`, `zeroed`, `full_sync`, …).

> La synchro est **autoritaire** : si le snapshot est complet, Odoo remet à 0
> le stock des lignes non reçues (ruptures). En cas d'échec partiel de
> récupération, la remise à zéro est désactivée par sécurité.

### Planification (exemples)

- **Windows (Planificateur de tâches)** : action quotidienne
  `python C:\chemin\suivi_stock\stock_app.py --sync`.
- **Linux (cron)** : `0 3 * * * cd /chemin/suivi_stock && python stock_app.py --sync`
- **n8n** : nœud *Schedule* (3 h) → nœud *HTTP Request* `GET http://<hote>:5000/sync`.

## Endpoints disponibles

| Route | Rôle |
|-------|------|
| `GET /` | Interface de consultation par lieu |
| `GET /lieux` | Liste des lieux de stockage (JSON) |
| `GET /stock?lieu=X&filtre=positif\|tous` | Stock d'un lieu (JSON) |
| `GET /stock_all?filtre=positif\|tous` | Stock de **tous** les lieux (JSON) |
| `GET /sync` | Récupère tout le stock et pousse vers Odoo |
| `GET /sync_parc` | Pousse le parc machines vers Odoo |
| `GET /sync_catalog` | Pousse le catalogue Orthop vers Odoo |
| `GET /sync_conso` | Pousse la consommation (90 j) vers Odoo |

---

## 6. Déploiement Docker sur VPS (n8n dans Docker)

Cible : VPS Hostinger (template « Ubuntu 24.04 with n8n ») où **n8n tourne dans
Docker** (`root-n8n-1`) derrière **Traefik**, sur le réseau Docker `root_default`.
`suivi_stock` rejoint **ce même réseau** : n8n l'appelle par son **nom de service**
(`http://suivi_stock:5000/...`). **Aucun port n'est publié** → rien sur Internet,
tout reste interne au réseau Docker.

> Le `docker-compose.yml` fourni se branche sur le réseau externe `root_default`.
> Vérifiez ce nom : `docker network ls` (et `docker inspect root-n8n-1 --format
> '{{json .NetworkSettings.Networks}}'`). S'il diffère, ajustez `name:` dans le
> bloc `networks:` du compose.

### Prérequis
- Le fichier `.env` présent à côté de `docker-compose.yml` (copié depuis
  `.env.example` et renseigné). **Ne jamais committer le `.env`** ; il n'est pas
  inclus dans l'image (voir `.dockerignore`).
  ```
  ODOO_SYNC_URL=https://mcm-call-support.odoo.com/api/stock/sync
  ODOO_STOCK_API_KEY=<clé définie dans Odoo>
  ORTHOP_URL=...  ORTHOP_ORIGINE=...  ORTHOP_USERNAME=...  ORTHOP_PASSWORD=...
  ```

### Lancer (sur le VPS)
```bash
# copier le dossier suivi_stock sur le VPS, puis :
cd /root/suivi_stock        # ou le chemin choisi
docker compose up -d --build
docker compose ps           # doit être "healthy"
docker compose logs -f      # logs gunicorn

# Test depuis le conteneur n8n (même réseau) :
docker exec root-n8n-1 wget -qO- http://suivi_stock:5000/ | head
```
Après une mise à jour du code : `docker compose up -d --build`.

### Déclenchement par n8n
Un workflow par synchro : **Schedule Trigger → HTTP Request (GET)** :

| Synchro | URL appelée par n8n | Fréquence conseillée |
|---------|---------------------|----------------------|
| Stock | `http://suivi_stock:5000/sync` | quotidienne (ex. 03 h) |
| Parc | `http://suivi_stock:5000/sync_parc` | quotidienne |
| Catalogue | `http://suivi_stock:5000/sync_catalog` | hebdomadaire |
| Consommation | `http://suivi_stock:5000/sync_conso` | mensuelle |

> Dans le nœud HTTP Request, mettre un **timeout élevé** (ex. 1 800 000 ms) :
> conso/parc peuvent durer plusieurs minutes. Chaque endpoint renvoie un
> récapitulatif JSON (créés / mis à jour / etc.).

### Lancer une synchro ponctuelle en CLI (sans n8n)
```bash
docker compose run --rm suivi_stock python stock_app.py --sync-conso
```

### Sécurité
- Aucun port publié : le service n'est joignable **que** depuis le réseau Docker
  `root_default` (donc par n8n). Les routes `/sync*` n'ont pas d'authentification
  — **ne pas** les exposer via Traefik sans ajouter d'abord un jeton.
- Le `.env` (identifiants Orthop, clé Odoo) reste **hors image** et hors git.

