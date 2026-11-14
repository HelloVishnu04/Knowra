from pathlib import Path
import json,wave,zipfile,subprocess
import numpy as np
root=Path(__file__).resolve().parent
report=json.loads((root/'output/quality-report.json').read_text())
with wave.open(str(root/'public/kivo-score.wav'),'rb') as w: src=np.frombuffer(w.readframes(w.getnframes()),'<i2').reshape(-1,2).mean(axis=1)
with wave.open(str(root/'output/final-qa/decoded-audio.wav'),'rb') as w: dst=np.frombuffer(w.readframes(w.getnframes()),'<i2').reshape(-1,2).mean(axis=1)
lags=[]
for sec in [1,7,12,19,27]:
    # Compare the AAC decode with the source at 1kHz around key picture cues.
    a=src[sec*48000:(sec+1)*48000:48].astype(float)
    b=dst[(sec*48000)-4800:((sec+1)*48000)+4800:48].astype(float)
    a-=a.mean();b-=b.mean()
    lag=int(np.argmax(np.correlate(b,a,mode='valid')))-100
    lags.append({'at_seconds':sec,'audio_offset_milliseconds':lag})
report['audio_cue_alignment']=lags
report['visual_review']={'sample_times_seconds':[i+.5 for i in range(30)],'reviewed':True,'findings':'All 30 samples reviewed for readable main copy, consistent layout and scene progression. Initial empty entrances were corrected. Workflow UI is illustrative. End card holds from 27–30 seconds.'}
ff=root/'node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe'
fp=ff.with_name('ffprobe.exe')
master=root/'output/Kivo-AI-Promo-30s-4K.mp4'
meta=json.loads(subprocess.check_output([str(fp),'-v','error','-show_entries','stream=codec_type,width,height,r_frame_rate,duration,nb_frames','-of','json',str(master)]))
subprocess.run([str(ff),'-v','error','-i',str(master),'-c:v','rawvideo','-c:a','pcm_s16le','-f','null','-'],check=True)
report['master_4k']={'streams':meta['streams'],'complete_decode':'passed'}
(root/'output/quality-report.json').write_text(json.dumps(report,indent=2))
with zipfile.ZipFile(root/'output/Kivo-AI-Editable-Project.zip','w',zipfile.ZIP_DEFLATED) as z:
    for filename in ['package.json','package-lock.json','README.md','render.mjs','make_audio.py','verify_video.py','qa_contact.py','package_delivery.py']:
        z.write(root/filename,'kivo-promo/'+filename)
    for folder in ['src','public']:
        for f in (root/folder).rglob('*'):
            if f.is_file():z.write(f,'kivo-promo/'+f.relative_to(root).as_posix())
    for filename in ['quality-report.json','audio-report.json','final-review-1.jpg','final-review-2.jpg']:
        z.write(root/'output'/filename,'kivo-promo/output/'+filename)
print(json.dumps({'audio_cue_alignment':lags,'4k_decode':'passed','deliverables':[{ 'name':p.name,'bytes':p.stat().st_size} for p in (root/'output').iterdir() if p.suffix in ['.mp4','.zip']]},indent=2))
