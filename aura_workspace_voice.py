"""Windows System.Speech WAV and real viseme timings, when the installed voice emits them."""
import base64
import json
import tempfile
from pathlib import Path

# Collect events in C#; callbacks do not depend on a PowerShell runspace.
SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$source=@'
using System;
using System.Collections.Generic;
using System.Speech.Synthesis;
public class AuraCue { public int viseme; public double time; public double duration; }
public class AuraSpeech {
 public static List<AuraCue> Run(string text, string voice, string wav) {
  List<AuraCue> cues=new List<AuraCue>();
  using(SpeechSynthesizer s=new SpeechSynthesizer()) {
   if(!String.IsNullOrWhiteSpace(voice)) s.SelectVoice(voice);
   s.VisemeReached += delegate(object sender, VisemeReachedEventArgs e) {
    lock(cues) { cues.Add(new AuraCue {viseme=e.Viseme,time=e.AudioPosition.TotalSeconds,duration=e.Duration.TotalSeconds}); }
   };
   s.SetOutputToWaveFile(wav); s.Speak(text);
  }
  return cues;
 }
}
'@
Add-Type -TypeDefinition $source -ReferencedAssemblies System.Speech
$text=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:AURA_TEXT))
ConvertTo-Json -InputObject @([AuraSpeech]::Run($text,$env:AURA_VOICE,$env:AURA_WAV)) -Compress
'''


def synthesize(text,voice=''):
    if not isinstance(text,str) or not 1<=len(text)<=4000:raise ValueError('Speech text must be 1–4000 characters')
    if not isinstance(voice,str) or len(voice)>200:raise ValueError('Invalid voice')
    from phase3_web import powershell
    with tempfile.TemporaryDirectory(prefix='aura_visemes_') as folder:
        path=Path(folder)/'speech.wav'
        output=powershell(SCRIPT,{'AURA_TEXT':base64.b64encode(text.encode('utf-8')).decode(),'AURA_VOICE':voice,'AURA_WAV':str(path)})
        cues=json.loads(output or '[]')
        if isinstance(cues,dict):cues=[cues]
        cues=[c for c in cues if isinstance(c,dict) and type(c.get('viseme'))==int and 0<=c['viseme']<=21 and isinstance(c.get('time'),(float,int)) and c['time']>=0]
        raw=path.read_bytes()
    return {'audio':base64.b64encode(raw).decode(),'mime':'audio/wav','cues':cues,'sync':'Windows voice visemes' if cues else 'Amplitude fallback: this voice emitted no visemes'}
