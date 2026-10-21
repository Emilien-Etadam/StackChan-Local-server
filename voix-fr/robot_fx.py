"""robot_fx.py : effet « petit robot » en flux, sans dependance GPL, pour voix 24 kHz mono float32.

Trois etages, chacun traite l'audio morceau par morceau en gardant son etat
(on peut l'appliquer au fil de la synthese, sans attendre la phrase entiere) :
  1. hauteur : decaleur a ligne a retard (deux tetes de lecture qui se relaient,
     comme les pedales de guitare « pitch shifter »). Retard ajoute ~ fenetre/2.
  2. modulation en anneau : le signal est multiplie par une onde lente (vibration robot).
  3. echo metallique tres court : filtre en peigne reinjecte (voix dans une boite en tole).
  4. option : reduction de resolution (bitcrush).
  5. egaliseur petit haut-parleur : coupe les graves (il ne peut pas les rendre, il
     vibre et gresille) et releve un peu les mediums ou la voix se comprend.
  6. volume : gain puis limiteur doux (monte le niveau sans saturer).
"""
import numpy as np
from scipy.signal import butter, lfilter, lfilter_zi


class RobotFX:
    def __init__(self, sr=24000, demi_tons=0.0, fenetre_ms=30.0,
                 anneau_hz=50.0, anneau_dose=0.0,
                 peigne_ms=6.0, peigne_retour=0.0, peigne_dose=0.0,
                 bits=0, gain_db=0.0, coupe_graves_hz=0.0, presence_db=0.0):
        self.sr = sr
        self.r = 2.0 ** (demi_tons / 12.0)
        self.W = max(64, int(sr * fenetre_ms / 1000))
        self.hist = np.zeros(self.W + 4, dtype=np.float64)
        self.phase = 0.0
        self.anneau_hz, self.anneau_dose, self.anneau_t = anneau_hz, anneau_dose, 0
        D = max(1, int(sr * peigne_ms / 1000))
        self.peigne_a = np.zeros(D + 1); self.peigne_a[0] = 1.0; self.peigne_a[D] = -peigne_retour
        self.peigne_zi = np.zeros(D)
        self.peigne_dose = peigne_dose
        self.bits = bits
        self.gain = 10.0 ** (gain_db / 20.0)
        # egaliseur : chaque filtre garde son etat d'un morceau a l'autre
        self.filtres = []
        if coupe_graves_hz and coupe_graves_hz > 20:
            b, a = butter(2, coupe_graves_hz / (sr / 2), btype="highpass")
            self.filtres.append([b, a, np.zeros(max(len(a), len(b)) - 1)])
        if presence_db:
            b, a = _cloche(sr, 2500.0, presence_db, q=0.9)
            self.filtres.append([b, a, np.zeros(2)])

    def _hauteur(self, x):
        if abs(self.r - 1.0) < 1e-6:
            return x
        n, W = len(x), self.W
        ext = np.concatenate([self.hist, x])
        pos = len(self.hist) + np.arange(n)
        ph1 = (self.phase + np.arange(n) * (1.0 - self.r) / W) % 1.0
        self.phase = (self.phase + n * (1.0 - self.r) / W) % 1.0
        ph2 = (ph1 + 0.5) % 1.0
        y = np.zeros(n)
        for ph in (ph1, ph2):
            idx = pos - ph * W - 1.0
            i0 = np.floor(idx).astype(np.int64)
            f = idx - i0
            lu = ext[i0] * (1 - f) + ext[i0 + 1] * f
            y += lu * np.sin(np.pi * ph) ** 2
        self.hist = ext[-len(self.hist):]
        return y

    def process(self, x):
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if x.size == 0:
            return x.astype(np.float32)
        y = self._hauteur(x)
        if self.anneau_dose > 0:
            t = (self.anneau_t + np.arange(len(y))) / self.sr
            self.anneau_t += len(y)
            y = y * ((1 - self.anneau_dose) + self.anneau_dose * np.sin(2 * np.pi * self.anneau_hz * t))
        if self.peigne_dose > 0:
            wet, self.peigne_zi = lfilter([1.0], self.peigne_a, y, zi=self.peigne_zi)
            y = (1 - self.peigne_dose) * y + self.peigne_dose * wet
        if self.bits:
            q = 2.0 ** (self.bits - 1)
            y = np.round(y * q) / q
        for f in self.filtres:
            y, f[2] = lfilter(f[0], f[1], y, zi=f[2])
        if self.gain != 1.0:
            y = limiter(y * self.gain)
        return np.clip(y, -1.0, 1.0).astype(np.float32)


def _cloche(sr, f0, gain_db, q=1.0):
    """Filtre en cloche (egaliseur parametrique, formules RBJ) : bosse de gain_db autour de f0."""
    A = 10 ** (gain_db / 40.0)
    w = 2 * np.pi * f0 / sr
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w), 1 - al / A])
    return b / a[0], a / a[0]


def limiter(y, seuil=0.7):
    """Limiteur doux sans etat : lineaire sous le seuil, puis courbe tanh qui
    tend vers 1.0 (comme un ressort qui durcit au lieu d'une butee seche)."""
    a = np.abs(y)
    au_dessus = a > seuil
    if not au_dessus.any():
        return y
    out = y.copy()
    marge = 1.0 - seuil
    out[au_dessus] = np.sign(y[au_dessus]) * (seuil + marge * np.tanh((a[au_dessus] - seuil) / marge))
    return out


RECETTES = {
    "naturel":           dict(),
    "petit_robot_leger": dict(demi_tons=3, anneau_hz=40, anneau_dose=0.15, peigne_ms=5, peigne_retour=0.3, peigne_dose=0.2),
    "petit_robot":       dict(demi_tons=5, anneau_hz=50, anneau_dose=0.30, peigne_ms=6, peigne_retour=0.4, peigne_dose=0.35),
    "robot_marque":      dict(demi_tons=4, anneau_hz=60, anneau_dose=0.60, peigne_ms=8, peigne_retour=0.5, peigne_dose=0.45, bits=8),
}
