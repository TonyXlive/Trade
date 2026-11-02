"""Point d'entrée.

    python -m bot.main                          # simulation de 90 jours, config.json
    python -m bot.main --jours 30 --graine 7
    python -m bot.main --monte-carlo 100        # rejoue 100 fois pour voir la variance
    python -m bot.main --config config_optimiste.json
    python -m bot.main --bavard                 # affiche chaque journée
"""
import argparse
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from bot.simulation import Simulation  # noqa: E402
from bot.rapport import tout_ecrire  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Simulateur de bot de trading sur marchés prédictifs (argent fictif)")
    ap.add_argument("--config", default=os.path.join(RACINE, "config.json"))
    ap.add_argument("--jours", type=int)
    ap.add_argument("--graine", type=int)
    ap.add_argument("--monte-carlo", type=int, default=0, help="nombre de simulations supplémentaires")
    ap.add_argument("--sortie", default=os.path.join(RACINE, "sortie"))
    ap.add_argument("--bavard", action="store_true")
    a = ap.parse_args(argv)

    with open(a.config, encoding="utf-8") as f:
        cfg = json.load(f)

    sim = Simulation(cfg, graine=a.graine, dossier_stop=RACINE, bavard=a.bavard)
    res = sim.lancer(a.jours)

    mc = None
    if a.monte_carlo > 0:
        base = a.graine if a.graine is not None else cfg["graine_aleatoire"]
        mc = []
        for i in range(a.monte_carlo):
            mc.append(Simulation(cfg, graine=base + 1000 + i, dossier_stop=RACINE).lancer(a.jours))
            if (i + 1) % 10 == 0 or i + 1 == a.monte_carlo:
                print(f"Monte-Carlo : {i+1}/{a.monte_carlo}", flush=True)
        print()

    tout_ecrire(sim, res, a.sortie, mc, os.path.basename(a.config))

    print("\n=== Résultat (argent fictif) ===")
    print(f"Capital         : {res['capital_depart']:.2f} -> {res['valeur_finale']:.2f} ({res['rendement']:+.1%})")
    print(f"Transactions    : {res['nb_transactions']}  | réussite {res['taux_reussite']:.0%}")
    print(f"Sharpe          : {res['sharpe']:.2f}  | baisse max {res['drawdown_max']:.1%}")
    if res["brier_modele"] is not None:
        print(f"Brier modèles   : {res['brier_modele']:.4f}  | marché {res['brier_marche']:.4f}")
    if res["bloque_drawdown_jour"]:
        print(f"Nouveaux ordres bloqués à partir du jour {res['bloque_drawdown_jour']} (baisse max dépassée)")
    if mc:
        rs = sorted(r["rendement"] for r in mc)
        print(f"Monte-Carlo     : médiane {rs[len(rs)//2]:+.1%} | "
              f"{sum(r < 0 for r in rs)}/{len(rs)} simulations en perte")
    print(f"\nRapport : {os.path.join(a.sortie, 'rapport.html')}")
    return res


if __name__ == "__main__":
    main()
