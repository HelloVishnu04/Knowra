import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia,renderStill} from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs';
const root=process.cwd();const out=path.join(root,'output');fs.mkdirSync(out,{recursive:true});
const serveUrl=await bundle({entryPoint:path.join(root,'src/index.tsx'),publicDir:path.join(root,'public'),outDir:path.join(out,'bundle')});
const composition=await selectComposition({serveUrl,id:'KivoAI'});
const mode=process.argv[2]||'video';
if(mode==='stills'){
 const frames=[0,30,60,90,120,150,180,210,240,270,300,330,360,390,420,435,450,480,510,540,570,600,630,660,690,720,750,765,780,810,840,870,899];
 fs.mkdirSync(path.join(out,'qa'),{recursive:true});
 for(const frame of frames){await renderStill({serveUrl,composition,frame,output:path.join(out,'qa',`${String(frame).padStart(4,'0')}.png`),scale:.5});console.log(`Checked frame ${frame} (${(frame/30).toFixed(2)}s)`);}
}else{
 let last=-1;
 await renderMedia({serveUrl,composition,codec:'h264',outputLocation:path.join(out,mode==='4k'?'Kivo-AI-Promo-30s-4K.mp4':'Kivo-AI-Promo-30s.mp4'),scale:mode==='4k'?2:1,crf:17,pixelFormat:'yuv420p',audioCodec:'aac',audioBitrate:'320k',concurrency:3,onProgress:({progress})=>{const pct=Math.floor(progress*100);if(pct>=last+5){console.log(`Render ${pct}%`);last=pct;}}});
 console.log('VIDEO COMPLETE');
}
