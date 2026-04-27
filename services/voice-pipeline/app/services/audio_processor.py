"""
Audio Processing — High-performance resampling and normalization.
Uses LiveKit RTC local engine for click-free stateful resampling.
"""
from typing import Optional
import numpy as np
from livekit import rtc
import audioop

class AudioProcessor:
    """
    Standardizes audio for the VAD and STT pipeline.
    
    16kHz, mono, 16-bit PCM is our 'Gold Standard' for:
    - Silero VAD (requires 8k or 16k)
    - Deepgram/Cartesia (optimal at 16k)
    - PII Redaction
    """

    def __init__(self, input_rate: int = 8000, output_rate: int = 16000):
        self.input_rate = input_rate
        self.output_rate = output_rate
        # Official LiveKit resampler: stateful to prevent 'clicks' between chunks
        self._resampler = rtc.AudioResampler(
            input_rate=input_rate,
            output_rate=output_rate,
            quality=rtc.AudioResamplerQuality.HIGH
        )

    def resample_and_normalize(self, pcm_bytes: bytes) -> bytes:
        """
        1. Resamples from input_rate to output_rate using stateful sinc interpolation.
        2. Normalizes peak volume to -1dB.
        """
        # Convert bytes to AudioFrame (LiveKit's metadata-rich container)
        frame = rtc.AudioFrame(
            data=pcm_bytes,
            sample_rate=self.input_rate,
            num_channels=1,
            samples_per_channel=len(pcm_bytes) // 2
        )
        
        # Resample (stateful — handles chunk boundaries perfectly)
        resampled_frames = self._resampler.push(frame)
        
        # Combine resampled chunks back to bytes
        output_pcm = bytearray()
        for f in resampled_frames:
            output_pcm.extend(f.data)
            
        if not output_pcm:
            return b""

        # Normalize peak volume (using numpy for speed)
        samples = np.frombuffer(output_pcm, dtype=np.int16).astype(np.float32)
        peak = np.abs(samples).max()
        if peak > 0:
            # Target -1dB (approx 0.9 multiplier)
            norm_factor = (32767 * 0.9) / peak
            samples = (samples * norm_factor).clip(-32768, 32767)
            
        return samples.astype(np.int16).tobytes()

    @staticmethod
    def normalize(pcm_bytes: bytes) -> bytes:
        """Single-pass normalization for existing 16kHz audio."""
        if not pcm_bytes:
            return b""
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        peak = np.abs(samples).max()
        if peak > 100:  # Only normalize if there's actual signal
            norm_factor = (32767 * 0.9) / peak
            samples = (samples * norm_factor).clip(-32768, 32767)
            return samples.astype(np.int16).tobytes()
        return pcm_bytes

    @staticmethod
    def convert_mulaw_to_pcm(mulaw_bytes: bytes) -> bytes:
        """Standard 8kHz G.711 mu-law (Twilio) to 8kHz PCM."""
        return audioop.ulaw2lin(mulaw_bytes, 2)
