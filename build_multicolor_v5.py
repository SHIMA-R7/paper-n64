"""20-panel raw color-separability probe. No ECC, ROM or fractional-bit claim.
Nested candidate palettes keep the original eight RGB corner colors unchanged.
"""
from pathlib import Path
import itertools,random,json,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
root=Path(__file__).resolve().parent
base=list(itertools.product((0,255),repeat=3))
candidates=np.array(list(itertools.product((0,64,128,192,255),repeat=3)),float)
def lab(rgb):
    v=np.asarray(rgb,dtype=float)/255
    lin=np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)
    xyz=lin@np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]).T
    xyz/=np.array([.95047,1.,1.08883])
    f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)
colors=list(base);all_lab=lab(candidates)
while len(colors)<20:
    distance=((all_lab[:,None,:]-lab(colors)[None,:,:])**2).sum(2).min(1)
    colors.append(tuple(candidates[distance.argmax()].astype(int).tolist()))
palette=[int(v) for c in colors for v in c]+[0]*(768-60)
dpi=1200
im=Image.new('P',(round(210*dpi/25.4),round(297*dpi/25.4)),7);im.putpalette(palette)
draw=ImageDraw.Draw(im)
pdf=canvas.Canvas(str(root.parent/'pdf/paper-n64-multicolor-v5.pdf'),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 v5 - 8 / 10 / 12 / 16 / 20 colors')
def px(x):return round(x*dpi/25.4)
def rect(x,y,w,h,index=0):
    draw.rectangle((px(x),px(y),max(px(x),px(x+w)-1),max(px(y),px(y+h)-1)),fill=int(index))
    pdf.setFillColorRGB(*(v/255 for v in colors[index]));pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,fill=1,stroke=0)
def text(x,y,s,pt=8):
    draw.text((px(x),px(y)),s,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72)),fill=0)
    pdf.setFillColorRGB(0,0,0);pdf.setFont('Helvetica',pt);pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(cx,cy):rect(cx-1.5,cy-1.5,3,3);rect(cx-.75,cy-.75,1.5,1.5,7)
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / 8 - 10 - 12 - 16 - 20 COLORS / v5',13)
text(16,24,'Plain paper / COLOR / BEST QUALITY + mode ON / A4 actual size / Scan COLOR 1200 dpi',8)
text(16,31,'70% dot width throughout. Nested candidate palettes. Same symbols repeated across densities.',8)
text(16,38,'Raw classification test: no ECC, no game ROM. Reference swatches below each patch.',8)
panels=[];checked=0
for row,density in enumerate([200,300,400,460]):
    for col,nc in enumerate([8,10,12,16,20]):
        x=16+col*37;y=57+row*51;n=96;step=25.4/density;size=n*step;fill=.7
        text(x,y-12,f'{nc} colors / {density} cells/in',7.5)
        seed=645000+nc;rng=random.Random(seed)
        symbols=[j%nc for j in range(n*n)];rng.shuffle(symbols)
        for j,s in enumerate(symbols):
            rect(x+(j%n+.15)*step,y+(j//n+.15)*step,.7*step,.7*step,s)
        centers=[(x-3,y-3),(x+size+3,y-3),(x-3,y+size+3),(x+size+3,y+size+3)]
        for mx,my in centers:marker(mx,my)
        refs=[]
        for k in range(nc):
            rx=x+(k%5)*3.2;ry=y+22+(k//5)*3.2
            rect(rx,ry,2.6,2.6,k);refs.append((rx+1.3,ry+1.3))
        read=[im.getpixel((int((x+(j%n+.5)*step)*dpi/25.4),int((y+(j//n+.5)*step)*dpi/25.4))) for j in range(n*n)]
        assert read==symbols, (density,nc,sum(a!=b for a,b in zip(read,symbols)),[(j,read[j],symbols[j]) for j in range(len(read)) if read[j]!=symbols[j]][:5])
        raw=bytes(symbols);filename=f'multicolor-v5-{nc}-reference.symbols';(root/filename).write_bytes(raw)
        panels.append(dict(density=density,color_count=nc,colors=colors[:nc],cells=n,cell_mm=step,
            dot_width_fraction=.7,x_mm=x,y_mm=y,marker_centers_mm=centers,color_centers_mm=refs,
            storage='one symbol index per byte, raw classification only; not payload bits',seed=seed,
            reference_file=filename,symbol_count=len(raw),sha256=hashlib.sha256(raw).hexdigest(),raster_symbol_errors=0))
        checked+=len(raw)
text(16,253,'Reference swatches are ordered left-to-right, top-to-bottom. Five swatches per row.',8)
text(16,260,'Additional colors chosen by max-min CIELAB distance on an sRGB grid; print gamut not calibrated.',8)
rect(20,277,100,.2);rect(20,275,.2,4);rect(119.8,275,.2,4)
text(20,282,'100 mm ruler / v5 / 2026-10-24',8)
pdf.showPage();pdf.save()
im.save(root/'multicolor-v5-print-1200dpi.png',dpi=(1200,1200));im.thumbnail((1000,1415));im.convert('RGB').save(root/'multicolor-v5-preview.png')
(root/'multicolor-v5-manifest.json').write_text(json.dumps(dict(version=5,panels=panels,
    palette_method='nested 8 RGB corners plus max-min CIE76 candidates; not printer-calibrated',
    raster_symbols_verified=checked),indent=2))
print(f'Created 20-panel v5 sheet. Verified all {checked} raster symbols exactly.',flush=True)
