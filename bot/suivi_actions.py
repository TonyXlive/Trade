"""Page de suivi du portefeuille fictif sur actions réelles."""
import html
import os
from datetime import date, datetime

from .rapport import STYLE, _num
from .actions_reelles import nom, comparer, criteres_prod, nom_regle, ADOPTION, CANDIDATS
from .suivi import STYLE_SUIVI, MOIS_COURT, date_fr, _signe, _classe, NAV
from .suivi import _ligne_evt as _ligne_evt_base


def _ligne_evt(titre, detail, montant=None):
    return _ligne_evt_base(titre, detail, montant, " $")


def _pct(x):
    """Pourcentage signé, sans « −0,0 % »."""
    v = round(x * 100, 1)
    return "0,0 %" if v == 0 else f"{v:+.1f} %".replace(".", ",")


def _actions(n):
    return f"{n} action" + ("s" if n > 1 else "")


def _d(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MOIS_COURT[d.month-1]}"


def courbes_svg(historique, depart, largeur=760, hauteur=220):
    pts_bot = [h["valeur"] for h in historique]
    pts_ind = [h["indice"] for h in historique if h["indice"]]
    if len(pts_bot) < 2:
        return "<p class='vide'>La courbe apparaîtra après quelques séances.</p>"
    toutes = pts_bot + pts_ind + [depart]
    mn, mx = min(toutes), max(toutes)
    mx = mx if mx > mn else mn + 1
    pad = 10

    def ligne(vals, classe):
        n = len(vals)
        p = " ".join(f"{pad + i*(largeur-2*pad)/(n-1):.1f},{hauteur-pad-(v-mn)*(hauteur-2*pad)/(mx-mn):.1f}"
                     for i, v in enumerate(vals))
        return f'<polyline points="{p}" fill="none" class="{classe}" stroke-width="2.5" stroke-linejoin="round"/>'

    y0 = hauteur - pad - (depart - mn) * (hauteur - 2 * pad) / (mx - mn)
    svg = (f'<svg viewBox="0 0 {largeur} {hauteur}" class="courbe" role="img" aria-label="Bot contre indice">'
           f'<line x1="{pad}" x2="{largeur-pad}" y1="{y0:.1f}" y2="{y0:.1f}" class="ref"/>'
           + (ligne(pts_ind, "l-ind") if len(pts_ind) >= 2 else "") + ligne(pts_bot, "l-bot") + "</svg>")
    return svg + ("<p class='sous' style='margin:6px 0 0'><span class='pastille bot'></span>le bot "
                  "<span class='pastille ind'></span>garder l'indice S&amp;P 500</p>")


STYLE_ACTIONS = """
.l-bot{stroke:var(--accent)}.l-ind{stroke:var(--doux);stroke-dasharray:5 4}
.pastille{display:inline-block;width:14px;height:3px;vertical-align:middle;margin:0 4px 0 8px;border-radius:2px}
.pastille.bot{background:var(--accent)}.pastille.ind{background:var(--doux)}
"""


def generer_page_actions(etat, res, dossier, erreurs_du_jour):
    os.makedirs(dossier, exist_ok=True)
    h = etat["historique"]
    dep = 10000.0
    dern = h[-1] if h else None
    veille = h[-2]["valeur"] if len(h) > 1 else dep
    var_jour = (dern["valeur"] - veille) if dern else 0.0

    alertes = []
    if etat.get("stop_actif"):
        alertes.append("Fichier <b>STOP</b> présent : aucune nouvelle entrée. Les sorties continuent.")
    if dern and dern.get("bloque") and not etat.get("stop_actif"):
        alertes.append("Baisse depuis le plus haut supérieure à 10 % : nouvelles entrées suspendues.")
    if erreurs_du_jour:
        alertes.append("Données incomplètes au dernier lancement : "
                       + html.escape(" ; ".join(erreurs_du_jour[:3]))
                       + (" …" if len(erreurs_du_jour) > 3 else ""))
    if not h:
        alertes.append("Aucune séance jouée pour l'instant : la page se remplira au prochain lancement réussi.")

    # Mouvements de la dernière séance
    evts = []
    if dern:
        for t in etat["transactions"]:
            if t["date_sortie"] == dern["date"]:
                evts.append(_ligne_evt(f"Vendu {html.escape(nom(t['symbole']))} — {html.escape(t['motif'])}",
                                       f"{_actions(t['actions'])} · achat {t['prix_entree']:.2f} $ → vente {t['prix_sortie']:.2f} $ · {t['r']:+.2f} R",
                                       t["pnl"]))
        for p in etat["positions"]:
            if p["date_entree"] == dern["date"]:
                evts.append(_ligne_evt(f"Acheté {html.escape(nom(p['symbole']))}",
                                       f"{_actions(p['actions'])} à {p['prix_entree']:.2f} $ · stop {p['stop']:.2f} · "
                                       f"objectif {p['objectif']:.2f} · perte max {_num(p['perte_max'], 0)} $"))
    bloc_jour = "".join(evts) or "<p class='vide'>Aucun achat ni vente à la dernière séance.</p>"

    pos = []
    for p in sorted(etat["positions"], key=lambda p: p["date_entree"]):
        latent = p["actions"] * p["dernier_cours"] - p["cout"]
        pos.append(_ligne_evt(f"{html.escape(nom(p['symbole']))} · {_actions(p['actions'])}",
                              f"achat {p['prix_entree']:.2f} → {p['dernier_cours']:.2f} $ · stop {p['stop']:.2f} · "
                              f"objectif {p['objectif']:.2f} · depuis le {_d(p['date_entree'])}", latent))
    bloc_pos = "".join(pos) or "<p class='vide'>Aucune position ouverte.</p>"

    kpis = [
        ("Transactions finies", str(res["nb"]), ""),
        ("Taux de réussite", f"{res['reussite']*100:.0f} %" if res["reussite"] is not None else "—", ""),
        ("Gain moyen en R", f"{res['r_moyen']:+.2f}" if res["r_moyen"] is not None else "—", _classe(res["r_moyen"] or 0)),
        ("Baisse maximale", f"{res['drawdown_max']*100:.1f} %", ""),
    ]

    # Journal complet : chaque achat, et sa vente quand elle a eu lieu (plus récent en premier)
    journal = []
    tous = [(p["date_entree"], p, None) for p in etat["positions"]] + \
           [(t["date_entree"], t, t) for t in etat["transactions"]]
    for _, a, vente in sorted(tous, key=lambda x: (x[0], x[1].get("date_sortie") or "9999"), reverse=True):
        achat = (f"acheté le {_d(a['date_entree'])} : {a['actions']} × {a['prix_entree']:.2f} $ "
                 f"= {_num(a['cout'])} $")
        if vente:
            detail = (f"{achat}<br>vendu le {_d(vente['date_sortie'])} à {vente['prix_sortie']:.2f} $ · "
                      f"{html.escape(vente['motif'])} · {vente['r']:+.2f} R")
            journal.append(_ligne_evt(html.escape(nom(a["symbole"])), detail, vente["pnl"]))
        else:
            journal.append(_ligne_evt(html.escape(nom(a["symbole"])) + " <span class='badge'>en cours</span>",
                                      f"{achat}<br>stop {a['stop']:.2f} $ · objectif {a['objectif']:.2f} $"))
    bloc_journal = "".join(journal) or "<p class='vide'>Aucun achat pour l'instant.</p>"

    # Ce que le bot apprend : variantes testées en parallèle
    lignes_var = []
    for n, v in etat.get("variantes", {}).items():
        c = comparer(etat, v)
        if not c:
            lignes_var.append(f"<tr><td>{html.escape(n)}</td><td class='n'>—</td><td class='n'>—</td><td class='n'>—</td></tr>")
            continue
        lignes_var.append(f"<tr><td>{html.escape(n)}</td><td class='n'>{c['seances']}</td><td class='n'>{c['transactions']}</td>"
                          f"<td class='n {_classe(c['avance'])}'>{c['avance']*100:+.1f} pts</td></tr>")
    a = ADOPTION
    reste = max(0, a["seances_min"] - max([comparer(etat, v)["seances"] for v in etat.get("variantes", {}).values()
                                           if v["historique"]] or [0]))
    bloc_appr = (f"<p>Règle en place : <b>{html.escape(nom_regle(etat))}</b>. En parallèle, le bot fait tourner "
                 f"{len(lignes_var)} variantes sur les mêmes vrais cours, en argent fictif.</p>"
                 "<div class='defil'><table><tr><th>Variante</th><th class='n'>Séances</th><th class='n'>Ventes</th>"
                 "<th class='n'>Écart</th></tr>" + "".join(lignes_var) + "</table></div>"
                 f"<p class='sous'>Écart = performance de la variante moins celle de la règle en place, sur la même période. "
                 f"Le bot n'adopte une variante qu'après au moins {a['seances_min']} séances et {a['transactions_min']} "
                 f"transactions, si elle fait au moins {a['avance_min']*100:.0f} points de mieux sans baisse plus forte. "
                 + (f"Encore au moins {reste} séances avant qu'une variante puisse être adoptée." if reste else "")
                 + "</p>")
    chg = etat.get("changements", [])
    if chg:
        bloc_appr += "<ul>" + "".join(f"<li>{_d(c['date'])} : « {html.escape(c['ancienne'])} » remplacée par "
                                      f"« {html.escape(c['nouvelle'])} », {html.escape(c['raison'])}.</li>" for c in chg) + "</ul>"

    crit = criteres_prod(etat, res)
    bloc_prod = "".join(_ligne_evt(("✅ " if ok else "⬜ ") + html.escape(t), html.escape(val)) for t, ok, val in crit)
    nb_ok = sum(1 for _, ok, _ in crit if ok)
    bloc_prod = (f"<p><b>{nb_ok} / {len(crit)}</b> conditions remplies.</p>" + bloc_prod +
                 "<p class='sous'>Même avec tout coché : commencer avec une petite somme, et chaque vrai ordre devra "
                 "être validé par toi. Des résultats passés ne garantissent pas les résultats futurs.</p>")

    lignes = []
    for i in range(len(h) - 1, max(-1, len(h) - 61), -1):
        x = h[i]
        prec = h[i - 1]["valeur"] if i > 0 else dep
        lignes.append(f"<tr><td class='n' style='text-align:left'>{_d(x['date'])}</td><td class='n'>{_num(x['valeur'])}</td>"
                      f"<td class='n {_classe(x['valeur']-prec)}'>{_signe(x['valeur']-prec, '')}</td>"
                      f"<td class='n'>{_num(x['indice']) if x['indice'] else '—'}</td></tr>")
    tab = ("<div class='defil'><table><tr><th>Séance</th><th class='n'>Bot</th><th class='n'>Variation</th>"
           "<th class='n'>Indice</th></tr>" + "".join(lignes) + "</table></div>") if lignes else \
        "<p class='vide'>Pas encore d'historique.</p>"

    titre_date = date_fr(date.fromisoformat(dern["date"])) if dern else "—"
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Actions réelles</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icone.svg"><meta name="theme-color" content="#2f5d8a">
<style>{STYLE}{STYLE_SUIVI}{STYLE_ACTIONS}</style></head><body><main>
{NAV.format(a1="", a2="actif")}
<div class="tete"><h1>Actions réelles</h1><span class="badge">cours réels · argent fictif</span></div>
<p class="sous">Séance du {titre_date} · mis à jour le {html.escape(etat.get('derniere_execution') or '—')}</p>
{''.join(f'<div class="alerte">{a}</div>' for a in alertes)}
<div class="carte"><div class="sous" style="margin:0">Valeur du portefeuille</div>
<div class="valeur">{_num(res['valeur'])} $</div>
<div><span class="var {_classe(var_jour)}">{_signe(var_jour, ' $')} à la dernière séance</span> ·
<span class="var {_classe(res['perf'])}">{_pct(res['perf'])} depuis le début</span></div>
<p class="sous" style="margin:6px 0 0">Avec 10 000 $ simplement placés sur l'indice : {_num(res['indice'])} $ ({_pct(res['perf_indice'])})</p></div>
<div class="carte" style="margin-top:10px"><b>Verdict.</b> {html.escape(res['verdict'])}</div>
<h2>Dernière séance</h2><div class="carte">{bloc_jour}</div>
<h2>Bot contre indice</h2><div class="carte">{courbes_svg(h, dep)}</div>
<div class="grille" style="margin-top:10px">{''.join(f'<div class="kpi"><b class="{c}">{v}</b><span>{k}</span></div>' for k, v, c in kpis)}</div>
<h2>Positions ouvertes</h2><div class="carte">{bloc_pos}</div>
<h2>Ce que le bot apprend</h2><div class="carte">{bloc_appr}</div>
<h2>Prêt pour de l'argent réel ?</h2><div class="carte">{bloc_prod}</div>
<h2>Tous les achats et ventes</h2><div class="carte">{bloc_journal}</div>
<h2>Séance par séance</h2><div class="carte">{tab}</div>
<h2>La règle suivie</h2><div class="carte"><ul>
<li>Achat quand une action clôture au plus haut de ses 20 dernières séances, en tendance haussière (au-dessus de ses moyennes 50 et 200 jours).</li>
<li>Stop à 2 fois la variation moyenne quotidienne sous le prix d'achat ; objectif à 2 fois le risque ; sortie au bout de 20 séances sinon.</li>
<li>Perte maximale de 1 % du portefeuille par position, 20 % du portefeuille au plus par action, 5 positions et 2 achats par séance au maximum.</li>
<li>Ordres simulés au cours de clôture, 0,05 % de frais à l'achat et à la vente. Un vrai ordre peut être exécuté moins bien, surtout sur un stop.</li>
<li>Pas pris en compte : dividendes, conversion euro/dollar et ses frais, impôts.</li>
</ul></div>
<p class="sous" style="margin-top:24px">Démarré le {_d(etat['date_debut']) if etat.get('date_debut') else '—'} avec 10 000 $ fictifs.
Cours : Yahoo Finance (secours : Stooq), gratuits et non officiels. Aucun ordre réel. Ceci n'est pas un conseil en investissement.</p>
</main></body></html>"""
    with open(os.path.join(dossier, "actions.html"), "w", encoding="utf-8") as f:
        f.write(page)
