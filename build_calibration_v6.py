"""Printer calibration: 4096 labeled colors at large and actual dot sizes.
A and B contain the same colors in independent arrangements. These are known
calibration labels, not payload recovery. Validate learned parameters on B.
"""
from pathlib import Path
import random,itertools,json,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
root=Path(__file__).resolve().parent
colors=list(itertools.product(range(0,256,17),repeat=3))
dpi=1200
im=Image.new('RGB',(round(210*dpi/25.4),round(297*dpi/25.4)),'white');draw=ImageDraw.Draw(im)
pdf=canvas.Canvas(str(root.parent/'pdf/paper-n64-calibration-v6.pdf'),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 v6 - printer calibration, 4096 colors')
def px(x):return round(x*dpi/25.4)
def rect(x,y,w,h,color=(0,0,0)):
    draw.rectangle((px(x),px(y),max(px(x),px(x+w)-1),max(px(y),px(y+h)-1)),fill=tuple(color))
    pdf.setFillColorRGB(*(v/255 for v in color));pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,fill=1,stroke=0)
def text(x,y,s,pt=9):
    draw.text((px(x),px(y)),s,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72)),fill='black')
    pdf.setFillColorRGB(0,0,0);pdf.setFont('Helvetica',pt);pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(x,y):rect(x-1.5,y-1.5,3,3);rect(x-.75,y-.75,1.5,1.5,(255,255,255))
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / PRINTER COLOR CALIBRATION / v6',14)
text(16,24,'4096 RGB colors (16 levels/channel). Plain paper / COLOR / BEST QUALITY + mode ON.',8)
text(16,31,'Scan COLOR at 1200 dpi. A = calibration, B = held-out arrangement. A4 actual size.',8)
text(16,38,'Known calibration targets only. Scores on this sheet do not demonstrate payload recovery.',8)
orders=[]
for seed in (646001,646002):
    order=list(range(4096));random.Random(seed).shuffle(order);orders.append(order)
panels=[]
for row,(pitch,fill,y,title) in enumerate([(1.,1.,59.,'LARGE / 1 mm swatches'),(25.4/200,.7,164.,'DENSE / 200 cells/in'),(25.4/300,.7,218.,'DENSE / 300 cells/in')]):
    for col,x in enumerate((16.,110.)):
        split='A' if col==0 else 'B';order=orders[col];size=64*pitch
        text(x,y-11,f'{split}: {title}',10)
        for j,index in enumerate(order):
            rect(x+(j%64+(1-fill)/2)*pitch,y+(j//64+(1-fill)/2)*pitch,pitch*fill,pitch*fill,colors[index])
        centers=[(x-3,y-3),(x+size+3,y-3),(x-3,y+size+3),(x+size+3,y+size+3)]
        for mx,my in centers:marker(mx,my)
        for j,index in enumerate(order):
            measured=im.getpixel((int((x+(j%64+.5)*pitch)*dpi/25.4),int((y+(j//64+.5)*pitch)*dpi/25.4)))
            assert measured==colors[index],(row,col,j)
        panels.append(dict(split=split,label=title,cells=64,cell_mm=pitch,dot_width_fraction=fill,x_mm=x,y_mm=y,
            marker_centers_mm=centers,color_indices=order,labels_are_calibration_only=True))
text(16,143,'Large patches measure printable gamut. Dense targets measure ink spread and neighboring-color effects.',8)
text(16,197,'A and B use independent spatial arrangements. Keep B out of fitting and parameter selection.',8)
text(16,251,'Next: choose colors by measured separation, then verify on a fresh data sheet with ECC.',8)
rect(20,277,100,.2);rect(20,275,.2,4);rect(119.8,275,.2,4)
text(20,282,'100 mm ruler / v6 / 2026-10-24',8)
pdf.showPage();pdf.save()
im.save(root/'calibration-v6-print-1200dpi.png',dpi=(1200,1200));im.thumbnail((1000,1415));im.save(root/'calibration-v6-preview.png')
(root/'calibration-v6-manifest.json').write_text(json.dumps(dict(version=6,colors=colors,panels=panels,
    raster_cells_verified=24576,calibration_only=True,split_policy='fit on A; evaluate B; finally validate on fresh printed payload'),indent=2))
print('Created v6. All 24576 calibration cells verified exactly. Six targets, two independent arrangements.')
