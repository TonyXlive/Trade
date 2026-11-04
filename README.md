# Bot de trading sur marchés prédictifs — simulateur

Reprend l'architecture du guide (scan → recherche → prédiction → risque/Kelly →
capitalisation), **en argent fictif et sur des marchés fictifs**.
Aucune connexion à Polymarket ou Kalshi, aucun compte, aucune clé.

> Polymarket et Kalshi sont interdits ou restreints en France. Ce projet sert à
> comprendre la mécanique et à tester des réglages, pas à gagner de l'argent.

## Installation
Python 3.9 ou plus récent. Aucune bibliothèque à installer.

## Lancer
Windows : double-clic sur `lancer.bat`. Mac/Linux : `./lancer.sh`.
Ou en ligne de commande, depuis ce dossier :

```
python -m bot.main                         # 90 jours simulés
python -m bot.main --monte-carlo 100       # + 100 rejeux pour voir la variance
python -m bot.main --config config_optimiste.json
python -m bot.main --jours 30 --graine 7 --bavard
```

Résultats dans `sortie/` :
- `rapport.html` — à ouvrir dans le navigateur (courbe, indicateurs, pertes, leçons)
- `transactions.csv` — toutes les transactions (s'ouvre dans Excel)
- `failure_log.md` — leçons et pertes classées

## Portefeuille fictif au quotidien
Le bot démarre avec 10 000 € fictifs et joue **une journée par jour réel**. Il garde
ses positions d'un jour à l'autre et met à jour une page de suivi : valeur du jour,
ordres passés, positions dénouées, positions ouvertes, historique jour par jour.

S'il n'a pas tourné pendant quelques jours, il rattrape les journées manquées.
Lancé deux fois le même jour, il ne rejoue rien.

```
python -m bot.portefeuille            # avance jusqu'à aujourd'hui
python -m bot.portefeuille --statut   # met à jour la page sans avancer
python -m bot.portefeuille --nouveau  # repart de zéro
```

### Deux portefeuilles, deux onglets
- **Marchés fictifs** : le simulateur ci-dessus, 1 journée par jour réel.
- **Actions réelles** : 23 grandes actions américaines avec leurs **vrais cours de clôture**,
  10 000 $ fictifs. Règle : achat sur cassure d'un plus haut de 20 séances en tendance
  haussière, stop à 2 fois la variation moyenne, objectif 2 fois le risque, 1 % de perte
  maximale par position. Le bot est comparé chaque jour à un simple placement sur l'indice
  S&P 500 : s'il ne fait pas mieux, il ne sert à rien. Cours gratuits Yahoo (secours Stooq),
  aucun ordre réel. Ce mode a besoin d'internet : il tourne sur GitHub ou sur ton PC.

### Option A — sur GitHub (rien à laisser allumé, page lisible sur le téléphone)
1. Créer un dépôt **public** sur GitHub et y mettre le contenu de ce dossier
   (la page gratuite de GitHub ne fonctionne pas sur un dépôt privé).
2. Dans le dépôt : **Settings → Pages → Source : GitHub Actions**.
3. **Actions → Journée du bot → Run workflow** pour le premier lancement.
4. Ensuite, le bot tourne seul : GitHub le lance toutes les heures, et il joue chaque séance
   dès qu'elle est terminée (GitHub a souvent plusieurs heures de retard ; ce n'est pas grave). La page est à l'adresse
   `https://<pseudo>.github.io/<nom-du-dépôt>/` — l'ajouter à l'écran d'accueil du téléphone.

Le portefeuille est sauvegardé sur une branche à part nommée `etat`.
Pour arrêter le bot : créer un fichier `STOP` à la racine du dépôt (depuis l'appli GitHub).
Si GitHub met en pause les tâches automatiques après une longue période sans modification
du dépôt, il prévient par mail : il suffit de les réactiver dans l'onglet Actions.

### Option B — sur le PC Windows
- `lancer_portefeuille.bat` : joue la journée et ouvre la page.
- `installer_tache_windows.bat` (une seule fois) : lance le bot automatiquement chaque jour à 7 h.
  Si le PC était éteint, les journées manquées sont rattrapées au lancement suivant.
- La page est dans `docs/index.html`.

## Arrêt d'urgence
Créez un fichier vide nommé `STOP` à la racine du dossier : plus aucun nouvel ordre.
Supprimez-le pour reprendre.

## Régler la stratégie
Tout est dans `config.json` : seuil d'avantage, fraction de Kelly, plafonds, budget IA,
qualité des modèles (`bruit`), et surtout `correlation_avec_marche` (à quel point vos
modèles reproduisent les erreurs du marché — dans la réalité, beaucoup).

Un biais volontaire est placé sur la catégorie « crypto » (`biais_modeles_par_categorie`) :
le bot doit le découvrir seul et exclure la catégorie. Les tests vérifient qu'il y arrive.

## Ce que montrent 100 rejeux (90 jours, 10 000 € fictifs)
| Scénario | Résultat médian | Simulations en perte |
|---|---|---|
| Réaliste (`config.json`) | −1,6 % | 51 / 100 |
| Optimiste (`config_optimiste.json`) | +6,0 % | 43 / 100 |

Même dans le scénario optimiste, presque une simulation sur deux perd. Un seul
backtest à « 68 % de réussite » ne prouve rien : regardez la répartition.

## Tests
```
python -m unittest discover -s tests -v
```
62 tests : calcul de Kelly, chaque règle de risque, arrêt d'urgence, comptabilité,
respect des plafonds jour par jour, détection du biais, rapports, et pour le mode
quotidien : reprise, rattrapage, un seul jour joué par jour réel, arrêt puis reprise ;
pour les actions réelles : lecture des cours, secours en cas de panne, stops, objectifs,
ouvertures en écart, séance en cours ignorée, comptabilité.

## Structure
```
bot/            les 5 étapes + moteur + rapport + portefeuille continu (portefeuille.py, suivi.py)
.github/        tâche automatique quotidienne (GitHub Actions)
scripts/        kelly_size.py, validate_risk.py (règles déterministes)
references/     formules.md, failure_log.md
tests/          tests automatiques
SKILL.md        fiche à donner à Claude pour travailler sur le projet
```
