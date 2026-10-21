"""[voix-fr] Recherche internet par le SearXNG local, pour le LLM du robot.

Reglage dans data/.config.yaml (ecrit par activer-recherche.sh) :
plugins:
  recherche_web:
    url: http://192.168.30.122:8080     # SearXNG, format json active
    resultats: 5
    langue: fr
et "recherche_web" dans Intent.function_call.functions.
"""
import httpx

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()

DESCRIPTION = {
    "type": "function",
    "function": {
        "name": "recherche_web",
        "description": (
            "Cherche sur internet une information récente ou que tu ne connais pas "
            "(actualité, météo, horaires, prix, résultats sportifs, définition...). "
            "Résume ensuite la réponse en une ou deux phrases, sans lire les adresses web."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "mots-clés de la recherche, en français"},
            },
            "required": ["requete"],
        },
    },
}


@register_function("recherche_web", DESCRIPTION, ToolType.SYSTEM_CTL)
async def recherche_web(conn, requete: str = None):
    if not requete:
        return ActionResponse(Action.REQLLM, "Aucune recherche demandée.", None)
    cfg = conn.config.get("plugins", {}).get("recherche_web", {})
    base = (cfg.get("url") or "").rstrip("/")
    n = int(cfg.get("resultats", 5))
    if not base:
        return ActionResponse(Action.REQLLM, "La recherche internet n'est pas configurée.", None)
    logger.bind(tag=TAG).info(f"[voix-fr] recherche : {requete}")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=3.0)) as client:
            r = await client.get(f"{base}/search", params={
                "q": requete, "format": "json", "language": cfg.get("langue", "fr"), "safesearch": 1})
        r.raise_for_status()
        resultats = r.json().get("results", [])[:n]
    except Exception as e:
        logger.bind(tag=TAG).error(f"[voix-fr] SearXNG : {e}")
        return ActionResponse(Action.REQLLM, "La recherche internet a échoué.", None)
    if not resultats:
        return ActionResponse(Action.REQLLM, f"Aucun résultat pour « {requete} ».", None)
    lignes = [f"Résultats de recherche pour « {requete} » :"]
    for i, x in enumerate(resultats, 1):
        lignes.append(f"{i}. {x.get('title', '')}")
        if x.get("publishedDate"):
            lignes.append(f"   date : {x['publishedDate'][:10]}")
        if x.get("content"):
            lignes.append(f"   {x['content'][:400]}")
    return ActionResponse(Action.REQLLM, "\n".join(lignes), None)
