"""« Mes 50 €/mois » : ta situation réelle, simulée sur les vrais cours.

Deux portefeuilles partent de zéro et reçoivent chacun 50 € au début de chaque mois,
convertis en dollars au vrai taux euro/dollar du jour :
- le BOT : même règle que l'onglet « Actions réelles », avec des morceaux d'action ;
- l'INDICE : achat automatique du S&P 500 (ETF SPY) avec les 50 €, une fois par mois.
Les deux paient les mêmes frais : 1 $ par ordre. Argent fictif, aucun ordre réel.
"""
import json
import os
from datetime import datetime

from .actions_reelles import INDICE, REGLES, atr, signal_entree, dates_completes, sauver_etat
from .actions_donnees import cours_journaliers

DEVISE = "EURUSD=X"
PARAMS = {
    "versement_eur": 50.0,
    "frais_ordre": 1.0,        # $ par ordre, à l'achat comme à la vente
    "ordre_min": 5.0,          # $ : en dessous, l'ordre n'est pas passé
}


def etat_vide():
    return {"version": 1, "date_debut": None, "derniere_date": None,
            "bot": {"cash": 0.0, "positions": [], "transactions": [], "frais": 0.0, "ordres": 0},
            "indice": {"cash": 0.0, "parts": 0.0, "frais": 0.0, "ordres": 0, "achats": []},
            "verse_eur": 0.0, "versements": [], "historique": [], "taux": None, "erreurs": []}


def charger_etat(chemin):
    if os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    return etat_vide()


def taux_du_jour(barres_devise, date):
    """Dernier taux euro/dollar connu à cette date (dollars pour 1 euro)."""
    ok = [b for b in (barres_devise or []) if b["date"] <= date]
    return ok[-1]["close"] if ok else None


def valeur_bot(b, du_jour):
    return b["cash"] + sum(p["actions"] * du_jour.get(p["symbole"], {}).get("close", p["dernier_cours"])
                           for p in b["positions"])


def _vendre(etat, p, prix, date, motif):
    b, f = etat["bot"], PARAMS["frais_ordre"]
    produit = p["actions"] * prix - f
    b["cash"] += produit
    b["frais"] += f
    b["ordres"] += 1
    b["positions"].remove(p)
    b["transactions"].append(dict(p, date_sortie=date, prix_sortie=round(prix, 4), motif=motif,
                                  pnl=round(produit - p["cout"], 2)))


def jouer_seance(etat, date, barres, taux):
    """Joue une séance. barres : {symbole: [barres jusqu'à date incluse]}."""
    du_jour = {s: bs[-1] for s, bs in barres.items() if bs and bs[-1]["date"] == date}
    b, ind, f = etat["bot"], etat["indice"], PARAMS["frais_ordre"]
    evts = {"versement": None, "achats": [], "ventes": []}

    # 1. Sorties du bot (stop, objectif, durée)
    for p in list(b["positions"]):
        x = du_jour.get(p["symbole"])
        if not x or date <= p["date_entree"]:
            continue
        p["jours"] += 1
        p["dernier_cours"] = x["close"]
        if x["open"] <= p["stop"]:
            _vendre(etat, p, x["open"], date, "stop (ouverture sous le stop)")
        elif x["low"] <= p["stop"]:
            _vendre(etat, p, p["stop"], date, "stop")
        elif x["open"] >= p["objectif"]:
            _vendre(etat, p, x["open"], date, "objectif (ouverture au-dessus)")
        elif x["high"] >= p["objectif"]:
            _vendre(etat, p, p["objectif"], date, "objectif")
        elif p["jours"] >= REGLES["duree_max"]:
            _vendre(etat, p, x["close"], date, f"{REGLES['duree_max']} séances écoulées")
        else:
            continue
        evts["ventes"].append(b["transactions"][-1])

    # 2. Versement mensuel (première séance jouée de chaque mois) et achat de l'indice
    mois = date[:7]
    if taux and mois not in [v["mois"] for v in etat["versements"]] and INDICE in du_jour:
        usd = round(PARAMS["versement_eur"] * taux, 2)
        etat["versements"].append({"mois": mois, "date": date, "eur": PARAMS["versement_eur"], "taux": taux, "usd": usd})
        etat["verse_eur"] += PARAMS["versement_eur"]
        b["cash"] += usd
        ind["cash"] += usd
        evts["versement"] = usd
        prix = du_jour[INDICE]["close"]
        if ind["cash"] - f >= PARAMS["ordre_min"]:
            parts = (ind["cash"] - f) / prix
            ind["parts"] += parts
            ind["frais"] += f
            ind["ordres"] += 1
            ind["achats"].append({"date": date, "montant": round(ind["cash"] - f, 2), "prix": prix,
                                  "parts": round(parts, 6)})
            ind["cash"] = 0.0

    # 3. Entrées du bot (morceaux d'action autorisés)
    v = valeur_bot(b, du_jour)
    detenus = {p["symbole"] for p in b["positions"]}
    candidats = []
    for s, hist in barres.items():
        if s in (INDICE, DEVISE) or s in detenus or s not in du_jour:
            continue
        force = signal_entree(hist)
        if force:
            candidats.append((force, s, hist))
    candidats.sort(reverse=True)
    for _force, s, hist in candidats:
        if len(evts["achats"]) >= REGLES["max_entrees_jour"] or len(b["positions"]) >= REGLES["max_positions"]:
            break
        c = hist[-1]["close"]
        stop = round(c - REGLES["atr_stop"] * atr(hist), 4)
        risque = c - stop
        if stop <= 0 or risque <= 0 or v <= 0:
            continue
        montant = min(v * REGLES["risque_par_trade"] / risque * c,   # perte au stop = 1 % du portefeuille
                      v * REGLES["max_par_position"],                   # 20 % maximum dans une action
                      b["cash"] - f - v * REGLES["reserve_cash"])      # garder 5 % de côté
        if montant < PARAMS["ordre_min"]:
            continue
        n = montant / c
        b["cash"] -= montant + f
        b["frais"] += f
        b["ordres"] += 1
        p = {"symbole": s, "date_entree": date, "prix_entree": round(c, 4), "actions": round(n, 6),
             "cout": round(montant + f, 2), "stop": stop, "objectif": round(c + REGLES["objectif_r"] * risque, 4),
             "jours": 0, "dernier_cours": c}
        b["positions"].append(p)
        evts["achats"].append(p)

    # 4. Valorisation
    t = taux or etat.get("taux")
    if taux:
        etat["taux"] = taux
    vb = valeur_bot(b, du_jour)
    vi = ind["cash"] + ind["parts"] * du_jour[INDICE]["close"] if INDICE in du_jour else None
    etat["historique"].append({"date": date, "bot_usd": round(vb, 2), "indice_usd": round(vi, 2) if vi is not None else None,
                               "taux": t, "verse_eur": etat["verse_eur"],
                               "achats": [a["symbole"] for a in evts["achats"]],
                               "ventes": [(x["symbole"], x["pnl"]) for x in evts["ventes"]],
                               "versement": evts["versement"]})
    etat["derniere_date"] = date
    return evts


def mettre_a_jour(etat, cours, maintenant=None, max_rattrapage=30):
    if INDICE not in cours:
        raise RuntimeError("cours de l'indice indisponibles : séance non jouée")
    dates = dates_completes(cours[INDICE], maintenant)
    if not dates:
        return 0
    if etat["derniere_date"] is None:
        a_jouer = [dates[-1]]
        etat["date_debut"] = dates[-1]
    else:
        a_jouer = [d for d in dates if d > etat["derniere_date"]][-max_rattrapage:]
    for d in a_jouer:
        tranche = {s: [b for b in bs if b["date"] <= d] for s, bs in cours.items() if s != DEVISE}
        jouer_seance(etat, d, tranche, taux_du_jour(cours.get(DEVISE), d))
    return len(a_jouer)


def resume(etat):
    h = etat["historique"]
    verse = etat["verse_eur"]
    if not h or not h[-1]["taux"]:
        return {"verse": verse, "bot": verse, "indice": verse, "gain_bot": 0.0, "gain_indice": 0.0,
                "verdict": "Pas encore de séance jouée."}
    t = h[-1]["taux"]
    vb = h[-1]["bot_usd"] / t
    vi = (h[-1]["indice_usd"] or 0) / t
    gb, gi = vb - verse, vi - verse
    ecart = gb - gi
    if abs(ecart) < 1:
        verdict = "Égalité pour l'instant"
    elif ecart > 0:
        verdict = f"Le bot est devant de {ecart:.2f} €"
    else:
        verdict = f"L'achat mensuel de l'indice est devant de {-ecart:.2f} €"
    verdict += f" sur {verse:.0f} € versés."
    if len(etat["versements"]) < 6:
        verdict += " Moins de 6 mois de versements : trop tôt pour conclure."
    return {"verse": verse, "bot": vb, "indice": vi, "gain_bot": gb, "gain_indice": gi, "verdict": verdict,
            "frais_bot": etat["bot"]["frais"] / t, "frais_indice": etat["indice"]["frais"] / t,
            "ordres_bot": etat["bot"]["ordres"], "ordres_indice": etat["indice"]["ordres"]}


def executer_mensuel(chemin_etat, dossier_page, cours, erreurs_cours=None, maintenant=None, bavard=True):
    from .suivi_mensuel import generer_page_mensuel
    etat = charger_etat(chemin_etat)
    erreurs = list(erreurs_cours or [])
    if DEVISE not in cours:
        erreurs.insert(0, "taux euro/dollar indisponible : versement reporté à la prochaine séance")
    joues = 0
    try:
        joues = mettre_a_jour(etat, cours, maintenant)
    except RuntimeError as e:
        erreurs.insert(0, str(e))
    etat["derniere_execution"] = (maintenant or datetime.now()).strftime("%Y-%m-%d %H:%M")
    etat["erreurs"] = erreurs[:10]
    sauver_etat(etat, chemin_etat)
    r = resume(etat)
    generer_page_mensuel(etat, r, dossier_page, erreurs)
    if bavard:
        print(f"Mes 50 €/mois : {joues} séance(s) jouée(s), versé {r['verse']:.0f} € | "
              f"bot {r['bot']:.2f} € | indice {r['indice']:.2f} €")
    return etat, joues, erreurs


def telecharger_devise(telecharger=None):
    try:
        bs, _ = cours_journaliers(DEVISE, telecharger) if telecharger else cours_journaliers(DEVISE)
        return bs, None
    except Exception as e:  # noqa: BLE001
        return None, f"{DEVISE} : {e}"
