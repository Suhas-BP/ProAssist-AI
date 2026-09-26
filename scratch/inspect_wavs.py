from faster_whisper import WhisperModel
from pathlib import Path

model = WhisperModel('tiny.en', device='cpu', compute_type='int8')
names = ['d:/Agent.wav', 'd:/Agent (1).wav', 'd:/Agent (2).wav', 'd:/agent_test.wav', 'd:/Alex.wav', 'd:/Alien.wav', 'd:/Animal.wav']
for name in names:
    p = Path(name)
    if p.exists():
        segments, _ = model.transcribe(str(p), language='en')
        text = ' '.join(s.text for s in segments).strip()
        print(f'{name} transcript: "{text}"')
