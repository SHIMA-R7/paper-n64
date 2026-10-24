"""Measure color-symbol accuracy. No reference payload is used before scoring."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parent
Image.MAX_IMAGE_PIXELS=200_000_000
path=Path(sys.argv[1]);im=Image.open(path).convert('RGB')
core='--core' in sys.argv
transport='--transport' in sys.argv
calibrated='--calibrated' in sys.argv or core
lossless=False
thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
def orientation(g):
    h,w=g.shape
    return float((g[int(h*59/297):int(h*67/297),int(w*18/210):int(w*26/210)]<170).mean())
rotation=180 if orientation(gray[::-1,::-1])>orientation(gray) else 0
if rotation:im=im.transpose(Image.Transpose.ROTATE_180);gray=gray[::-1,::-1].copy()
a=np.asarray(im);h,w=gray.shape;sx=im.width/w;sy=im.height/h
def marker(x,y,r=26):
    x0=max(0,int(x-r));y0=max(0,int(y-r));x1=min(w,int(x+r+1));y1=min(h,int(y+r+1))
    unseen=set(zip(*np.where(gray[y0:y1,x0:x1]<110)));best=[]
    while unseen:
        q=unseen.pop();stack=[q];part=[q]
        while stack:
            yy,xx=stack.pop()
            for near in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                if near in unseen:unseen.remove(near);stack.append(near);part.append(near)
        if len(part)>len(best):best=part
    if not best:raise ValueError('Marker not found')
    p=np.array(best);u=x0+(p[:,1].min()+p[:,1].max())/2;v=y0+(p[:,0].min()+p[:,0].max())/2
    cx=(u+.5)*sx-.5;cy=(v+.5)*sy-.5;rr=85
    xx=round(cx-rr);yy=round(cy-rr)
    if xx<0 or yy<0 or xx+2*rr>=im.width or yy+2*rr>=im.height:return [cx,cy]
    ys,xs=np.where(a[yy:yy+2*rr+1,xx:xx+2*rr+1].max(2)<110)
    return [xx+(xs.min()+xs.max())/2,yy+(ys.min()+ys.max())/2]
corners=np.array([marker(w*.04,h*.027,95),marker(w*.96,h*.027,95),marker(w*.04,h*.973,95),marker(w*.96,h*.973,95)])
aff=np.linalg.lstsq(np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float),corners,rcond=None)[0]
def homography(src,dst):
    rows=[];rhs=[]
    for (x,y),(u,v) in zip(src,dst):
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
    return np.append(np.linalg.solve(rows,rhs),1).reshape(3,3)
def sample(matrix,x,y):
    p=np.stack(np.broadcast_arrays(x,y,np.ones_like(x)),axis=-1)@matrix.T
    u=p[...,0]/p[...,2];v=p[...,1]/p[...,2]
    if calibrated or lossless:return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
    xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
    return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
def assignment(cost):
    # Hungarian minimum-cost one-to-one matching, O(n^3), including 20 colors.
    n=len(cost);u=np.zeros(n+1);v=np.zeros(n+1);p=np.zeros(n+1,dtype=int);way=np.zeros(n+1,dtype=int)
    for i in range(1,n+1):
        p[0]=i;j0=0;mins=np.full(n+1,np.inf);used=np.zeros(n+1,dtype=bool)
        while True:
            used[j0]=True;i0=p[j0];delta=np.inf;j1=0
            for j in range(1,n+1):
                if not used[j]:
                    cur=cost[i0-1,j-1]-u[i0]-v[j]
                    if cur<mins[j]:mins[j]=cur;way[j]=j0
                    if mins[j]<delta:delta=mins[j];j1=j
            for j in range(n+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:mins[j]-=delta
            j0=j1
            if p[j0]==0:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:break
    result=np.zeros(n,dtype=int)
    for j in range(1,n+1):result[p[j]-1]=j-1
    return result
assert np.array_equal(assignment(np.array([[10.,1.,8.],[1.,9.,8.],[8.,8.,1.]])),[1,0,2])
def models(x,refs):
    nc=len(refs);means=refs.copy()
    for _ in range(35):
        label=((x[:,None,:]-means[None,:,:])**2).sum(2).argmin(1)
        new=np.array([x[label==k].mean(0) if (label==k).any() else means[k] for k in range(nc)])
        if np.max(abs(new-means))<.02:break
        means=new
    km=label.copy();floor=np.eye(3)*max(float(np.var(x,axis=0).mean())*.003,1.)
    covs=np.array([np.cov(x[label==k].T)+floor if (label==k).sum()>4 else np.cov(x.T)+floor for k in range(nc)])
    for _ in range(35):
        scores=[]
        for k in range(nc):
            d=x-means[k];scores.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(covs[k]),d)+np.linalg.slogdet(covs[k])[1]))
        z=np.stack(scores,1);z-=z.max(1,keepdims=True);prob=np.exp(z);prob/=prob.sum(1,keepdims=True)
        nk=prob.sum(0);new=prob.T@x/nk[:,None];newcov=[]
        for k in range(nc):
            d=x-new[k];newcov.append(d.T@(d*prob[:,k,None])/nk[k]+floor)
        if np.max(abs(new-means))<.02:break
        means=new;covs=np.array(newcov)
    perm=assignment(((means[:,None,:]-refs[None,:,:])**2).sum(2))
    return km,perm[prob.argmax(1)]
manifest=json.loads((root/'multicolor-v5-manifest.json').read_text());out=root/(path.stem+'-measured');out.mkdir(exist_ok=True)
if calibrated:
    out=root/(path.stem+'-calibrated');out.mkdir(exist_ok=True)
if core:
    out=root/(path.stem+'-core');out.mkdir(exist_ok=True)
if transport:
    out=root/(path.stem+'-transport');out.mkdir(exist_ok=True)
reports=[]
for panel in manifest['panels']:
    n=panel['cells'];nc=panel['color_count'];step=panel['cell_mm']
    src=np.array(panel['marker_centers_mm']);pred=np.column_stack([src,np.ones(4)])@aff
    found=np.array([marker((x+.5)/sx-.5,(y+.5)/sy-.5) for x,y in pred]);matrix=homography(src,found)
    xx,yy=np.meshgrid(np.arange(n)+.5,np.arange(n)+.5)
    lossless=False
    if transport:
        # Preserve already exact palette data. This decision uses only image
        # pixels and printed palette samples, never payload labels or filenames.
        def pixel_sample(x,y):
            p=np.stack(np.broadcast_arrays(x,y,np.ones_like(x)),axis=-1)@matrix.T
            u=p[...,0]/p[...,2];v=p[...,1]/p[...,2]
            return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
        untouched=pixel_sample(panel['x_mm']+xx*step,panel['y_mm']+yy*step).reshape(-1,3)
        palette=np.array([pixel_sample(np.array(x),np.array(y)) for x,y in panel['color_centers_mm']])
        residual=((untouched[:,None,:]-palette[None,:,:])**2).sum(2).min(1)
        lossless=bool(residual.max()<.25)
    def read(params,dx=0,dy=0):
        ox,oy,kx,ky=params
        gx=(xx-n/2)*kx+n/2+ox+dx;gy=(yy-n/2)*ky+n/2+oy+dy
        return sample(matrix,panel['x_mm']+gx*step,panel['y_mm']+gy*step)
    params=np.array([0.,0.,1.,1.])
    for radius in (() if calibrated or lossless else (.4,.12,.04)):
        for axis in (0,1,2,3):
            choices=[]
            for delta in np.linspace(-radius,radius,11):
                trial=params.copy();trial[axis]+=delta*(.02 if axis>=2 else 1)
                if abs(trial[0])>.45 or abs(trial[1])>.45 or abs(trial[2]-1)>.008 or abs(trial[3]-1)>.008:continue
                value=read(trial)
                choices.append((float(value.var(axis=(0,1)).sum())/(1+.04*(trial[0]**2+trial[1]**2)),trial))
            params=max(choices,key=lambda q:q[0])[1]
    values=read(params) if calibrated or lossless else np.mean([read(params,dx,dy) for dx,dy in [(0,0),(-.10,0),(.10,0),(0,-.10),(0,.10)]],axis=0)
    if core:
        stack=np.stack([read(params,dx,dy) for dx in (-.24,0,.24) for dy in (-.24,0,.24)],axis=0)
        brightness=stack@np.array([.2126,.7152,.0722])
        order=np.argsort(brightness,axis=0)[:3]
        values=np.take_along_axis(stack,order[...,None],axis=0).mean(0)
    refs=[]
    for x,y in panel['color_centers_mm']:
        refs.append(np.median([sample(matrix,np.array(x+dx),np.array(y+dy)) for dx in (-.2,0,.2) for dy in (-.2,0,.2)],axis=0))
    refs=np.array(refs);raw=values.reshape(-1,3)
    nearest=((raw[:,None,:]-refs[None,:,:])**2).sum(2).argmin(1)
    pad=np.pad(values,((1,1),(1,1),(0,0)),mode='edge')
    neighbor=(pad[:-2,1:-1]+pad[2:,1:-1]+pad[1:-1,:-2]+pad[1:-1,2:])/4
    corrected=(values if calibrated or lossless else (1.4*values-.4*neighbor)).reshape(-1,3)
    if transport and not lossless:
        # Align the unlabeled dense-dot color distribution to the measured
        # isolated palette (CORAL-style moment normalization). No payload labels.
        def power(matrix,exponent):
            eigenvectors,eigenbasis=np.linalg.eigh(matrix)
            return (eigenbasis*np.maximum(eigenvectors,1e-5)**exponent)@eigenbasis.T
        dc=np.cov(corrected.T);rc=np.cov(refs.T)
        dh=power(dc,.5);dih=power(dc,-.5)
        mapping=dih@power(dh@rc@dh,.5)@dih
        corrected=(corrected-corrected.mean(0))@mapping+refs.mean(0)
    km,gmm=models(corrected,refs)
    # Only now read true symbol indices for scoring all predeclared methods.
    truth=np.frombuffer((root/panel['reference_file']).read_bytes(),dtype='uint8')
    result=dict(density=panel['density'],colors=nc,symbols=len(truth),blind_grid_parameters=params.tolist(),
                exact_palette_preserved=lossless,methods={})
    for name,prediction in [('nearest_swatch',nearest),('adaptive_unsharp',km),('gaussian_unsharp',gmm)]:
        rawbytes=prediction.astype('uint8').tobytes();digest=hashlib.sha256(rawbytes).hexdigest()
        confusion=np.zeros((nc,nc),dtype=int);np.add.at(confusion,(truth,prediction),1)
        correct=int((prediction==truth).sum())
        result['methods'][name]=dict(correct=correct,accuracy=correct/len(truth),symbol_errors=len(truth)-correct,
            exact=digest==panel['sha256'],confusion_matrix=confusion.tolist())
        (out/f'{panel["density"]}-{nc}-{name}.symbols').write_bytes(rawbytes)
    reports.append(result)
    print(f'{panel["density"]} cells/in {nc} colors: correct '+', '.join(f'{k}={v["accuracy"]:.2%}' for k,v in result['methods'].items()),flush=True)
    (out/'report.json').write_text(json.dumps(dict(scan=str(path),rotation=rotation,metric='symbol accuracy, not BER',
        primary_method=('palette moment normalization + gaussian classification; no payload labels used in fitting' if transport else 'gaussian classification; exploratory; source references used for scoring only'),panels=reports),indent=2))
im.thumbnail((1000,1415));im.save(out/'preview.png');print(out,flush=True)
