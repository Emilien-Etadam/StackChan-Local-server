"""locuteur.py : reconnaissance du locuteur (empreinte vocale) pour voix-fr.

Principe : un modele (WeSpeaker ResNet34, via sherpa-onnx) transforme 1 a 10 s de voix
en un vecteur de 256 nombres, l'« empreinte ». Deux enregistrements de la meme personne
donnent des vecteurs proches (cosinus pres de 1), deux personnes differentes des vecteurs
eloignes. On garde pour chaque personne les empreintes de quelques phrases, et on compare.

Le calcul tourne dans un processus a part : sherpa-onnx embarque son propre onnxruntime,
qu'il vaut mieux ne pas charger a cote de celui de Parakeet.

Stockage : /etc/voix-fr/locuteurs.json
  {"emilien": [[...256 nombres...], ...], ...}
Les derniers extraits recus du robot sont gardes en memoire (pas sur disque) pour que la
page /test permette de dire « c'est moi » sur un extrait reel, capte par le micro du robot.
"""
import base64, io, json, threading, time, wave
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import numpy as np

_extracteur = None


def _init_worker(modele, threads):
    global _extracteur
    import sherpa_onnx
    _extracteur = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=modele, num_threads=threads, provider="cpu"))


def _calcul(audio16k):
    s = _extracteur.create_stream()
    s.accept_waveform(sample_rate=16000, waveform=audio16k)
    s.input_finished()
    if not _extracteur.is_ready(s):
        return None
    v = np.asarray(_extracteur.compute(s), dtype=np.float32)
    n = np.linalg.norm(v)
    return (v / n).tolist() if n > 0 else None


class Locuteurs:
    def __init__(self, modele, fichier, threads=2, extraits=20):
        self.fichier = Path(fichier)
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"),
                                        initializer=_init_worker, initargs=(str(modele), threads))
        self.verrou = threading.Lock()
        self.profils = self._lire()
        self.recents = deque(maxlen=extraits)   # {id, t, wav_b64, emb, meilleur, score}
        self._num = 0
        self.empreinte(np.zeros(16000, dtype=np.float32) + 1e-4)   # chauffe

    # ----- stockage -----
    def _lire(self):
        try:
            return {k: [np.asarray(e, dtype=np.float32) for e in v]
                    for k, v in json.loads(self.fichier.read_text(encoding="utf-8")).items()}
        except FileNotFoundError:
            return {}

    def _ecrire(self):
        self.fichier.write_text(json.dumps({k: [e.tolist() for e in v] for k, v in self.profils.items()}),
                                encoding="utf-8")

    # ----- calcul -----
    def empreinte(self, audio16k):
        r = self.pool.submit(_calcul, np.asarray(audio16k, dtype=np.float32)).result(timeout=20)
        return None if r is None else np.asarray(r, dtype=np.float32)

    def score(self, emb, ident):
        """Cosinus moyen des 3 phrases enregistrees les plus proches (resiste a une phrase ratee)."""
        refs = self.profils.get(ident) or []
        if emb is None or not refs:
            return 0.0
        s = sorted((float(np.dot(emb, r)) for r in refs), reverse=True)[:3]
        return sum(s) / len(s)

    def identifier(self, audio16k, ids, wav_bytes=None):
        emb = self.empreinte(audio16k)
        with self.verrou:
            inscrits = [i for i in ids if self.profils.get(i)]
            if not inscrits:
                # Personne d'inscrit : on laisse passer (sinon le robot serait sourd avant
                # l'inscription). Signale par "amorce" dans la reponse.
                meilleur, sc, amorce = (ids[0] if ids else ""), 1.0, True
            else:
                meilleur, sc = max(((i, self.score(emb, i)) for i in inscrits), key=lambda x: x[1])
                amorce = False
            if wav_bytes is not None and emb is not None:
                self._num += 1
                self.recents.appendleft({"id": self._num, "t": time.time(), "emb": emb,
                                         "wav": base64.b64encode(wav_bytes).decode(),
                                         "meilleur": meilleur, "score": round(sc, 3), "amorce": amorce})
        return meilleur, sc, amorce

    def inscrire_extrait(self, num, ident):
        with self.verrou:
            for e in self.recents:
                if e["id"] == num:
                    self.profils.setdefault(ident, []).append(e["emb"])
                    self._ecrire()
                    return len(self.profils[ident])
        return None

    def inscrire_audio(self, audio16k, ident):
        emb = self.empreinte(audio16k)
        if emb is None:
            return None
        with self.verrou:
            self.profils.setdefault(ident, []).append(emb)
            self._ecrire()
            return len(self.profils[ident])

    def effacer(self, ident):
        with self.verrou:
            self.profils.pop(ident, None)
            self._ecrire()

    def etat(self):
        with self.verrou:
            out = []
            for e in self.recents:
                scores = {i: round(self.score(e["emb"], i), 3) for i in self.profils}
                out.append({"id": e["id"], "t": e["t"], "wav": e["wav"], "scores": scores,
                            "meilleur": e["meilleur"], "score": e["score"], "amorce": e["amorce"]})
            return {"inscrits": {k: len(v) for k, v in self.profils.items()}, "recents": out}


def wav_16k(donnees):
    """Petit WAV PCM16 a partir d'un signal float 16 kHz (pour reecouter un extrait)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.clip(donnees, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()
