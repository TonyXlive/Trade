# Formules utilisées

Un contrat binaire acheté au prix **c** (entre 0 et 1) rapporte 1 si l'on a raison, 0 sinon.

| Indicateur | Formule | Seuil retenu |
|---|---|---|
| Avantage | p_modèle − prix effectif (prix + demi-écart + frais) | > 0,04 |
| Cote nette | b = (1 − c) / c | — |
| Valeur attendue | EV = p × b − (1 − p) | > 0 |
| Kelly complet | f* = (p × b − q) / b = (p − c) / (1 − c) | — |
| Kelly retenu | f* × 0,25, plafonné à 5 % du capital | — |
| Score de décalage | (p_modèle − p_marché) / écart-type des modèles | plus élevé = signal plus net |
| Score de Brier | moyenne de (prévision − résultat)² | à comparer au Brier du marché |
| VaR 95 % | 1,645 × √Σ p(1−p)(mise/c)² − gain moyen attendu | ≤ 15 % du capital |
| Baisse maximale | (plus haut − valeur) / plus haut | blocage au-delà de 8 % |
| Facteur de profit | gains bruts / pertes brutes | > 1,5 visé |
| Sharpe | moyenne / écart-type des rendements journaliers × √365 | > 2 visé |

## Le point clé
Un score de Brier « bon » dans l'absolu ne suffit pas : il faut qu'il soit **inférieur
à celui du prix du marché**. Sinon, le marché sait déjà ce que vous savez, et les
frais vous font perdre.
