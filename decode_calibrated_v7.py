"""Labeled training only for fitting; payload labels/hashes only for final score.
Two predeclared models: QDA and a linear observed-neighbor cancellation + QDA.
This is a small new implementation, not a reproduction of a research system.
"""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from PIL import Image
from codec_v7 import recover
from analyze_calibration_v6 import homography

root=Path(__file__).resolve().parent
Image.MAX_IMAGE_PIXELS=200_000_000

def neighbors(values):
    p=np.pad(values/255,((1,1),(1,1),(0,0)),mode='edge')
    return np.column_stack([q.reshape(-1,3) for q in [p[:-2,1:-1],p[2:,1:-1],p[1:-1,:-2],p[1:-1,2:]]])

def fit(values,labels,nc,cancel,mask):
    center=values.reshape(-1,3);labels=labels.ravel();near=neighbors(values)
    onehot=np.eye(nc)[labels]
    if cancel:
        x=np.column_stack([onehot,near]);xx=x[mask];yy=center[mask]/255
        coef=np.linalg.solve(xx.T@xx+np.eye(xx.shape[1])*.001,xx.T@yy)*255
        means=coef[:nc];beta=coef[nc:]
    else:
        means=np.array([center[mask&(labels==k)].mean(0) for k in range(nc)]);beta=np.zeros((12,3))
    residual=center-near@beta-means[labels]
    pooled=np.cov(residual[mask].T);covs=[]
    for k in range(nc):
        group=residual[mask&(labels==k)]
        cov=np.cov(group.T) if len(group)>4 else pooled
        covs.append(.6*cov+.4*pooled+np.eye(3)*3.)
    return means,beta,np.array(covs)

def classify(values,model):
    means,beta,covs=model;z=values.reshape(-1,3)-neighbors(values)@beta;scores=[]
    for mean,cov in zip(means,covs):
        d=z-mean;scores.append(-.5*(np.einsum('ni,ij,nj->n',d,np.linalg.inv(cov),d)+np.linalg.slogdet(cov)[1]))
    scores=np.stack(scores,1);scores-=scores.max(1,keepdims=True)
    prob=np.exp(scores);prob/=prob.sum(1,keepdims=True)
    ordered=np.sort(prob,axis=1)
    return prob.argmax(1),ordered[:,-1]-ordered[:,-2]

def decode(path):
    im=Image.open(path).convert('RGB');thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
    def orientation(g):
        h,w=g.shape
        return (g[int(h*54/297):int(h*76/297),int(w*14/210):int(w*46/210)]<180).mean()
    rotated=bool(orientation(gray[::-1,::-1])>orientation(gray))
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
        if not best:raise ValueError('Registration marker missing')
        p=np.array(best);cx=(x0+(p[:,1].min()+p[:,1].max())/2+.5)*sx-.5;cy=(y0+(p[:,0].min()+p[:,0].max())/2+.5)*sy-.5
        # Rings on adjacent panels are only 4 mm apart: use < half spacing.
        rr=80;xx=round(cx-rr);yy=round(cy-rr);crop=a[yy:yy+2*rr+1,xx:xx+2*rr+1]
        ys,xs=np.where(crop.max(2)<110)
        if not len(xs):raise ValueError('Registration ring refinement failed')
        return [xx+(xs.min()+xs.max())/2,yy+(ys.min()+ys.max())/2]
    corners=np.array([marker(w*.04,h*.027,95),marker(w*.96,h*.027,95),marker(w*.04,h*.973,95),marker(w*.96,h*.973,95)])
    aff=np.linalg.lstsq(np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float),corners,rcond=None)[0]
    manifest=json.loads((root/'calibrated-v7-manifest.json').read_text());out=root/(path.stem+'-decoded-v7');out.mkdir(exist_ok=True)
    reports=[]
    for panel in manifest['panels']:
        nc=panel['color_count'];src=np.array(panel['marker_centers_mm']);pred=np.column_stack([src,np.ones(4)])@aff
        # The 26-thumbnail-pixel search used by earlier sheets can overlap the
        # next panel's ring here. A 20 px search contains only the intended ring.
        found=np.array([marker((x+.5)/sx-.5,(y+.5)/sy-.5,20) for x,y in pred]);matrix=homography(src,found)
        def sample(x,y,nearest=False):
            p=np.stack(np.broadcast_arrays(x,y,np.ones_like(x)),-1)@matrix.T
            u=p[...,0]/p[...,2];v=p[...,1]/p[...,2]
            if nearest:return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
            xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
            return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        refs=np.array([sample(np.array(x),np.array(y),True) for x,y in panel['color_centers_mm']])
        def grid(x,y,n):
            xx,yy=np.meshgrid(np.arange(n)+.5,np.arange(n)+.5);step=panel['cell_mm']
            def read(params,dx=0,dy=0,nearest=False):
                ox,oy,kx,ky=params
                gx=(xx-n/2)*kx+n/2+ox+dx;gy=(yy-n/2)*ky+n/2+oy+dy
                return sample(x+gx*step,y+gy*step,nearest)
            params=np.array([0.,0.,1.,1.]);untouched=read(params,nearest=True)
            residual=((untouched.reshape(-1,1,3)-refs[None,:,:])**2).sum(2).min(1)
            exact=bool(residual.max()<.25)
            if exact:return untouched,params.tolist(),True
            for radius in (.4,.12,.04):
                for axis in (0,1,2,3):
                    choices=[]
                    for delta in np.linspace(-radius,radius,11):
                        trial=params.copy();trial[axis]+=delta*(.02 if axis>=2 else 1)
                        if abs(trial[0])>.45 or abs(trial[1])>.45 or abs(trial[2]-1)>.008 or abs(trial[3]-1)>.008:continue
                        value=read(trial);choices.append((float(value.var(axis=(0,1)).sum())/(1+.04*(trial[0]**2+trial[1]**2)),trial))
                    params=max(choices,key=lambda q:q[0])[1]
            values=np.mean([read(params,dx,dy) for dx,dy in [(0,0),(-.1,0),(.1,0),(0,-.1),(0,.1)]],axis=0)
            return values,params.tolist(),False
        training,train_params,train_exact=grid(panel['training_x_mm'],panel['training_y_mm'],32)
        data,data_params,data_exact=grid(panel['x_mm'],panel['y_mm'],96)
        labels=np.array(panel['training_symbols']);yy,xx=np.indices((32,32));interior=((yy>0)&(yy<31)&(xx>0)&(xx<31)).ravel()
        validation=(np.arange(1024)%5==0)&interior;fitting=interior&~validation
        candidates=[]
        for cancel in (False,True):
            name='neighbor_cancellation_qda' if cancel else 'center_qda'
            model=fit(training,labels,nc,cancel,fitting);cal_pred,_=classify(training,model)
            accuracy=float((cal_pred[validation]==labels.ravel()[validation]).mean())
            model=fit(training,labels,nc,cancel,interior);prediction,confidence=classify(data,model)
            payload,detail=recover(prediction,confidence,nc)
            candidates.append(dict(name=name,calibration_validation_accuracy=accuracy,prediction=prediction,payload=payload,recovery=detail))
        primary=max(candidates,key=lambda c:c['calibration_validation_accuracy'])['name']
        # All model predictions and RS/CRC searches are fixed before reading
        # payload reference symbols or hashes. Calibration labels are public.
        truth=np.frombuffer((root/panel['reference_file']).read_bytes(),dtype='uint8');methods={}
        for candidate in candidates:
            prediction=candidate['prediction'];payload=candidate['payload'];digest=hashlib.sha256(payload).hexdigest() if payload is not None else None
            name=f'{panel["density"]}-{nc}-{candidate["name"]}'
            (out/f'{name}.symbols').write_bytes(prediction.astype('uint8').tobytes())
            if payload is not None:(out/f'{name}.bin').write_bytes(payload)
            methods[candidate['name']]=dict(calibration_validation_accuracy=candidate['calibration_validation_accuracy'],
                symbol_errors=int((prediction!=truth).sum()),symbols=len(truth),symbol_accuracy=float((prediction==truth).mean()),
                sha256_match=digest==panel['payload_sha256'],sha256=digest,payload_bytes=len(payload) if payload is not None else 0,**candidate['recovery'])
        result=dict(density=panel['density'],colors=nc,primary_model=primary,methods=methods,
            train_exact_palette=train_exact,data_exact_palette=data_exact,train_grid_parameters=train_params,data_grid_parameters=data_params)
        reports.append(result)
        print(panel['density'],nc,'primary',primary,{k:(v['symbol_errors'],v['rs_crc_blocks'],v['sha256_match']) for k,v in methods.items()},flush=True)
        (out/'report.json').write_text(json.dumps(dict(image=str(path),rotation_180=rotated,panels=reports,selection='Calibration validation only; payload references consulted only after all predictions and ECC attempts.'),indent=2))
    return out

if __name__=='__main__':print(decode(Path(sys.argv[1])),flush=True)
