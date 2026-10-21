"""voix-fr : service vocal francais sur CPU pour xiaozhi-esp32-server.

  POST /v1/audio/transcriptions  Parakeet TDT 0.6B v3 (format OpenAI, champ "file")
  POST /tts/stream               Pocket TTS + effet robot, PCM s16le mono 24 kHz au fil de l'eau
                                 (contrat du fournisseur xiaozhi "index_stream" : {"text","character"})
  POST /v1/audio/speech          idem en un seul fichier WAV (format OpenAI)
  GET  /test                     page de reglage et d'essai
  GET  /config  POST /config     lecture / enregistrement du reglage (voix + effet)
  GET  /health
  POST /voiceprint/identify      reconnaissance du locuteur (contrat « voiceprint » de xiaozhi)
  GET  /voiceprint/health
  GET  /locuteurs  POST /locuteurs/inscrire|inscrire-fichier|effacer   inscription depuis /test
Configuration : /etc/voix-fr/voix.yaml
"""
import io, os, subprocess, threading, time, wave
from pathlib import Path

import numpy as np
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from normaliser_fr import normaliser
from robot_fx import RobotFX

CONFIG_PATH = Path(os.environ.get("VOIX_FR_CONFIG", "/etc/voix-fr/voix.yaml"))
ICI = Path(__file__).parent
VOIX = ["estelle", "alba", "anna", "azelma", "caro_davy", "cosette", "eponine", "eve",
        "fantine", "jane", "lola", "mary", "vera", "charles", "jean", "javert", "marius",
        "paul", "george", "michael", "bill_boerst", "peter_yearsley", "stuart_bell",
        "juergen", "giovanni", "rafael", "daan"]
CLES_FX = ["demi_tons", "fenetre_ms", "anneau_hz", "anneau_dose",
           "peigne_ms", "peigne_retour", "peigne_dose", "bits", "gain_db",
           "coupe_graves_hz", "presence_db"]
# valeurs si voix.yaml ne les precise pas (reglage pour le petit haut-parleur du CoreS3)
DEFAUTS_FX = {"gain_db": 9.0, "coupe_graves_hz": 250.0, "presence_db": 3.0}


def lire_config():
    c = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    for k, v in DEFAUTS_FX.items():
        c.setdefault("effet", {}).setdefault(k, v)
    return c


cfg = lire_config()

# ---------- Modeles (charges une fois, gardes en memoire) ----------
import torch
import onnxruntime as ort
import onnx_asr
from pocket_tts import TTSModel

torch.set_num_threads(int(cfg["pocket"]["threads"]))   # pocket_tts force 1 a l'import

so = ort.SessionOptions()
so.intra_op_num_threads = int(cfg["parakeet"]["threads"])
so.inter_op_num_threads = 1
asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", cfg["parakeet"]["dossier"],
                          quantization=cfg["parakeet"].get("quantization"),
                          sess_options=so, providers=["CPUExecutionProvider"])
asr_verrou = threading.Lock()

tts = TTSModel.load_model(language=cfg["pocket"]["langue"])
SR = tts.sample_rate                                     # 24000
tts_verrou = threading.Lock()
etats = {}


def etat_voix(nom):
    nom = nom if nom in VOIX else cfg["voix"]
    if nom not in etats:
        etats[nom] = tts.get_state_for_audio_prompt(nom)
    return etats[nom]


etat_voix(cfg["voix"])
with tts_verrou:                                         # chauffe
    tts.generate_audio(etat_voix(cfg["voix"]), "Bonjour.")

app = FastAPI(title="voix-fr")

# ---------- Reconnaissance du locuteur ----------
loc_cfg = cfg.get("locuteur") or {}
MODELE_LOC = Path(loc_cfg.get("modele", "/opt/voix-fr/modeles/wespeaker_en_voxceleb_resnet34_LM.onnx"))
locuteurs = None
from locuteur import wav_16k
if MODELE_LOC.exists() and MODELE_LOC.stat().st_size > 1_000_000:
    try:
        from locuteur import Locuteurs
        locuteurs = Locuteurs(MODELE_LOC, CONFIG_PATH.parent / "locuteurs.json",
                              threads=int(loc_cfg.get("threads", 2)))
    except Exception as e:                       # le reste du service doit tourner quand meme
        print(f"reconnaissance du locuteur desactivee : {e}", flush=True)


# ---------- Transcription ----------
def decoder_16k(donnees: bytes) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le",
                          "-ac", "1", "-ar", "16000", "pipe:1"],
                         input=donnees, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.float32)


@app.post("/v1/audio/transcriptions")
async def transcrire(file: UploadFile = File(...), model: str = Form(None),
                     language: str = Form(None), response_format: str = Form("json")):
    audio = decoder_16k(await file.read())
    if audio.size == 0:
        return {"text": ""}
    t0 = time.perf_counter()
    with asr_verrou:
        texte = asr.recognize(audio, sample_rate=16000)
    duree = time.perf_counter() - t0
    if response_format == "text":
        return Response(texte, media_type="text/plain")
    return {"text": texte, "duree_calcul_s": round(duree, 3), "duree_audio_s": round(audio.size / 16000, 2)}


# ---------- Synthese ----------
class DemandeTTS(BaseModel):
    text: str
    character: str | None = None
    fx: dict | None = None          # surcharge ponctuelle (page /test)


def flux_pcm(texte, voix, fx_params):
    texte = normaliser(texte)
    fx = RobotFX(SR, **{k: v for k, v in fx_params.items() if k in CLES_FX})
    with tts_verrou:
        for morceau in tts.generate_audio_stream(etat_voix(voix), texte):
            y = fx.process(morceau.reshape(-1).numpy())
            yield (y * 32767.0).astype("<i2").tobytes()


@app.post("/tts/stream")
def tts_stream(d: DemandeTTS):
    texte = d.text.strip()
    if not texte:
        raise HTTPException(400, "texte vide")
    return StreamingResponse(flux_pcm(texte, d.character or cfg["voix"], d.fx or cfg["effet"]),
                             media_type="audio/L16;rate=24000;channels=1")


class DemandeSpeech(BaseModel):
    input: str
    voice: str | None = None
    model: str | None = None
    response_format: str | None = "wav"


@app.post("/v1/audio/speech")
def speech(d: DemandeSpeech):
    pcm = b"".join(flux_pcm(d.input.strip(), d.voice or cfg["voix"], cfg["effet"]))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
    return Response(buf.getvalue(), media_type="audio/wav")


# ---------- Reglage ----------
@app.get("/config")
def lire():
    return {"voix": cfg["voix"], "effet": cfg["effet"], "voix_disponibles": VOIX}


class NouveauReglage(BaseModel):
    voix: str
    effet: dict


@app.post("/config")
def enregistrer(r: NouveauReglage):
    if r.voix not in VOIX:
        raise HTTPException(400, f"voix inconnue : {r.voix}")
    cfg["voix"] = r.voix
    cfg["effet"] = {**cfg["effet"], **{k: r.effet[k] for k in CLES_FX if k in r.effet}}
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True}


@app.get("/test", response_class=HTMLResponse)
def page_test():
    return (ICI / "test.html").read_text(encoding="utf-8")


class Texte(BaseModel):
    text: str


@app.post("/normaliser")
def voir_normalisation(t: Texte):
    return {"text": normaliser(t.text)}


@app.get("/voiceprint/health")
def voiceprint_sante():
    if locuteurs is None:
        raise HTTPException(503, f"modele absent : {MODELE_LOC}")
    return {"status": "healthy"}


@app.post("/voiceprint/identify")
async def voiceprint_identifier(file: UploadFile = File(...), speaker_ids: str = Form("")):
    if locuteurs is None:
        raise HTTPException(503, "reconnaissance du locuteur indisponible")
    audio = decoder_16k(await file.read())
    ids = [i.strip() for i in speaker_ids.split(",") if i.strip()]
    if audio.size < 8000:                       # moins de 0,5 s : pas fiable
        return {"speaker_id": "", "score": 0.0}
    ident, score, amorce = locuteurs.identifier(audio, ids, wav_16k(audio))
    return {"speaker_id": ident, "score": round(float(score), 3), "amorce": amorce}


@app.get("/locuteurs")
def locuteurs_etat():
    if locuteurs is None:
        return {"actif": False, "modele": str(MODELE_LOC)}
    return {"actif": True, **locuteurs.etat()}


class Inscription(BaseModel):
    ident: str
    extrait: int | None = None


@app.post("/locuteurs/inscrire")
def locuteurs_inscrire(r: Inscription):
    n = locuteurs.inscrire_extrait(r.extrait, r.ident.strip().lower()) if locuteurs else None
    if n is None:
        raise HTTPException(400, "extrait introuvable")
    return {"ok": True, "phrases": n}


@app.post("/locuteurs/inscrire-fichier")
async def locuteurs_inscrire_fichier(ident: str = Form(...), file: UploadFile = File(...)):
    if locuteurs is None:
        raise HTTPException(503, "reconnaissance du locuteur indisponible")
    n = locuteurs.inscrire_audio(decoder_16k(await file.read()), ident.strip().lower())
    if n is None:
        raise HTTPException(400, "audio trop court")
    return {"ok": True, "phrases": n}


@app.post("/locuteurs/effacer")
def locuteurs_effacer(r: Inscription):
    if locuteurs:
        locuteurs.effacer(r.ident.strip().lower())
    return {"ok": True}


@app.get("/health")
def sante():
    return JSONResponse({"ok": True, "voix": cfg["voix"], "sr": SR})
