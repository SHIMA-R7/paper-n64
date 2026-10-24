"""Decode BW v2 with local geometric registration; references only score results."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from PIL import Image,ImageDraw,ImageFont
Image.MAX_IMAGE_PIXELS=200_000_000
root=Path(__file__).resolve().parent
path=Path(sys.argv[1])
im=Image.open(path).convert('RGB')
thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
def orientation_score(g):
    hh,ww=g.shape
    return float((g[int(hh*63/297):int(hh*83/297),int(ww*25/210):int(ww*45/210)]<150).mean())
rotated=orientation_score(gray[::-1,::-1])>orientation_score(gray)
if rotated:
    im=im.transpose(Image.Transpose.ROTATE_180);gray=gray[::-1,::-1].copy()
hh,ww=gray.shape
def marker(px,py,r):
    x0=max(0,int(px-r));y0=max(0,int(py-r));x1=min(ww,int(px+r+1));y1=min(hh,int(py+r+1))
    crop=gray[y0:y1,x0:x1]
    unseen=set(zip(*np.where(crop<110)));best=[]
    while unseen:
        q=unseen.pop();stack=[q];comp=[q]
        while stack:
            y,x=stack.pop()
            for near in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if near in unseen:unseen.remove(near);stack.append(near);comp.append(near)
        if len(comp)>len(best):best=comp
    if not best:raise ValueError('No marker')
    c=np.array(best)
    return [x0+(c[:,1].min()+c[:,1].max())/2,y0+(c[:,0].min()+c[:,0].max())/2]
corners=[marker(ww*.04,hh*.027,95),marker(ww*.96,hh*.027,95),
         marker(ww*.04,hh*.973,95),marker(ww*.96,hh*.973,95)]
physical=np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float)
aff=np.linalg.lstsq(physical,np.array(corners),rcond=None)[0]
def homography(src,dst):
    aa=[];bb=[]
    for (x,y),(u,v) in zip(src,dst):
        aa.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);bb.extend([u,v])
    return np.append(np.linalg.solve(aa,bb),1).reshape(3,3)
a=np.asarray(im)
sx=im.width/ww;sy=im.height/hh
color_mode='--color' in sys.argv
manifest=json.loads((root/('color-v3-manifest.json' if color_mode else 'bw-v2-manifest.json')).read_text())
out=root/(path.stem+'-decoded');out.mkdir(exist_ok=True)
refine='--refine' in sys.argv
channels='--channels' in sys.argv
if refine:
    out=root/(path.stem+'-refined');out.mkdir(exist_ok=True)
if channels:
    out=root/(path.stem+'-channels');out.mkdir(exist_ok=True)
results=[]
for panel in manifest['panels']:
    if '--maxdensity' in sys.argv and panel['density']>int(sys.argv[sys.argv.index('--maxdensity')+1]):continue
    src=np.array(panel['marker_centers_mm'])
    predicted=np.column_stack([src,np.ones(4)])@aff
    found=np.array([marker(x,y,26) for x,y in predicted])
    # Refine ring centers at the original resolution; thumbnail rounding is
    # significant for cells only 2-3 pixels wide.
    refined=[]
    for u,v in found:
        cx=(u+.5)*sx-.5;cy=(v+.5)*sy-.5
        rx=round(1.8/25.4*1200);ry=rx
        x0=round(cx-rx);y0=round(cy-ry)
        crop=a[y0:round(cy+ry)+1,x0:round(cx+rx)+1]
        ys,xs=np.where(crop.max(axis=2)<110)
        fx=x0+(xs.min()+xs.max())/2;fy=y0+(ys.min()+ys.max())/2
        refined.append([(fx+.5)/sx-.5,(fy+.5)/sy-.5])
    found=np.array(refined)
    matrix=homography(src,found)
    n=panel['cells'];step=panel['cell_mm']
    xx,yy=np.meshgrid(np.arange(n)+.5,np.arange(n)+.5)
    def read_grid(dx=0,dy=0,parameters=None):
        ox,oy,kx,ky=parameters if parameters is not None else (0,0,1,1)
        gx=(xx-n/2)*kx+n/2+ox+dx;gy=(yy-n/2)*ky+n/2+oy+dy
        points=np.stack([panel['x_mm']+gx*step,panel['y_mm']+gy*step,np.ones_like(xx)],axis=-1)@matrix.T
        u=(points[...,0]/points[...,2]+.5)*sx-.5;v=(points[...,1]/points[...,2]+.5)*sy-.5
        xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
        rgb=a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        return (rgb if color_mode else rgb@np.array([.2126,.7152,.0722])),u,v
    parameters=np.array([0.,0.,1.,1.])
    if refine:
        # Blind grid fit: maximize sampled black/white contrast, without reading
        # reference bits. Optimize translation and scale within explicit bounds.
        for radius in (1.,.3,.08):
            for axis in (0,1,2,3):
                choices=[]
                for delta in np.linspace(-radius,radius,21):
                    trial=parameters.copy();trial[axis]+=delta*(.025 if axis>=2 else 1)
                    if abs(trial[0])>.45 or abs(trial[1])>.45 or abs(trial[2]-1)>.008 or abs(trial[3]-1)>.008: continue
                    val,_,_=read_grid(parameters=trial)
                    penalty=1+.04*(trial[0]**2+trial[1]**2)+4*((trial[2]-1)**2+(trial[3]-1)**2)
                    variance=float(val.var(axis=(0,1)).sum()) if color_mode else float(val.var())
                    choices.append((variance/penalty,trial))
                parameters=max(choices,key=lambda q:q[0])[1]
    samples=[]
    for dx in (-.18,0,.18):
        for dy in (-.18,0,.18):
            val,u,v=read_grid(dx,dy,parameters);samples.append(val)
    values=np.mean(samples,axis=0)
    channel_parameters=[]
    if color_mode and channels:
        channel_values=[]
        for channel in range(3):
            cp=parameters.copy()
            for radius in (.35,.12,.035):
                for axis in (0,1,2,3):
                    choices=[]
                    for delta in np.linspace(-radius,radius,15):
                        trial=cp.copy();trial[axis]+=delta*(.02 if axis>=2 else 1)
                        if abs(trial[0])>.45 or abs(trial[1])>.45 or abs(trial[2]-1)>.008 or abs(trial[3]-1)>.008:continue
                        val,_,_=read_grid(parameters=trial)
                        penalty=1+.04*(trial[0]**2+trial[1]**2)+4*((trial[2]-1)**2+(trial[3]-1)**2)
                        choices.append((float(val[...,channel].var())/penalty,trial))
                    cp=max(choices,key=lambda q:q[0])[1]
            cs=[]
            for dx in (-.18,0,.18):
                for dy in (-.18,0,.18):
                    val,_,_=read_grid(dx,dy,cp);cs.append(val[...,channel])
            channel_values.append(np.mean(cs,axis=0));channel_parameters.append(cp.tolist())
        values=np.stack(channel_values,axis=-1)
    if color_mode:
        refs=[]
        for rx,ry in panel['color_centers_mm']:
            p=matrix@np.array([rx,ry,1.]);u=(p[0]/p[2]+.5)*sx-.5;v=(p[1]/p[2]+.5)*sy-.5
            ui,vi=round(u),round(v)
            refs.append(a[vi-12:vi+13,ui-12:ui+13].mean(axis=(0,1)))
        refs=np.array(refs);nc=len(refs);obs=values.reshape(-1,3)
        np.savez_compressed(out/f'{panel["density"]}-{nc}colors-samples.npz',values=values,refs=refs)
        direct=np.argmin(((obs[:,None,:]-refs[None,:,:])**2).sum(2),axis=1)
        means=refs.copy()
        for iteration in range(30):
            labels=np.argmin(((obs[:,None,:]-means[None,:,:])**2).sum(2),axis=1)
            new=np.array([obs[labels==j].mean(0) if (labels==j).any() else means[j] for j in range(nc)])
            if np.max(abs(new-means))<.01:break
            means=new
        bps=int(np.log2(nc))
        def packed(symbols):
            return np.packbits(((symbols[:,None]>>np.arange(bps-1,-1,-1))&1).astype('uint8').ravel()).tobytes()
        # References enter only after both classifications have been fixed.
        reference=(root/panel['reference_file']).read_bytes()
        truthbits=np.unpackbits(np.frombuffer(reference,dtype='uint8'))
        truth=(truthbits.reshape(-1,bps)*(1<<np.arange(bps-1,-1,-1))).sum(1)
        def evaluate(symbols):
            payload=packed(symbols);bits=np.unpackbits(np.frombuffer(payload,dtype='uint8'))
            digest=hashlib.sha256(payload).hexdigest()
            return dict(bit_errors=int((bits!=truthbits).sum()),bits=len(bits),bit_error_rate=float((bits!=truthbits).mean()),
                        symbol_error_rate=float((symbols!=truth).mean()),sha256=digest,sha256_matches=digest==panel['sha256'])
        direct_score=evaluate(direct);adaptive_score=evaluate(labels)
        extra={}
        if channels:
            # Fixed mild inverse blur; no ground-truth-based coefficient fitting.
            padded=np.pad(values,((1,1),(1,1),(0,0)),mode='edge')
            neighbors=(padded[:-2,1:-1]+padded[2:,1:-1]+padded[1:-1,:-2]+padded[1:-1,2:])/4
            corrected=(1.4*values-.4*neighbors).reshape(-1,3)
            cm=refs.copy()
            for iteration in range(30):
                cl=np.argmin(((corrected[:,None,:]-cm[None,:,:])**2).sum(2),axis=1)
                new=np.array([corrected[cl==j].mean(0) if (cl==j).any() else cm[j] for j in range(nc)])
                if np.max(abs(new-cm))<.01:break
                cm=new
            extra['fixed_unsharp']=evaluate(cl)
            extra['channel_parameters']=channel_parameters
            (out/f'{panel["density"]}-{nc}colors-unsharp.bin').write_bytes(packed(cl))
        for method,symbols in [('direct',direct),('adaptive',labels)]:
            (out/f'{panel["density"]}-{nc}colors-{method}.bin').write_bytes(packed(symbols))
        results.append(dict(density=panel['density'],colors=nc,direct=direct_score,adaptive=adaptive_score,
                            blind_grid_parameters=parameters.tolist(),color_references_rgb=refs.tolist(),**extra))
        print(f'{panel["density"]} cells/in {nc} colors: direct BER={direct_score["bit_error_rate"]:.4%}; adaptive BER={adaptive_score["bit_error_rate"]:.4%}; exact={adaptive_score["sha256_matches"]}',flush=True)
        if channels:print(f'  fixed inverse blur BER={extra["fixed_unsharp"]["bit_error_rate"]:.4%}',flush=True)
        continue
    means=np.percentile(values,[20,80])
    for _ in range(30):
        threshold=means.mean();low=values<threshold
        new=np.array([values[low].mean(),values[~low].mean()])
        if np.max(abs(new-means))<.001:break
        means=new
    bits=(values<means.mean()).astype('uint8').ravel()
    payload=np.packbits(bits).tobytes()
    digest=hashlib.sha256(payload).hexdigest()
    (out/f'{panel["density"]}-decoded.bin').write_bytes(payload)
    reference=(root/f'bw-v2-{panel["density"]}-reference.bin').read_bytes()
    reference_bits=np.unpackbits(np.frombuffer(reference,dtype='uint8'))
    errors=int((bits!=reference_bits).sum())
    if panel['density'] in (100,150,200):
        _,u,v=read_grid(parameters=parameters)
        x0=int(u.min()-step*1200/25.4);y0=int(v.min()-step*1200/25.4)
        x1=int(u.max()+step*1200/25.4);y1=int(v.max()+step*1200/25.4)
        crop=im.crop((x0,y0,x1,y1)).convert('RGB');draw=ImageDraw.Draw(crop)
        wrong=(bits!=reference_bits).reshape(n,n)
        for row,col in zip(*np.where(wrong)):
            cx=float(u[row,col]-x0);cy=float(v[row,col]-y0)
            draw.ellipse((cx-2,cy-2,cx+2,cy+2),outline='red',width=1)
        crop.save(out/f'{panel["density"]}-errors.png')
        # Small enlarged diagnostic with inferred cell boundaries overlaid.
        _,edge_u,edge_v=read_grid(-.5,-.5,parameters)
        bx=int(edge_u[:25,:25].min()-4);by=int(edge_v[:25,:25].min()-4)
        ex=int(edge_u[:25,:25].max()+5);ey=int(edge_v[:25,:25].max()+5)
        zoom=im.crop((bx,by,ex,ey)).resize(((ex-bx)*3,(ey-by)*3),Image.Resampling.NEAREST)
        zd=ImageDraw.Draw(zoom)
        def pos(r,c):return ((float(edge_u[r,c])-bx)*3,(float(edge_v[r,c])-by)*3)
        for j in range(25):
            zd.line([pos(0,j),pos(24,j)],fill=(0,190,220),width=1)
            zd.line([pos(j,0),pos(j,24)],fill=(0,190,220),width=1)
        for row,col in zip(*np.where(wrong[:24,:24])):
            cx=(float(u[row,col])-bx)*3;cy=(float(v[row,col])-by)*3
            zd.ellipse((cx-4,cy-4,cx+4,cy+4),outline='red',width=2)
        zoom.save(out/f'{panel["density"]}-grid-detail.png')
    result=dict(density=panel['density'],bits=len(bits),bit_errors=errors,bit_error_rate=errors/len(bits),
                sha256=digest,sha256_matches=digest==panel['payload_sha256'],threshold=float(means.mean()),
                marker_centers=found.tolist(),blind_grid_parameters=parameters.tolist())
    results.append(result)
    print(f'{panel["density"]:3} cells/in: {errors}/{len(bits)} bit errors ({errors/len(bits):.4%}); SHA256 match={result["sha256_matches"]}',flush=True)
im.thumbnail((1000,1415));im.save(out/'preview.png')
(out/'report.json').write_text(json.dumps(dict(scan=str(path),rotation=180 if rotated else 0,results=results),indent=2))
print(out,flush=True)
