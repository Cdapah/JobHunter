# JobHunter

**Veille d’offres d’emploi, classement par pertinence et notifications automatisées.**

Projet développé par **Moi** pour centraliser une recherche dispersée entre plusieurs sources et faciliter le suivi des opportunités. L’application rassemble les offres, applique des critères métier et géographiques, explique leur score de correspondance et les présente dans un tableau de bord.

**Stack :** Python · FastAPI · SQLAlchemy · PostgreSQL / SQLite · Jinja2 · APScheduler · Docker Compose · pytest

## Le besoin

Consulter plusieurs plateformes, trier les annonces et suivre les candidatures demande du temps. JobHunter automatise une partie de cette veille tout en laissant à l’utilisateur la vérification des offres et la décision de postuler. Aucune candidature n’est envoyée automatiquement.

## Fonctionnalités

- Collecte via l’API France Travail et lecture des alertes reçues par e-mail via IMAP.
- Sources facultatives : Arbeitnow, Remotive et posts publics indexés par Brave Search.
- Lecture des e-mails Google Alertes contenant des posts de recrutement.
- Filtrage selon le métier, la localisation en France, le contrat et l’expérience explicitement mentionnée.
- Classement heuristique avec explication du score et des compétences reconnues.
- Réduction des doublons par identifiant, URL normalisée et caractéristiques de l’offre.
- Tableau de bord avec filtres, statistiques et diagnostic par source.
- Suivi des statuts : nouveau, favori, postulé, entretien, refus, offre reçue, ignoré.
- Alertes SMTP et récapitulatif quotidien à 18 h, heure de Paris.
- Collecte au démarrage, puis périodique ; endpoint `/health`.

## Ma contribution

Conception et développement du backend, des collecteurs et du classement ; modélisation des données ; intégration des alertes Gmail ; création du tableau de bord ; configuration Docker et tests de parsing et de filtrage.

Le profil fourni cible le développement logiciel et la data en France. Les intitulés, compétences et localisations se personnalisent dans `app/profile.py` ; certaines règles de filtrage restent dans `app/matching.py`.

## Architecture

| Composant | Responsabilité |
|---|---|
| `app/collectors.py` | APIs et parsing des alertes e-mail |
| `app/public_posts.py` | Résultats Brave Search et e-mails Google Alertes |
| `app/matching.py`, `app/profile.py` | Éligibilité et score de correspondance |
| `app/services.py` | Orchestration, dédoublonnage et notifications |
| `app/models.py`, `app/database.py` | Modèles et persistance SQLAlchemy |
| `app/emailer.py` | Envoi SMTP |
| `app/main.py`, `app/templates/` | Routes FastAPI, planification et interface |

Les collecteurs produisent des offres normalisées. Le service les filtre, recherche les doublons, calcule leur score et enregistre les résultats. Le tableau de bord et les notifications utilisent ces données.

## Lancer en local — SQLite

Prérequis : **Python 3.12**. Depuis la racine du dépôt :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Ouvrir <http://localhost:8000> ; vérifier <http://localhost:8000/health>.

**Toutes les sources et tous les envois sont désactivés par défaut.** Le premier lancement affiche donc un tableau de bord vide, sans accès à une boîte mail ni à une API externe. Pour obtenir des offres, configurer au moins une source dans `.env`, puis redémarrer l’application. La base SQLite est créée automatiquement.

## Lancer avec Docker — PostgreSQL

Prérequis : Docker avec Docker Compose. Depuis la racine du dépôt :

```bash
cp .env.docker.example .env
python3 -c "import secrets; print(secrets.token_hex(24))"
```

Copier le mot de passe généré dans `POSTGRES_PASSWORD` du fichier `.env`, puis lancer :

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app
```

L’URL PostgreSQL est construite par Compose avec ce même mot de passe. Utiliser une valeur hexadécimale pour éviter les caractères réservés des URLs. PostgreSQL conserve ses données dans un volume Docker ; le port web est lié uniquement à `127.0.0.1:8000`.

Ne pas utiliser `docker compose down -v` pour un simple redémarrage : cela supprime le volume de données. Modifier le mot de passe du fichier `.env` ne change pas celui d’une base PostgreSQL déjà initialisée.

## Configuration des sources et des e-mails

Voir le [guide de configuration](docs/configuration.md) pour France Travail, les alertes officielles, Gmail, Google Alertes, Brave et l’accès par tunnel SSH.

- IMAP lit les alertes reçues dans votre boîte mail ; il ne crée pas les alertes sur les plateformes.
- SMTP envoie les notifications. Activer `EMAIL_ENABLED` et renseigner le destinataire.
- Pour Gmail, utiliser un mot de passe d’application si votre compte le permet, jamais le mot de passe principal.
- Les e-mails sont sélectionnés pour les nouvelles offres dont le score dépasse 85 et atteint le seuil configuré. L’historique des notifications évite les renvois.

## Tests

Après installation des dépendances :

```bash
python -m pytest -q
```

La suite couvre les règles d’éligibilité, le score, les liens d’alertes, la normalisation des URLs, le parsing des posts et la sélection du dossier Gmail. Elle utilise des données de test et des doublures IMAP ; elle ne valide pas les accès réels à vos comptes ou les formats futurs des fournisseurs.

## Limites connues

- Le score est une heuristique de correspondance, pas une probabilité d’embauche ni un modèle de machine learning.
- Sans date de publication, la date de réception ou de première observation sert à la fraîcheur ; cela ne prouve pas une publication dans les dernières 24 h.
- Les informations d’expérience ou de fermeture peuvent manquer dans les extraits. L’ouverture des candidatures doit être vérifiée sur l’annonce d’origine.
- Les formats d’e-mail et liens de suivi peuvent évoluer ; certains liens Cadremploi restent opaques.
- Les sources désactivées n’apportent aucun résultat. Les posts indexés ne constituent pas une couverture exhaustive.
- L’application n’a pas d’authentification utilisateur. Cette version est destinée à un usage local ou privé via tunnel SSH ; une exposition publique nécessite une protection supplémentaire.
- Le schéma est créé au démarrage ; aucune migration de schéma n’est fournie.

## Pistes d’évolution

- Ajouter un mode démonstration avec des offres fictives.
- Améliorer la reprise après échec SMTP et la validation des statuts.
- Ajouter une authentification avant tout usage partagé.
- Introduire des migrations et renforcer les tests d’intégration.

## Portfolio et auteur

**Carole DAPAH** — développement logiciel, backend et data.

[Portfolio](https://cdapah.github.io/Portfolio/) · [GitHub](https://github.com/Cdapah)
