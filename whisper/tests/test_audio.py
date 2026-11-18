import io
from types import SimpleNamespace
import unittest
import wave

from fastapi import HTTPException

from app import transcribe, validate_wav


def wav_bytes(seconds=1, rate=8000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(width)
        file.setframerate(rate)
        file.writeframes(b"\0" * int(seconds * rate * channels * width))
    return output.getvalue()


class AudioValidationTests(unittest.TestCase):
    def test_phone_and_stereo_wav(self):
        self.assertEqual(validate_wav(wav_bytes()), 1)
        self.assertEqual(validate_wav(wav_bytes(rate=48000, channels=2)), 1)

    def test_invalid_inputs_are_rejected(self):
        for audio in (
            b"not audio", wav_bytes(seconds=0), wav_bytes(seconds=121),
            wav_bytes(width=1), wav_bytes(channels=3), wav_bytes(rate=4000),
            wav_bytes()[:-2],
        ):
            with self.subTest(size=len(audio)), self.assertRaises(HTTPException) as caught:
                validate_wav(audio)
            self.assertEqual(caught.exception.status_code, 422)

    def test_transcription_consumes_generator_without_vad(self):
        class Model:
            def transcribe(self, file, **options):
                self.options = options
                return iter([SimpleNamespace(text=" 세탁기"), SimpleNamespace(text=" 수리 문의")]), None

        model = Model()
        result = transcribe(model, wav_bytes(), 1)
        self.assertEqual(result["text"], "세탁기 수리 문의")
        self.assertEqual(model.options["language"], "ko")
        self.assertFalse(model.options["vad_filter"])


if __name__ == "__main__":
    unittest.main()
