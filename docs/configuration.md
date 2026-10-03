# JobHunter — veille France, CDI et junior

Application de veille personnalisable, développée par Carole Dapah. Elle collecte des offres autorisées, élimine avant enregistrement les annonces hors France ou incompatibles avec un profil junior, les classe selon le profil métier, puis envoie des alertes. Elle ne postule jamais automatiquement.

Les alertes APEC reçues via `neomarket.diffusion.apec.fr` et HelloWork reçues via `emails.hellowork.com` sont décodées sans ouvrir leurs liens de suivi : seule l'adresse publique de l'offre est conservée pour éviter les doublons. Les alertes des autres sites dépendent du format réel des liens présents dans chaque e-mail.

Les liens Cadremploi `r.emails4.alertes.cadremploi.fr/tr/cl/…` ne contiennent pas d'adresse d'offre décodable. Une carte d'offre identifiable est retenue avec son lien d'alerte ; son titre, son entreprise et sa ville servent à réduire les doublons. Pour cette source, l'application ne peut pas confirmer automatiquement la destination finale ou l'ouverture des candidatures à partir de l'e-mail seul.

Avec Gmail, si `IMAP_MAILBOX=INBOX` (valeur par défaut), le collecteur détecte automatiquement via l'attribut IMAP `\\All` le dossier « Tous les messages » : cela inclut les alertes archivées ou classées hors boîte de réception. Un autre `IMAP_MAILBOX` configuré explicitement reste prioritaire. La ligne `Dossier IMAP utilisé pour les alertes` apparaît dans les logs de l'application. Les dossiers Spam et Corbeille ne sont pas inclus.

## Sources réellement prises en charge

| Source | Méthode | Configuration nécessaire |
|---|---|---|
| France Travail | API officielle Offres d'emploi v2 | Identifiants développeur France Travail |
| LinkedIn | Alertes officielles reçues par e-mail | Créer une alerte France/CDI/junior sur LinkedIn |
| APEC | Alertes officielles reçues par e-mail | Créer une alerte sur APEC |
| Indeed | Alertes officielles reçues par e-mail | Créer une alerte sur Indeed |
| HelloWork | Alertes officielles reçues par e-mail | Créer une alerte sur HelloWork |
| Cadremploi | Alertes officielles reçues par e-mail | Créer une alerte sur Cadremploi |
| Google Alertes (posts LinkedIn publics) | E-mails Google Alertes lus via IMAP | Créer des alertes Google ciblant `site:linkedin.com/posts/` ; sans clé API |
| Posts LinkedIn publics | Résultats indexés par l'API Brave Search, sans parcourir LinkedIn | Clé Brave Search API, source facultative |
| Arbeitnow et Remotive | API publique, facultative | Désactivées par défaut et filtrées sur la France |

JobHunter ne contourne pas les protections de LinkedIn, APEC, Indeed ou HelloWork. Pour les posts, il consulte les extraits publics envoyés par Google Alertes ou renvoyés par Brave ; il ne se connecte pas à LinkedIn et ne lit pas le fil personnel.

## Solution gratuite : Google Alertes pour les posts

Cette source est incluse dès que `IMAP_ENABLED=true` et que les e-mails Google Alertes arrivent dans la même boîte que les alertes emploi. Aucune clé Brave n'est requise : garder `PUBLIC_POSTS_ENABLED=false` si vous n'utilisez pas l'API Brave.

Créer sur <https://www.google.com/alerts> plusieurs alertes comme :

```text
site:linkedin.com/posts/ "data engineer" "CDI" "France"
site:linkedin.com/posts/ "data analyst" "CDI" "France"
site:linkedin.com/posts/ "Power BI" "CDI" "France"
site:linkedin.com/posts/ "développeur Python" "CDI" "France"
site:linkedin.com/posts/ "ingénieur logiciel" "CDI" "France"
```

Régler l'envoi à l'adresse Gmail lue par JobHunter, France, français et tous les résultats. JobHunter lit les e-mails expédiés par `googlealerts-noreply@google.com`, déplie leurs liens et ignore les posts dont les extraits ne mentionnent pas un métier ciblé, un CDI et un lieu en France. Les posts sont affichés sous « Google Alertes (posts) » dans le diagnostic. La date de réception de l'e-mail n'est pas présentée comme la date de publication du post.

Google ne découvre pas nécessairement tous les posts et peut les indexer avec retard. Le texte complet, les conditions d'expérience et la possibilité de postuler doivent être vérifiés sur l'offre d'origine. Les e-mails Google Alertes ne sont pas les alertes Emploi LinkedIn et peuvent produire des résultats différents.

## Posts de recrutement publics (facultatif)

1. Créer un compte sur <https://api.search.brave.com/> et activer un abonnement API Search. Lire les tarifs et fixer une limite de dépenses dans le compte Brave.
2. Récupérer la clé API et ajouter ces lignes dans le `.env` de de votre installation, sans supprimer les valeurs existantes :

```dotenv
PUBLIC_POSTS_ENABLED=true
BRAVE_SEARCH_API_KEY=votre-cle-api-brave
PUBLIC_POSTS_INTERVAL_HOURS=6
```

3. Redémarrer l'application avec `sudo docker compose up -d --build`, puis cliquer sur **Rechercher maintenant**. La source « Public Posts » apparaît dans le diagnostic après une recherche.

Quatre recherches prédéfinies couvrent Data Engineer, Data Analyst, développement junior et Power BI. Elles peuvent être ajustées dans `app/public_posts.py`. Au plus une série de quatre appels API est faite toutes les six heures, y compris si la collecte générale tourne tous les quarts d'heure. Le nombre de requêtes, les tarifs et la disponibilité dépendent de Brave. Si la clé manque, la ligne « Public Posts » apparaît en erreur ; les autres sources continuent.

Le moteur ne renvoie pas tout LinkedIn : seuls les posts publics déjà indexés peuvent être trouvés. L'option `freshness=pd` porte sur la date estimée de la page dans l'index, qui peut être sa dernière modification ; cela ne prouve pas que l'offre a été publiée il y a moins de 24 h. Si le post n'indique pas explicitement un rôle, un CDI et un lieu en France dans les extraits, il n'est pas ajouté. Un post conservé reste **à vérifier sur l'offre d'origine** : expérience demandée, contrat exact, date de publication et candidatures encore ouvertes ne sont pas garanties par un extrait de recherche.

## Filtrage appliqué

Une annonce est refusée avant son ajout si elle :

- est senior, lead, staff, principal, manager, architecte ou responsable ;
- demande au moins trois ans d'expérience explicitement ;
- est un stage, une alternance, une mission freelance ou un temps partiel ;
- n'est pas située en France ;
- ne correspond pas à l'un des métiers explicitement recherchés dans le profil ;
- a été publiée ou reçue il y a plus de 24 heures ;
- contient une indication explicite que les candidatures sont fermées.

Les offres sont classées de la plus récente à la plus ancienne. Pour les alertes e-mail, JobHunter conserve uniquement les vrais liens d'offres et écarte les liens génériques tels que « Gérer les alertes » ou une page de résultats. LinkedIn ne fournit toutefois pas d'API publique permettant de revérifier automatiquement qu'une candidature est encore ouverte après l'envoi de l'alerte : une fermeture très rapide peut donc exceptionnellement n'être visible qu'en ouvrant l'annonce.

Les métiers et compétences sont définis dans `app/profile.py`. Le score ne remplace pas la vérification humaine de l'annonce.

## 1. Configurer France Travail

1. Créer un compte sur <https://francetravail.io/inscription>.
2. Créer une application et demander l'accès à **Offres d'emploi v2**.
3. Copier l'identifiant client et le secret dans `.env`.

```dotenv
FRANCE_TRAVAIL_ENABLED=true
FRANCE_TRAVAIL_CLIENT_ID=votre-identifiant
FRANCE_TRAVAIL_CLIENT_SECRET=votre-secret
```

Sans ces deux valeurs, la source France Travail apparaîtra en erreur dans le diagnostic du tableau de bord.

## 2. Créer les alertes officielles

Sur LinkedIn, APEC, Indeed, HelloWork et Cadremploi, créer plusieurs alertes avec :

- lieu : France, puis Strasbourg/Grand Est si le site le permet ;
- contrat : CDI ;
- niveau : débutant, junior, jeune diplômé ou première expérience ;
- recherches : développeur logiciel, développeur Python, backend Python, data analyst, data engineer, Power BI, Power Platform.

Faire envoyer toutes ces alertes vers `votre-adresse@example.com`.

## 3. Configurer Gmail sans donner le mot de passe principal

Activer la validation en deux étapes du compte Google, puis créer un **mot de passe d'application** Google. Utiliser ce même mot de passe d'application pour SMTP et IMAP. Ne jamais mettre le mot de passe habituel de Gmail dans `.env`.

```dotenv
IMAP_ENABLED=true
IMAP_USER=votre-adresse@example.com
IMAP_PASSWORD=mot-de-passe-application-google
MAX_JOB_AGE_HOURS=24

EMAIL_ENABLED=true
SMTP_USER=votre-adresse@example.com
SMTP_PASSWORD=mot-de-passe-application-google
EMAIL_DESTINATION=votre-adresse@example.com
```

Le bouton **Tester l'e-mail** du tableau de bord confirme que l'envoi fonctionne. Le diagnostic de la dernière recherche montre, pour chaque source, les annonces lues, retenues, rejetées et les erreurs éventuelles.

## Installation Docker et accès SSH

Dans le dossier décompressé :

```bash
cp .env.docker.example .env
# Renseigner POSTGRES_PASSWORD avec un mot de passe hexadécimal aléatoire.
nano .env
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 app
curl -i http://localhost:8000/health
```

Le port web est lié à `127.0.0.1` sur le serveur et n'est donc pas exposé directement à Internet. Depuis l'ordinateur personnel :

```bash
ssh -i ~/.ssh/votre-cle.key -L 8000:localhost:8000 ubuntu@ADRESSE_IP_DU_SERVEUR
```

Ouvrir ensuite <http://localhost:8000>.

## Mettre à jour l'installation existante

Avant de remplacer l'ancien dossier, conserver son `.env`. La base PostgreSQL reste dans le volume Docker `jobhunter_postgres_data`.

```bash
cd ~/JobHunter
cp .env ~/.jobhunter.env.backup
cd ..
# Décompresser la nouvelle version dans ~/JobHunter, puis :
cp ~/.jobhunter.env.backup ~/JobHunter/.env
cd ~/JobHunter
sudo docker compose up -d --build
sudo docker compose logs --tail=100 app
```

Ne pas exécuter `docker compose down -v` : l'option `-v` supprimerait la base de données.

## E-mails automatiques

Les notes sont des scores heuristiques : 86 % signifie que les mots et critères détectés correspondent au profil, et ne garantit pas 86 % de chances d'obtenir le poste. Si l'alerte ou le résultat du moteur ne contient qu'un extrait de l'annonce, l'expérience demandée peut être absente du texte reçu et doit être contrôlée sur la page de l'employeur. La recherche facultative de posts indexés ne parcourt pas tout Internet.

Pour mettre à jour une ancienne installation, conserver les secrets et définir dans `.env` :

```dotenv
MIN_DAILY_SCORE=86
MIN_INSTANT_SCORE=86
EMAIL_ALL_NEW_ELIGIBLE=false
```

- Une nouvelle offre dont le score dépasse 85 et atteint `MIN_INSTANT_SCORE` est sélectionnée pour un e-mail immédiat.
- Seules les offres dont le score est strictement supérieur à 85 % sont envoyées par e-mail. Une ancienne valeur `EMAIL_ALL_NEW_ELIGIBLE=true` est ignorée pour préserver ce filtre.
- À 18 h, les nouvelles offres ayant au moins `MIN_DAILY_SCORE` sont regroupées dans un récapitulatif.
- L'historique d'envoi est conservé après expiration des offres : une offre déjà envoyée n'est pas renvoyée lors de la prochaine collecte ou dans le récapitulatif quotidien.
- La collecte s'exécute au démarrage, puis toutes les `SEARCH_INTERVAL_MINUTES` minutes.

## Tests

```bash
pytest -q
```
