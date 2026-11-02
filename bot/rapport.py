"""Génération des sorties : rapport HTML, journal CSV, journal des erreurs."""
import csv
import html
import os
from datetime import datetime


def _pct(x, d=1):
    return "—" if x is None else f"{x*100:+.{d}f} %" if x < 0 or x > 0 else f"{x*100:.{d}f} %"


def _num(x, d=2):
    if x is None:
        return "—"
    if x == float("inf"):
        return "∞"
    return f"{x:,.{d}f}".replace(",", "\u202f")  # espace fine insécable


def courbe_svg(valeurs, depart, largeur=760, hauteur=220):
    if len(valeurs) < 2:
        return ""
    mn, mx = min(valeurs + [depart]), max(valeurs + [depart])
    if mx == mn:
        mx = mn + 1
    pad = 10

    def xy(i, v):
        x = pad + i * (largeur - 2 * pad) / (len(valeurs) - 1)
        y = hauteur - pad - (v - mn) * (hauteur - 2 * pad) / (mx - mn)
        return x, y

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(valeurs)))
    _, y0 = xy(0, depart)
    couleur = "var(--gain)" if valeurs[-1] >= depart else "var(--perte)"
    return (f'<svg viewBox="0 0 {largeur} {hauteur}" class="courbe" role="img" aria-label="Évolution du capital">'
            f'<line x1="{pad}" x2="{largeur-pad}" y1="{y0:.1f}" y2="{y0:.1f}" class="ref"/>'
            f'<polyline points="{pts}" fill="none" stroke="{couleur}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<text x="{pad}" y="{y0-6:.1f}" class="lib">capital de départ</text></svg>')


def histogramme_svg(rendements, largeur=760, hauteur=200, nb=20):
    mn, mx = min(rendements), max(rendements)
    if mx == mn:
        mx = mn + 0.01
    pas = (mx - mn) / nb
    comptes = [0] * nb
    for r in rendements:
        comptes[min(nb - 1, int((r - mn) / pas))] += 1
    haut = max(comptes)
    bw = (largeur - 20) / nb
    barres = []
    for i, c in enumerate(comptes):
        centre = mn + (i + 0.5) * pas
        h = (hauteur - 40) * c / haut if haut else 0
        cls = "b-gain" if centre >= 0 else "b-perte"
        barres.append(f'<rect x="{10+i*bw+1:.1f}" y="{hauteur-25-h:.1f}" width="{bw-2:.1f}" height="{h:.1f}" '
                      f'class="{cls}"><title>{centre*100:+.0f} % : {c} simulation(s)</title></rect>')
    return (f'<svg viewBox="0 0 {largeur} {hauteur}" class="courbe" role="img" aria-label="Répartition des résultats">'
            + "".join(barres)
            + f'<text x="10" y="{hauteur-6}" class="lib">{mn*100:+.0f} %</text>'
            + f'<text x="{largeur-10}" y="{hauteur-6}" class="lib" text-anchor="end">{mx*100:+.0f} %</text></svg>')


STYLE = """
:root{--fond:#f6f5f1;--carte:#fff;--texte:#1d1d1b;--doux:#6b6a65;--bord:#e4e2dc;--gain:#1f7a4d;--perte:#b3362f;--accent:#2f5d8a;--alerte:#fff4d6;--alerte-bord:#e0b84a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fond:#151514;--carte:#1f1f1d;--texte:#eceae4;--doux:#a19f98;--bord:#33322f;--gain:#4cc38a;--perte:#ef6f66;--accent:#7fb0e0;--alerte:#3a3220;--alerte-bord:#8a7333}}
:root[data-theme="dark"]{--fond:#151514;--carte:#1f1f1d;--texte:#eceae4;--doux:#a19f98;--bord:#33322f;--gain:#4cc38a;--perte:#ef6f66;--accent:#7fb0e0;--alerte:#3a3220;--alerte-bord:#8a7333}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 60px}h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.1rem;margin:32px 0 10px}
.sous{color:var(--doux);margin:0 0 18px}.alerte{background:var(--alerte);border:1px solid var(--alerte-bord);border-radius:10px;padding:12px 14px;margin:16px 0}
.grille{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:12px}.kpi b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}
.kpi span{color:var(--doux);font-size:.85rem}.g{color:var(--gain)}.p{color:var(--perte)}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:10px;padding:14px}
.courbe{width:100%;height:auto;display:block}.ref{stroke:var(--doux);stroke-dasharray:4 4;stroke-width:1}.lib{fill:var(--doux);font-size:12px}
.b-gain{fill:var(--gain)}.b-perte{fill:var(--perte)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.9rem}th,td{padding:6px 8px;border-bottom:1px solid var(--bord);text-align:left}
th{color:var(--doux);font-weight:600}.defil{overflow-x:auto}td.n,th.n{text-align:right}ul{padding-left:20px}
"""


def generer_html(res: dict, courbe: list, transactions: list, chemin: str, monte_carlo: list = None, nom_config=""):
    dep = res["capital_depart"]
    verdict_brier = ""
    if res["brier_modele"] is not None:
        mieux = res["brier_modele"] < res["brier_marche"]
        verdict_brier = ("Vos prédictions sont <b>plus précises</b> que le prix du marché."
                         if mieux else
                         "Vos prédictions <b>ne sont pas plus précises</b> que le prix du marché : "
                         "sans cet avantage, le bot ne peut pas gagner durablement.")

    alertes = []
    if res["bloque_drawdown_jour"]:
        alertes.append(f"Les nouveaux ordres ont été <b>bloqués à partir du jour {res['bloque_drawdown_jour']}</b>, "
                       f"tant que la perte depuis le plus haut dépassait la limite. Les positions déjà ouvertes "
                       f"continuent jusqu'à leur échéance : c'est pourquoi la baisse maximale peut dépasser la limite.")
    if res["positions_ouvertes_fin"]:
        alertes.append(f"{res['positions_ouvertes_fin']} position(s) encore ouvertes en fin de simulation, "
                       f"valorisées au prix du marché.")
    if res["arret_stop"]:
        alertes.append("Le fichier <b>STOP</b> a été détecté : aucun nouvel ordre n'a été passé.")

    kpis = [
        ("Résultat", _pct(res["rendement"]), "g" if res["rendement"] >= 0 else "p"),
        ("Valeur finale", _num(res["valeur_finale"]) + " €", ""),
        ("Transactions", str(res["nb_transactions"]), ""),
        ("Taux de réussite", f"{res['taux_reussite']*100:.0f} %", ""),
        ("Ratio de Sharpe", _num(res["sharpe"]), "g" if res["sharpe"] >= 2 else ""),
        ("Baisse maximale", f"{res['drawdown_max']*100:.1f} %", "p" if res["drawdown_max"] > 0.08 else ""),
        ("Facteur de profit", _num(res["facteur_profit"]), "g" if res["facteur_profit"] >= 1.5 else ""),
        ("Coût IA simulé", _num(res["cout_ia_total"]) + " €", ""),
    ]

    lignes_calib = "".join(
        f"<tr><td>{t['tranche']}</td><td class='n'>{t['n']}</td><td class='n'>{t['prevu']*100:.0f} %</td>"
        f"<td class='n'>{t['observe']*100:.0f} %</td></tr>" for t in res["calibration"])
    causes = "".join(f"<li>{html.escape(k)} : {v}</li>" for k, v in
                     sorted(res["causes_pertes"].items(), key=lambda kv: -kv[1])) or "<li>Aucune perte.</li>"
    refus = "".join(f"<li>{html.escape(k)} : {v}</li>" for k, v in
                    sorted(res["refus"].items(), key=lambda kv: -kv[1])) or "<li>Aucun refus.</li>"
    lecons = "".join(f"<li>Jour {l['jour']} — {html.escape(l['lecon'])}</li>" for l in res["lecons"]) \
        or "<li>Aucune leçon enregistrée (pas assez de données ou aucune catégorie problématique).</li>"

    lignes_tx = "".join(
        f"<tr><td>{t['id']}</td><td>{t['jour_entree']}</td><td>{html.escape(t['categorie'])}</td><td>{t['cote']}</td>"
        f"<td class='n'>{t['prix_effectif']:.2f}</td><td class='n'>{t['proba_cote']*100:.0f} %</td>"
        f"<td class='n'>{_num(t['mise'])}</td><td>{t['resultat']}</td>"
        f"<td class='n {'g' if (t['pnl'] or 0) > 0 else 'p'}'>{_num(t['pnl']) if t['pnl'] is not None else '—'}</td></tr>"
        for t in transactions)

    bloc_mc = ""
    if monte_carlo:
        rs = sorted(r["rendement"] for r in monte_carlo)
        n = len(rs)
        perdants = sum(1 for r in rs if r < 0)
        bloc_mc = (f"<h2>Le même bot rejoué {n} fois</h2><div class='carte'>"
                   f"<p>Même stratégie, hasard différent. Résultat médian : <b>{_pct(rs[n//2])}</b> — "
                   f"pire : {_pct(rs[0])} — meilleur : {_pct(rs[-1])}. "
                   f"<b>{perdants} simulation(s) sur {n}</b> finissent en perte.</p>"
                   f"{histogramme_svg(rs)}<p class='sous'>Un seul backtest « gagnant » ne prouve rien : "
                   f"regardez toujours la répartition.</p></div>")

    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Rapport de simulation</title>
<style>{STYLE}</style></head><body><main>
<h1>Rapport de simulation</h1>
<p class="sous">Argent fictif, marchés fictifs. Généré le {datetime.now():%d/%m/%Y à %H:%M} — configuration : {html.escape(nom_config)} — graine {res.get('graine')} (même graine = mêmes résultats)</p>
{''.join(f'<div class="alerte">{a}</div>' for a in alertes)}
<div class="grille">{''.join(f'<div class="kpi"><b class="{c}">{v}</b><span>{k}</span></div>' for k, v, c in kpis)}</div>
<div class="carte" style="margin-top:10px"><b>Verdict.</b> {html.escape(res['verdict']['texte'])}</div>
<h2>Évolution du capital</h2><div class="carte">{courbe_svg(courbe, dep)}</div>
<h2>Êtes-vous meilleur que le marché ?</h2><div class="carte">
<p>Score de Brier (plus bas = meilleur) sur {res['nb_predictions']} marchés résolus : vos modèles <b>{_num(res['brier_modele'], 4)}</b>
contre <b>{_num(res['brier_marche'], 4)}</b> pour le prix du marché.</p><p>{verdict_brier}</p>
<div class="defil"><table><tr><th>Prévision</th><th class="n">Marchés</th><th class="n">Prévu</th><th class="n">Réalisé</th></tr>{lignes_calib}</table></div></div>
<h2>Pourquoi les pertes</h2><div class="carte"><ul>{causes}</ul></div>
<h2>Ordres refusés par le contrôle de risque</h2><div class="carte"><ul>{refus}</ul></div>
<h2>Leçons retenues par le bot</h2><div class="carte"><ul>{lecons}</ul></div>
{bloc_mc}
<h2>Transactions</h2><div class="carte defil"><table>
<tr><th>N°</th><th>Jour</th><th>Catégorie</th><th>Côté</th><th class="n">Prix</th><th class="n">Proba estimée</th><th class="n">Mise</th><th>Issue</th><th class="n">Gain/perte</th></tr>
{lignes_tx}</table></div>
</main></body></html>"""
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)


def ecrire_csv(transactions: list, chemin: str):
    champs = ["id", "jour_entree", "jour_sortie", "marche", "categorie", "question", "cote", "prix_effectif",
              "contrats", "mise", "proba_cote", "avantage", "kelly_complet", "slippage", "resultat", "pnl", "cause_perte"]
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=champs, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for t in transactions:
            w.writerow({k: t.get(k, "") for k in champs})


def ecrire_failure_log(transactions: list, lecons: list, chemin: str):
    pertes = [t for t in transactions if t.get("cause_perte")]
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("# Journal des erreurs et leçons\n\n")
        f.write("Fichier consulté avant chaque nouvelle analyse. Généré par la simulation.\n\n## Leçons\n\n")
        for l in lecons:
            f.write(f"- Jour {l['jour']} : {l['lecon']}\n")
        if not lecons:
            f.write("- Aucune leçon pour l'instant.\n")
        f.write("\n## Pertes\n\n| N° | Jour | Catégorie | Côté | Mise | Perte | Cause |\n|---|---|---|---|---|---|---|\n")
        for t in pertes:
            f.write(f"| {t['id']} | {t['jour_entree']} | {t['categorie']} | {t['cote']} | {t['mise']:.2f} | "
                    f"{t['pnl']:.2f} | {t['cause_perte']} |\n")


def tout_ecrire(sim, res, dossier, monte_carlo=None, nom_config=""):
    os.makedirs(dossier, exist_ok=True)
    generer_html(res, sim.courbe, sim.transactions, os.path.join(dossier, "rapport.html"), monte_carlo, nom_config)
    ecrire_csv(sim.transactions, os.path.join(dossier, "transactions.csv"))
    ecrire_failure_log(sim.transactions, res["lecons"], os.path.join(dossier, "failure_log.md"))
