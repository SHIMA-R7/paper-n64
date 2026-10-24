"""Read synthetic probe cells. Reference seeds are used ONLY for scoring."""
from pathlib import Path
import json, random, hashlib, sys
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
synthetic='--synthetic' in sys.argv
scan = ROOT / ('print-1200dpi.png' if synthetic else 'scan-J1270N-300dpi-20261024-150723.png')
if '--scan' in sys.argv: scan=Path(sys.argv[sys.argv.index('--scan')+1])
Image.MAX_IMAGE_PIXELS=200_000_000
scan_dpi=1200 if '1200dpi' in scan.name and not synthetic else 300
output_dir=ROOT/scan.stem if '--scan' in sys.argv else ROOT
output_dir.mkdir(exist_ok=True)
im = Image.open(scan).convert('RGB')
if synthetic:
    im=im.resize((im.width//4,im.height//4),Image.Resampling.LANCZOS)
else:
    im=im.transpose(Image.Transpose.ROTATE_180)
a = np.asarray(im)
h,w = a.shape[:2]
def marker_center(x0,y0,x1,y1):
    crop=a[y0:y1,x0:x1]
    mask=crop.max(axis=2)<100
    # Marker ring is the largest connected dark component in this small window.
    unseen=set(zip(*np.where(mask)))
    components=[]
    while unseen:
        p=unseen.pop(); stack=[p]; comp=[p]
        while stack:
            y,x=stack.pop()
            for q in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if q in unseen: unseen.remove(q); stack.append(q); comp.append(q)
        components.append(comp)
    c=np.array(max(components,key=len))
    return [x0+(c[:,1].min()+c[:,1].max())/2,
            y0+(c[:,0].min()+c[:,0].max())/2]
radius=round(170*scan_dpi/300)
centers=[marker_center(0,0,radius,radius),marker_center(w-radius,0,w,radius),
         marker_center(0,h-radius,radius,h),marker_center(w-radius,h-radius,w,h)]
mm=np.array([[9,9,1],[201,9,1],[9,288,1],[201,288,1]],float)
aff=np.linalg.lstsq(mm,np.array(centers),rcond=None)[0]
def sample(coords):
    p=np.asarray(coords)@aff
    xx=np.clip(p[...,0],0,w-2); yy=np.clip(p[...,1],0,h-2)
    x=xx.astype(int); y=yy.astype(int); fx=(xx-x)[...,None]; fy=(yy-y)[...,None]
    return (a[y,x]*(1-fx)*(1-fy)+a[y,x+1]*fx*(1-fy)+
            a[y+1,x]*(1-fx)*fy+a[y+1,x+1]*fx*fy)
manifest=json.loads((ROOT/'probe-manifest.json').read_text())
results=[]
for k,p in enumerate(manifest['patches']):
    n=p['cells']; x=p['x_mm']; y=p['y_mm']; size=p['width_mm']; colors=p['colors']; nc=len(colors)
    # Find two nearby printed markers, independent of the data pattern.
    local=[]
    for cy in (y+2,y+size-2):
        pred=np.array([x+27,cy,1])@aff
        px,py=pred.round().astype(int)
        r=round(29*scan_dpi/300)
        local.append(marker_center(px-r,py-r,px+r+1,py+r+1))
    expected=np.array([[x+27,y+2,1],[x+27,y+size-2,1]])@aff
    shifts=np.array(local)-expected
    gx,gy=np.meshgrid(x+(np.arange(n)+.5)*size/n,y+(np.arange(n)+.5)*size/n)
    coords=np.stack([gx,gy,np.ones_like(gx)],axis=-1)
    # Local translation and vertical drift correction. Convert pixel shifts to mm.
    t=np.clip((gy-(y+2))/(size-4),0,1)[...,None]
    delta=shifts[0]*(1-t)+shifts[1]*t
    coords[...,:2]+=delta@np.linalg.inv(aff[:2,:])
    observed=sample(coords).reshape(-1,3)
    refs=np.array([sample([x+36+(j%2)*5,y+(j//2)*5+2,1]) for j in range(nc)])
    direct=np.argmin(((observed[:,None,:]-refs[None,:,:])**2).sum(2),axis=1)
    # Unsupervised adaptation to the colors in dense patterns, no reference bits.
    means=refs.copy()
    for iteration in range(25):
        labels=np.argmin(((observed[:,None,:]-means[None,:,:])**2).sum(2),axis=1)
        new=np.array([observed[labels==j].mean(0) if (labels==j).any() else means[j] for j in range(nc)])
        if np.max(abs(new-means))<.02: break
        means=new
    rng=random.Random(p['seed'])
    truth=np.array([rng.randrange(nc) for _ in range(n*n)])
    bits=int(np.log2(nc))
    def score(decoded):
        xor=decoded^truth
        biterrors=sum(int(((xor>>b)&1).sum()) for b in range(bits))
        return dict(symbol_errors=int((xor!=0).sum()),symbols=n*n,
                    symbol_error_rate=float((xor!=0).mean()),bit_error_rate=biterrors/(n*n*bits),
                    exact=bool(np.array_equal(decoded,truth)))
    raw=labels.astype('uint8').tobytes()
    if not synthetic: (output_dir/f'decoded-{p["density"]}-{nc}colors.bin').write_bytes(raw)
    results.append(dict(density=p['density'],colors=nc,direct=score(direct),adaptive=score(labels),
                        storage='one decoded symbol index per byte; not ROM data',sha256=hashlib.sha256(raw).hexdigest()))
    print(f'{p["density"]:3} cells/in {nc} colors: direct SER={score(direct)["symbol_error_rate"]:.3%}; adaptive SER={score(labels)["symbol_error_rate"]:.3%}, BER={score(labels)["bit_error_rate"]:.3%}')
report=dict(scan=str(scan),scan_dpi=scan_dpi,orientation_correction=180,corner_centers=centers,
            note='No ECC on probe. No original values used in classification or alignment. Adaptive clustering is exploratory.',results=results)
(output_dir/('synthetic-report.json' if synthetic else 'decode-report.json')).write_text(json.dumps(report,indent=2))
