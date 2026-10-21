"""[voix-fr] Outils publies par le firmware stackchan-idf : descriptions japonaises
remplacees par du francais, outils inutilisables en francais masques.

- speak_katakoto : voix japonaise du robot, en kana uniquement.
Avec le firmware stackchan-idf-EN-FR, get_time (heure locale) et set_timer (rappel lu
par voix-fr) fonctionnent en francais ; avec le firmware d'origine ils restent en
japonais (heure du Japon, rappel lu en kana).
"""

MASQUES = {"speak_katakoto"}

FR = {
    "set_expression": (
        "Change l'expression du visage de Stack-chan pour montrer une émotion.",
        {"expression": "neutral (neutre), happy (content), sad (triste), angry (fâché), "
                       "doubt (perplexe), sleepy (endormi)"},
    ),
    "set_head_pose": (
        "Tourne la tête de Stack-chan. yaw_deg : gauche-droite de -40 à 40 degrés ; "
        "pitch_deg : bas-haut de -10 à 25 degrés. 0 et 0 = regarder droit devant.",
        {"yaw_deg": "angle gauche-droite en degrés (-40 à 40)",
         "pitch_deg": "angle bas-haut en degrés (-10 à 25)"},
    ),
    "get_time": (
        "Donne la date, l'heure et le jour de la semaine (heure locale). À utiliser chaque fois "
        "qu'on demande l'heure ou la date.",
        {},
    ),
    "set_timer": (
        "Dans N secondes, Stack-chan prévient de lui-même (rappel). message : phrase courte "
        "affichée et dite à voix haute. Un seul rappel à la fois, effacé au redémarrage. "
        "Pour « préviens-moi dans 10 minutes ».",
        {"seconds": "délai en secondes (1 à 43200)", "message": "phrase du rappel, en français",
         "reading": "laisser vide"},
    ),
    "lt_timer": (
        "Compte à rebours affiché sur l'écran (exposé, cuisson...). action : start (durée en "
        "minutes, ex. 1 ou 5), stop (arrêter), status (temps restant). "
        "Pour « mets un minuteur de 3 minutes », « arrête le minuteur », « il reste combien ? ».",
        {"action": "start, stop ou status", "minutes": "durée en minutes (0,5 à 180)"},
    ),
    "set_volume": (
        "Change le volume du haut-parleur. action : up (un peu plus fort), down (un peu moins fort), "
        "mute (couper le son), unmute (remettre le son), set (niveau level de 0 à 200, 100 = normal). "
        "Pour « plus fort », « moins fort », « tais-toi », « remets le son ».",
        {"action": "up, down, mute, unmute ou set", "level": "niveau de 0 à 200 (100 = normal)"},
    ),
    "get_status": (
        "Donne l'état de Stack-chan : capteur de proximité (une main est-elle proche), niveau de "
        "batterie, temps depuis le démarrage, temps restant du minuteur. À utiliser pour les "
        "questions sur sa batterie, sa forme ou ce qui est près de lui.",
        {},
    ),
    "remember": (
        "Enregistre une information importante dans une mémoire qui reste après extinction. "
        "key : titre court en français (ex. « prénom de l'utilisateur »), text : contenu. "
        "Une même key est remplacée.",
        {"key": "titre court", "text": "contenu à retenir"},
    ),
    "recall": (
        "Relit les notes enregistrées. Sans key, renvoie tout. À utiliser quand on demande "
        "ce qui a été dit ou promis avant.",
        {"key": "titre de la note (facultatif)"},
    ),
    "forget": (
        "Efface la note enregistrée sous cette key.",
        {"key": "titre de la note à effacer"},
    ),
}


# remplaces par la memoire du serveur (voixfr_memoire, page /memoire de voix-fr)
MEMOIRE_ROBOT = {"remember", "recall", "forget"}


def adapter(nom, description, schema, config=None):
    """Renvoie (description, schema) en francais, ou None pour masquer l'outil."""
    if nom in MASQUES:
        return None
    fonctions = (((config or {}).get("Intent") or {}).get("function_call") or {}).get("functions") or []
    if nom in MEMOIRE_ROBOT and "retenir" in fonctions:
        return None
    if nom not in FR:
        return description, schema
    desc, props = FR[nom]
    for cle, texte in props.items():
        if cle in schema.get("properties", {}):
            schema["properties"][cle]["description"] = texte
    return desc, schema
