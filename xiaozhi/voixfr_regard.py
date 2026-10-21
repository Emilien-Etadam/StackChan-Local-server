"""[voix-fr] Le robot tourne la tete vers la personne qui lui parle.

A chaque phrase acceptee, xiaozhi prend une photo par la camera du robot (sa page
web : GET http://<robot>/api/camera/capture, image brute RGB565), cherche le visage le
plus grand, et envoie au robot l'outil set_head_pose pour le centrer. La camera est
sur la tete : on corrige l'angle actuel de l'ecart vu sur la photo, comme un tireur
qui recentre sa visee.

Ce n'est pas un suivi continu : une photo par phrase (la prise de vue fige le visage
anime du robot ~0,5 s). Le suivi en continu demandera une detection sur le robot.

Reglages dans data/.config.yaml :
regard:
  actif: true
  port: 80                # page web du robot
  champ_h: 62             # angle de vue horizontal de la camera (degres)
  champ_v: 48
  sens_yaw: 1             # -1 si la tete tourne du mauvais cote
  sens_pitch: 1           # -1 si elle monte au lieu de descendre
"""
import asyncio
import json
import time
from pathlib import Path

import httpx
import numpy as np

from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

MODELE_YUNET = Path(__file__).resolve().parents[2] / "models" / "face_detection_yunet_2023mar.onnx"
_detecteurs = {}


def _detecteur(w, h):
    import cv2
    if MODELE_YUNET.exists():
        d = _detecteurs.get((w, h))
        if d is None:
            d = cv2.FaceDetectorYN.create(str(MODELE_YUNET), "", (w, h), 0.7, 0.3, 50)
            _detecteurs[(w, h)] = d
        return ("yunet", d)
    d = _detecteurs.get("haar")
    if d is None:
        d = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        _detecteurs["haar"] = d
    return ("haar", d)


def rgb565be_vers_bgr(brut, w, h):
    v = np.frombuffer(brut, dtype=">u2").reshape(h, w).astype(np.uint16)
    r = ((v >> 11) & 0x1F) << 3
    g = ((v >> 5) & 0x3F) << 2
    b = (v & 0x1F) << 3
    return np.dstack([b, g, r]).astype(np.uint8)


def plus_grand_visage(bgr):
    """(cx, cy, largeur) en fraction de l'image, ou None."""
    import cv2
    h, w = bgr.shape[:2]
    if w > 320:                                   # VGA -> QVGA : 4x plus rapide, assez precis
        bgr = cv2.resize(bgr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        h, w = bgr.shape[:2]
    genre, d = _detecteur(w, h)
    if genre == "yunet":
        _, faces = d.detect(bgr)
        boites = [] if faces is None else [f[:4] for f in faces]
    else:
        gris = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        boites = d.detectMultiScale(gris, scaleFactor=1.15, minNeighbors=5, minSize=(30, 30))
    if len(boites) == 0:
        return None
    x, y, bw, bh = max(boites, key=lambda b: b[2] * b[3])
    return ((x + bw / 2) / w, (y + bh / 2) / h, bw / w)


async def _photo(ip, port):
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=2.0)) as c:
        r = await c.get(f"http://{ip}:{port}/api/camera/capture")
    r.raise_for_status()
    w, h = int(r.headers["X-Frame-Width"]), int(r.headers["X-Frame-Height"])
    fmt = r.headers.get("X-Frame-Format", "")
    if fmt == "rgb565be":
        return rgb565be_vers_bgr(r.content, w, h)
    if fmt == "gray8":
        g = np.frombuffer(r.content, dtype=np.uint8).reshape(h, w)
        return np.dstack([g, g, g])
    raise ValueError(f"format d'image inconnu : {fmt}")


async def regarder(conn):
    cfg = conn.config.get("regard") or {}
    ip = getattr(conn, "client_ip", None)
    if not ip or not getattr(conn, "mcp_client", None):
        return
    t0 = time.monotonic()
    try:
        bgr = await _photo(ip, int(cfg.get("port", 80)))
        visage = await asyncio.to_thread(plus_grand_visage, bgr)
    except Exception as e:
        logger.bind(tag=TAG).warning(f"[voix-fr] regard : photo impossible ({e})")
        return
    if visage is None:
        logger.bind(tag=TAG).info(f"[voix-fr] regard : pas de visage ({time.monotonic() - t0:.2f} s)")
        return
    cx, cy, _ = visage
    yaw = getattr(conn, "voixfr_yaw", 0.0) + float(cfg.get("sens_yaw", 1)) * (0.5 - cx) * float(cfg.get("champ_h", 62))
    pitch = getattr(conn, "voixfr_pitch", 0.0) + float(cfg.get("sens_pitch", 1)) * (0.5 - cy) * float(cfg.get("champ_v", 48))
    yaw = max(-40.0, min(40.0, yaw))
    pitch = max(-10.0, min(25.0, pitch))
    conn.voixfr_yaw, conn.voixfr_pitch = yaw, pitch
    try:
        from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
        await call_mcp_tool(conn, conn.mcp_client, "set_head_pose",
                            json.dumps({"yaw_deg": round(yaw, 1), "pitch_deg": round(pitch, 1)}), timeout=5)
        logger.bind(tag=TAG).info(f"[voix-fr] regard : visage en ({cx:.2f}, {cy:.2f}) -> tete yaw {yaw:.0f} pitch {pitch:.0f} "
                                  f"({time.monotonic() - t0:.2f} s)")
    except Exception as e:
        logger.bind(tag=TAG).warning(f"[voix-fr] regard : set_head_pose a echoue ({e})")


def lancer(conn):
    """Appele quand une phrase est acceptee : une seule prise de vue a la fois."""
    if not (conn.config.get("regard") or {}).get("actif", False):
        return
    t = getattr(conn, "voixfr_regard_tache", None)
    if t is not None and not t.done():
        return
    conn.voixfr_regard_tache = asyncio.get_running_loop().create_task(regarder(conn))
