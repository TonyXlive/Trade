"""Générateur de marchés fictifs.

Chaque marché a une probabilité réelle cachée. Le prix affiché par le
marché est cette probabilité + du bruit : le marché se trompe un peu,
mais pas beaucoup. C'est ce bruit que le bot essaie d'exploiter.
"""
from dataclasses import dataclass, field
import random


def borner(x, bas=0.02, haut=0.98):
    return max(bas, min(haut, x))


@dataclass
class Marche:
    id: str
    categorie: str
    question: str
    proba_reelle: float          # inconnue du bot (sert à simuler le résultat)
    prix: float                  # prix du "OUI" affiché par le marché
    prix_veille: float
    spread: float
    volume: int
    liquidite: float
    jour_creation: int
    jour_echeance: int
    resultat: int = None          # 1 = OUI, 0 = NON, None = pas encore résolu
    historique_volume: list = field(default_factory=list)

    def jours_restants(self, jour):
        return self.jour_echeance - jour


QUESTIONS = {
    "politique": "Le texte n°{n} sera-t-il adopté avant l'échéance ?",
    "economie": "L'indicateur fictif n°{n} dépassera-t-il son seuil ?",
    "meteo": "Pleuvra-t-il plus de 10 mm dans la ville fictive n°{n} ?",
    "sport": "L'équipe fictive n°{n} gagnera-t-elle son match ?",
    "crypto": "Le jeton fictif n°{n} finira-t-il au-dessus de son prix cible ?",
    "culture": "Le film fictif n°{n} dépassera-t-il 1 M d'entrées ?",
}


class GenerateurMarches:
    def __init__(self, cfg_marches: dict, rng: random.Random):
        self.cfg = cfg_marches
        self.rng = rng
        self.compteur = 0

    def nouveaux(self, jour: int) -> list:
        out = []
        for _ in range(self.cfg["nouveaux_par_jour"]):
            self.compteur += 1
            cat = self.rng.choice(self.cfg["categories"])
            vraie = borner(self.rng.betavariate(2, 2), 0.05, 0.95)
            prix = round(borner(vraie + self.rng.gauss(0, self.cfg["bruit_prix_marche"])), 3)
            volume = int(self.rng.lognormvariate(6, 1.2))
            out.append(Marche(
                id=f"M{self.compteur:05d}",
                categorie=cat,
                question=QUESTIONS[cat].format(n=self.compteur),
                proba_reelle=vraie,
                prix=prix,
                prix_veille=prix,
                spread=round(self.rng.choice([0.01, 0.02, 0.02, 0.03, 0.04, 0.06, 0.08]), 3),
                volume=volume,
                liquidite=round(volume * self.rng.uniform(0.5, 3.0), 2),
                jour_creation=jour,
                jour_echeance=jour + self.rng.randint(2, 60),
            ))
        return out

    def faire_evoluer(self, marche: Marche):
        """Chaque jour, le prix se rapproche un peu de la vérité (l'information arrive)."""
        marche.prix_veille = marche.prix
        vers_verite = 0.10 * (marche.proba_reelle - marche.prix)
        marche.prix = round(borner(marche.prix + vers_verite + self.rng.gauss(0, 0.025)), 3)
        marche.historique_volume.append(marche.volume)
        marche.volume = max(1, int(marche.volume * self.rng.uniform(0.7, 1.4)))

    def resoudre(self, marche: Marche):
        marche.resultat = 1 if self.rng.random() < marche.proba_reelle else 0
