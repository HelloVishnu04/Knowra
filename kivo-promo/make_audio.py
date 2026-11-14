"""Original 120 BPM score sharing the video's 30fps cue clock."""
from pathlib import Path
import json, wave
import numpy as np
ROOT=Path(__file__).resolve().parent
SR=48000; N=SR*30
mix=np.zeros((N,2),dtype=np.float64); rng=np.random.default_rng(173)
def add(sound,start,gain=1,pan=0):
    i=round(start*SR)
    if i>=N:return
    sound=sound[:N-i]
    mix[i:i+len(sound),0]+=sound*gain*np.sqrt((1-pan)/2)
    mix[i:i+len(sound),1]+=sound*gain*np.sqrt((1+pan)/2)
def hz(m):return 440*2**((m-69)/12)
def pluck(m,duration=.7):
    t=np.arange(round(SR*duration))/SR; f=hz(m)
    env=(1-np.exp(-t*400))*np.exp(-t*7)
    return env*(np.sin(2*np.pi*f*t)+.25*np.sin(2*np.pi*f*2*t)+.07*np.sin(2*np.pi*f*3*t))
def kick():
    t=np.arange(round(SR*.32))/SR
    phase=2*np.pi*(47*t+70*.035*(1-np.exp(-t/.035)))
    return np.sin(phase)*np.exp(-t*17)*(1-np.exp(-t*900))
def hat():
    t=np.arange(round(SR*.055))/SR; noise=rng.normal(0,1,len(t));noise=np.r_[0,np.diff(noise)]
    return noise*np.exp(-t*95)*(1-np.exp(-t*2000))
chords=[[50,57,60,64,69],[46,53,57,60,65],[41,53,57,60,67],[48,55,58,62,67]]
for start in np.arange(0,28,2):
    chord=chords[int(start//2)%4];dur=2.8;t=np.arange(round(SR*dur))/SR
    env=np.minimum(t/.25,1)*np.minimum((dur-t)/.8,1)
    pad=sum(np.sin(2*np.pi*hz(m)*t+.10*np.sin(2*np.pi*.19*t)) for m in chord)/len(chord)
    add(pad*env,start,.18 if start>=7 else .10,-.12)
    add(pad*env,start+.019,.13 if start>=7 else .07,.2)
for b in range(54):
    start=b*.5;intensity=.20 if start<7 else .34
    if start>=24:intensity=.24
    add(kick(),start,intensity)
    if start>=7:add(hat(),start+.25,.025,(-1 if b%2 else 1)*.35)
    if b%2 and start>=7:
        t=np.arange(round(SR*.12))/SR
        clap=rng.normal(0,1,len(t))*np.exp(-t*40)*(1-np.exp(-t*600))
        add(clap,start,.027,.08)
for b in range(28,108):
    start=b*.25;chord=chords[int(start//2)%4];m=chord[(b//2)%len(chord)]+12
    gain=.045 if b%2 else .075;note=pluck(m,.9)
    add(note,start,gain,-.38 if b%2 else .38)
    add(note,start+.375,gain*.24,.35 if b%2 else -.35)
t=np.arange(round(SR*.65))/SR;noise=rng.normal(0,1,len(t));smooth=np.convolve(noise,np.ones(32)/32,mode='same')
add(smooth*np.sin(np.pi*t/.65)**2,6.35,.19)
mix[round(6.8*SR):7*SR]*=np.linspace(1,.08,round(.2*SR))[:,None]
cues=[7,12,14.5,17,19,24,25.5,27]
for start in cues:
    for m,g in [(74,.10),(81,.065),(86,.025)]:add(pluck(m,1.2),start,g)
for m in [50,57,62,65,69,74]:
    t=np.arange(3*SR)/SR;note=np.sin(2*np.pi*hz(m)*t)*np.exp(-t*1.9)*(1-np.exp(-t*90))
    add(note,27,.07)
mix*=np.minimum(np.arange(N)/SR/.04,1)[:,None]
mix*=np.minimum((N-1-np.arange(N))/SR/.75,1)[:,None]
mix*=10**(-3/20)/np.max(np.abs(mix))
with wave.open(str(ROOT/'public'/'kivo-score.wav'),'wb') as w:
    w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR)
    w.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())
report={'duration_seconds':30,'sample_rate':SR,'bpm':120,'beat_frames':15,'cue_seconds':cues,'cue_frames':[round(t*30) for t in cues],'peak_dbfs':float(20*np.log10(np.max(np.abs(mix)))),'rms_dbfs':float(20*np.log10(np.sqrt(np.mean(mix**2)))),'original_synthesized_score':True}
(ROOT/'output'/'audio-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
