"""Étape 3 — Prédiction : plusieurs modèles votent, on agrège.

Les modèles sont simulés (estimations bruitées, certains biaisés).
Un signal n'est émis que si l'avantage dépasse le seuil ET si
une majorité suffisante de modèles est d'accord.
"""
import statistics
from .marches import borner


def predire(marche, note, modeles: list, cfg_pred: dict, biais_categorie: dict, rng) -> dict:
    biais_cat = biais_categorie.get(marche.categorie, 0.0)
    rho = cfg_pred.get("correlation_avec_marche", 0.0)
    erreur_marche = marche.prix - marche.proba_reelle
    independant = (1 - rho ** 2) ** 0.5
    votes = []
    for mod in modeles:
        propre = marche.proba_reelle + rho * erreur_marche + independant * rng.gauss(0, mod["bruit"])
        estimation = 0.5 * note["consensus"] + 0.5 * propre + mod.get("biais", 0.0) + biais_cat
        votes.append({"modele": mod["nom"], "poids": mod["poids"], "proba": round(borner(estimation), 3)})

    total_poids = sum(v["poids"] for v in votes)
    p_modele = sum(v["proba"] * v["poids"] for v in votes) / total_poids
    ecart_type = statistics.pstdev([v["proba"] for v in votes]) or 0.01

    # Côté du pari et prix d'achat effectif (prix + demi-spread + frais)
    if p_modele >= marche.prix:
        cote = "OUI"
        proba_cote = p_modele
        prix_achat = marche.prix + marche.spread / 2
        accord = sum(1 for v in votes if v["proba"] > marche.prix) / len(votes)
    else:
        cote = "NON"
        proba_cote = 1 - p_modele
        prix_achat = (1 - marche.prix) + marche.spread / 2
        accord = sum(1 for v in votes if v["proba"] < marche.prix) / len(votes)
    prix_achat = borner(prix_achat, 0.01, 0.99)
    prix_effectif = borner(prix_achat + cfg_pred.get("frais_par_contrat", 0.0), 0.01, 0.99)

    avantage = proba_cote - prix_effectif
    b = (1 - prix_effectif) / prix_effectif
    ev = proba_cote * b - (1 - proba_cote)
    z = (p_modele - marche.prix) / ecart_type

    signal = avantage > cfg_pred["avantage_min"] and accord >= cfg_pred["accord_min_modeles"]
    return {
        "marche": marche.id,
        "categorie": marche.categorie,
        "votes": votes,
        "p_modele": round(p_modele, 4),
        "p_marche": marche.prix,
        "cote": cote,
        "proba_cote": round(proba_cote, 4),
        "prix_achat": round(prix_achat, 4),
        "prix_effectif": round(prix_effectif, 4),
        "avantage": round(avantage, 4),
        "valeur_attendue": round(ev, 4),
        "score_z": round(z, 2),
        "accord": round(accord, 2),
        "signal": signal,
        "cout_ia": cfg_pred["cout_appel_ia"] * len(modeles),
    }
