from pathlib import Path
import random, json, hashlib
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

root=Path(__file__).resolve().parent
pdfpath=root.parent/'pdf/paper-n64-bw-v2.pdf'
dpi=1200
image=Image.new('1',(round(210/25.4*dpi),round(297/25.4*dpi)),1)
draw=ImageDraw.Draw(image)
pdf=canvas.Canvas(str(pdfpath),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 - monochrome diagnostic v2')
def px(v): return round(v/25.4*dpi)
def rect(x,y,w,h,black=True):
    draw.rectangle((px(x),px(y),px(x+w)-1,px(y+h)-1),fill=0 if black else 1)
    pdf.setFillColorRGB(*((0,0,0) if black else (1,1,1)))
    pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,fill=1,stroke=0)
def text(x,y,s,pt=10):
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72))
    draw.text((px(x),px(y)),s,font=font,fill=0)
    pdf.setFont('Helvetica',pt);pdf.setFillColorRGB(0,0,0)
    pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(cx,cy):
    rect(cx-1.5,cy-1.5,3,3);rect(cx-.75,cy-.75,1.5,1.5,False)
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / BLACK & WHITE DIAGNOSTIC v2',14)
text(16,24,'A4 / 100% actual size / pure black-white / native Brother driver',10)
text(16,31,'Scan: 1200 dpi color or grayscale. Keep all corner markers.',9)
text(16,37,'Known random data, 1152 bytes per panel. No ECC. No game ROM on this page.',9)
panels=[]
for k,density in enumerate([75,100,150,200,300,400,480,600]):
    x=20+(k%2)*94;y=58+(k//2)*48
    n=96; step=25.4/density;size=n*step
    text(x,y-10,f'{density} cells/in | 96 x 96 bits',11)
    seed=640200+k;rng=random.Random(seed)
    bits=[rng.randrange(2) for _ in range(n*n)]
    for j,bit in enumerate(bits):
        if bit:rect(x+(j%n)*step,y+(j//n)*step,step,step)
    markers=[(x-3,y-3),(x+size+3,y-3),(x-3,y+size+3),(x+size+3,y+size+3)]
    for mx,my in markers:marker(mx,my)
    # Sample generated raster independently at the intended physical cell centers.
    recovered=[int(image.getpixel((px(x+(j%n+.5)*step),px(y+(j//n+.5)*step)))==0) for j in range(n*n)]
    assert recovered==bits, f'Raster round trip failed: {density}'
    payload=bytes(sum(bits[i+b]<<(7-b) for b in range(8)) for i in range(0,len(bits),8))
    (root/f'bw-v2-{density}-reference.bin').write_bytes(payload)
    panels.append(dict(density=density,cells=n,x_mm=x,y_mm=y,cell_mm=step,seed=seed,
                       marker_centers_mm=markers,payload_sha256=hashlib.sha256(payload).hexdigest(),raster_bit_errors=0))
text(16,252,'Alignment: four local markers per panel. Density changes; bit count stays constant.',9)
rect(20,270,100,.2);rect(20,268,.2,4);rect(119.8,268,.2,4)
text(20,276,'100 mm ruler - check printed length',9)
text(16,283,'v2 / 2026-10-24 / synthetic diagnostic data / source raster verified: zero bit errors',8)
pdf.showPage();pdf.save()
image.save(root/'bw-v2-print-1200dpi.png',dpi=(1200,1200))
image.thumbnail((1000,1415));image.save(root/'bw-v2-preview.png')
(root/'bw-v2-manifest.json').write_text(json.dumps(dict(version=2,panels=panels,raster_dpi=dpi),indent=2))
print('Created PDF and 1200 dpi 1-bit PNG. All 73728 source bits verified exactly.')
