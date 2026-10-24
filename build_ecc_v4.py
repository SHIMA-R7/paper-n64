"""PaperBack-inspired experiment, NOT compatible with the PaperBack file format.
Fresh implementation: 32x32 bits/layer, RS(128,96), CRC16, 3+1 XOR blocks.
"""
from pathlib import Path
import sys,random,json,hashlib,struct,binascii
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'vendor'))
from reedsolo import RSCodec
codec=RSCodec(32)
dpi=1200
im=Image.new('RGB',(round(210*dpi/25.4),round(297*dpi/25.4)),'white');draw=ImageDraw.Draw(im)
pdf=canvas.Canvas(str(root.parent/'pdf/paper-n64-ecc-v4.pdf'),pagesize=(210*mm,297*mm))
pdf.setTitle('Paper N64 v4 - spaced dots, local blocks and ECC')
def px(x):return round(x*dpi/25.4)
def rect(x,y,w,h,color=(0,0,0)):
    draw.rectangle((px(x),px(y),max(px(x),px(x+w)-1),max(px(y),px(y+h)-1)),fill=tuple(color))
    pdf.setFillColorRGB(*(v/255 for v in color));pdf.rect(x*mm,(297-y-h)*mm,w*mm,h*mm,fill=1,stroke=0)
def text(x,y,s,pt=9):
    draw.text((px(x),px(y)),s,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',round(pt*dpi/72)),fill='black')
    pdf.setFillColorRGB(0,0,0);pdf.setFont('Helvetica',pt);pdf.drawString(x*mm,(297-y)*mm-pt*.8,s)
def marker(x,y):rect(x-1.5,y-1.5,3,3);rect(x-.75,y-.75,1.5,1.5,(255,255,255))
for x,y in [(8,8),(202,8),(8,289),(202,289)]:marker(x,y)
text(16,14,'PAPER N64 / SPACED DOTS + ECC / v4',15)
text(16,24,'PaperBack-inspired experiment. New format; not readable by PaperBack.',9)
text(16,31,'Plain paper / COLOR / BEST QUALITY / 1200 dpi scan / A4 actual size',9)
text(16,38,'Each group: three data blocks + one XOR recovery block; RS + CRC on every block.',8)
palettes=[[(255,255,255),(0,0,0)],[(255,255,255),(0,255,255),(255,0,255),(0,0,0)],
          [(r,g,b) for r in (0,255) for g in (0,255) for b in (0,255)]]
panels=[];allchecks=[]
for row,(density,fill) in enumerate([(200,1.),(200,.7),(300,1.),(300,.7)]):
    for col,colors in enumerate(palettes):
        layers=int(np.log2(len(colors)));x=20+col*62;y=61+row*50;step=25.4/density;extent=70*step
        text(x,y-15,f'{len(colors)} colors / {density} cells/in',10)
        text(x,y-9,f'Dot width {int(fill*100)}% / {270*layers} useful bytes',8)
        for line in (0,35,70):
            rect(x+line*step,y,.2*step,extent+.2*step)
            rect(x,y+line*step,extent+.2*step,.2*step)
        centers=[(x-3,y-3),(x+extent+3,y-3),(x-3,y+extent+3),(x+extent+3,y+extent+3)]
        for mx,my in centers:marker(mx,my)
        refs=[]
        for k,color in enumerate(colors):
            rx=x+29+(k%2)*5;ry=y+(k//2)*5
            rect(rx,ry,3,3,color);refs.append((rx+1.5,ry+1.5))
        rng=random.Random(644000+col)
        payloads=[[rng.randbytes(90) for _ in range(3)] for layer in range(layers)]
        groups=[]
        for layer in range(layers):
            parity=bytes(a^b^c for a,b,c in zip(*payloads[layer]))
            group=payloads[layer]+[parity];groups.append(group)
            for lost in range(4):
                recovered=bytes(a^b^c for a,b,c in zip(*(group[k] for k in range(4) if k!=lost)))
                assert recovered==group[lost]
        tiles=[]
        for block in range(4):
            bx=x+(block%2)*35*step+2*step;by=y+(block//2)*35*step+2*step
            codes=[];bits=[]
            for layer in range(layers):
                addr=struct.pack('<I',(col<<12)|(layer<<8)|block)
                msg=addr+groups[layer][block]
                msg+=struct.pack('<H',binascii.crc_hqx(msg,0xFFFF))
                code=bytes(codec.encode(msg));assert len(code)==128
                damaged=bytearray(code)
                for j in range(16):damaged[j*7]^=(j+1)
                assert bytes(codec.decode(damaged)[0])==msg
                codes.append(code)
                plane=np.unpackbits(np.frombuffer(code,dtype='uint8')).reshape(32,32)
                checker=(np.indices((32,32)).sum(0)%2).astype('uint8')
                bits.append(plane^checker)
            symbols=sum(plane.astype(int)<<(layers-layer-1) for layer,plane in enumerate(bits))
            for j,symbol in enumerate(symbols.ravel()):
                rect(bx+(j%32+(1-fill)/2)*step,by+(j//32+(1-fill)/2)*step,fill*step,fill*step,colors[symbol])
            recovered=[]
            for j in range(1024):
                recovered.append(colors.index(im.getpixel((px(bx+(j%32+.5)*step),px(by+(j//32+.5)*step)))))
            recovered=np.array(recovered).reshape(32,32)
            for layer in range(layers):
                plane=((recovered>>(layers-layer-1))&1)^checker
                raw=np.packbits(plane.astype('uint8').ravel()).tobytes()
                assert raw==codes[layer]
                decoded=bytes(codec.decode(raw)[0]);assert binascii.crc_hqx(decoded[:94],0xFFFF)==struct.unpack('<H',decoded[94:])[0]
                allchecks.append(True)
            tiles.append(dict(block=block,x_mm=bx,y_mm=by,sha256_codewords=[hashlib.sha256(c).hexdigest() for c in codes]))
        useful=b''.join(chunk for layer in payloads for chunk in layer)
        refname=f'ecc-v4-{density}-{len(colors)}-{int(fill*100)}-reference.bin';(root/refname).write_bytes(useful)
        panels.append(dict(density=density,dot_width_fraction=fill,colors=colors,layers=layers,cell_mm=step,
                           x_mm=x,y_mm=y,grid_extent_mm=extent,marker_centers_mm=centers,color_centers_mm=refs,
                           tiles=tiles,reference_file=refname,payload_bytes=len(useful),sha256=hashlib.sha256(useful).hexdigest()))
text(16,252,'32 x 32 dots per block/layer; 90 payload bytes + 4 address + 2 CRC + 32 RS parity.',8)
text(16,259,'Three data blocks + one XOR: one whole block loss per group can be recovered.',8)
text(16,266,'70% dot width leaves white gaps. 100% is a matched control. Synthetic data only.',8)
rect(20,277,100,.2);rect(20,275,.2,4);rect(119.8,275,.2,4)
text(20,282,'100 mm ruler / plain-paper comparison / 2026-10-24',8)
pdf.showPage();pdf.save()
im.save(root/'ecc-v4-print-1200dpi.png',dpi=(1200,1200));im.thumbnail((1000,1415));im.save(root/'ecc-v4-preview.png')
(root/'ecc-v4-manifest.json').write_text(json.dumps(dict(version=4,not_paperback_compatible=True,
    ecc='RS(128,96), 32 parity bytes, GF(256) reedsolo defaults',crc='CRC16 CCITT init FFFF',
    checks=dict(source_codeword_roundtrips=len(allchecks),sixteen_byte_error_test=True,one_block_xor_loss_test=True),panels=panels),indent=2))
print(f'Created v4: {len(panels)} panels; {len(allchecks)} exact raster/ECC round trips; 16-byte corruption and XOR loss tests passed.')
