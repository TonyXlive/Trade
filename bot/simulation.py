"""Moteur de simulation : enchaîne les 5 étapes jour après jour, en argent fictif.

Étape 4 (risque + exécution) est ici : chaque ordre est dimensionné par
scripts/kelly_size.py puis validé par scripts/validate_risk.py.
"""
import random
from collections import Counter

from scripts.kelly_size import taille_position
from scripts.validate_risk import valider, kill_switch_actif

from .marches import GenerateurMarches
from .scan import scanner
from .recherche import rechercher
from .prediction import predire
from .capitalisation import BaseConnaissances, classer_perte, indicateurs


def _categorie_refus(motif: str) -> str:
    """Regroupe les motifs de refus (sans les chiffres) pour le rapport."""
    if motif.startswith("VaR"):
        return "VaR 95 % au-delà de la limite"
    if motif.startswith("drawdown"):
        return "drawdown max dépassé : trading bloqué"
    if motif.startswith("avantage"):
        return "avantage insuffisant"
    return motif


class Simulation:
    def __init__(self, cfg: dict, graine: int = None, dossier_stop: str = ".", bavard: bool = False):
        self.cfg = cfg
        self.graine = cfg["graine_aleatoire"] if graine is None else graine
        self.rng = random.Random(self.graine)
        self.dossier_stop = dossier_stop
        self.bavard = bavard
        self.gen = GenerateurMarches(cfg["marches"], self.rng)
        self.base = BaseConnaissances()
        self.marches = {}                 # id -> Marche (non résolus)
        self.deja_analyses = set()
        self.predictions = {}             # id -> prédiction (pour le suivi d'étalonnage)
        self.predictions_resolues = []
        self.positions = []               # positions ouvertes
        self.transactions = []            # historique complet
        self.cash = float(cfg["capital_depart"])
        self.pic = self.cash
        self.courbe = [self.cash]
        self.refus = Counter()
        self.cout_ia_total = 0.0
        self.journal_jours = []
        self.bloque_drawdown_jour = None
        self.arret_stop = False

    # ---------- valorisation ----------
    def prix_cote(self, marche, cote):
        return marche.prix if cote == "OUI" else 1 - marche.prix

    def valeur_portefeuille(self):
        total = self.cash
        for p in self.positions:
            m = self.marches.get(p["marche"])
            if m:
                total += p["contrats"] * self.prix_cote(m, p["cote"])
        return total

    # ---------- dénouement ----------
    def _fermer(self, pos, encaissement, jour, anticipee=False):
        self.cash += encaissement
        pos["pnl"] = round(encaissement - pos["mise"], 2)
        pos["jour_sortie"] = jour
        pos["cloture_anticipee"] = anticipee
        if pos["pnl"] <= 0:
            pos["cause_perte"] = classer_perte(pos)
        self.positions.remove(pos)

    def _resoudre_echeances(self, jour):
        for mid, m in list(self.marches.items()):
            if m.jour_echeance > jour:
                continue
            self.gen.resoudre(m)
            for pos in [p for p in self.positions if p["marche"] == mid]:
                gagne = (m.resultat == 1) == (pos["cote"] == "OUI")
                pos["resultat"] = "gagné" if gagne else "perdu"
                self._fermer(pos, pos["contrats"] * (1.0 if gagne else 0.0), jour)
            pred = self.predictions.pop(mid, None)
            if pred:
                # On ne garde que l'essentiel : la sauvegarde reste légère sur des mois
                self.predictions_resolues.append({"categorie": m.categorie, "p_modele": pred["p_modele"],
                                                  "p_marche": pred["p_marche"], "resultat": m.resultat})
                self.base.enregistrer_prediction(m.categorie, pred["p_modele"], pred["p_marche"], m.resultat)
            del self.marches[mid]
            self.deja_analyses.discard(mid)

    def _couverture_auto(self, jour):
        """Si le prix part fortement contre nous (> 10 points), on coupe la position."""
        frais = self.cfg["marches"]["frais_par_contrat"]
        for pos in list(self.positions):
            m = self.marches[pos["marche"]]
            prix_actuel = self.prix_cote(m, pos["cote"])
            if pos["prix_entree_marche"] - prix_actuel > 0.10:
                vente = max(0.0, prix_actuel - m.spread / 2 - frais)
                pos["resultat"] = "coupé"
                self._fermer(pos, pos["contrats"] * vente, jour, anticipee=True)

    # ---------- une journée ----------
    def jour(self, j):
        r = self.cfg["risque"]
        for m in self.marches.values():
            self.gen.faire_evoluer(m)
        for m in self.gen.nouveaux(j):
            self.marches[m.id] = m

        self._resoudre_echeances(j)
        self._couverture_auto(j)

        debut_jour = self.valeur_portefeuille()
        cout_ia_jour = 0.0
        nb_ordres = 0
        mises_jour = 0.0
        stats_scan = {}

        # Vérifié chaque jour : supprimer le fichier STOP fait repartir le bot
        self.arret_stop = kill_switch_actif(self.dossier_stop)

        if not self.arret_stop:
            candidats = [m for m in self.marches.values() if m.id not in self.deja_analyses
                         and not any(p["marche"] == m.id for p in self.positions)]
            retenus, stats_scan = scanner(candidats, j, self.cfg["scan"], self.base)

            cfg_pred = dict(self.cfg["prediction"], frais_par_contrat=self.cfg["marches"]["frais_par_contrat"])
            biais_cat = self.cfg["marches"].get("biais_modeles_par_categorie", {})
            regles = dict(r, avantage_min=self.cfg["prediction"]["avantage_min"])

            for m, _anomalies in retenus:
                if cout_ia_jour + cfg_pred["cout_appel_ia"] * len(self.cfg["modeles"]) > r["max_cout_ia_jour"]:
                    self.refus["budget IA du jour épuisé (analyse stoppée)"] += 1
                    break
                self.deja_analyses.add(m.id)
                note = rechercher(m, self.rng, cfg_pred.get("correlation_avec_marche", 0.0))
                pred = predire(m, note, self.cfg["modeles"], cfg_pred, biais_cat, self.rng)
                cout_ia_jour += pred["cout_ia"]
                self.predictions[m.id] = pred
                if not pred["signal"]:
                    continue

                capital = self.valeur_portefeuille()
                taille = taille_position(pred["proba_cote"], pred["prix_effectif"], capital,
                                         r["fraction_kelly"], r["max_par_position"])
                ordre = {"avantage": pred["avantage"], "mise": taille["montant"], "mise_kelly": taille["montant"],
                         "prix": pred["prix_effectif"], "proba": pred["proba_cote"]}
                etat = {"capital": capital, "capital_pic": self.pic,
                        "perte_jour": max(0.0, debut_jour - capital), "capital_debut_jour": debut_jour,
                        "positions": [{"mise": p["mise"], "prix": p["prix_effectif"], "proba": p["proba_cote"]}
                                      for p in self.positions],
                        "cout_ia_jour": cout_ia_jour, "mises_jour": mises_jour, "ordres_jour": nb_ordres}
                ok, motifs = valider(ordre, etat, regles, self.dossier_stop)
                if not ok:
                    for mo in motifs:
                        self.refus[_categorie_refus(mo)] += 1
                    if any("drawdown" in mo for mo in motifs) and self.bloque_drawdown_jour is None:
                        self.bloque_drawdown_jour = j
                    continue

                # Exécution : ordre à cours limité, on abandonne si le glissement est trop fort
                slip = abs(self.rng.gauss(0, 0.008))
                if slip > r["slippage_max"]:
                    self.refus["glissement de prix trop fort (ordre abandonné)"] += 1
                    continue
                prix_rempli = round(min(0.99, pred["prix_effectif"] + slip), 4)
                contrats = int(ordre["mise"] // prix_rempli)
                if contrats < 1:
                    self.refus["mise trop petite pour un contrat"] += 1
                    continue
                mise = round(contrats * prix_rempli, 2)
                self.cash -= mise
                nb_ordres += 1
                mises_jour += mise
                pos = {
                    "id": f"T{len(self.transactions)+1:04d}", "marche": m.id, "categorie": m.categorie,
                    "question": m.question, "cote": pred["cote"], "jour_entree": j,
                    "prix_entree_marche": self.prix_cote(m, pred["cote"]),
                    "prix_effectif": prix_rempli, "contrats": contrats, "mise": mise,
                    "proba_cote": pred["proba_cote"], "avantage": pred["avantage"],
                    "kelly_complet": taille["kelly_complet"], "slippage": round(slip, 4),
                    "proba_reelle_cote": m.proba_reelle if pred["cote"] == "OUI" else 1 - m.proba_reelle,
                    "pnl": None, "resultat": "en cours",
                }
                self.positions.append(pos)
                self.transactions.append(pos)

        self.cout_ia_total += cout_ia_jour
        self.base.consolider(j)
        valeur = self.valeur_portefeuille()
        self.pic = max(self.pic, valeur)
        self.courbe.append(valeur)
        self.journal_jours.append({"jour": j, "valeur": round(valeur, 2), "ordres": nb_ordres,
                                   "positions_ouvertes": len(self.positions),
                                   "cout_ia": round(cout_ia_jour, 2), "scan": stats_scan})
        if self.bavard:
            print(f"Jour {j:3d} | valeur {valeur:10.2f} | ordres {nb_ordres:2d} | "
                  f"positions {len(self.positions):2d} | IA {cout_ia_jour:5.2f}")

    def lancer(self, jours: int = None):
        jours = jours or self.cfg["jours_simulation"]
        for j in range(1, jours + 1):
            self.jour(j)
        return self.resultats()

    def resultats(self):
        ind = indicateurs(self.transactions, self.courbe, self.predictions_resolues)
        ind["cout_ia_total"] = round(self.cout_ia_total, 2)
        ind["positions_ouvertes_fin"] = len(self.positions)
        ind["bloque_drawdown_jour"] = self.bloque_drawdown_jour
        ind["arret_stop"] = self.arret_stop
        ind["capital_depart"] = self.cfg["capital_depart"]
        ind["graine"] = self.graine
        ind["valeur_finale"] = round(self.courbe[-1], 2)
        causes = Counter(t["cause_perte"] for t in self.transactions if t.get("cause_perte"))
        ind["causes_pertes"] = dict(causes)
        ind["refus"] = dict(self.refus)
        ind["lecons"] = self.base.lecons
        return ind
