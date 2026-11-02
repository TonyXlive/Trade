"""Étape 5 — Capitalisation : tirer les leçons de chaque transaction.

- Journal de toutes les transactions
- Classement de chaque perte (prédiction, exécution, variance)
- Base de connaissances consultée par le scan avant chaque journée
- Indicateurs de performance (réussite, Sharpe, drawdown, facteur de profit, Brier)
"""
import math
from collections import defaultdict


def _stats_vides():
    return {"n": 0, "brier_modele": 0.0, "brier_marche": 0.0}


class BaseConnaissances:
    """Retient, par catégorie, si nos prédictions battent le marché."""

    def __init__(self, min_echantillon: int = 80, marge: float = 0.004):
        self.min_echantillon = min_echantillon
        self.marge = marge  # évite d'exclure une catégorie sur du simple bruit
        self.par_cat = defaultdict(_stats_vides)
        self.exclues = {}
        self.lecons = []

    def enregistrer_prediction(self, categorie, p_modele, p_marche, resultat):
        c = self.par_cat[categorie]
        c["n"] += 1
        c["brier_modele"] += (p_modele - resultat) ** 2
        c["brier_marche"] += (p_marche - resultat) ** 2

    def categorie_exclue(self, categorie) -> bool:
        return categorie in self.exclues

    def consolider(self, jour):
        """Tâche « nocturne » : on exclut une catégorie où l'on fait pire que le marché."""
        for cat, c in self.par_cat.items():
            if cat in self.exclues or c["n"] < self.min_echantillon:
                continue
            bm, bk = c["brier_modele"] / c["n"], c["brier_marche"] / c["n"]
            if bm > bk + self.marge:
                self.exclues[cat] = jour
                self.lecons.append({
                    "jour": jour, "categorie": cat,
                    "lecon": (f"Sur {c['n']} marchés « {cat} », nos prédictions (Brier {bm:.3f}) "
                              f"font pire que le prix du marché (Brier {bk:.3f}). "
                              f"Catégorie exclue des prochains scans."),
                })


def classer_perte(transaction) -> str:
    """Cause d'une perte. Le simulateur connaît la vraie probabilité :
    dans la vraie vie, cette analyse se fait après coup, avec moins de certitude."""
    if transaction["slippage"] > 0.01:
        return "mauvaise exécution"
    if transaction.get("cloture_anticipee"):
        return "mauvais timing (sortie avant échéance)"
    if transaction["proba_reelle_cote"] < transaction["prix_effectif"]:
        return "mauvaise prédiction"
    return "variance (bon pari, mauvais résultat)"


def verdict_honnete(transactions: list) -> dict:
    """Verdict en une ligne, sur le modèle de trader-timemachine.

    Un contrat payé c rapporte 1 : pour être à l'équilibre il faut gagner
    une part des contrats égale au prix moyen payé. On compare cette part
    nécessaire à la part réellement gagnée.
    """
    fermees = [t for t in transactions if t.get("pnl") is not None and t.get("contrats")
               and not t.get("cloture_anticipee")]
    contrats = sum(t["contrats"] for t in fermees)
    if not contrats:
        return {"texte": "Pas encore de transaction arrivée à échéance.", "necessaire": None, "obtenu": None, "n": 0}
    necessaire = sum(t["mise"] for t in fermees) / contrats
    obtenu = sum(t["contrats"] for t in fermees if t["pnl"] > 0) / contrats
    ecart = (obtenu - necessaire) * 100
    if abs(ecart) < 5:
        texte = "Proche d'un pile ou face"
    elif abs(ecart) < 15:
        texte = "Penche vers le gain" if ecart > 0 else "Penche vers la perte"
    else:
        texte = "Nettement gagnant" if ecart > 0 else "Nettement perdant"
    texte += f" : il fallait gagner {necessaire*100:.0f} % des contrats pour être à l'équilibre, le bot en a gagné {obtenu*100:.0f} %."
    if len(fermees) < 50:
        texte += f" Seulement {len(fermees)} transactions : trop peu pour conclure."
    return {"texte": texte, "necessaire": necessaire, "obtenu": obtenu, "n": len(fermees)}


def indicateurs(transactions: list, courbe_capital: list, predictions_resolues: list) -> dict:
    fermees = [t for t in transactions if t.get("pnl") is not None]
    gagnantes = [t for t in fermees if t["pnl"] > 0]
    gains = sum(t["pnl"] for t in gagnantes)
    pertes = -sum(t["pnl"] for t in fermees if t["pnl"] <= 0)

    rendements = []
    for a, b in zip(courbe_capital, courbe_capital[1:]):
        if a > 0:
            rendements.append(b / a - 1)
    if len(rendements) > 1:
        moy = sum(rendements) / len(rendements)
        sd = math.sqrt(sum((r - moy) ** 2 for r in rendements) / (len(rendements) - 1))
        sharpe = (moy / sd) * math.sqrt(365) if sd > 0 else 0.0
    else:
        sharpe = 0.0

    pic, dd_max = courbe_capital[0] if courbe_capital else 0, 0.0
    for v in courbe_capital:
        pic = max(pic, v)
        if pic > 0:
            dd_max = max(dd_max, (pic - v) / pic)

    n = len(predictions_resolues)
    brier_modele = sum((p["p_modele"] - p["resultat"]) ** 2 for p in predictions_resolues) / n if n else None
    brier_marche = sum((p["p_marche"] - p["resultat"]) ** 2 for p in predictions_resolues) / n if n else None

    # Calibration : nos prédictions à 70 % se réalisent-elles 70 % du temps ?
    tranches = []
    for i in range(10):
        bas, haut = i / 10, (i + 1) / 10
        lot = [p for p in predictions_resolues if bas <= p["p_modele"] < haut or (i == 9 and p["p_modele"] == 1)]
        if lot:
            tranches.append({
                "tranche": f"{int(bas*100)}-{int(haut*100)} %",
                "n": len(lot),
                "prevu": sum(p["p_modele"] for p in lot) / len(lot),
                "observe": sum(p["resultat"] for p in lot) / len(lot),
            })

    depart = courbe_capital[0] if courbe_capital else 0
    fin = courbe_capital[-1] if courbe_capital else 0
    return {
        "nb_transactions": len(fermees),
        "taux_reussite": len(gagnantes) / len(fermees) if fermees else 0.0,
        "pnl_total": round(gains - pertes, 2),
        "rendement": (fin / depart - 1) if depart else 0.0,
        "sharpe": sharpe,
        "drawdown_max": dd_max,
        "facteur_profit": (gains / pertes) if pertes > 0 else float("inf") if gains > 0 else 0.0,
        "brier_modele": brier_modele,
        "brier_marche": brier_marche,
        "nb_predictions": n,
        "calibration": tranches,
        "verdict": verdict_honnete(transactions),
    }
