from pathlib import Path
import random,json,hashlib,math
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
root=Path(__file__).resolve().parent
dpi=1200
im=Image.new('RGB',(round(210*dpi/25.4),round(297*dpi/25.4)),'white')
draw=ImageDraw.Draw(im)
pdf=canvas.Canvas(str(root.parent/'pdf/paper-n64-color-v3.pdf'),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 color diagnostic v3')
def px(x):return round(x*dpi/25.4)
def rect(x,y,w,h,color=(0,0,0)):
    draw.rectangle((px(x),px(y),px(x+w)-1,px(y+h)-1),fill=tuple(color))
    pdf.setFillColorRGB(*(v/255 for v in color));pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,stroke=0,fill=1)
def text(x,y,s,pt=10):
    draw.text((px(x),px(y)),s,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72)),fill='black')
    pdf.setFillColorRGB(0,0,0);pdf.setFont('Helvetica',pt);pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(x,y):rect(x-1.5,y-1.5,3,3);rect(x-.75,y-.75,1.5,1.5,(255,255,255))
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / COLOR DIAGNOSTIC v3',15)
text(16,24,'PLAIN PAPER / BEST QUALITY + BEST QUALITY MODE / COLOR / A4 100%',9)
text(16,31,'Scan at 1200 dpi COLOR. Keep all corner markers. No game ROM on this page.',9)
palettes=[[(255,255,255),(0,255,255),(255,0,255),(0,0,0)],
          [(r,g,b) for r in (0,255) for g in (0,255) for b in (0,255)]]
panels=[]
for row,density in enumerate([200,300,400,480,600]):
    for col,colors in enumerate(palettes):
        x=20+col*94;y=55+row*39;n=128;step=25.4/density;size=n*step
        seed=643000+row*10+col;rng=random.Random(seed)
        symbols=[rng.randrange(len(colors)) for _ in range(n*n)]
        text(x,y-10,f'{density} cells/in | {len(colors)} colors | 128 x 128',10)
        for j,s in enumerate(symbols):rect(x+(j%n)*step,y+(j//n)*step,step,step,colors[s])
        centers=[(x-3,y-3),(x+size+3,y-3),(x-3,y+size+3),(x+size+3,y+size+3)]
        for mx,my in centers:marker(mx,my)
        refs=[]
        for k,color in enumerate(colors):
            rx=x+34+(k%2)*6;ry=y+(k//2)*6
            rect(rx,ry,4,4,color);refs.append((rx+2,ry+2))
        recovered=[colors.index(im.getpixel((px(x+(j%n+.5)*step),px(y+(j//n+.5)*step)))) for j in range(n*n)]
        assert symbols==recovered
        bits=int(math.log2(len(colors)));payload=bytearray();acc=0;count=0
        for symbol in symbols:
            acc=(acc<<bits)|symbol;count+=bits
            while count>=8:count-=8;payload.append((acc>>count)&255)
        refname=f'color-v3-{density}-{len(colors)}-reference.bin'
        (root/refname).write_bytes(payload)
        panels.append(dict(density=density,colors=colors,cells=n,cell_mm=step,x_mm=x,y_mm=y,seed=seed,
                           marker_centers_mm=centers,color_centers_mm=refs,reference_file=refname,
                           payload_bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),raster_symbol_errors=0))
text(16,257,'Each panel has four registration markers and isolated color references.',9)
text(16,264,'Compare with BW v2. Payloads are synthetic; no error correction in this probe.',9)
rect(20,277,100,.2);rect(20,275,.2,4);rect(119.8,275,.2,4)
text(20,281,'100 mm ruler / v3 / 2026-10-24',8)
pdf.showPage();pdf.save()
im.save(root/'color-v3-print-1200dpi.png',dpi=(1200,1200))
im.thumbnail((1000,1415));im.save(root/'color-v3-preview.png')
(root/'color-v3-manifest.json').write_text(json.dumps(dict(version=3,panels=panels,raster_dpi=dpi),indent=2))
print('Created color v3 PDF and raster; all 163840 source symbols verified exactly.',flush=True)
