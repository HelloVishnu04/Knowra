import React from 'react';
import {AbsoluteFill,Sequence,Img,staticFile,useCurrentFrame,useVideoConfig,interpolate,Easing} from 'remotion';
import {Audio} from '@remotion/media';
import {loadFont} from '@remotion/fonts';
for(const weight of ['400','500','600','700','800'])loadFont({family:'Manrope',url:staticFile(`Manrope-${weight}.ttf`),weight});
const C={ink:'#0D1718',panel:'#152426',line:'#314446',mint:'#BBF7D0',white:'#F5F7F2',muted:'#A7B8B5',orange:'#F7B48D'};
const ease=Easing.bezier(.16,1,.3,1);
const p=(f:number,a:number,b:number)=>interpolate(f,[a,b],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:ease});
function Icon({type='spark',size=38,color='currentColor'}:{type?:string,size?:number,color?:string}){
 const paths:Record<string,React.ReactNode>={
  spark:<path d="M12 2L14.7 9.3L22 12L14.7 14.7L12 22L9.3 14.7L2 12L9.3 9.3Z"/>,
  people:<><circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0112 0v3M17 4a4 4 0 010 8M19 15a5 5 0 012 4v2"/></>,
  sales:<path d="M4 19V5M4 19h17M8 14l5-5 4 3 4-7M17 5h4v4"/>,
  project:<><rect x="3" y="4" width="18" height="17" rx="3"/><path d="M8 2v4M16 2v4M3 10h18M8 15h3M14 15h3"/></>,
  check:<path d="M5 12l4 4L19 6"/>, arrow:<path d="M4 12h16M13 5l7 7-7 7"/>,
  bell:<path d="M5 16h14l-2-4V8A5 5 0 007 8v4zM10 20h4"/>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></>,
  alert:<path d="M12 3L2 21h20zM12 9v5M12 17v1"/>,
  grid:<><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>
 };
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">{paths[type]||paths.spark}</svg>
}
function Logo({width=170,dark=false}:{width?:number,dark?:boolean}){return <Img src={staticFile('kivo-logo.svg')} style={{width,height:width*36/122,objectFit:'contain',filter:dark?'brightness(0)':'none'}}/>}
function Shell({light=false,label='AI FOR THE WAY YOU WORK',children}:{light?:boolean,label?:string,children:React.ReactNode}){
 return <AbsoluteFill style={{background:light?C.white:C.ink,color:light?C.ink:C.white,fontFamily:'Manrope',overflow:'hidden'}}>
  <AbsoluteFill style={{backgroundImage:`radial-gradient(${light?'#15242611':'#bbf7d00b'} 1px,transparent 1px)`,backgroundSize:'36px 36px',opacity:.5}}/>
  <div style={{position:'absolute',left:100,top:62}}><Logo dark={light}/></div>
  <div style={{position:'absolute',right:100,top:77,fontSize:19,letterSpacing:3.4,fontWeight:700,color:light?'#677774':C.muted}}>{label}</div>{children}
 </AbsoluteFill>
}
function Enter({children,at=0,style={},distance=34}:{children:React.ReactNode,at?:number,style?:React.CSSProperties,distance?:number}){
 const f=useCurrentFrame();const a=p(f+9,at,at+22);
 return <div style={{...style,opacity:a,translate:`0px ${(1-a)*distance}px`}}>{children}</div>
}
function Tag({children,light=false,color}:{children:React.ReactNode,light?:boolean,color?:string}){
 return <div style={{display:'inline-flex',gap:12,alignItems:'center',fontSize:22,fontWeight:700,letterSpacing:1.5,color:color||(light?'#466157':C.mint)}}><span style={{width:8,height:8,borderRadius:8,background:'currentColor'}}/>{children}</div>
}
function Card({title,icon,children,style={},light=false}:{title:string,icon:string,children:React.ReactNode,style?:React.CSSProperties,light?:boolean}){
 return <div style={{border:`1px solid ${light?'#d5dfd6':C.line}`,borderRadius:24,background:light?'#FFFFFF':C.panel,padding:30,boxShadow:light?'0 20px 70px #16362b0a':'0 30px 60px #00000025',...style}}><div style={{display:'flex',gap:18,alignItems:'center',fontWeight:700,fontSize:26,marginBottom:28}}><div style={{color:light?'#34694c':C.mint}}><Icon type={icon} size={30}/></div>{title}</div>{children}</div>
}
function Status({children,orange=false,light=false}:{children:React.ReactNode,orange?:boolean,light?:boolean}){
 return <div style={{display:'inline-flex',alignItems:'center',gap:10,borderRadius:30,padding:'10px 16px',fontSize:20,fontWeight:600,background:orange?'#f7b48d14':light?'#e6f5e8':'#bbf7d015',color:orange?C.orange:light?'#285e3c':C.mint}}><Icon type={orange?'clock':'check'} size={21}/>{children}</div>
}
function Opening(){
 const f=useCurrentFrame();const q=p(f+9,0,32);const ask=p(f,66,84);
 return <Shell>
  <div style={{position:'absolute',width:1000,height:1000,right:-180,top:110,borderRadius:'50%',border:'1px solid #bbf7d021',scale:1+.025*Math.sin(f/70)}}/>
  <div style={{position:'absolute',left:100,top:242,width:970}}><Enter><Tag>GROWING BUSINESS. GROWING COMPLEXITY.</Tag></Enter><Enter at={4}><div style={{fontSize:128,fontWeight:600,lineHeight:1.07,letterSpacing:-7,marginTop:36}}>Your business.<br/><span style={{color:C.mint}}>In motion.</span></div></Enter><div style={{fontSize:39,color:C.muted,marginTop:42,opacity:ask,translate:`0 ${(1-ask)*15}px`}}>Is your work keeping up?</div></div>
  <svg width="1920" height="1080" style={{position:'absolute',pointerEvents:'none'}}><path d="M1015 420H1165V675H1350" stroke="#67817A" strokeWidth="2" strokeDasharray="8 12" fill="none" strokeDashoffset={-f*1.4}/></svg>
  <div style={{position:'absolute',left:1110,top:225,rotate:'-5deg',translate:`${(1-q)*80}px ${Math.sin(f/28)*5}px`,opacity:q}}><Card title="People" icon="people" style={{width:490}}><div style={{fontSize:29,marginBottom:25}}>Leave request</div><Status orange>Awaiting approval</Status></Card></div>
  <div style={{position:'absolute',left:1250,top:500,rotate:'4deg',translate:`${(1-p(f,12,40))*80}px ${Math.sin(f/31+1)*5}px`,opacity:p(f,12,40)}}><Card title="Sales" icon="sales" style={{width:430}}><div style={{display:'flex',gap:10,marginBottom:23}}>{[80,120,65].map((w,i)=><div key={i} style={{width:w,height:9,borderRadius:5,background:i===1?C.mint:'#475f59'}}/>)}</div><Status orange>Update needed</Status></Card></div>
  <div style={{position:'absolute',left:1070,top:745,rotate:'-2deg',opacity:p(f,24,48)}}><Card title="Projects" icon="project" style={{width:420,padding:25}}><div style={{fontSize:24,color:C.muted}}>One more follow-up.</div></Card></div>
  <div style={{position:'absolute',bottom:65,left:100,fontSize:20,color:C.muted,letterSpacing:2}}>CONNECTED TEAMS START HERE</div>
 </Shell>
}
function Friction(){
 const f=useCurrentFrame();
 return <Shell label="THE COST OF DISCONNECTED WORK"><div style={{position:'absolute',left:100,top:275}}><Enter distance={22}><div style={{fontSize:122,fontWeight:600,letterSpacing:-6,lineHeight:1.12}}>Too many tools.</div></Enter><Enter at={15} distance={22}><div style={{fontSize:122,fontWeight:600,letterSpacing:-6,lineHeight:1.12,color:C.orange}}>Too little flow.</div></Enter><Enter at={28}><div style={{fontSize:35,color:C.muted,marginTop:40}}>Updates. Approvals. Follow-ups.</div></Enter></div>
  {[{top:230,left:1260,text:'Manual update',icon:'sales',delay:0},{top:415,left:1150,text:'Approval pending',icon:'clock',delay:12},{top:600,left:1280,text:'Any progress?',icon:'bell',delay:24}].map((a,i)=><div key={a.text} style={{position:'absolute',top:a.top,left:a.left,width:450,opacity:p(f,a.delay,a.delay+14),translate:`${(1-p(f,a.delay,a.delay+16))*60}px 0`,rotate:`${i===1?-4:3}deg`}}><div style={{display:'flex',gap:21,alignItems:'center',border:`1px solid ${C.line}`,borderRadius:22,padding:'32px 26px',background:C.panel,fontSize:28,boxShadow:'0 24px 70px #0003'}}><Icon type={a.icon} color={C.orange}/>{a.text}</div></div>)}
  <div style={{position:'absolute',left:100,bottom:85,height:2,width:1720,background:C.line}}><div style={{height:2,width:1720*p(f,0,75),background:C.orange}}/></div>
 </Shell>
}
function Connected(){
 const f=useCurrentFrame();const join=p(f,12,65);
 return <Shell light label="MEET YOUR CONNECTED WORKSPACE"><div style={{position:'absolute',top:205,left:100,right:100,textAlign:'center'}}><Enter><Tag light>MEET KIVO AI</Tag></Enter><Enter at={4}><div style={{fontSize:112,letterSpacing:-6,fontWeight:600,marginTop:24}}>One connected workspace.</div></Enter></div>
  <svg width="1920" height="1080" style={{position:'absolute'}}><path d="M470 610H1450" stroke="#CEDBD0" strokeWidth="3"/><path d="M470 610H1450" stroke="#4B9670" strokeWidth="4" strokeDasharray={980} strokeDashoffset={980*(1-join)}/><circle cx={470+980*join} cy="610" r="7" fill="#4B9670"/>{[0,1,2].map(i=><circle key={i} cx={470+((f*7+i*326)%980)} cy="610" r="6" fill="#346e4b" opacity={p(f,60,75)}/>)}</svg>
  {[{x:230,title:'HR',icon:'people',sub:'People, in sync.'},{x:760,title:'Sales',icon:'sales',sub:'Pipelines, connected.'},{x:1290,title:'Projects',icon:'project',sub:'Progress, visible.'}].map((a,i)=><div key={a.title} style={{position:'absolute',left:a.x,top:470,opacity:p(f,14+i*10,40+i*10),translate:`${(i-1)*(1-join)*95}px ${(1-join)*35}px`,width:400,height:280,border:'1px solid #d7dfd7',borderRadius:28,background:'#fff',boxShadow:'0 30px 75px #183e2a0c',padding:'35px 35px'}}><div style={{width:65,height:65,borderRadius:19,background:'#e7f4e7',display:'flex',alignItems:'center',justifyContent:'center',color:'#306544'}}><Icon type={a.icon}/></div><div style={{fontSize:42,fontWeight:700,marginTop:24,letterSpacing:-1.6}}>{a.title}</div><div style={{fontSize:25,color:'#65786b',marginTop:10}}>{a.sub}</div></div>)}
  <Enter at={65} style={{position:'absolute',top:842,left:0,width:'100%',textAlign:'center'}}><div style={{display:'inline-flex',gap:14,alignItems:'center',fontSize:28,color:'#41604b'}}><Icon type="spark" size={28}/>AI agents that move work forward.</div></Enter>
 </Shell>
}
function DemoFrame({number,category,title,sub,children}:{number:string,category:string,title:React.ReactNode,sub:string,children:React.ReactNode}){
 return <Shell label="AI AGENTS IN ACTION"><div style={{position:'absolute',left:100,top:253,width:740}}><Enter distance={22}><Tag>{number} / {category}</Tag></Enter><Enter at={2} distance={26}><div style={{fontSize:100,fontWeight:600,lineHeight:1.1,letterSpacing:-5,marginTop:35}}>{title}</div></Enter><Enter at={10} distance={14}><div style={{fontSize:32,lineHeight:1.5,color:C.muted,marginTop:36,maxWidth:670}}>{sub}</div></Enter></div>{children}
  <div style={{position:'absolute',left:100,bottom:64,display:'flex',gap:12}}>{[1,2,3].map(i=><div key={i} style={{height:4,width:i===Number(number)?100:44,borderRadius:4,background:i===Number(number)?C.mint:C.line}}/>)}</div><div style={{position:'absolute',right:100,bottom:60,fontSize:18,color:'#7D9490',letterSpacing:1}}>WORKFLOW ILLUSTRATION</div>
 </Shell>
}
function Request(){
 const f=useCurrentFrame();const a=p(f,14,37);
 return <DemoFrame number="01" category="HR" title={<>Requests.<br/><span style={{color:C.mint}}>Routed.</span></>} sub="Send the next step to the right person."><div style={{position:'absolute',left:930,top:260,width:860}}><Enter><Card title="Leave request" icon="people" style={{padding:38}}><div style={{display:'flex',alignItems:'center',gap:20,marginBottom:28}}><div style={{width:62,height:62,borderRadius:40,background:'#314a43',display:'grid',placeItems:'center',fontSize:22,color:C.mint}}>AM</div><div><div style={{fontSize:30,fontWeight:600}}>Alex Morgan</div><div style={{fontSize:22,color:C.muted,marginTop:5}}>2 days · Annual leave</div></div></div><div style={{borderTop:`1px solid ${C.line}`,paddingTop:24,display:'flex',justifyContent:'space-between',alignItems:'center'}}><span style={{fontSize:24,color:C.muted}}>Next step</span><Status>{f<32?'Routing request':'Sent to manager'}</Status></div></Card></Enter></div>
  <svg width="1920" height="1080" style={{position:'absolute'}}><path d="M1360 590V697" stroke={C.line} strokeWidth="3"/><path d="M1360 590V697" stroke={C.mint} strokeWidth="3" strokeDasharray={107} strokeDashoffset={107*(1-a)}/><circle cx="1360" cy={590+107*a} r="6" fill={C.mint}/></svg>
  <Enter at={26} style={{position:'absolute',left:1080,top:696,width:560}}><div style={{borderRadius:20,border:'1px solid #78a88c',background:'#1d332b',padding:26,display:'flex',gap:20,alignItems:'center'}}><Icon type="check" color={C.mint}/><div><div style={{fontSize:28,fontWeight:600}}>Ready for review</div><div style={{fontSize:21,color:C.muted,marginTop:6}}>Your manager makes the decision.</div></div></div></Enter>
 </DemoFrame>
}
function Sales(){
 const f=useCurrentFrame();const a=p(f,10,35);
 return <DemoFrame number="02" category="SALES" title={<>Pipelines.<br/><span style={{color:C.mint}}>Updated.</span></>} sub="Keep the next conversation in view."><Enter style={{position:'absolute',left:900,top:255,width:900}}><Card title="Sales pipeline" icon="sales" style={{padding:34,height:510}}><div style={{display:'flex',gap:18}}>{['New lead','In progress','Follow-up'].map((x,i)=><div key={x} style={{width:265,height:300,background:'#0f1d1f',borderRadius:14,padding:20}}><div style={{fontSize:21,color:C.muted,marginBottom:25}}>{x}</div>{i!==0&&<div style={{height:74,border:'1px solid #233a35',borderRadius:10,background:'#152623',marginTop:i===1?135:0}}/>}</div>)}</div><div style={{position:'absolute',left:54+283*a,top:160,width:225,padding:24,background:C.mint,borderRadius:13,color:C.ink,boxShadow:'0 15px 40px #0003',rotate:`${-2*Math.sin(a*Math.PI)}deg`}}><div style={{fontSize:24,fontWeight:800}}>Acme Studio</div><div style={{fontSize:19,marginTop:9}}>Discovery call</div><div style={{width:'100%',height:4,background:'#6c9d7b55',marginTop:25,borderRadius:3}}/></div><div style={{position:'absolute',left:34,bottom:30,opacity:p(f,32,44)}}><Status>Pipeline updated</Status></div></Card></Enter></DemoFrame>
}
function Risk(){
 const f=useCurrentFrame();const a=p(f,14,33);
 return <DemoFrame number="03" category="PROJECTS" title={<>Risks.<br/><span style={{color:C.mint}}>Flagged.</span></>} sub="See what needs your attention."><Enter style={{position:'absolute',left:930,top:250,width:860}}><Card title="Project overview" icon="project" style={{padding:36,height:510}}><div style={{fontSize:33,fontWeight:600,marginBottom:32}}>Product launch</div>{['Design','Development','Review'].map((name,i)=><div key={name} style={{display:'flex',alignItems:'center',gap:22,marginBottom:27}}><div style={{fontSize:23,width:170,color:C.muted}}>{name}</div><div style={{height:16,width:480,background:'#233633',borderRadius:10}}><div style={{height:16,width:[390,260,120][i],background:i===1&&f>18?C.orange:C.mint,borderRadius:10,opacity:i===2?.4:1}}/></div></div>)}<div style={{marginTop:29,opacity:a,translate:`0 ${(1-a)*16}px`,display:'flex',alignItems:'center',gap:16,padding:'20px 23px',border:'1px solid #a2785d',borderRadius:14,background:'#f7b48d0b',color:C.orange}}><Icon type="alert" size={30}/><span style={{fontSize:25,fontWeight:600}}>Timeline risk · Review needed</span></div></Card></Enter></DemoFrame>
}
function Focus(){
 const f=useCurrentFrame();
 return <Shell light label="MORE ROOM FOR YOUR NEXT MOVE"><div style={{position:'absolute',left:100,top:260,width:800}}><Enter><Tag light>CONNECTED WORK. CLEARER PRIORITIES.</Tag></Enter><Enter at={4}><div style={{fontSize:128,letterSpacing:-7,lineHeight:1.09,fontWeight:600,marginTop:36}}>Focus on<br/>what’s next.</div></Enter><Enter at={20}><div style={{fontSize:34,lineHeight:1.5,color:'#60766a',marginTop:40}}>AI handles routine steps.<br/>Your team makes the decisions.</div></Enter></div><div style={{position:'absolute',left:1030,top:217,width:760,height:640,borderRadius:32,background:'#fff',border:'1px solid #d8e2d9',boxShadow:'0 35px 80px #285f3c0b',padding:36,opacity:p(f,0,22)}}><div style={{display:'flex',alignItems:'center',gap:15,fontSize:29,fontWeight:700,borderBottom:'1px solid #e2e9e2',paddingBottom:27}}><Icon type="grid" color="#497755"/>Your connected workspace</div>{[{title:'HR',sub:'Request sent to manager',icon:'people'},{title:'Sales',sub:'Pipeline updated',icon:'sales'},{title:'Projects',sub:'Risk ready for review',icon:'project'}].map((item,i)=><div key={item.title} style={{display:'flex',alignItems:'center',gap:22,borderBottom:'1px solid #edf0ec',padding:'27px 0',opacity:p(f,15+i*12,32+i*12),translate:`${(1-p(f,15+i*12,32+i*12))*25}px 0`}}><div style={{width:59,height:59,display:'grid',placeItems:'center',background:'#eaf6e9',borderRadius:16,color:'#356447'}}><Icon type={item.icon} size={29}/></div><div style={{flex:1}}><div style={{fontSize:26,fontWeight:700}}>{item.title}</div><div style={{fontSize:22,color:'#6c7d70',marginTop:5}}>{item.sub}</div></div><Icon type="check" size={26} color="#42875b"/></div>)}<Enter at={60}><div style={{display:'flex',alignItems:'center',gap:12,fontSize:23,color:'#41674c',marginTop:30}}><Icon size={26}/>One place to move forward.</div></Enter></div></Shell>
}
function PromiseScene(){
 const f=useCurrentFrame();const a=p(f,45,62);
 return <Shell label="MAKE SPACE FOR PROGRESS"><div style={{position:'absolute',left:100,top:290}}><Enter distance={24}><div style={{fontSize:145,lineHeight:1.13,fontWeight:600,letterSpacing:-8}}>Less busywork.</div></Enter><div style={{fontSize:145,lineHeight:1.13,fontWeight:600,letterSpacing:-8,color:C.mint,marginTop:18,opacity:a,translate:`0 ${(1-a)*35}px`}}>More progress.</div></div><svg width="1920" height="1080" style={{position:'absolute'}}><path d="M106 714H1400" stroke={C.mint} strokeWidth="4" strokeDasharray={1294} strokeDashoffset={1294*(1-p(f,49,79))}/><circle cx={106+1294*p(f,49,79)} cy="714" r="6" fill={C.mint}/></svg></Shell>
}
function EndCard(){
 return <AbsoluteFill style={{background:C.ink,color:C.white,fontFamily:'Manrope',alignItems:'center',justifyContent:'center'}}><div style={{position:'absolute',inset:0,background:'radial-gradient(ellipse at 50% 85%,#28563b55,transparent 65%)'}}/><div style={{position:'absolute',top:223}}><Logo width={460}/></div><div style={{position:'absolute',top:431,fontSize:43,fontWeight:500,letterSpacing:-1}}>Less busywork. More progress.</div><div style={{position:'absolute',top:564,borderRadius:18,background:C.mint,color:C.ink,padding:'28px 48px',fontSize:37,fontWeight:800,display:'flex',alignItems:'center',gap:36}}>Book a demo<Icon type="arrow" size={35}/></div><div style={{position:'absolute',top:740,fontSize:31,color:C.muted,letterSpacing:1}}>kivo.ai</div></AbsoluteFill>
}
export const KivoPromo=()=>{
 const {fps}=useVideoConfig();
 return <AbsoluteFill style={{background:C.ink}}><Sequence name="01 · The hook" from={0} durationInFrames={4*fps}><Opening/></Sequence><Sequence name="02 · Disconnected work" from={4*fps} durationInFrames={3*fps}><Friction/></Sequence><Sequence name="03 · Kivo reveal" from={7*fps} durationInFrames={5*fps}><Connected/></Sequence><Sequence name="04 · Requests routed" from={12*fps} durationInFrames={2.5*fps}><Request/></Sequence><Sequence name="05 · Pipelines updated" from={14.5*fps} durationInFrames={2.5*fps}><Sales/></Sequence><Sequence name="06 · Risks flagged" from={17*fps} durationInFrames={2*fps}><Risk/></Sequence><Sequence name="07 · Focus on what's next" from={19*fps} durationInFrames={5*fps}><Focus/></Sequence><Sequence name="08 · The promise" from={24*fps} durationInFrames={3*fps}><PromiseScene/></Sequence><Sequence name="09 · Book a demo" from={27*fps} durationInFrames={3*fps}><EndCard/></Sequence><Audio src={staticFile('kivo-score.wav')} name="Original score · 120 BPM"/></AbsoluteFill>
};
