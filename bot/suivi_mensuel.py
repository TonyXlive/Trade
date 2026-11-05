"""Page « Mes 50 €/mois »."""
import html
import os
from datetime import date

from .rapport import STYLE, _num
from .actions_reelles import nom
from .mensuel import PARAMS
from .suivi import STYLE_SUIVI, MOIS, MOIS_COURT, date_fr, _signe, _classe, NAV
from .suivi import _ligne_evt as _ligne_base
from .suivi_actions import STYLE_ACTIONS


def _d(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {MOIS_COURT[d.month-1]}"


def _quand(x):
    """'2026-12-31 05:17' -> '31/12/2026 à 05:17'."""
    if not x or len(x) < 16:
        return "—"
    return f"{x[8:10]}/{x[5:7]}/{x[:4]} à {x[11:16]}"


def _evt(titre, detail, montant=None):
    return _ligne_base(titre, detail, montant, " €")


def courbes(etat, largeur=760, hauteur=220):
    h = [x for x in etat["historique"] if x["taux"] and x["indice_usd"] is not None]
    if len(h) < 2:
        return "<p class='vide'>La courbe apparaîtra après quelques séances.</p>"
    bot = [x["bot_usd"] / x["taux"] for x in h]
    ind = [x["indice_usd"] / x["taux"] for x in h]
    verse = [x["verse_eur"] for x in h]
    mn, mx = min(bot + ind + verse), max(bot + ind + verse)
    mx = mx if mx > mn else mn + 1
    pad = 10

    def ligne(vals, cls, extra=""):
        n = len(vals)
        pts = " ".join(f"{pad + i*(largeur-2*pad)/(n-1):.1f},{hauteur-pad-(v-mn)*(hauteur-2*pad)/(mx-mn):.1f}"
                       for i, v in enumerate(vals))
        return f'<polyline points="{pts}" fill="none" class="{cls}" stroke-width="2.5" stroke-linejoin="round" {extra}/>'
    return (f'<svg viewBox="0 0 {largeur} {hauteur}" class="courbe" role="img" aria-label="Bot, indice et sommes versées">'
            + ligne(verse, "ref", 'stroke-width="1.5"') + ligne(ind, "l-ind") + ligne(bot, "l-bot") + "</svg>"
            "<p class='sous' style='margin:6px 0 0'><span class='pastille bot'></span>le bot "
            "<span class='pastille ind'></span>l'indice <span class='pastille' style='border-top:2px dashed var(--doux);"
            "height:0'></span>ce que tu as versé</p>")


def generer_page_mensuel(etat, r, dossier, erreurs):
    os.makedirs(dossier, exist_ok=True)
    alertes = []
    if erreurs:
        alertes.append("Données incomplètes au dernier lancement : " + html.escape(" ; ".join(erreurs[:3])))
    if not etat["historique"]:
        alertes.append("Aucune séance jouée pour l'instant.")

    blocs = []
    for titre, val, gain, detail in [
        ("Le bot", r["bot"], r["gain_bot"],
         f"{r.get('ordres_bot', 0)} ordres · {_num(r.get('frais_bot', 0))} € de frais"),
        ("Achat mensuel de l'indice", r["indice"], r["gain_indice"],
         f"{r.get('ordres_indice', 0)} ordres · {_num(r.get('frais_indice', 0))} € de frais"),
    ]:
        blocs.append(f"<div class='kpi'><span>{titre}</span><b>{_num(val)} €</b>"
                     f"<span class='{_classe(gain)}'>{_signe(gain)}</span><br><span>{detail}</span></div>")

    # Journal du bot
    b = etat["bot"]
    journal = []
    tous = [(p["date_entree"], p, None) for p in b["positions"]] + [(t["date_entree"], t, t) for t in b["transactions"]]
    t_act = etat.get("taux") or 1
    for _, a, vente in sorted(tous, key=lambda x: (x[0], x[1].get("date_sortie") or "9999"), reverse=True):
        achat = (f"acheté le {_d(a['date_entree'])} : {str(round(a['actions'], 4)).replace('.', ',')} action à {a['prix_entree']:.2f} $ "
                 f"(coût {_num(a['cout'] / t_act)} € frais compris)")
        if vente:
            journal.append(_evt(html.escape(nom(a["symbole"])),
                                f"{achat}<br>vendu le {_d(vente['date_sortie'])} à {vente['prix_sortie']:.2f} $ · "
                                f"{html.escape(vente['motif'])}", vente["pnl"] / t_act))
        else:
            journal.append(_evt(html.escape(nom(a["symbole"])) + " <span class='badge'>en cours</span>",
                                f"{achat}<br>stop {a['stop']:.2f} $ · objectif {a['objectif']:.2f} $"))
    bloc_journal = "".join(journal) or "<p class='vide'>Le bot n'a encore rien acheté.</p>"

    vers = "".join(
        f"<tr><td>{MOIS[int(v['mois'][5:7])-1]} {v['mois'][:4]}</td><td>{_d(v['date'])}</td>"
        f"<td class='n'>{_num(v['eur'], 0)} €</td><td class='n'>{_num(v['usd'])} $</td></tr>"
        for v in reversed(etat["versements"]))
    tab_vers = ("<div class='defil'><table><tr><th>Mois</th><th>Versé le</th><th class='n'>Euros</th>"
                "<th class='n'>Dollars</th></tr>" + vers + "</table></div>") if vers else \
        "<p class='vide'>Aucun versement pour l'instant.</p>"

    lignes = []
    for x in reversed(etat["historique"][-60:]):
        if not x["taux"]:
            continue
        lignes.append(f"<tr><td>{_d(x['date'])}</td><td class='n'>{_num(x['verse_eur'], 0)}</td>"
                      f"<td class='n'>{_num(x['bot_usd'] / x['taux'])}</td>"
                      f"<td class='n'>{_num((x['indice_usd'] or 0) / x['taux'])}</td></tr>")
    tab = ("<div class='defil'><table><tr><th>Séance</th><th class='n'>Versé €</th><th class='n'>Bot €</th>"
           "<th class='n'>Indice €</th></tr>" + "".join(lignes) + "</table></div>") if lignes else \
        "<p class='vide'>Pas encore d'historique.</p>"

    dern = etat["historique"][-1]["date"] if etat["historique"] else None
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Mes 50 € par mois</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icone.svg"><meta name="theme-color" content="#2f5d8a">
<style>{STYLE}{STYLE_SUIVI}{STYLE_ACTIONS}.kpi span{{display:inline}}.kpi b{{margin:2px 0}}</style></head><body><main>
{NAV.format(a1="", a2="", a3="actif", a4="")}
<div class="tete"><h1>Mes 50 € par mois</h1><span class="badge">cours réels · argent fictif</span></div>
<p class="sous">Séance du {date_fr(date.fromisoformat(dern)) if dern else '—'} · mis à jour le {_quand(etat.get('derniere_execution'))}</p>
{''.join(f'<div class="alerte">{a}</div>' for a in alertes)}
<div class="carte"><div class="sous" style="margin:0">Total versé</div>
<div class="valeur">{_num(r['verse'], 0)} €</div>
<p class="sous" style="margin:4px 0 0">{PARAMS['versement_eur']:.0f} € versés au début de chaque mois dans chacun des deux portefeuilles.</p></div>
<div class="grille" style="margin-top:10px">{''.join(blocs)}</div>
<div class="carte" style="margin-top:10px"><b>Verdict.</b> {html.escape(r['verdict'])}</div>
<h2>Évolution</h2><div class="carte">{courbes(etat)}</div>
<h2>Achats et ventes du bot</h2><div class="carte">{bloc_journal}</div>
<h2>Versements</h2><div class="carte">{tab_vers}</div>
<h2>Séance par séance</h2><div class="carte">{tab}</div>
<h2>Comment c'est simulé</h2><div class="carte"><ul>
<li>Chaque mois, à la première séance de bourse, 50 € sont convertis en dollars au vrai taux du jour et versés dans chaque portefeuille.</li>
<li><b>Le bot</b> suit la même règle que l'onglet « Actions réelles » et peut acheter des morceaux d'action. Il n'achète pas pour moins de {PARAMS['ordre_min']:.0f} $.</li>
<li><b>L'indice</b> : les 50 € servent aussitôt à acheter l'indice S&amp;P 500 (fonds SPY), puis on n'y touche plus.</li>
<li>Mêmes frais pour les deux : {PARAMS['frais_ordre']:.0f} $ par ordre, à l'achat comme à la vente. Les montants sont affichés en euros au taux du dernier jour.</li>
<li>Pas pris en compte : dividendes, frais de change du courtier, impôts.</li>
</ul></div>
<p class="sous" style="margin-top:24px">Démarré le {_d(etat['date_debut']) if etat.get('date_debut') else '—'}. Argent fictif, aucun ordre réel. Ceci n'est pas un conseil en investissement.</p>
</main></body></html>"""
    with open(os.path.join(dossier, "mensuel.html"), "w", encoding="utf-8") as f:
        f.write(page)
