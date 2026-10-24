"""Decode v4 using marker geometry, blind color models and RS+CRC validation.
Payload references and stored SHA256 are consulted only after recovery stops.
"""
from pathlib import Path
import sys,json,struct,binascii,hashlib,itertools
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'vendor'))
from reedsolo import RSCodec,ReedSolomonError
codec=RSCodec(32)
Image.MAX_IMAGE_PIXELS=200_000_000
path=Path(sys.argv[1]);im=Image.open(path).convert('RGB')
thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
def orientation(g):
    h,w=g.shape
    return float((g[int(h*62/297):int(h*69/297),int(w*21/210):int(w*28/210)]<160).mean())
rotated=orientation(gray[::-1,::-1])>orientation(gray)
if rotated:im=im.transpose(Image.Transpose.ROTATE_180);gray=gray[::-1,::-1].copy()
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
    v=np.array(best);u=x0+(v[:,1].min()+v[:,1].max())/2;v=y0+(v[:,0].min()+v[:,0].max())/2
    cx=(u+.5)*sx-.5;cy=(v+.5)*sy-.5;radius=85
    xx=int(cx-radius);yy=int(cy-radius)
    if xx<0 or yy<0 or xx+2*radius>=im.width or yy+2*radius>=im.height:return [cx,cy]
    ys,xs=np.where(a[yy:yy+2*radius+1,xx:xx+2*radius+1].max(2)<110)
    return [xx+(xs.min()+xs.max())/2,yy+(ys.min()+ys.max())/2]
corners=np.array([marker(w*.04,h*.027,95),marker(w*.96,h*.027,95),marker(w*.04,h*.973,95),marker(w*.96,h*.973,95)])
page=np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float)
aff=np.linalg.lstsq(page,corners,rcond=None)[0]
def homography(src,dst):
    rows=[];rhs=[]
    for (x,y),(u,v) in zip(src,dst):
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
    return np.append(np.linalg.solve(rows,rhs),1).reshape(3,3)
def sample(matrix,x,y):
    points=np.stack(np.broadcast_arrays(x,y,np.ones_like(x)),axis=-1)@matrix.T
    u=points[...,0]/points[...,2];v=points[...,1]/points[...,2]
    xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
    return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
def fit_models(x,refs):
    nc=len(refs);means=refs.copy()
    for _ in range(35):
        labels=((x[:,None,:]-means[None,:,:])**2).sum(2).argmin(1)
        new=np.array([x[labels==k].mean(0) if (labels==k).any() else means[k] for k in range(nc)])
        if np.max(abs(new-means))<.01:break
        means=new
    km=means.copy();floor=np.eye(3)*max(float(np.var(x,axis=0).mean())*.003,1.)
    covs=np.array([np.cov(x[labels==k].T)+floor if (labels==k).sum()>4 else np.cov(x.T)+floor for k in range(nc)])
    for _ in range(35):
        logp=[]
        for k in range(nc):
            d=x-means[k];logp.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(covs[k]),d)+np.linalg.slogdet(covs[k])[1]))
        logp=np.stack(logp,1);logp-=logp.max(1,keepdims=True);p=np.exp(logp);p/=p.sum(1,keepdims=True)
        nk=p.sum(0);new=p.T@x/nk[:,None];newcov=[]
        for k in range(nc):
            d=x-new[k];newcov.append(d.T@(d*p[:,k,None])/nk[k]+floor)
        if np.max(abs(new-means))<.01:break
        means=new;covs=np.array(newcov)
    costs=((means[:,None,:]-refs[None,:,:])**2).sum(2)
    perm=min(itertools.permutations(range(nc)),key=lambda q:sum(costs[k,q[k]] for k in range(nc)))
    inverse=np.argsort(perm)
    return [('swatch',refs,np.tile(np.eye(3)*900,(nc,1,1))),('kmeans',km,np.tile(np.eye(3)*900,(nc,1,1))),('gaussian',means[inverse],covs[inverse])]
def posterior(x,model):
    _,means,covs=model;logp=[]
    for k in range(len(means)):
        d=x-means[k];logp.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(covs[k]),d)+np.linalg.slogdet(covs[k])[1]))
    logp=np.stack(logp,1);logp-=logp.max(1,keepdims=True);p=np.exp(logp);p/=p.sum(1,keepdims=True)
    return p
manifest=json.loads((root/'ecc-v4-manifest.json').read_text());out=root/(path.stem+'-recovered');out.mkdir(exist_ok=True)
checker=(np.indices((32,32)).sum(0)%2).astype('uint8');xx,yy=np.meshgrid(np.arange(32)+.5,np.arange(32)+.5)
reports=[]
for index,panel in enumerate(manifest['panels']):
    nc=len(panel['colors']);layers=panel['layers'];step=panel['cell_mm'];fill=panel['dot_width_fraction']
    src=np.array(panel['marker_centers_mm']);pred=np.column_stack([src,np.ones(4)])@aff
    found=np.array([marker((u+.5)/sx-.5,(v+.5)/sy-.5) for u,v in pred]);matrix=homography(src,found)
    refs=[]
    for rx,ry in panel['color_centers_mm']:refs.append(sample(matrix,np.array(rx),np.array(ry)))
    refs=np.array(refs)
    def read(tile,params=(0,0,1,1),shift=(0,0),window=.10):
        ox,oy,kx,ky=params;dx,dy=shift;readings=[]
        for wx,wy in ((0,0),(-window,0),(window,0),(0,-window),(0,window)):
            gx=(xx-16)*kx+16+ox+dx+wx;gy=(yy-16)*ky+16+oy+dy+wy
            readings.append(sample(matrix,tile['x_mm']+gx*step,tile['y_mm']+gy*step))
        return np.mean(readings,axis=0)
    parameters=[];values=[]
    for tile in panel['tiles']:
        params=np.array([0.,0.,1.,1.])
        for radius in (.4,.12):
            for axis in (0,1,2,3):
                choices=[]
                for delta in np.linspace(-radius,radius,9):
                    trial=params.copy();trial[axis]+=delta*(.02 if axis>=2 else 1)
                    if abs(trial[0])>.5 or abs(trial[1])>.5 or abs(trial[2]-1)>.012 or abs(trial[3]-1)>.012:continue
                    value=read(tile,trial,window=0.)
                    choices.append((float(value.var(axis=(0,1)).sum())/(1+.04*(trial[0]**2+trial[1]**2)),trial))
                params=max(choices,key=lambda q:q[0])[1]
        parameters.append(params);values.append(read(tile,params))
    models=fit_models(np.concatenate([v.reshape(-1,3) for v in values]),refs)
    decoded=[[None]*4 for _ in range(layers)];details=[]
    # Recovery uses only the transmitted RS/CRC/address. Stored hashes are not
    # consulted during candidate search or erasure selection.
    for block,tile in enumerate(panel['tiles']):
        for shift in [(0,0)]+[(x,y) for x in (-.2,0,.2) for y in (-.2,0,.2) if (x,y)!=(0,0)]:
            if all(decoded[layer][block] is not None for layer in range(layers)):break
            value=read(tile,parameters[block],shift)
            pad=np.pad(value,((1,1),(1,1),(0,0)),mode='edge')
            neighbor=(pad[:-2,1:-1]+pad[2:,1:-1]+pad[1:-1,:-2]+pad[1:-1,2:])/4
            for strength in (0.,.4):
                obs=((1+strength)*value-strength*neighbor).reshape(-1,3)
                for model in models:
                    post=posterior(obs,model);hard=post.argmax(1)
                    for layer in range(layers):
                        if decoded[layer][block] is not None:continue
                        bit_index=layers-layer-1;membership=((np.arange(nc)>>bit_index)&1).astype(bool)
                        probability=post[:,membership].sum(1)
                        for decision in ('symbol','bit'):
                            bits=((hard>>bit_index)&1) if decision=='symbol' else (probability>.5).astype('uint8')
                            bits=bits.reshape(32,32)^checker
                            raw=np.packbits(bits.astype('uint8').ravel()).tobytes()
                            confidence=np.abs(probability-.5).reshape(-1,8).min(1)
                            order=np.argsort(confidence)
                            for erased in (0,8,16,24,32):
                                try:
                                    msg,corrected,errors=codec.decode(raw,erase_pos=order[:erased].tolist())
                                    msg=bytes(msg)
                                    expected=(index%3)<<12 | layer<<8 | block
                                    if len(msg)!=96 or struct.unpack('<I',msg[:4])[0]!=expected:continue
                                    if binascii.crc_hqx(msg[:94],0xFFFF)!=struct.unpack('<H',msg[94:])[0]:continue
                                    decoded[layer][block]=msg[4:94]
                                    details.append(dict(layer=layer,block=block,model=model[0],decision=decision,shift=list(shift),
                                                        neighbor_strength=strength,erasures=erased,corrected_bytes=len(errors)))
                                    break
                                except (ReedSolomonError,ValueError,IndexError):pass
                            if decoded[layer][block] is not None:break
    xor_recovered=[]
    for layer in range(layers):
        missing=[b for b in range(4) if decoded[layer][b] is None]
        if len(missing)==1:
            b=missing[0];decoded[layer][b]=bytes(a^b^c for a,b,c in zip(*(decoded[layer][j] for j in range(4) if j!=b)))
            xor_recovered.append(dict(layer=layer,block=b))
    complete=all(decoded[layer][b] is not None for layer in range(layers) for b in range(3))
    recovered=b''.join(decoded[layer][b] for layer in range(layers) for b in range(3)) if complete else None
    digest=hashlib.sha256(recovered).hexdigest() if complete else None
    # Final hash is for verification only; it never directs candidate search.
    exact=complete and digest==panel['sha256']
    name=f'{panel["density"]}-{nc}colors-{int(fill*100)}'
    if complete:(out/f'{name}.bin').write_bytes(recovered)
    report=dict(density=panel['density'],colors=nc,dot_width_percent=round(fill*100),rs_crc_blocks=len(details),
                total_blocks=layers*4,xor_recovered=xor_recovered,complete=complete,sha256_match=exact,
                payload_bytes=len(recovered) if complete else 0,details=details,sha256=digest,
                blind_grid_parameters=[p.tolist() for p in parameters])
    reports.append(report)
    print(f'{name}: RS+CRC {len(details)}/{layers*4}; XOR {len(xor_recovered)}; complete={complete}; SHA256={exact}',flush=True)
    (out/'report.json').write_text(json.dumps(dict(scan=str(path),rotation=180 if rotated else 0,panels=reports),indent=2))
im.thumbnail((1000,1415));im.save(out/'preview.png');print(out,flush=True)
