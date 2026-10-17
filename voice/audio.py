"""Audio conversion between Twilio (8 kHz mu-law) and Nova Sonic (16 kHz PCM in, 8 kHz PCM out)."""
import audioop


class Converter:
    def __init__(self):
        self.up_state = None
        self.down_state = None

    def twilio_to_sonic(self, mulaw_8k: bytes) -> bytes:
        pcm_8k = audioop.ulaw2lin(mulaw_8k, 2)
        pcm_16k, self.up_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, self.up_state)
        return pcm_16k

    def sonic_to_twilio(self, pcm: bytes, rate: int = 8000) -> bytes:
        if rate != 8000:
            pcm, self.down_state = audioop.ratecv(pcm, 2, 1, rate, 8000, self.down_state)
        return audioop.lin2ulaw(pcm, 2)
