"""Contrôles de risque déterministes. AUCUN ordre ne passe sans validation ici.

Toutes les règles doivent être respectées, sinon l'ordre est refusé
avec la liste des motifs. Ces règles ne concernent que les ENTRÉES :
sortir d'une position (couverture, coupure) n'est jamais bloqué. Le code (et non un texte d'instructions)
garantit que la règle s'applique toujours de la même façon.
"""
import math
import os

Z_95 = 1.645
FICHIER_STOP = "STOP"


def var95(positions: list) -> float:
    """Valeur à risque à 95 % du portefeuille (approximation normale).

    Chaque position : {"mise": montant, "prix": prix d'achat, "proba": proba estimée}.
    Gain si succès = mise*(1-prix)/prix ; perte si échec = mise.
    """
    moyenne = 0.0
    variance = 0.0
    for pos in positions:
        mise, prix, p = pos["mise"], pos["prix"], pos["proba"]
        ecart = mise / prix  # différence de résultat entre succès et échec
        moyenne += p * ecart - mise
        variance += p * (1 - p) * ecart ** 2
    return max(0.0, Z_95 * math.sqrt(variance) - moyenne)


def kill_switch_actif(dossier: str = ".") -> bool:
    return os.path.exists(os.path.join(dossier, FICHIER_STOP))


def valider(ordre: dict, etat: dict, regles: dict, dossier_stop: str = ".") -> tuple:
    """Retourne (accepte: bool, motifs_refus: list[str]).

    ordre : avantage, mise, mise_kelly, prix, proba
    etat  : capital, capital_pic, perte_jour, positions (liste), cout_ia_jour
    regles: section "risque" de config.json (+ avantage_min)
    """
    motifs = []
    capital = etat["capital"]

    if kill_switch_actif(dossier_stop):
        motifs.append("kill switch : fichier STOP présent")

    if ordre["avantage"] <= regles["avantage_min"]:
        motifs.append(f"avantage {ordre['avantage']:.3f} <= {regles['avantage_min']}")

    if ordre["mise"] <= 0:
        motifs.append("mise nulle")

    if ordre["mise"] > ordre["mise_kelly"] + 1e-9:
        motifs.append("mise supérieure au calcul de Kelly")

    if ordre["mise"] > capital * regles["max_par_position"] + 1e-9:
        motifs.append("mise > plafond par position")

    exposition = sum(p["mise"] for p in etat["positions"])
    if exposition + ordre["mise"] > capital * regles["max_exposition_totale"] + 1e-9:
        motifs.append("exposition totale dépassée")

    if len(etat["positions"]) >= regles["max_positions"]:
        motifs.append("nombre max de positions atteint")

    nouvelle_var = var95(etat["positions"] + [{"mise": ordre["mise"], "prix": ordre["prix"],
                                               "proba": ordre["proba"]}])
    if nouvelle_var > capital * regles["var95_max_jour"]:
        motifs.append(f"VaR95 {nouvelle_var:.0f} > limite")

    pic = etat["capital_pic"]
    drawdown = (pic - capital) / pic if pic > 0 else 0
    if drawdown > regles["max_drawdown"]:
        motifs.append(f"drawdown {drawdown:.1%} > {regles['max_drawdown']:.0%} : trading bloqué")

    if etat["perte_jour"] > etat.get("capital_debut_jour", capital) * regles["max_perte_jour"]:
        motifs.append("perte du jour au-delà du seuil : arrêt pour la journée")

    # Risque engagé du jour : chaque mise compte en entier, gagnée ou perdue
    # (un pari binaire peut perdre 100 % de la mise). Repris de trader-risk.
    if "max_risque_engage_jour" in regles:
        engage = etat.get("mises_jour", 0.0) + ordre["mise"]
        if engage > etat.get("capital_debut_jour", capital) * regles["max_risque_engage_jour"] + 1e-9:
            motifs.append("risque engagé du jour au-delà de la limite")

    if "max_ordres_jour" in regles and etat.get("ordres_jour", 0) >= regles["max_ordres_jour"]:
        motifs.append("nombre max d'ordres du jour atteint")

    if etat["cout_ia_jour"] > regles["max_cout_ia_jour"]:
        motifs.append("budget IA du jour épuisé")

    return (len(motifs) == 0, motifs)
