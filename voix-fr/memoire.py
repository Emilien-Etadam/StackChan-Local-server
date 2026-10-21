"""memoire.py : notes du robot (« retiens que... »), gardees sur le serveur.

Le robot (via xiaozhi) les lit et les ecrit par /memoire/api ; la page /memoire permet
de les voir, corriger et supprimer. Fichier : /etc/voix-fr/memoire.json
  [{"cle": "prenom de ma fille", "texte": "...", "date": "2026-10-21T19:02"}, ...]
"""
import json
import threading
import time
from pathlib import Path


class Memoire:
    def __init__(self, fichier, maxi=200):
        self.fichier = Path(fichier)
        self.maxi = maxi
        self.verrou = threading.Lock()

    def _lire(self):
        try:
            return json.loads(self.fichier.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _ecrire(self, notes):
        tmp = self.fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.fichier)

    def liste(self):
        with self.verrou:
            return self._lire()

    def retenir(self, cle, texte):
        cle, texte = cle.strip()[:80], texte.strip()[:1000]
        if not cle or not texte:
            raise ValueError("cle et texte requis")
        with self.verrou:
            notes = [n for n in self._lire() if n["cle"].lower() != cle.lower()]
            notes.append({"cle": cle, "texte": texte, "date": time.strftime("%Y-%m-%dT%H:%M")})
            self._ecrire(notes[-self.maxi:])
            return len(notes)

    def oublier(self, cle):
        with self.verrou:
            notes = self._lire()
            reste = [n for n in notes if n["cle"].lower() != cle.strip().lower()]
            self._ecrire(reste)
            return len(notes) - len(reste)
