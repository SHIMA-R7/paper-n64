"""Build a reproducible print/scan probe; no ROM bytes are printed on it."""
from pathlib import Path
import hashlib, json, lzma, random, math
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent.parent
ROM = WORK / '64-ROM/Super Mario 64 - Shindou Edition (Japan).z64'
OUT = WORK / 'output/pdf'
OUT.mkdir(parents=True, exist_ok=True)
data = ROM.read_bytes()
packed = lzma.compress(data, preset=9)
assert lzma.decompress(packed) == data
(ROOT / 'sm64-shindou.z64.xz').write_bytes(packed)
palettes = {
    '2 colors': [(255,255,255),(0,0,0)],
    '4 colors': [(255,255,255),(0,255,255),(255,0,255),(0,0,0)],
    '8 colors': [(r,g,b) for r in (0,255) for g in (0,255) for b in (0,255)],
}
pdf = canvas.Canvas(str(OUT / 'paper-n64-calibration.pdf'), pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 - print and scan calibration v1')
def label(x,y,s,size=9):
    pdf.setFont('Helvetica',size)
    pdf.setFillColorRGB(0,0,0)
    pdf.drawString(x*mm,(297-y)*mm,s)
def square(x,y,w,color):
    pdf.setFillColorRGB(*(v/255 for v in color))
    pdf.rect(x*mm,(297-y-w)*mm,w*mm,w*mm,fill=1,stroke=0)
def marker(x,y):
    square(x,y,4,(0,0,0)); square(x+1,y+1,2,(255,255,255))
for x,y in [(7,7),(199,7),(7,286),(199,286)]: marker(x,y)
label(16,17,'PAPER N64 / PRINT-SCAN PROBE v1',15)
label(16,24,'A4 - Actual size 100% - Borderless OFF - High quality - No photo enhancement')
label(16,30,'Scan: COLOR, 1200 dpi, PNG or lossless TIFF. Keep all four corner markers.')
label(16,36,'Synthetic test data only. This page does not contain the game.')
patches=[]
for row,density in enumerate([200,300,400,480,600]):
    top = 44 + row*44
    for col,(name,palette) in enumerate(palettes.items()):
        x = 16 + col*64
        label(x,top,f'{density} cells/in | {name}',10)
        seed = 640000 + row*10 + col
        rng = random.Random(seed)
        count = round(20*density/25.4)
        cell = 2400//density
        img = Image.new('RGB',(count,count))
        img.putdata([palette[rng.randrange(len(palette))] for _ in range(count*count)])
        img = img.resize((count*cell,count*cell),Image.Resampling.NEAREST)
        size = count*25.4/density
        y = top+3
        pdf.drawImage(ImageReader(img),x*mm,(297-y-size)*mm,width=size*mm,height=size*mm,mask=None)
        marker(x+25,y); marker(x+25,y+size-4)
        for k,color in enumerate(palette): square(x+34+(k%2)*5,y+(k//2)*5,4,color)
        patches.append(dict(density=density,palette=name,seed=seed,cells=count,
                            x_mm=x,y_mm=y,width_mm=size,colors=palette))
pdf.setStrokeColorRGB(0,0,0)
pdf.line(16*mm,22*mm,116*mm,22*mm)
pdf.line(16*mm,20*mm,16*mm,24*mm)
pdf.line(116*mm,20*mm,116*mm,24*mm)
label(16,281,'Ruler: exactly 100 mm. Measure after printing. Do not fit to page.',8)
label(16,289,'Keep paper type, quality, ink and scan settings for comparison. v1 / 2026-10-23',8)
pdf.showPage(); pdf.save()
report = dict(source=str(ROM),source_bytes=len(data),compressed_bytes=len(packed),
              sha256=hashlib.sha256(data).hexdigest(),roundtrip_verified=True,
              model='Brother DCP-J1200N',
              capacity_assumptions=dict(area_mm=[200,277],payload_fraction=0.65),
              required_density_8color=math.sqrt(len(packed)*8/(3*.65*(200*277/25.4**2))),
              patches=patches)
(ROOT/'probe-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='patches'},indent=2))
