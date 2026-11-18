# powtv-data

Données publiques du **Sport Hub** de POWTV, régénérées chaque matin par une
GitHub Action et servies par GitHub Pages :

    https://nrkcb.github.io/powtv-data/sports.json

Les applications téléchargent ce fichier une fois par jour (cache 24 h). Aucun
appel à Supabase, aucune clé d'API dans les applications.

## Ce que contient le fichier

- Football : Ligue des champions, Premier League, LaLiga, Bundesliga, Serie A,
  Ligue 1, Eredivisie, Liga Portugal, Euro et Coupe du monde
  (source : football-data.org, offre gratuite).
- Formule 1 : course, qualifications, sprint (source : Jolpica, sans clé).
- Fenêtre : de la veille à J+7.
- Texte seulement : aucun logo, aucune image.

Le format est décrit en tête de `scripts/build_sports.py`.

## Mise en place (une seule fois)

1. Créer le dépôt **public** `Nrkcb/powtv-data` sur GitHub (vide, sans README).
2. Y copier le contenu de ce dossier (`README.md`, `scripts/`, `.github/`).
3. Créer une clé gratuite sur https://www.football-data.org/client/register
   (elle arrive par e-mail).
4. Dans le dépôt : **Settings → Secrets and variables → Actions → New
   repository secret**, nom `FOOTBALL_DATA_KEY`, valeur = la clé.
5. **Settings → Pages → Build and deployment → Source : GitHub Actions**.
6. **Actions → sports.json quotidien → Run workflow** pour un premier passage.
   Ensuite, il tourne seul tous les jours vers 5 h (heure de Paris).
7. Vérifier que https://nrkcb.github.io/powtv-data/sports.json s'ouvre.

## En cas de panne

- Si une source ne répond pas, l'autre est quand même publiée.
- Si aucune ne répond, la publication est annulée : le fichier de la veille
  reste en ligne et les applications gardent leur copie locale.
- Les noms d'équipes utilisés dans les guides TV (« Bayern Munich »,
  « Man Utd »…) sont dans le tableau `ALIASES` du script : on peut en ajouter
  sans mettre à jour l'application.
