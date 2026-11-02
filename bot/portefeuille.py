"""Portefeuille fictif en continu : 1 journée simulée par jour réel.

    python -m bot.portefeuille                 # avance jusqu'à aujourd'hui, met à jour la page
    python -m bot.portefeuille --nouveau       # repart de zéro (efface le portefeuille)
    python -m bot.portefeuille --statut        # affiche l'état sans avancer

Le portefeuille est sauvegardé dans etat/. Si le programme n'a pas tourné
pendant quelques jours, il rattrape les journées manquées. Lancé deux fois
le même jour, il ne fait rien la deuxième fois.
"""
import argparse
import gzip
import json
import os
import pickle
import sys
from datetime import date, datetime, timedelta

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from bot.simulation import Simulation  # noqa: E402
from bot.suivi import generer_page_suivi  # noqa: E402

DOSSIER_ETAT = os.path.join(RACINE, "etat")
FICHIER_SIM = os.path.join(DOSSIER_ETAT, "simulation.pkl.gz")
FICHIER_META = os.path.join(DOSSIER_ETAT, "meta.json")
DOSSIER_PAGE = os.path.join(RACINE, "docs")
VERSION_ETAT = 1


def aujourd_hui() -> date:
    """Date du jour à Paris (repli sur UTC si les fuseaux ne sont pas installés)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        return datetime.utcnow().date()


def charger_config(chemin=None):
    with open(chemin or os.path.join(RACINE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def sauvegarder(sim, meta, dossier=DOSSIER_ETAT):
    os.makedirs(dossier, exist_ok=True)
    tmp = os.path.join(dossier, "simulation.pkl.gz.tmp")
    try:
        with gzip.open(tmp, "wb") as f:
            pickle.dump(sim, f)
    except Exception:
        os.remove(tmp)
        raise
    os.replace(tmp, os.path.join(dossier, "simulation.pkl.gz"))  # écriture atomique : jamais de fichier à moitié écrit
    with open(os.path.join(dossier, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def charger(dossier=DOSSIER_ETAT):
    fs, fm = os.path.join(dossier, "simulation.pkl.gz"), os.path.join(dossier, "meta.json")
    if not (os.path.exists(fs) and os.path.exists(fm)):
        return None, None
    with gzip.open(fs, "rb") as f:
        sim = pickle.load(f)
    with open(fm, encoding="utf-8") as f:
        meta = json.load(f)
    return sim, meta


def nouveau_portefeuille(cfg, date_debut: date, graine=None):
    graine = int(datetime.now().timestamp()) % 1_000_000 if graine is None else graine
    sim = Simulation(cfg, graine=graine, dossier_stop=RACINE)
    meta = {"version": VERSION_ETAT, "date_debut": date_debut.isoformat(), "dernier_jour": 0,
            "graine": graine, "capital_depart": cfg["capital_depart"], "dates": {}}
    return sim, meta


def date_du_jour_simule(meta, j: int) -> date:
    return date.fromisoformat(meta["date_debut"]) + timedelta(days=j - 1)


def avancer(sim, meta, jusqu_au: date, max_rattrapage: int = 60) -> int:
    """Joue toutes les journées manquantes jusqu'à la date donnée. Retourne le nombre de jours joués."""
    cible = (jusqu_au - date.fromisoformat(meta["date_debut"])).days + 1
    joues = 0
    while meta["dernier_jour"] < cible and joues < max_rattrapage:
        j = meta["dernier_jour"] + 1
        sim.jour(j)
        meta["dernier_jour"] = j
        meta["dates"][str(j)] = date_du_jour_simule(meta, j).isoformat()
        joues += 1
    meta["derniere_execution"] = datetime.now().isoformat(timespec="seconds")
    return joues


def executer(nouveau=False, statut=False, dossier_etat=DOSSIER_ETAT, dossier_page=DOSSIER_PAGE,
             date_jour=None, graine=None, config=None, bavard=True, dossier_stop=RACINE):
    cfg = charger_config(config)
    date_jour = date_jour or aujourd_hui()
    sim, meta = (None, None) if nouveau else charger(dossier_etat)
    cree = False
    if sim is None:
        sim, meta = nouveau_portefeuille(cfg, date_jour, graine)
        cree = True
    sim.dossier_stop = dossier_stop  # le dossier peut changer d'un ordinateur à l'autre

    joues = 0 if statut else avancer(sim, meta, date_jour)
    if not statut or cree:
        sauvegarder(sim, meta, dossier_etat)
    generer_page_suivi(sim, meta, dossier_page)

    if bavard:
        v = sim.courbe[-1]
        dep = meta["capital_depart"]
        if cree:
            print(f"Nouveau portefeuille fictif de {dep:.0f} € créé le {meta['date_debut']}.")
        print(f"Journée {meta['dernier_jour']} | {joues} journée(s) jouée(s) | "
              f"valeur {v:.2f} € ({v/dep-1:+.1%}) | positions ouvertes {len(sim.positions)}")
        if sim.arret_stop:
            print("Fichier STOP présent : aucun nouvel ordre.")
        print(f"Page de suivi : {os.path.join(dossier_page, 'index.html')}")
    return sim, meta, joues


def main(argv=None):
    ap = argparse.ArgumentParser(description="Portefeuille fictif en continu")
    ap.add_argument("--nouveau", action="store_true", help="efface le portefeuille et repart de zéro")
    ap.add_argument("--statut", action="store_true", help="met à jour la page sans avancer")
    ap.add_argument("--sans-actions", action="store_true", help="ne pas mettre à jour le portefeuille sur actions réelles")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    executer(nouveau=a.nouveau, statut=a.statut, config=a.config)
    if not a.sans_actions and not a.statut:
        # Un problème de données sur les actions réelles ne doit jamais bloquer le reste
        try:
            from bot.actions_reelles import executer_actions
            executer_actions(os.path.join(DOSSIER_ETAT, "actions.json"), DOSSIER_PAGE, RACINE)
        except Exception as e:  # noqa: BLE001
            print(f"Actions réelles : échec ({e}). Le portefeuille sur marchés fictifs est à jour.")


if __name__ == "__main__":
    main()
