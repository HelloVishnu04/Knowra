from pathlib import Path
import subprocess,json,wave
import numpy as np
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parent
ff=root/'node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe'
fp=ff.with_name('ffprobe.exe')
video=root/'output/Kivo-AI-Promo-30s.mp4'
meta=json.loads(subprocess.check_output([str(fp),'-v','error','-show_streams','-show_format','-of','json',str(video)]))
out=root/'output/final-qa';out.mkdir(exist_ok=True)
# Decode the delivered file, not the source composition. Inspect the middle of
# every second, then all 900 frames at reduced resolution for corrupt/blank frames.
for second in range(30):
    subprocess.run([str(ff),'-y','-v','error','-ss',str(second+.5),'-i',str(video),'-vf','scale=960:540','-frames:v','1',str(out/f'second-{second+1:02d}.png')],check=True)
raw=subprocess.check_output([str(ff),'-v','error','-i',str(video),'-an','-vf','scale=96:54,format=gray','-c:v','rawvideo','-f','image2pipe','-'])
frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,54,96)
std=frames.std(axis=(1,2));means=frames.mean(axis=(1,2))
subprocess.run([str(ff),'-y','-v','error','-i',str(video),'-vn','-ac','2','-ar','48000','-c:a','pcm_s16le',str(out/'decoded-audio.wav')],check=True)
with wave.open(str(out/'decoded-audio.wav'),'rb') as w: audio=w.readframes(w.getnframes())
a=np.frombuffer(audio,dtype='<i2').reshape(-1,2).astype(float)/32768
video_stream=next(s for s in meta['streams'] if s['codec_type']=='video')
audio_stream=next(s for s in meta['streams'] if s['codec_type']=='audio')
report={'file':str(video),'video':{k:video_stream.get(k) for k in ['codec_name','width','height','pix_fmt','r_frame_rate','duration','nb_frames']},'audio':{k:audio_stream.get(k) for k in ['codec_name','sample_rate','channels','duration']},'decoded_frames':len(frames),'visually_blank_frame_candidates':np.where(std<1)[0].tolist(),'audio_peak_dbfs':float(20*np.log10(np.max(np.abs(a)))),'clipped_audio_samples':int(np.sum(np.abs(a)>=1)),'audio_video_duration_difference_seconds':abs(float(video_stream['duration'])-float(audio_stream['duration'])),'per_second':[]}
for i in range(30):
    section=a[i*48000:(i+1)*48000]
    report['per_second'].append({'second':i,'decoded_frames':len(frames[i*30:(i+1)*30]),'mean_luma':round(float(means[i*30:(i+1)*30].mean()),2),'audio_rms_dbfs':round(float(20*np.log10(max(1e-8,np.sqrt(np.mean(section**2))))),2)})
(root/'output/quality-report.json').write_text(json.dumps(report,indent=2))
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',22)
files=sorted(out.glob('second-*.png'))
for page in range(2):
    sheet=Image.new('RGB',(1920,1220),'#d7ded9');d=ImageDraw.Draw(sheet)
    for j,f in enumerate(files[page*16:(page+1)*16]):
        x=j%4*480;y=j//4*305
        sheet.paste(Image.open(f).resize((480,270)),(x,y))
        d.text((x+12,y+275),f'Second {page*16+j+1:02d}',font=font,fill='#152426')
    sheet.save(root/f'output/final-review-{page+1}.jpg',quality=95)
print(json.dumps({k:v for k,v in report.items() if k!='per_second'},indent=2))
