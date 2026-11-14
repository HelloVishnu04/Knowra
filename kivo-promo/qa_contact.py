from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
root=Path(__file__).resolve().parent/'output'
files=sorted((root/'qa').glob('*.png'))
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',20)
for page in range((len(files)+15)//16):
    sheet=Image.new('RGB',(1920,1220),'#d7ded9');d=ImageDraw.Draw(sheet)
    for j,f in enumerate(files[page*16:(page+1)*16]):
        x=(j%4)*480;y=(j//4)*305
        im=Image.open(f).convert('RGB').resize((480,270))
        sheet.paste(im,(x,y));d.text((x+12,y+276),f'{int(f.stem)/30:05.2f}s · frame {int(f.stem)}',font=font,fill='#152426')
    sheet.save(root/f'contact-sheet-{page+1}.jpg',quality=94)
print(f'{len(files)} sampled frames, {(len(files)+15)//16} contact sheets')
