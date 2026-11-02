"""Étape 1 — Scan : garder les marchés sur lesquels on peut réellement trader."""


def scanner(marches: list, jour: int, cfg_scan: dict, base_connaissances) -> tuple:
    """Retourne (marchés retenus triés par intérêt, statistiques du filtrage)."""
    stats = {"total": len(marches), "volume": 0, "echeance": 0, "liquidite": 0,
             "categorie_exclue": 0, "retenus": 0, "anomalies": 0}
    retenus = []
    for m in marches:
        if m.volume < cfg_scan["volume_min_contrats"]:
            stats["volume"] += 1
            continue
        restant = m.jours_restants(jour)
        if restant <= 0 or restant > cfg_scan["jours_max_avant_echeance"]:
            stats["echeance"] += 1
            continue
        if m.liquidite < cfg_scan["liquidite_min"]:
            stats["liquidite"] += 1
            continue
        # Les leçons passées passent en premier : catégories à éviter
        if base_connaissances.categorie_exclue(m.categorie):
            stats["categorie_exclue"] += 1
            continue

        anomalies = []
        if m.spread > cfg_scan["seuil_ecart_prix_anormal"]:
            anomalies.append("écart achat/vente large")
        if m.prix_veille and abs(m.prix - m.prix_veille) / m.prix_veille > cfg_scan["seuil_mouvement_anormal"]:
            anomalies.append("mouvement de prix brutal")
        if m.historique_volume:
            moy7 = sum(m.historique_volume[-7:]) / len(m.historique_volume[-7:])
            if m.volume > 2 * moy7:
                anomalies.append("pic de volume")
        if anomalies:
            stats["anomalies"] += 1

        # Intérêt : on préfère liquide, serré, et proche de 50 % (plus d'incertitude)
        score = (m.liquidite ** 0.5) * (1 - m.spread * 5) * (1 - abs(m.prix - 0.5))
        retenus.append((score, m, anomalies))

    retenus.sort(key=lambda t: t[0], reverse=True)
    stats["retenus"] = len(retenus)
    return [(m, a) for _, m, a in retenus], stats
