"""Research-inspired baselines, NOT reproductions of HiQ or Bulan's EM model.
No payload labels are used to initialize, fit or select parameters.
"""
from pathlib import Path
import json,hashlib,itertools
import numpy as np
root=Path(__file__).resolve().parent
source=root/'scan-color-v3-1200dpi-20261024-155331-channels'
manifest=json.loads((root/'color-v3-manifest.json').read_text())

def kmeans(x,means):
    means=means.copy()
    for _ in range(40):
        labels=((x[:,None,:]-means[None,:,:])**2).sum(2).argmin(1)
        new=np.array([x[labels==k].mean(0) if (labels==k).any() else means[k] for k in range(len(means))])
        if np.max(abs(new-means))<1e-5:break
        means=new
    return labels,means

def gaussian_em(x,refs):
    labels,means=kmeans(x,refs)
    nc=len(refs);dim=x.shape[1]
    floor=np.eye(dim)*max(np.mean(np.var(x,axis=0))*.003,1e-6)
    covs=np.array([np.cov(x[labels==k].T)+floor if (labels==k).sum()>4 else np.cov(x.T)+floor for k in range(nc)])
    for _ in range(50):
        z=[]
        for k in range(nc):
            d=x-means[k]
            z.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(covs[k]),d)+np.linalg.slogdet(covs[k])[1]))
        z=np.stack(z,1);z-=z.max(1,keepdims=True)
        p=np.exp(z);p/=p.sum(1,keepdims=True)
        counts=p.sum(0);new=(p.T@x)/counts[:,None]
        newcov=[]
        for k in range(nc):
            d=x-new[k];newcov.append((d.T@(d*p[:,k,None]))/counts[k]+floor)
        if np.max(abs(new-means))<1e-5:break
        means=new;covs=np.array(newcov)
    # Keep the known palette identity using a one-to-one match to swatches.
    costs=((means[:,None,:]-refs[None,:,:])**2).sum(2)
    permutation=min(itertools.permutations(range(nc)),key=lambda q:sum(costs[j,q[j]] for j in range(nc)))
    return np.array(permutation)[p.argmax(1)]

results=[]
for panel in manifest['panels']:
    density=panel['density'];nc=len(panel['colors']);f=source/f'{density}-{nc}colors-samples.npz'
    if not f.exists():continue
    d=np.load(f);values=d['values'];refs=d['refs']/255.
    p=np.pad(values,((1,1),(1,1),(0,0)),mode='edge')
    neighbor=(p[:-2,1:-1]+p[2:,1:-1]+p[1:-1,:-2]+p[1:-1,2:])/4
    rgb=(1.4*values-.4*neighbor).reshape(-1,3)/255.
    # Density transform is a simplified feature transform, not a calibrated
    # physical ink separation (the RGB driver may generate black ink).
    white=refs.max(0)
    od=-np.log(np.clip(rgb,.01,1.2)/white)
    odrefs=-np.log(np.clip(refs,.01,1.2)/white)
    symbols={}
    symbols['rgb_kmeans']=kmeans(rgb,refs)[0]
    symbols['rgb_gaussian_em']=gaussian_em(rgb,refs)
    symbols['optical_density_kmeans']=kmeans(od,odrefs)[0]
    symbols['optical_density_gaussian_em']=gaussian_em(od,odrefs)
    target=1-np.array(panel['colors'])/255.
    transform=np.linalg.lstsq(np.column_stack([odrefs,np.ones(nc)]),target,rcond=None)[0]
    separated=np.column_stack([od,np.ones(len(od))])@transform
    symbols['swatch_density_linear_unmix']=kmeans(separated,target)[0]
    # Score only now, after all unsupervised methods have fixed their outputs.
    reference=(root/panel['reference_file']).read_bytes()
    tb=np.unpackbits(np.frombuffer(reference,dtype='uint8'));bps=int(np.log2(nc))
    row=dict(density=density,colors=nc,methods={})
    for name,prediction in symbols.items():
        bits=((prediction[:,None]>>np.arange(bps-1,-1,-1))&1).astype('uint8').ravel()
        raw=np.packbits(bits).tobytes();digest=hashlib.sha256(raw).hexdigest()
        row['methods'][name]=dict(bit_errors=int((bits!=tb).sum()),bits=len(bits),ber=float((bits!=tb).mean()),exact=digest==panel['sha256'])
    results.append(row)
    print(density,nc,{k:round(v['ber']*100,4) for k,v in row['methods'].items()},flush=True)
(root/'research-color-model-results.json').write_text(json.dumps(dict(note=__doc__,results=results),indent=2))
