"""Fresh synthetic payload using palettes selected on v6 A only.
Training labels are public calibration; data labels are for final scoring only.
"""
from pathlib import Path
import sys,json,random,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from codec_v7 import make_data,width,self_test

root=Path(__file__).resolve().parent
palfile=root/'scan-calibration-v6-1200dpi-20261024-172350-calibrated-v6/selected-palettes.json'
palettes=json.loads(palfile.read_text());assert self_test()
dpi=1200;im=Image.new('RGB',(round(210*dpi/25.4),round(297*dpi/25.4)),'white');draw=ImageDraw.Draw(im)
pdf=canvas.Canvas(str(root.parent/'pdf/paper-n64-calibrated-v7.pdf'),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 v7 - calibrated palettes and independent ECC payload')
def px(x):return round(x*dpi/25.4)
def rect(x,y,w,h,color=(0,0,0)):
    draw.rectangle((px(x),px(y),max(px(x),px(x+w)-1),max(px(y),px(y+h)-1)),fill=tuple(color))
    pdf.setFillColorRGB(*(v/255 for v in color));pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,fill=1,stroke=0)
def text(x,y,s,pt=8):
    draw.text((px(x),px(y)),s,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72)),fill='black')
    pdf.setFillColorRGB(0,0,0);pdf.setFont('Helvetica',pt);pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(x,y):rect(x-1.5,y-1.5,3,3);rect(x-.75,y-.75,1.5,1.5,(255,255,255))
def dots(x,y,symbols,step,colors):
    n=symbols.shape[1]
    for j,s in enumerate(symbols.ravel()):
        rect(x+(j%n+.15)*step,y+(j//n+.15)*step,.7*step,.7*step,colors[int(s)])
    recovered=np.array([colors.index(im.getpixel((int((x+(j%n+.5)*step)*dpi/25.4),int((y+(j//n+.5)*step)*dpi/25.4)))) for j in range(symbols.size)]).reshape(symbols.shape)
    assert np.array_equal(recovered,symbols)
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / CALIBRATED PALETTES + ECC / v7',13)
text(16,24,'Plain paper / COLOR / BEST QUALITY + mode ON / A4 actual size / Scan COLOR 1200 dpi',8)
text(16,31,'8 / 10 / 12 / 16 / 20 colors selected from measured J1270N colors. 70% dot width.',8)
text(16,38,'Left: independent data (96 x 96). Right: labeled training (32 x 32) and isolated swatches.',8)
panels=[];verified=0
for row,density in enumerate((200,250,300,400)):
    for col,nc in enumerate((8,10,12,16,20)):
        x=16+37*col;y=57+51*row;step=25.4/density;colors=[tuple(c) for c in palettes[str(nc)]['rgb']]
        symbols,payload,encoded=make_data(nc)
        rng=random.Random(647300+nc);cal=[j%nc for j in range(1024)];rng.shuffle(cal);cal=np.array(cal).reshape(32,32)
        text(x,y-12,f'{nc} colors / {density} cells/in',7.5)
        text(x,y-7,'DATA                 TRAIN',6.5)
        dots(x,y,symbols,step,colors);dots(x+20,y,cal,step,colors)
        centers=[(x-3,y-3),(x+30,y-3),(x-3,y+19),(x+30,y+19)]
        for mx,my in centers:marker(mx,my)
        refs=[]
        for k,color in enumerate(colors):
            rx=x+20+(k%5)*1.5;ry=y+6+(k//5)*1.8
            rect(rx,ry,1.2,1.2,color);refs.append([rx+.6,ry+.6])
        text(x,y+25,'696 bytes / 16 RS blocks',6.5)
        refname=f'calibrated-v7-{nc}-reference.symbols';(root/refname).write_bytes(symbols.astype('uint8').tobytes())
        payloadname='calibrated-v7-reference.bin';(root/payloadname).write_bytes(payload)
        panels.append(dict(density=density,colors=[list(c) for c in colors],color_count=nc,cell_mm=step,dot_width_fraction=.7,
            x_mm=x,y_mm=y,cells=96,training_x_mm=x+20,training_y_mm=y,training_cells=32,training_symbols=cal.tolist(),
            marker_centers_mm=centers,color_centers_mm=refs,reference_file=refname,payload_reference_file=payloadname,
            payload_bytes=len(payload),payload_sha256=hashlib.sha256(payload).hexdigest(),symbols_sha256=hashlib.sha256(symbols.astype('uint8').tobytes()).hexdigest(),
            encoded_cells=encoded,filler_cells=9216-encoded,radix_digits_per_two_bytes=width(nc),radix_efficiency=16/(width(nc)*np.log2(nc))))
        verified+=symbols.size+cal.size
text(16,253,'RS(128,64) + CRC16 + 3 data / 1 XOR. Same 696-byte payload for every condition. Synthetic data.',8)
text(16,260,'Two-byte radix groups bound error propagation. Non-power-of-two colors include radix overhead.',8)
text(16,267,'Training is labeled; payload is scored only after predictions and ECC recovery are fixed.',8)
rect(20,277,100,.2);rect(20,275,.2,4);rect(119.8,275,.2,4)
text(20,282,'100 mm ruler / v7 / 2026-10-24',8)
pdf.showPage();pdf.save();im.save(root/'calibrated-v7-print-1200dpi.png',dpi=(1200,1200))
im.thumbnail((1000,1415));im.save(root/'calibrated-v7-preview.png')
(root/'calibrated-v7-manifest.json').write_text(json.dumps(dict(version=7,calibration_source=str(palfile),
    ecc='RS(128,64), 64 parity bytes; 58 payload + 4 address + 2 CRC per message; groups 3+1 XOR',
    mapping='fixed-length radix per two bytes; deterministic additive-mod-N whitening and spatial shuffle',
    verified_raster_cells=verified,software_tests='radix roundtrip all colors; 32 bad bytes RS; one lost block per XOR group',panels=panels),indent=2))
print(f'Created v7: {len(panels)} conditions; {verified} exact raster cells; codec and loss tests passed.',flush=True)
