from abc import ABC, abstractmethod

import numpy as np


class Vad(ABC):
    frame_samples: int

    @abstractmethod
    def is_speech(self, frame: bytes) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        return None


class WebRtcVad(Vad):
    frame_samples = 480

    def __init__(self) -> None:
        import webrtcvad
        self._vad = webrtcvad.Vad(2)

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, 16000)


class EnergyVad(Vad):
    frame_samples = 480

    def __init__(self) -> None:
        self._noise = 0.004

    def is_speech(self, frame: bytes) -> bool:
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return False
        energy = float(np.sqrt(np.mean(audio * audio)))
        self._noise = self._noise * 0.96 + min(energy, 0.05) * 0.04
        return energy > max(0.012, self._noise * 3.2)


class SileroVad(Vad):
    frame_samples = 512

    def __init__(self) -> None:
        import torch
        from silero_vad import load_silero_vad
        self._torch = torch
        self._model = load_silero_vad(onnx=True)

    def is_speech(self, frame: bytes) -> bool:
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = self._torch.from_numpy(audio)
        confidence = float(self._model(tensor, 16000).item())
        return confidence >= 0.52

    def reset(self) -> None:
        self._model.reset_states()


def create_vad(name: str) -> Vad:
    if name == "silero":
        try:
            return SileroVad()
        except Exception:
            pass
    try:
        return WebRtcVad()
    except Exception:
        return EnergyVad()
