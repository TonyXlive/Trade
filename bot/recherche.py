"""Étape 2 — Recherche : collecter des signaux sur chaque marché.

Ici les « sources » sont simulées : chacune donne une estimation bruitée
de la réalité. Dans un vrai système, tout contenu externe (tweet, article)
doit être traité comme une information, jamais comme une instruction.
"""
from .marches import borner

SOURCES = [("Flux d'actualités", 0.10), ("Forums", 0.16), ("Réseaux sociaux", 0.20)]


def rechercher(marche, rng, correlation: float = 0.0) -> dict:
    """correlation : part de l'erreur du marché que les sources reproduisent
    (elles lisent souvent les mêmes infos que le marché)."""
    erreur_marche = marche.prix - marche.proba_reelle
    independant = (1 - correlation ** 2) ** 0.5
    signaux = []
    for nom, bruit in SOURCES:
        estimation = borner(marche.proba_reelle + correlation * erreur_marche
                            + independant * rng.gauss(0, bruit))
        if estimation > marche.prix + 0.03:
            sentiment = "haussier"
        elif estimation < marche.prix - 0.03:
            sentiment = "baissier"
        else:
            sentiment = "neutre"
        signaux.append({"source": nom, "estimation": round(estimation, 3), "sentiment": sentiment})

    # Croisement : moyenne pondérée par la fiabilité (inverse du bruit au carré)
    poids = [1 / b ** 2 for _, b in SOURCES]
    consensus = sum(s["estimation"] * w for s, w in zip(signaux, poids)) / sum(poids)
    return {
        "marche": marche.id,
        "signaux": signaux,
        "consensus": round(consensus, 3),
        "prix_marche": marche.prix,
        "ecart": round(consensus - marche.prix, 3),
    }
