"""Page « Day trading »."""
import html
import os
from datetime import date

from .rapport import STYLE, _num
from .actions_reelles import nom
from .daytrading import REGLES, SYMBOLES
from .suivi import STYLE_SUIVI, MOIS_COURT, date_fr, _signe, _classe, NAV
from .suivi import _ligne_evt as _ligne_base
from .suivi_actions import STYLE_ACTIONS, courbes_svg


def _d(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MOIS_COURT[d.month-1]}"


def _quand(x):
    if not x or len(x) < 16:
        return "—"
    return f"{x[8:10]}/{x[5:7]}/{x[:4]} à {x[11:16]}"


def _pct(x):
    v = round(x * 100, 1)
    return "0,0 %" if v == 0 else f"{v:+.1f} %".replace(".", ",")


def _evt(titre, detail, montant=None):
    return _ligne_base(titre, detail, montant, " $")


def _h(x):
    return x.replace(":", " h ")


def _operation(o):
    sens = "Achat puis revente" if o["cote"] == "hausse" else "Vente à découvert puis rachat"
    detail = (f"{sens} · {o['actions']} action{'s' if o['actions'] > 1 else ''}<br>"
              f"entrée à {_h(o['heure_entree'])} à {o['prix_entree']:.2f} $ → sortie à {_h(o['heure_sortie'])} "
              f"à {o['prix_sortie']:.2f} $<br>{html.escape(o['motif'])} · {o['r']:+.2f} R")
    return _evt(html.escape(nom(o["symbole"])), detail, o["pnl"])


def generer_page_daytrading(etat, r, dossier, erreurs):
    os.makedirs(dossier, exist_ok=True)
    h = etat["historique"]
    dern = h[-1] if h else None

    alertes = []
    if etat.get("stop_actif"):
        alertes.append("Fichier <b>STOP</b> présent : aucune opération.")
    if erreurs:
        alertes.append("Données incomplètes au dernier lancement : " + html.escape(" ; ".join(erreurs[:3])))
    if not h:
        alertes.append("Aucune séance jouée pour l'instant.")

    ops_jour = [o for o in etat["operations"] if dern and o["date"] == dern["date"]]
    bloc_jour = "".join(_operation(o) for o in ops_jour) or \
        "<p class='vide'>Aucune opération : aucune cassure assez nette ce jour-là.</p>"

    kpis = [
        ("Opérations", str(r["nb"]), ""),
        ("Taux de réussite", f"{r['reussite']*100:.0f} %" if r["reussite"] is not None else "—", ""),
        ("Gain moyen en R", f"{r['r_moyen']:+.2f}" if r["r_moyen"] is not None else "—", _classe(r["r_moyen"] or 0)),
        ("Jours gagnants", f"{r['jours_gagnants']} / {r['jours']}", ""),
        ("Frais payés", f"{_num(r['frais'], 0)} $", ""),
        ("Baisse maximale", f"{r['drawdown_max']*100:.1f} %".replace(".", ","), ""),
    ]

    jours = []
    for x in reversed(h[-40:]):
        ops = [o for o in etat["operations"] if o["date"] == x["date"]]
        detail = ", ".join(f"{o['symbole']} {'↑' if o['cote'] == 'hausse' else '↓'} {o['pnl']:+.0f}" for o in ops) \
            or "aucune opération"
        jours.append(_evt(f"{_d(x['date'])} · capital {_num(x['valeur'])} $", html.escape(detail), x["pnl"]))
    bloc_jours = "".join(jours) or "<p class='vide'>Pas encore d'historique.</p>"

    histo = [{"valeur": x["valeur"], "indice": x["indice"]} for x in h]
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Day trading</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icone.svg"><meta name="theme-color" content="#2f5d8a">
<style>{STYLE}{STYLE_SUIVI}{STYLE_ACTIONS}</style></head><body><main>
{NAV.format(a1="", a2="", a3="", a4="actif")}
<div class="tete"><h1>Day trading</h1><span class="badge">cours réels · argent fictif</span></div>
<p class="sous">Séance du {date_fr(date.fromisoformat(dern['date'])) if dern else '—'} · mis à jour le {_quand(etat.get('derniere_execution'))}</p>
{''.join(f'<div class="alerte">{a}</div>' for a in alertes)}
<div class="carte"><div class="sous" style="margin:0">Capital</div>
<div class="valeur">{_num(r['valeur'])} $</div>
<div><span class="var {_classe(dern['pnl'] if dern else 0)}">{_signe(dern['pnl'] if dern else 0, ' $')} à la dernière séance</span> ·
<span class="var {_classe(r['perf'])}">{_pct(r['perf'])} depuis le début</span></div>
<p class="sous" style="margin:6px 0 0">Avec 10 000 $ simplement placés sur l'indice : {_num(r['indice'])} $ ({_pct(r['perf_indice'])})</p></div>
<div class="carte" style="margin-top:10px"><b>Verdict.</b> {html.escape(r['verdict'])}</div>
<h2>Opérations de la dernière séance</h2><div class="carte">{bloc_jour}</div>
<h2>Day trading contre indice</h2><div class="carte">{courbes_svg(histo, REGLES['capital_depart'])}</div>
<div class="grille" style="margin-top:10px">{''.join(f'<div class="kpi"><b class="{c}">{v}</b><span>{k}</span></div>' for k, v, c in kpis)}</div>
<h2>Séance par séance</h2><div class="carte">{bloc_jours}</div>
<h2>La règle suivie</h2><div class="carte"><ul>
<li>Chaque séance est rejouée barre de 5 minutes après barre de 5 minutes, sur les vrais cours, sans jamais regarder la suite.</li>
<li>Range d'ouverture = plus haut et plus bas des 15 premières minutes : 9 h 30 – 9 h 45 à New York, soit 15 h 30 – 15 h 45 à Paris la plupart de l'année.</li>
<li>Si une barre de 5 minutes clôture au-dessus du range : achat. En dessous : vente à découvert (pari à la baisse). Exécution à l'ouverture de la barre suivante.</li>
<li>Stop au milieu du range, objectif à 2 fois le risque. Tout est fermé à 15 h 55 à New York (21 h 55 à Paris) : rien n'est gardé la nuit.</li>
<li>Une opération par action et par jour, aucune entrée après 11 h 30 à New York (17 h 30 à Paris), 4 positions au maximum, 0,5 % du capital risqué par opération, plus d'entrée si la journée perd 2 %.</li>
<li>Frais : 1 $ par ordre et 0,02 % de glissement de prix à chaque exécution. Si le stop et l'objectif sont touchés dans les mêmes 5 minutes, on compte le stop.</li>
<li>Actions suivies : {', '.join(html.escape(nom(s)) for s in SYMBOLES)}.</li>
</ul></div>
<p class="sous" style="margin-top:24px">Démarré le {_d(etat['date_debut']) if etat.get('date_debut') else '—'} avec 10 000 $ fictifs.
Cours : Yahoo Finance, barres de 5 minutes. Aucun ordre réel. Ceci n'est pas un conseil en investissement.</p>
</main></body></html>"""
    with open(os.path.join(dossier, "daytrading.html"), "w", encoding="utf-8") as f:
        f.write(page)
