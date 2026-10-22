"""Separacion de la voz con Demucs (htdemucs), un modelo de IA que corre en CPU.

Es una dependencia opcional y pesada (torch + demucs, ver requirements-vocals.txt): solo se importa al usarla.
Sin ella el resto del motor funciona igual y las pistas quedan con el analisis de voz "no disponible".
"""
import importlib.util
import os

import numpy as np

MODEL_NAME = 'htdemucs'
# Hilos de CPU que usa el modelo. Por defecto 2, para no dejar sin CPU al resto de servicios en un equipo modesto.
TORCH_THREADS = int(os.environ.get('VOCAL_TORCH_THREADS', '2'))
# Segundos de audio que el modelo procesa de una vez: menos segmento, menos memoria.
SEGMENT_SECONDS = 7

_model = None


class VocalSeparationUnavailable(RuntimeError):
    """Demucs y torch no estan instalados."""


def is_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ('torch', 'demucs'))


def _load_model():
    global _model
    if _model is None:
        from demucs.pretrained import get_model

        _model = get_model(MODEL_NAME)
        _model.eval()
    return _model


def separate_vocals(audio: np.ndarray) -> np.ndarray:
    """Pista de voz de una senal estereo (2, muestras) a 44.1 kHz; devuelve un array de la misma forma."""
    if not is_available():
        raise VocalSeparationUnavailable('Instala requirements-vocals.txt para separar la voz.')
    import torch
    from demucs.apply import apply_model

    torch.set_num_threads(TORCH_THREADS)
    model = _load_model()
    with torch.no_grad():
        stems = apply_model(
            model, torch.from_numpy(audio).float()[None], device='cpu', shifts=0, split=True,
            overlap=0.1, segment=SEGMENT_SECONDS, num_workers=0,
        )
    return stems[0, model.sources.index('vocals')].numpy()
