import numpy as np


class AdaptiveNoiseSuppressor:
    def __init__(self, enabled: bool, strength: float) -> None:
        self._enabled = enabled
        self._strength = max(0.0, min(0.95, strength))
        self._noise_rms = 0.003
        self._previous = 0.0

    def reset(self) -> None:
        self._noise_rms = 0.003
        self._previous = 0.0

    def process_frame(self, data: bytes, speaking: bool) -> bytes:
        if not self._enabled:
            return data
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return data
        filtered = np.empty_like(samples)
        filtered[0] = samples[0] - 0.97 * self._previous
        filtered[1:] = samples[1:] - 0.97 * samples[:-1]
        self._previous = float(samples[-1])
        rms = float(np.sqrt(np.mean(filtered * filtered) + 1e-9))
        if not speaking and rms < self._noise_rms * 3.0:
            self._noise_rms = self._noise_rms * 0.94 + rms * 0.06
        threshold = self._noise_rms * (1.3 + 2.0 * self._strength)
        if speaking:
            gain = max(0.46, min(1.0, (rms / max(threshold, 1e-5)) ** 0.55))
        else:
            ratio = max(0.0, min(1.0, (rms - threshold * 0.72) / max(threshold, 1e-5)))
            gain = (1.0 - self._strength) + self._strength * ratio
        cleaned = np.clip(filtered * gain, -1.0, 1.0)
        return (cleaned * 32767.0).astype(np.int16).tobytes()
