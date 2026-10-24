"""One A4 side, complete compressed ROM plus two layers of redundancy."""
from pathlib import Path
import sys,json,hashlib,argparse
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from codec_v8 import *

parser=argparse.ArgumentParser(description='Encode any local file as one v8 A4 paper archive.')
parser.add_argument('source',type=Path,help='Local input file; compressed data plus header must fit 317,376 bytes.')
parser.add_argument('--output',type=Path,default=Path('generated'),help='Output directory (default: generated).')
parser.add_argument('--no-pdf',action='store_true',help='Create PNG and report only.')
args=parser.parse_args()
root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
source=args.source
container,metadata,compressed=container_from_file(source)
print('Container:',len(container),'Capacity:',GROUPS*DATA_SHARDS*SHARD_BYTES,flush=True)
shards=self_test(container,metadata)
print('Inner corruption/XOR and every whole tile row/column erasure test passed.',flush=True)
(root/'smw-v8-container.bin').write_bytes(container);(root/'payload.xz').write_bytes(compressed)
dpi=1200;im=Image.new('P',(round(210*dpi/25.4),round(297*dpi/25.4)),1)
palette=[v for c in PALETTE for v in c]+[0]*(768-48);im.putpalette(palette);draw=ImageDraw.Draw(im)
def px(v):return round(v*dpi/25.4)
def rect(x,y,w,h,index):draw.rectangle((px(x),px(y),px(x+w)-1,px(y+h)-1),fill=index)
def marker(x,y,size,inner):rect(x-size/2,y-size/2,size,size,0);rect(x-inner/2,y-inner/2,inner,inner,1)
def text(x,y,s,pt=6):
    size=round(pt*dpi/72)
    try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',size)
    except OSError:
        try:font=ImageFont.truetype('DejaVuSans.ttf',size)
        except OSError:font=ImageFont.load_default(size=size)
    draw.text((px(x),px(y)),s,font=font,fill=0)
def patch(x,y,symbols):
    # At 200 cells/in every cell spans exactly six pixels at 1200 dpi.
    xb=px(x);yb=px(y);l=round(x*dpi/25.4+.9)-xb;r=round(x*dpi/25.4+5.1)-xb
    t=round(y*dpi/25.4+.9)-yb;b=round(y*dpi/25.4+5.1)-yb
    a=np.full((symbols.shape[0]*6,symbols.shape[1]*6),1,dtype='uint8')
    for yy in range(t,b):
        for xx in range(l,r):a[yy::6,xx::6]=symbols
    p=Image.fromarray(a,'P');p.putpalette(palette);im.paste(p,(xb,yb))
for x,y in PAGE_MARKERS:marker(x,y,3,1.5)
label=source.name.encode('ascii','replace').decode('ascii')[:70]
text(18,4.4,f'{label} | PAPER ARCHIVE v8 | A4 SIDE 1/1 | 16 colors / 200 cells/in',6.5)
text(18,7.0,f'FILE {metadata["raw_bytes"]:,} B -> XZ {len(compressed):,} B | 342 protected tiles | scan COLOR 1200 dpi',6)
for row in range(ROWS+1):
    for col in range(COLS+1):marker(X0+col*PW*STEP,Y0+row*PH*STEP,5*STEP,2*STEP)
for tile,shard in enumerate(shards):
    g=tile_geometry(tile);symbols=inner_encode(shard,tile)
    patch(g['data_x'],g['data_y'],symbols);patch(g['cal_x'],g['cal_y'],pilots(tile))
    if (tile+1)%52==0:print('Rendered tiles',tile+1,'/',TILES,flush=True)
text(18,287.3,'Inner: RS(128,64) + CRC16 + 3+1 XOR. Outer: 16 data + 2 tile parity, spatially interleaved.',6)
text(18,289.8,'FILE SHA256 '+metadata['raw_sha256'],5.5)
a=np.asarray(im);verified=0
for tile,shard in enumerate(shards):
    g=tile_geometry(tile)
    for x,y,symbols in [(g['data_x'],g['data_y'],inner_encode(shard,tile)),(g['cal_x'],g['cal_y'],pilots(tile))]:
        xx=np.rint((x+(np.arange(symbols.shape[1])+.5)*STEP)*dpi/25.4).astype(int)
        yy=np.rint((y+(np.arange(symbols.shape[0])+.5)*STEP)*dpi/25.4).astype(int)
        measured=a[yy[:,None],xx[None,:]];assert np.array_equal(measured,symbols),(tile,x,y)
        verified+=symbols.size
print('Exact raster cells verified:',verified,flush=True)
imagefile=root/'smw-v8-print-1200dpi.png';im.save(imagefile,dpi=(1200,1200))
preview=im.copy();preview.thumbnail((1200,1697));preview.convert('RGB').save(root/'smw-v8-preview.png')
pdfpath=root/'paper-v8.pdf'
if not args.no_pdf:
    pdf=canvas.Canvas(str(pdfpath),pagesize=(210*mm,297*mm))
    pdf.setTitle(source.name+' - one-side A4 paper archive v8')
    pdf.drawImage(str(imagefile),0,0,width=210*mm,height=297*mm);pdf.showPage();pdf.save()
report=dict(format=8,file=metadata,container_bytes=len(container),data_capacity_bytes=GROUPS*DATA_SHARDS*SHARD_BYTES,
    printed_tiles=TILES,physical_slots=COLS*ROWS,inner_codewords=TILES*24,verified_raster_cells=verified,
    layout=dict(cols=COLS,rows=ROWS,pitch_cells=[PW,PH],cell_mm=STEP,origin_mm=[X0,Y0]),
    outer='RS(18,16) per tile-byte, any 2 missing tiles per interleaved group',
    software_tests='exact raster colors; 32 bad bytes per inner codeword; 1 inner word lost per XOR group; every full physical tile row and column erased and whole ROM recovered')
(root/'smw-v8-encoding-report.json').write_text(json.dumps(report,indent=2))
print('Created:',imagefile if args.no_pdf else pdfpath,flush=True)
