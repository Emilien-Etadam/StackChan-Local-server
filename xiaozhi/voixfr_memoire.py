"""[voix-fr] Memoire du robot, gardee par voix-fr sur le R750xa (page /memoire).

Remplace les outils remember / recall / forget du robot (notes dans sa puce, invisibles).
Reglage : plugins.memoire.url (voix-fr, par defaut http://192.168.30.121:8200).
"""
import httpx

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()


def _base(conn):
    return ((conn.config.get("plugins", {}).get("memoire") or {}).get("url") or "http://192.168.30.121:8200").rstrip("/")


async def _api(conn, methode, corps=None):
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=2.0)) as c:
        r = await c.request(methode, f"{_base(conn)}/memoire/api", json=corps)
    r.raise_for_status()
    return r.json()


def _fn(nom, description, proprietes, requis):
    return {"type": "function", "function": {"name": nom, "description": description,
            "parameters": {"type": "object", "properties": proprietes, "required": requis}}}


@register_function("retenir", _fn(
    "retenir",
    "Garde une information en mémoire, durablement (« retiens que... », « n'oublie pas que... »). "
    "cle : sujet court, texte : l'information. Un même sujet est remplacé.",
    {"cle": {"type": "string", "description": "sujet court, ex. « anniversaire de Yannick »"},
     "texte": {"type": "string", "description": "ce qu'il faut retenir"}},
    ["cle", "texte"]), ToolType.SYSTEM_CTL)
async def retenir(conn, cle: str = "", texte: str = ""):
    try:
        await _api(conn, "POST", {"cle": cle, "texte": texte})
        return ActionResponse(Action.REQLLM, f"Retenu : {cle}.", None)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] memoire : {e}")
        return ActionResponse(Action.REQLLM, "Impossible d'enregistrer en mémoire.", None)


@register_function("se_souvenir", _fn(
    "se_souvenir",
    "Relit ce que tu as en mémoire. À utiliser dès qu'on te demande quelque chose qu'on a pu te dire "
    "avant (une date, un prénom, une préférence, une promesse).",
    {"sujet": {"type": "string", "description": "mot à chercher (facultatif : sans, tout est renvoyé)"}},
    []), ToolType.SYSTEM_CTL)
async def se_souvenir(conn, sujet: str = ""):
    try:
        notes = await _api(conn, "GET")
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] memoire : {e}")
        return ActionResponse(Action.REQLLM, "Mémoire inaccessible.", None)
    s = (sujet or "").lower()
    trouvees = [n for n in notes if not s or s in (n["cle"] + " " + n["texte"]).lower()] or notes
    if not trouvees:
        return ActionResponse(Action.REQLLM, "La mémoire est vide.", None)
    lignes = [f"- {n['cle']} : {n['texte']} (noté le {n['date'][:10]})" for n in trouvees[-40:]]
    return ActionResponse(Action.REQLLM, "Mémoire :\n" + "\n".join(lignes), None)


@register_function("oublier", _fn(
    "oublier", "Efface une information de la mémoire (« oublie que... »).",
    {"cle": {"type": "string", "description": "sujet de la note à effacer"}}, ["cle"]), ToolType.SYSTEM_CTL)
async def oublier(conn, cle: str = ""):
    try:
        r = await _api(conn, "DELETE", {"cle": cle})
        return ActionResponse(Action.REQLLM, "Effacé." if r.get("supprimees") else f"Rien en mémoire sous « {cle} ».", None)
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] memoire : {e}")
        return ActionResponse(Action.REQLLM, "Impossible d'effacer.", None)
