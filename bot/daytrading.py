"""Day trading en argent fictif, sur les vrais cours minute par minute (barres de 5 minutes).

Chaque séance terminée est rejouée barre après barre, sans jamais regarder la suite :
le bot ne connaît, à chaque instant, que ce qui s'est déjà passé. Toutes les positions
sont fermées avant la clôture : rien n'est gardé la nuit.

Règle (« cassure du range d'ouverture », classique du day trading) :
- range d'ouverture = plus haut et plus bas des 15 premières minutes (9 h 30 – 9 h 45 à New York) ;
- une barre de 5 minutes qui CLÔTURE au-dessus du haut → achat à l'ouverture de la barre suivante ;
  sous le bas → vente à découvert (pari à la baisse) ;
- stop au milieu du range, objectif à 2 fois le risque, sinon fermeture à 15 h 55 ;
- pas de nouvelle entrée après 11 h 30, une seule opération par action et par jour ;
- risque de 0,5 % du capital par opération, 25 % du capital au plus par position,
  4 positions en même temps au maximum, arrêt des entrées si la journée perd 2 %.
Frais : 1 $ par ordre + 0,02 % de glissement de prix à chaque exécution.
"""
import json
import math
import os
import urllib.request
from datetime import datetime, timezone

from .actions_donnees import NEW_YORK, AGENT

SYMBOLES = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX"]
INDICE = "SPY"

REGLES = {
    "capital_depart": 10000.0,
    "barres_range": 3,            # 3 barres de 5 min = 15 minutes
    "derniere_entree": "11:30",
    "fermeture": "15:55",
    "risque_par_trade": 0.005,
    "max_par_position": 0.25,
    "max_positions": 4,
    "perte_max_jour": 0.02,
    "objectif_r": 2.0,
    "range_min": 0.002,           # range < 0,2 % du prix : trop étroit, on ignore
    "range_max": 0.03,            # range > 3 % : trop agité, on ignore
    "frais_ordre": 1.0,
    "glissement": 0.0002,
}


# ---------- données ----------
def lire_yahoo_5min(contenu):
    """Réponse Yahoo « chart » 5 min -> {date: [barres de la séance normale, dans l'ordre]}."""
    d = json.loads(contenu) if isinstance(contenu, (bytes, str)) else contenu
    res = (d.get("chart") or {}).get("result")
    if not res:
        err = (d.get("chart") or {}).get("error") or {}
        raise ValueError(err.get("description") or "réponse Yahoo vide")
    r = res[0]
    q = r["indicators"]["quote"][0]
    jours = {}
    for i, ts in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or c <= 0:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if NEW_YORK:
            dt = dt.astimezone(NEW_YORK)
        heure = dt.strftime("%H:%M")
        if not ("09:30" <= heure <= "15:55"):
            continue
        jours.setdefault(dt.date().isoformat(), {})[heure] = {
            "heure": heure, "open": o, "high": h, "low": l, "close": c}
    return {j: [b[k] for k in sorted(b)] for j, b in jours.items()}


def _telecharger(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def telecharger_5min(telecharger=None):
    telecharger = telecharger or _telecharger
    cours, erreurs = {}, []
    for s in SYMBOLES:
        for hote in ("query2", "query1"):
            try:
                url = f"https://{hote}.finance.yahoo.com/v8/finance/chart/{s}?range=1mo&interval=5m"
                cours[s] = lire_yahoo_5min(telecharger(url))
                break
            except Exception as e:  # noqa: BLE001
                err = f"{s} : {e}"
        else:
            erreurs.append(err)
    return cours, erreurs


# ---------- une séance ----------
def _prix_execute(prix, achat):
    """Prix réellement obtenu : un peu plus cher à l'achat, un peu moins cher à la vente."""
    g = REGLES["glissement"]
    return prix * (1 + g) if achat else prix * (1 - g)


def _fermer(t, prix_brut, heure, motif):
    f = REGLES["frais_ordre"]
    if t["cote"] == "hausse":
        prix = _prix_execute(prix_brut, achat=False)      # on revend
        brut = (prix - t["prix_entree"]) * t["actions"]
    else:
        prix = _prix_execute(prix_brut, achat=True)       # on rachète ce qu'on a vendu à découvert
        brut = (t["prix_entree"] - prix) * t["actions"]
    t.update(heure_sortie=heure, prix_sortie=round(prix, 4), motif=motif,
             pnl=round(brut - 2 * f, 2), frais=2 * f)
    t["r"] = round(t["pnl"] / t["risque"], 2) if t["risque"] > 0 else 0.0
    return t["pnl"]


def jouer_seance(date, barres_jour, capital):
    """Rejoue une séance. barres_jour : {symbole: [barres 5 min]}. Retourne la liste des opérations."""
    R = REGLES
    ranges, actives, faites, ops = {}, [], set(), []
    pnl_jour = 0.0
    # toutes les heures de la séance, dans l'ordre
    heures = sorted({b["heure"] for bs in barres_jour.values() for b in bs})
    par_heure = {s: {b["heure"]: b for b in bs} for s, bs in barres_jour.items()}
    signaux = {}  # symbole -> côté, à exécuter à l'ouverture de la barre suivante

    for h in heures:
        # 1. exécuter les entrées décidées à la barre précédente
        for s, cote in list(signaux.items()):
            b = par_heure[s].get(h)
            del signaux[s]
            if not b or h > R["derniere_entree"] or len(actives) >= R["max_positions"]:
                continue
            if pnl_jour <= -capital * R["perte_max_jour"]:
                continue
            haut, bas = ranges[s]
            milieu = (haut + bas) / 2
            prix = _prix_execute(b["open"], achat=(cote == "hausse"))
            stop = milieu
            risque_u = (prix - stop) if cote == "hausse" else (stop - prix)
            if risque_u <= 0:
                continue  # l'ouverture a déjà dépassé le stop : on n'entre pas
            n = math.floor(min(capital * R["risque_par_trade"] / risque_u,
                               capital * R["max_par_position"] / prix))
            if n < 1:
                continue
            objectif = prix + R["objectif_r"] * risque_u if cote == "hausse" else prix - R["objectif_r"] * risque_u
            t = {"date": date, "symbole": s, "cote": cote, "heure_entree": h, "prix_entree": round(prix, 4),
                 "actions": n, "stop": round(stop, 4), "objectif": round(objectif, 4),
                 "risque": round(n * risque_u + 2 * R["frais_ordre"], 2), "range": [round(bas, 4), round(haut, 4)]}
            actives.append(t)
            faites.add(s)

        # 2. surveiller les positions ouvertes sur cette barre (y compris celle qui vient d'entrer)
        for t in list(actives):
            b = par_heure[t["symbole"]].get(h)
            if not b:
                continue
            hausse = t["cote"] == "hausse"
            touche_stop = b["low"] <= t["stop"] if hausse else b["high"] >= t["stop"]
            touche_obj = b["high"] >= t["objectif"] if hausse else b["low"] <= t["objectif"]
            ouv_stop = b["open"] <= t["stop"] if hausse else b["open"] >= t["stop"]
            ouv_obj = b["open"] >= t["objectif"] if hausse else b["open"] <= t["objectif"]
            if h != t["heure_entree"] and ouv_stop:
                pnl_jour += _fermer(t, b["open"], h, "stop (ouverture au-delà du stop)")
            elif h != t["heure_entree"] and ouv_obj:
                pnl_jour += _fermer(t, b["open"], h, "objectif (ouverture au-delà)")
            elif touche_stop:          # stop et objectif dans la même barre : on compte le stop (prudent)
                pnl_jour += _fermer(t, t["stop"], h, "stop")
            elif touche_obj:
                pnl_jour += _fermer(t, t["objectif"], h, "objectif")
            elif h >= R["fermeture"]:
                pnl_jour += _fermer(t, b["close"], h, "fermeture de fin de journée")
            else:
                continue
            actives.remove(t)
            ops.append(t)

        # 3. range d'ouverture, puis détection des cassures sur la barre qui se termine
        for s, bs in barres_jour.items():
            if s not in ranges and len([x for x in bs if x["heure"] <= h]) == R["barres_range"] \
                    and par_heure[s].get(h):
                premieres = bs[:R["barres_range"]]
                haut, bas = max(x["high"] for x in premieres), min(x["low"] for x in premieres)
                largeur = (haut - bas) / premieres[-1]["close"]
                ranges[s] = (haut, bas) if R["range_min"] <= largeur <= R["range_max"] else None
                continue
            if not ranges.get(s) or s in faites or s in signaux:
                continue
            b = par_heure[s].get(h)
            if not b or h >= R["derniere_entree"]:
                continue
            haut, bas = ranges[s]
            if b["close"] > haut:
                signaux[s] = "hausse"
            elif b["close"] < bas:
                signaux[s] = "baisse"

    # sécurité : rien ne reste ouvert la nuit (données incomplètes en fin de séance)
    for t in actives:
        bs = barres_jour[t["symbole"]]
        _fermer(t, bs[-1]["close"], bs[-1]["heure"], "fermeture (dernière barre disponible)")
        ops.append(t)
    return ops


# ---------- suivi dans le temps ----------
def etat_vide():
    return {"version": 1, "date_debut": None, "derniere_date": None, "capital": REGLES["capital_depart"],
            "parts_indice": None, "historique": [], "operations": [], "erreurs": []}


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


def seances_terminees(cours, maintenant=None):
    """Dates où l'indice a une séance complète (dernière barre 15:55) et terminée."""
    maintenant = maintenant or (datetime.now(NEW_YORK) if NEW_YORK else datetime.utcnow())
    aujourd = maintenant.date().isoformat()
    dates = []
    for d, bs in sorted((cours.get(INDICE) or {}).items()):
        if bs and bs[-1]["heure"] == REGLES["fermeture"]:
            if d < aujourd or (d == aujourd and (maintenant.hour, maintenant.minute) >= (16, 30)):
                dates.append(d)
    return dates


def mettre_a_jour(etat, cours, maintenant=None, stop_actif=False):
    dates = seances_terminees(cours, maintenant)
    if not dates:
        return []
    if etat["derniere_date"] is None:
        a_jouer = [dates[-1]]
        etat["date_debut"] = dates[-1]
    else:
        a_jouer = [d for d in dates if d > etat["derniere_date"]]
    for d in a_jouer:
        barres = {s: j[d] for s, j in cours.items() if d in j and j[d]}
        spy = barres.get(INDICE)
        if etat["parts_indice"] is None and spy:
            etat["parts_indice"] = REGLES["capital_depart"] / spy[0]["open"]
        ops = [] if stop_actif else jouer_seance(d, barres, etat["capital"])
        pnl = round(sum(o["pnl"] for o in ops), 2)
        etat["capital"] = round(etat["capital"] + pnl, 2)
        etat["operations"].extend(ops)
        etat["historique"].append({"date": d, "pnl": pnl, "valeur": etat["capital"], "nb": len(ops),
                                   "indice": round(etat["parts_indice"] * spy[-1]["close"], 2) if spy else None,
                                   "stop_actif": stop_actif})
        etat["derniere_date"] = d
    return a_jouer


def resume(etat):
    ops, h = etat["operations"], etat["historique"]
    dep = REGLES["capital_depart"]
    v = etat["capital"]
    ind = next((x["indice"] for x in reversed(h) if x["indice"]), dep)
    gagn = [o for o in ops if o["pnl"] > 0]
    pic, dd = dep, 0.0
    for x in h:
        pic = max(pic, x["valeur"])
        dd = max(dd, (pic - x["valeur"]) / pic)
    perf, perf_ind = v / dep - 1, ind / dep - 1

    def pc(x):
        r = round(x * 100, 1)
        return "0,0 %" if r == 0 else f"{r:+.1f} %".replace(".", ",")
    if not h:
        verdict = "Pas encore de séance jouée."
    else:
        ecart = (perf - perf_ind) * 100
        verdict = ("Équivalent à garder l'indice" if abs(ecart) < 1 else
                   "Fait mieux que garder l'indice" if ecart > 0 else "Fait moins bien que garder l'indice")
        verdict += f" : day trading {pc(perf)}, indice S&P 500 {pc(perf_ind)}."
        if len(ops) < 100:
            verdict += f" {len(ops)} opération(s) seulement : il en faut au moins 100 pour conclure."
    return {"valeur": v, "indice": ind, "perf": perf, "perf_indice": perf_ind, "nb": len(ops),
            "reussite": len(gagn) / len(ops) if ops else None,
            "r_moyen": sum(o["r"] for o in ops) / len(ops) if ops else None,
            "frais": sum(o["frais"] for o in ops), "drawdown_max": dd, "verdict": verdict,
            "jours": len(h), "jours_gagnants": sum(1 for x in h if x["pnl"] > 0)}


def executer_daytrading(chemin_etat, dossier_page, dossier_stop, telecharger=None, maintenant=None,
                        bavard=True, cours=None):
    from .suivi_daytrading import generer_page_daytrading
    etat = charger_etat(chemin_etat)
    stop = os.path.exists(os.path.join(dossier_stop, "STOP"))
    if cours is None:
        cours, erreurs = telecharger_5min(telecharger)
    else:
        erreurs = []
    joues = []
    if INDICE not in cours:
        erreurs.insert(0, "cours 5 minutes de l'indice indisponibles : séance non jouée")
    else:
        joues = mettre_a_jour(etat, cours, maintenant, stop)
    etat["derniere_execution"] = (maintenant or datetime.now()).strftime("%Y-%m-%d %H:%M")
    etat["erreurs"] = erreurs[:10]
    etat["stop_actif"] = stop
    sauver_etat(etat, chemin_etat)
    r = resume(etat)
    generer_page_daytrading(etat, r, dossier_page, erreurs)
    if bavard:
        print(f"Day trading : {len(joues)} séance(s) jouée(s) ({', '.join(joues) or 'aucune nouvelle'}) | "
              f"capital {r['valeur']:.2f} $ ({r['perf']:+.1%}) vs indice {r['perf_indice']:+.1%} | "
              f"{r['nb']} opérations" + (f" | {len(erreurs)} erreur(s)" if erreurs else ""))
    return etat, joues, erreurs
