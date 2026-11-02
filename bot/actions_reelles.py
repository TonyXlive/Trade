"""Portefeuille fictif sur de VRAIES actions américaines (cours réels, argent fictif).

Chaque jour de bourse, le bot :
1. relit les cours de clôture réels ;
2. ferme les positions qui ont touché leur stop, leur objectif, ou qui ont 20 jours ;
3. cherche des cassures de tendance et entre en position avec un risque de 1 % ;
4. compare sa valeur à celle d'un simple placement sur l'indice S&P 500 (SPY).

Aucun ordre réel n'est passé. Les ordres sont simulés au cours de clôture,
avec 0,05 % de frais à l'achat et à la vente.
"""
import json
import math
import os
from datetime import datetime

from .actions_donnees import cours_journaliers, NEW_YORK

INDICE = "SPY"
LISTE = ["QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
         "JPM", "V", "MA", "XOM", "JNJ", "LLY", "UNH", "PG", "KO", "COST", "WMT", "HD"]

NOMS = {"SPY": "Indice S&P 500 (ETF SPY)", "QQQ": "Indice Nasdaq 100 (ETF QQQ)", "AAPL": "Apple",
        "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "GOOGL": "Alphabet (Google)", "META": "Meta (Facebook)",
        "TSLA": "Tesla", "AVGO": "Broadcom", "AMD": "AMD", "NFLX": "Netflix", "JPM": "JPMorgan Chase", "V": "Visa",
        "MA": "Mastercard", "XOM": "ExxonMobil", "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly",
        "UNH": "UnitedHealth", "PG": "Procter & Gamble", "KO": "Coca-Cola", "COST": "Costco", "WMT": "Walmart",
        "HD": "Home Depot"}


def nom(symbole):
    return f"{NOMS[symbole]} ({symbole})" if symbole in NOMS and NOMS[symbole] != symbole else symbole


REGLES = {
    "capital_depart": 10000.0,
    "risque_par_trade": 0.01,      # perte max au stop : 1 % du portefeuille
    "max_par_position": 0.20,      # 20 % du portefeuille au maximum dans une action
    "reserve_cash": 0.05,          # garder 5 % en liquidités
    "max_positions": 5,
    "max_entrees_jour": 2,
    "max_drawdown": 0.10,          # au-delà, plus de nouvelle entrée
    "frais": 0.0005,
    "atr_stop": 2.0,               # stop = clôture − 2 × ATR(14)
    "objectif_r": 2.0,             # objectif = 2 fois le risque
    "duree_max": 20,               # jours de bourse
    "historique_min": 200,
}


# ---------- indicateurs ----------
def moyenne(valeurs):
    return sum(valeurs) / len(valeurs)


def atr(barres, n=14):
    vrais = []
    for a, b in zip(barres[-n - 1:-1], barres[-n:]):
        vrais.append(max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])))
    return moyenne(vrais)


def signal_entree(hist):
    """hist : barres jusqu'au jour inclus. Retourne la force du signal ou None.

    Cassure : clôture au plus haut des 20 jours précédents, dans une tendance
    haussière (clôture > moyenne 50 jours > moyenne 200 jours).
    """
    if len(hist) < REGLES["historique_min"] + 1:
        return None
    closes = [b["close"] for b in hist]
    c = closes[-1]
    sma50, sma200 = moyenne(closes[-50:]), moyenne(closes[-200:])
    if c > max(closes[-21:-1]) and c > sma50 > sma200:
        return c / sma50
    return None


# ---------- état ----------
def regles_de(etat):
    return dict(REGLES, **etat.get("reglages", {}))


# Variantes testées en parallèle, sur les mêmes vrais cours, en argent fictif
CANDIDATS = {
    "Règle de départ": {},
    "Stop plus serré": {"atr_stop": 1.5},
    "Stop plus large": {"atr_stop": 3.0},
    "Objectif plus lointain": {"objectif_r": 3.0},
    "Sorties plus rapides": {"duree_max": 10},
}

# Conditions pour que le bot adopte une variante (éviter d'apprendre du hasard)
ADOPTION = {"seances_min": 120, "transactions_min": 60, "avance_min": 0.03, "drawdown_tolere": 0.02}

# Conditions affichées avant d'envisager de l'argent réel
CRITERES_PROD = {"seances_min": 125, "transactions_min": 100, "drawdown_max": 0.15}


def etat_vide():
    return {"version": 1, "date_debut": None, "derniere_date": None, "cash": REGLES["capital_depart"],
            "parts_indice": None, "positions": [], "transactions": [], "historique": [], "erreurs": [],
            "pic": REGLES["capital_depart"]}


def charger_etat(chemin):
    if os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    return etat_vide()


def sauver_etat(etat, chemin):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


def valeur(etat, cours_du_jour):
    v = etat["cash"]
    for p in etat["positions"]:
        c = cours_du_jour.get(p["symbole"], {}).get("close", p["dernier_cours"])
        v += p["actions"] * c
    return v


# ---------- une journée de bourse ----------
def _sortie(etat, p, prix, date, motif):
    R = regles_de(etat)
    net = prix * (1 - R["frais"])
    pnl = p["actions"] * net - p["cout"]
    risque = p["actions"] * (p["prix_entree"] - p["stop"])
    etat["cash"] += p["actions"] * net
    etat["positions"].remove(p)
    etat["transactions"].append(dict(p, date_sortie=date, prix_sortie=round(net, 4), motif=motif,
                                     pnl=round(pnl, 2), r=round(pnl / risque, 2) if risque > 0 else 0))


def jouer_jour(etat, date, barres_par_symbole, stop_actif=False):
    """Joue une journée de bourse. barres_par_symbole : {symbole: [barres jusqu'à date incluse]}."""
    R = regles_de(etat)
    du_jour = {s: b[-1] for s, b in barres_par_symbole.items() if b and b[-1]["date"] == date}
    evts = {"date": date, "entrees": [], "sorties": []}

    # 1. Sorties (jamais bloquées)
    for p in list(etat["positions"]):
        b = du_jour.get(p["symbole"])
        if not b or date <= p["date_entree"]:
            continue
        p["jours"] += 1
        p["dernier_cours"] = b["close"]
        if b["open"] <= p["stop"]:
            _sortie(etat, p, b["open"], date, "stop (ouverture sous le stop)")
        elif b["low"] <= p["stop"]:
            _sortie(etat, p, p["stop"], date, "stop")
        elif b["open"] >= p["objectif"]:
            _sortie(etat, p, b["open"], date, "objectif (ouverture au-dessus)")
        elif b["high"] >= p["objectif"]:
            _sortie(etat, p, p["objectif"], date, "objectif")
        elif p["jours"] >= R["duree_max"]:
            _sortie(etat, p, b["close"], date, f"{R['duree_max']} jours écoulés")
        else:
            continue
        evts["sorties"].append(etat["transactions"][-1])

    # 2. Entrées
    v = valeur(etat, du_jour)
    drawdown = (etat["pic"] - v) / etat["pic"] if etat["pic"] else 0
    bloque = stop_actif or drawdown > R["max_drawdown"]
    detenus = {p["symbole"] for p in etat["positions"]}
    candidats = []
    if not bloque:
        for s, hist in barres_par_symbole.items():
            if s == INDICE or s in detenus or s not in du_jour:
                continue
            force = signal_entree(hist)
            if force:
                candidats.append((force, s, hist))
    candidats.sort(reverse=True)
    for force, s, hist in candidats:
        if len(evts["entrees"]) >= R["max_entrees_jour"] or len(etat["positions"]) >= R["max_positions"]:
            break
        c = hist[-1]["close"]
        entree = c * (1 + R["frais"])
        stop = round(c - R["atr_stop"] * atr(hist), 4)
        risque_action = entree - stop
        if stop <= 0 or risque_action <= 0:
            continue
        n_risque = math.floor(v * R["risque_par_trade"] / risque_action)
        n_plafond = math.floor(v * R["max_par_position"] / entree)
        n_cash = math.floor((etat["cash"] - v * R["reserve_cash"]) / entree)
        n = min(n_risque, n_plafond, n_cash)
        if n < 1:
            continue
        cout = round(n * entree, 2)
        etat["cash"] -= cout
        p = {"symbole": s, "date_entree": date, "prix_entree": round(entree, 4), "actions": n, "cout": cout,
             "stop": stop, "objectif": round(entree + R["objectif_r"] * risque_action, 4),
             "jours": 0, "dernier_cours": c, "perte_max": round(n * risque_action, 2)}
        etat["positions"].append(p)
        evts["entrees"].append(p)

    # 3. Valorisation et comparaison à l'indice
    v = valeur(etat, du_jour)
    etat["pic"] = max(etat["pic"], v)
    if etat["parts_indice"] is None and INDICE in du_jour:
        etat["parts_indice"] = R["capital_depart"] / du_jour[INDICE]["close"]
    indice = etat["parts_indice"] * du_jour[INDICE]["close"] if INDICE in du_jour else None
    etat["historique"].append({"date": date, "valeur": round(v, 2), "indice": round(indice, 2) if indice else None,
                               "entrees": [e["symbole"] for e in evts["entrees"]],
                               "sorties": [(t["symbole"], t["pnl"]) for t in evts["sorties"]],
                               "bloque": bloque})
    etat["derniere_date"] = date
    return evts


def dates_completes(barres_indice, maintenant=None):
    """Dates de bourse terminées (la séance du jour ne compte qu'après 16 h 30 à New York)."""
    maintenant = maintenant or (datetime.now(NEW_YORK) if NEW_YORK else datetime.utcnow())
    dates = [b["date"] for b in barres_indice]
    aujourd = maintenant.date().isoformat()
    if dates and dates[-1] == aujourd and (maintenant.hour, maintenant.minute) < (16, 30):
        dates = dates[:-1]
    return dates


def mettre_a_jour(etat, cours: dict, maintenant=None, stop_actif=False, max_rattrapage=30) -> int:
    """cours : {symbole: [barres]}. Joue toutes les séances nouvelles. Retourne le nombre joué."""
    if INDICE not in cours:
        raise RuntimeError("cours de l'indice indisponibles : journée non jouée")
    dates = dates_completes(cours[INDICE], maintenant)
    if not dates:
        return 0
    if etat["derniere_date"] is None:
        a_jouer = [dates[-1]]          # premier lancement : on démarre sur la dernière séance terminée
        etat["date_debut"] = dates[-1]
    else:
        a_jouer = [d for d in dates if d > etat["derniere_date"]][-max_rattrapage:]
    index = {s: [b["date"] for b in bs] for s, bs in cours.items()}
    etat["dernier_lot"] = a_jouer
    for d in a_jouer:
        tranche = {}
        for s, bs in cours.items():
            # barres jusqu'à d incluse (recherche simple, listes triées)
            n = sum(1 for x in index[s] if x <= d)
            tranche[s] = bs[:n]
        jouer_jour(etat, d, tranche, stop_actif)
    return len(a_jouer)


def resume(etat) -> dict:
    h = etat["historique"]
    tx = etat["transactions"]
    v = h[-1]["valeur"] if h else REGLES["capital_depart"]
    ind = h[-1]["indice"] if h and h[-1]["indice"] else REGLES["capital_depart"]
    perf, perf_ind = v / REGLES["capital_depart"] - 1, ind / REGLES["capital_depart"] - 1
    pic, dd = REGLES["capital_depart"], 0.0
    for x in h:
        pic = max(pic, x["valeur"])
        dd = max(dd, (pic - x["valeur"]) / pic)
    gagnants = [t for t in tx if t["pnl"] > 0]
    ecart = (perf - perf_ind) * 100
    if not h:
        verdict = "Pas encore de séance jouée."
    else:
        if abs(ecart) < 2:
            verdict = "Équivalent à garder l'indice"
        elif ecart > 0:
            verdict = "Fait mieux que garder l'indice"
        else:
            verdict = "Fait moins bien que garder l'indice"
        def pc(x):
            v = round(x * 100, 1)
            return "0,0 %" if v == 0 else f"{v:+.1f} %".replace(".", ",")
        verdict += f" : bot {pc(perf)}, indice S&P 500 {pc(perf_ind)}."
        if not tx:
            verdict += " Aucune transaction terminée pour l'instant : trop tôt pour conclure."
        elif len(tx) < 30:
            verdict += f" Seulement {len(tx)} transaction(s) terminée(s) : trop peu pour conclure."
    return {"valeur": v, "indice": ind, "perf": perf, "perf_indice": perf_ind, "drawdown_max": dd,
            "nb": len(tx), "reussite": len(gagnants) / len(tx) if tx else None,
            "r_moyen": sum(t["r"] for t in tx) / len(tx) if tx else None, "verdict": verdict}


# ---------- apprentissage prudent : variantes fantômes ----------
def nom_regle(etat):
    return etat.get("regle_nom", "Règle de départ")


def assurer_variantes(etat):
    actuelle = etat.get("reglages", {})
    var = etat.setdefault("variantes", {})
    for n, reg in CANDIDATS.items():
        if reg == actuelle:
            var.pop(n, None)
        elif n not in var:
            v = etat_vide()
            v["reglages"] = dict(reg)
            var[n] = v
    for n in list(var):
        if n not in CANDIDATS:
            del var[n]
    return var


def _base_avant(etat, d0):
    base = REGLES["capital_depart"]
    for h in etat["historique"]:
        if h["date"] < d0:
            base = h["valeur"]
    return base


def comparer(etat, variante):
    """Compare une variante au portefeuille principal sur la même période."""
    hv = variante["historique"]
    if not hv:
        return None
    d0 = hv[0]["date"]
    perf_v = hv[-1]["valeur"] / REGLES["capital_depart"] - 1
    base = _base_avant(etat, d0)
    perf_p = etat["historique"][-1]["valeur"] / base - 1 if etat["historique"] else 0.0

    def dd(hist, depart):
        pic, m = depart, 0.0
        for h in hist:
            pic = max(pic, h["valeur"])
            m = max(m, (pic - h["valeur"]) / pic)
        return m
    tx_p = [t for t in etat["transactions"] if t["date_entree"] >= d0]
    return {"debut": d0, "seances": len(hv), "transactions": len(variante["transactions"]),
            "transactions_principal": len(tx_p), "perf": perf_v, "perf_principal": perf_p,
            "avance": perf_v - perf_p,
            "drawdown": dd(hv, REGLES["capital_depart"]),
            "drawdown_principal": dd([h for h in etat["historique"] if h["date"] >= d0], base)}


def evaluer_adoption(etat):
    """Adopte la meilleure variante seulement si elle fait nettement mieux, longtemps."""
    a = ADOPTION
    meilleure = None
    for n, v in etat.get("variantes", {}).items():
        c = comparer(etat, v)
        if not c or c["seances"] < a["seances_min"]:
            continue
        if min(c["transactions"], c["transactions_principal"]) < a["transactions_min"]:
            continue
        if c["avance"] < a["avance_min"] or c["drawdown"] > c["drawdown_principal"] + a["drawdown_tolere"]:
            continue
        if not meilleure or c["avance"] > meilleure[1]["avance"]:
            meilleure = (n, c)
    if not meilleure:
        return None
    n, c = meilleure
    changement = {"date": etat["derniere_date"], "ancienne": nom_regle(etat), "nouvelle": n,
                  "raison": (f"sur {c['seances']} séances et {c['transactions']} transactions, "
                             f"{c['avance']*100:+.1f} points par rapport à la règle en place")}
    etat["reglages"] = dict(CANDIDATS[n])
    etat["regle_nom"] = n
    etat.setdefault("changements", []).append(changement)
    etat["variantes"] = {}          # nouvelle comparaison, à partir de zéro
    assurer_variantes(etat)
    return changement


def criteres_prod(etat, res):
    c = CRITERES_PROD
    seances = len(etat["historique"])
    return [
        (f"Au moins 6 mois de suivi ({c['seances_min']} séances)", seances >= c["seances_min"], f"{seances} séance" + ("s" if seances > 1 else "")),
        (f"Au moins {c['transactions_min']} transactions terminées", res["nb"] >= c["transactions_min"], f"{res['nb']}"),
        ("Fait mieux que garder l'indice, frais compris", seances > 0 and res["perf"] > res["perf_indice"],
         f"{(res['perf']-res['perf_indice'])*100:+.1f} points"),
        ("Gain moyen par transaction positif", (res["r_moyen"] or 0) > 0,
         f"{res['r_moyen']:+.2f} R" if res["r_moyen"] is not None else "—"),
        (f"Baisse maximale sous {c['drawdown_max']*100:.0f} % sur toute la période",
         seances >= c["seances_min"] and res["drawdown_max"] < c["drawdown_max"],
         f"{res['drawdown_max']*100:.1f} %"),
    ]


def telecharger_tout(telecharger=None):
    cours, erreurs, sources = {}, [], {}
    for s in [INDICE] + LISTE:
        try:
            if telecharger:
                bs, src = cours_journaliers(s, telecharger)
            else:
                bs, src = cours_journaliers(s)
            cours[s], sources[s] = bs, src
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"{s} : {e}")
    return cours, erreurs, sources


def executer_actions(chemin_etat, dossier_page, dossier_stop, telecharger=None, maintenant=None, bavard=True):
    from .suivi_actions import generer_page_actions
    etat = charger_etat(chemin_etat)
    stop = os.path.exists(os.path.join(dossier_stop, "STOP"))
    cours, erreurs, _sources = telecharger_tout(telecharger)
    joues = 0
    try:
        joues = mettre_a_jour(etat, cours, maintenant, stop)
        for n, v in assurer_variantes(etat).items():
            mettre_a_jour(v, cours, maintenant, stop)
        if joues:
            chg = evaluer_adoption(etat)
            if chg and bavard:
                print(f"Actions réelles : nouvelle règle adoptée — {chg['nouvelle']} ({chg['raison']})")
    except RuntimeError as e:
        erreurs.insert(0, str(e))
    horodatage = (maintenant or datetime.now()).strftime("%Y-%m-%d %H:%M")
    etat["erreurs"] = ([{"quand": horodatage, "detail": e} for e in erreurs] + etat.get("erreurs", []))[:20]
    etat["derniere_execution"] = horodatage
    etat["stop_actif"] = stop
    sauver_etat(etat, chemin_etat)
    generer_page_actions(etat, resume(etat), dossier_page, erreurs)
    if bavard:
        r = resume(etat)
        lot = ", ".join(etat.get("dernier_lot", [])) if joues else "aucune nouvelle"
        print(f"Actions réelles : {joues} séance(s) jouée(s) ({lot}), dernière {etat['derniere_date']} | "
              f"valeur {r['valeur']:.2f} $ ({r['perf']:+.1%}) vs indice {r['perf_indice']:+.1%}"
              + (f" | {len(erreurs)} erreur(s) de données" if erreurs else ""))
    return etat, joues, erreurs
