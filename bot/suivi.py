"""Page de suivi quotidienne du portefeuille fictif (pensée pour le téléphone)."""
import csv
import html
import json
import os
from datetime import date, datetime, timedelta

from .rapport import STYLE, courbe_svg, _num

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
MOIS_COURT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

NAV = ('<nav class="onglets"><a href="index.html" class="{a1}">Marchés fictifs</a>'
       '<a href="actions.html" class="{a2}">Actions réelles</a>'
       '<a href="mensuel.html" class="{a3}">Mes 50 €/mois</a></nav>')

STYLE_SUIVI = """
.onglets{display:flex;gap:6px;margin:0 0 14px}.onglets a{flex:1;text-align:center;padding:8px 6px;line-height:1.2;border-radius:99px;
border:1px solid var(--bord);color:var(--texte);text-decoration:none;font-size:.9rem;background:var(--carte)}
.onglets a.actif{background:var(--accent);border-color:var(--accent);color:#fff}
.tete{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.valeur{font-size:2.4rem;font-weight:700;font-variant-numeric:tabular-nums;margin:6px 0 0}
.var{font-size:1rem;font-weight:600}.badge{display:inline-block;font-size:.75rem;padding:2px 8px;border-radius:99px;
border:1px solid var(--bord);color:var(--doux)}
.evt{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--bord)}
.evt:last-child{border-bottom:0}.evt>div:last-child{white-space:nowrap;text-align:right}
td.n{white-space:nowrap}.evt small{color:var(--doux);display:block}.vide{color:var(--doux);margin:4px 0}
details summary{cursor:pointer;color:var(--accent);margin-top:8px}
a{color:var(--accent)}
"""


def date_fr(d: date, avec_jour=True) -> str:
    base = f"{d.day} {MOIS[d.month-1]} {d.year}"
    return f"{JOURS[d.weekday()]} {base}" if avec_jour else base


def _signe(x, suffixe=" €"):
    return f"{'+' if x > 0 else ''}{_num(x)}{suffixe}"


def _classe(x):
    return "g" if x > 0 else "p" if x < 0 else ""


def _date_jour(meta, j):
    d = meta["dates"].get(str(j))
    return date.fromisoformat(d) if d else None


def _ligne_evt(titre, detail, montant=None, devise=" €"):
    m = f"<b class='{_classe(montant)}'>{_signe(montant, devise)}</b>" if montant is not None else ""
    return f"<div class='evt'><div>{titre}<small>{detail}</small></div><div>{m}</div></div>"


def generer_page_suivi(sim, meta, dossier: str):
    os.makedirs(dossier, exist_ok=True)
    j = meta["dernier_jour"]
    dep = meta["capital_depart"]
    valeur = sim.courbe[-1]
    veille = sim.courbe[-2] if len(sim.courbe) > 1 else dep
    var_jour = valeur - veille
    dd_actuel = (sim.pic - valeur) / sim.pic if sim.pic else 0
    regles = sim.cfg["risque"]
    d_jour = _date_jour(meta, j) or date.fromisoformat(meta["date_debut"])

    alertes = []
    if sim.arret_stop:
        alertes.append("Fichier <b>STOP</b> présent : le bot ne passe plus de nouvel ordre. Supprimez-le pour reprendre.")
    if dd_actuel > regles["max_drawdown"]:
        alertes.append(f"Baisse de <b>{dd_actuel*100:.1f} %</b> depuis le plus haut : nouveaux ordres suspendus "
                       f"tant qu'elle dépasse {regles['max_drawdown']*100:.0f} %.")
    if j == 0:
        alertes.append("Portefeuille créé : la première journée sera jouée au prochain lancement.")

    # --- Aujourd'hui ---
    ouverts = [t for t in sim.transactions if t["jour_entree"] == j]
    fermes = [t for t in sim.transactions if t.get("jour_sortie") == j]
    evts = []
    for t in fermes:
        lib = {"gagné": "Gagné", "perdu": "Perdu", "coupé": "Coupé avant échéance"}.get(t["resultat"], t["resultat"])
        evts.append(_ligne_evt(f"{lib} — {html.escape(t['question'])}",
                               f"{t['cote']} · mise {_num(t['mise'])} €"
                               + (f" · {html.escape(t['cause_perte'])}" if t.get("cause_perte") else ""), t["pnl"]))
    for t in ouverts:
        evts.append(_ligne_evt(f"Nouvel ordre — {html.escape(t['question'])}",
                               f"{t['cote']} à {t['prix_effectif']:.2f} · mise {_num(t['mise'])} € · "
                               f"proba estimée {t['proba_cote']*100:.0f} %"))
    bloc_jour = "".join(evts) or "<p class='vide'>Aucun mouvement aujourd'hui.</p>"

    # --- Positions ouvertes ---
    lignes_pos, exposition, latent_total = [], 0.0, 0.0
    for p in sorted(sim.positions, key=lambda p: sim.marches[p["marche"]].jour_echeance):
        m = sim.marches[p["marche"]]
        prix = m.prix if p["cote"] == "OUI" else 1 - m.prix
        latent = p["contrats"] * prix - p["mise"]
        exposition += p["mise"]
        latent_total += latent
        ech = date.fromisoformat(meta["date_debut"]) + timedelta(days=m.jour_echeance - 1)
        lignes_pos.append(_ligne_evt(
            html.escape(m.question),
            f"{p['cote']} · {p['prix_effectif']:.2f} → {prix:.2f} · mise {_num(p['mise'], 0)} € · "
            f"échéance {ech.day} {MOIS_COURT[ech.month-1]}", latent))
    tab_pos = "".join(lignes_pos) or "<p class='vide'>Aucune position ouverte.</p>"

    # --- Indicateurs ---
    res = sim.resultats()
    brier = ("—" if res["brier_modele"] is None else
             "Meilleur" if res["brier_modele"] < res["brier_marche"] else "Pas meilleur")
    kpis = [
        ("Positions ouvertes", f"{len(sim.positions)}", ""),
        ("Argent engagé", f"{_num(exposition, 0)} €", ""),
        ("Transactions finies", f"{res['nb_transactions']}", ""),
        ("Taux de réussite", f"{res['taux_reussite']*100:.0f} %" if res["nb_transactions"] else "—", ""),
        ("Baisse maximale", f"{res['drawdown_max']*100:.1f} %", "p" if res["drawdown_max"] > regles["max_drawdown"] else ""),
        ("Précision vs marché", brier, ""),
    ]

    # --- Historique ---
    lignes_hist = []
    for jj in range(j, 0, -1):
        if j - jj >= 60:
            break
        v, vp = sim.courbe[jj], sim.courbe[jj - 1]
        info = sim.journal_jours[jj - 1] if jj - 1 < len(sim.journal_jours) else {}
        dj = _date_jour(meta, jj)
        lignes_hist.append(f"<tr><td>{jj}</td><td>{dj.day:02d}/{dj.month:02d}</td><td class='n'>{_num(v)}</td>"
                           f"<td class='n {_classe(v-vp)}'>{_signe(v-vp, '')}</td>"
                           f"<td class='n'>{info.get('ordres', 0)}</td></tr>")
    tab_hist = ("<div class='defil'><table><tr><th>Jour</th><th>Date</th><th class='n'>Valeur</th>"
                "<th class='n'>Variation</th><th class='n'>Ordres</th></tr>" + "".join(lignes_hist) + "</table></div>")

    lecons = "".join(f"<li>{_date_jour(meta, l['jour']).strftime('%d/%m') if _date_jour(meta, l['jour']) else 'Jour '+str(l['jour'])} — "
                     f"{html.escape(l['lecon'])}</li>" for l in res["lecons"]) or "<li>Pas encore assez de données.</li>"

    maj = datetime.now().strftime("%d/%m/%Y à %H:%M")
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Portefeuille fictif</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icone.svg"><meta name="theme-color" content="#2f5d8a">
<style>{STYLE}{STYLE_SUIVI}</style></head><body><main>
{NAV.format(a1="actif", a2="", a3="")}
<div class="tete"><h1>Marchés fictifs</h1><span class="badge">argent fictif</span></div>
<p class="sous">Journée {j} — {date_fr(d_jour)} · mis à jour le {maj}</p>
{''.join(f'<div class="alerte">{a}</div>' for a in alertes)}
<div class="carte"><div class="sous" style="margin:0">Valeur du portefeuille</div>
<div class="valeur">{_num(valeur)} €</div>
<div><span class="var {_classe(var_jour)}">{_signe(var_jour)} aujourd'hui</span> ·
<span class="var {_classe(valeur-dep)}">{(valeur/dep-1)*100:+.1f} % depuis le début</span></div></div>
<div class="carte" style="margin-top:10px"><b>Verdict.</b> {html.escape(res['verdict']['texte'])}</div>
<h2>Aujourd'hui</h2><div class="carte">{bloc_jour}</div>
<h2>Évolution</h2><div class="carte">{courbe_svg(sim.courbe, dep)}</div>
<div class="grille" style="margin-top:10px">{''.join(f'<div class="kpi"><b class="{c}">{v}</b><span>{k}</span></div>' for k, v, c in kpis)}</div>
<h2>Positions ouvertes <span class="sous">(latent total {_signe(latent_total)})</span></h2><div class="carte">{tab_pos}</div>
<h2>Leçons du bot</h2><div class="carte"><ul>{lecons}</ul></div>
<h2>Jour par jour</h2><div class="carte">{tab_hist}</div>
<p class="sous" style="margin-top:24px">Démarré le {date_fr(date.fromisoformat(meta['date_debut']), False)} avec {_num(dep, 0)} € fictifs.
Graine {meta['graine']}. Marchés fictifs, aucun ordre réel. <a href="historique.csv">Télécharger l'historique</a></p>
</main></body></html>"""

    with open(os.path.join(dossier, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(dossier, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "Portefeuille fictif", "short_name": "Portefeuille", "start_url": "./",
                   "display": "standalone", "background_color": "#f6f5f1", "theme_color": "#2f5d8a",
                   "icons": [{"src": "icone.svg", "sizes": "any", "type": "image/svg+xml"}]}, f, ensure_ascii=False)
    with open(os.path.join(dossier, "icone.svg"), "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
                'fill="#2f5d8a"/><polyline points="10,44 24,32 34,38 52,18" fill="none" stroke="#fff" '
                'stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    with open(os.path.join(dossier, "historique.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["jour", "date", "valeur", "variation", "ordres", "positions_ouvertes"])
        for jj in range(1, j + 1):
            info = sim.journal_jours[jj - 1]
            w.writerow([jj, meta["dates"].get(str(jj), ""), f"{sim.courbe[jj]:.2f}".replace(".", ","),
                        f"{sim.courbe[jj]-sim.courbe[jj-1]:.2f}".replace(".", ","), info["ordres"],
                        info["positions_ouvertes"]])
    # Fichier vide : empêche GitHub Pages de filtrer les fichiers
    open(os.path.join(dossier, ".nojekyll"), "w").close()
