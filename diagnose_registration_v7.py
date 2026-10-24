"""Separate calibration-only decoding from reference-assisted diagnosis.

Predeclared focus: 8 and 16 colors at all four printed densities.
The oracle is NOT a decoder: it uses reference labels for alignment and model
training, then scores held-out pixels. It only diagnoses remaining information.
No oracle result is counted as actual payload recovery.
"""
from pathlib import Path
import sys,json,hashlib
import numpy as np
from PIL import Image
from analyze_calibration_v6 import homography
from decode_calibrated_v7 import fit,classify
from codec_v7 import recover
root=Path(__file__).resolve().parent
Image.MAX_IMAGE_PIXELS=200_000_000

class Page:
    def __init__(self,path):
        im=Image.open(path).convert('RGB');thumb=im.copy();thumb.thumbnail((2480,3508));gray=np.asarray(thumb.convert('L'))
        def orientation(g):
            h,w=g.shape
            return (g[int(h*54/297):int(h*76/297),int(w*14/210):int(w*46/210)]<180).mean()
        self.rotated=bool(orientation(gray[::-1,::-1])>orientation(gray))
        if self.rotated:im=im.transpose(Image.Transpose.ROTATE_180);gray=gray[::-1,::-1].copy()
        self.a=np.asarray(im);self.gray=gray;self.h,self.w=gray.shape;self.sx=im.width/self.w;self.sy=im.height/self.h
        w,h=self.w,self.h
        corners=np.array([self.marker(w*.04,h*.027,95),self.marker(w*.96,h*.027,95),self.marker(w*.04,h*.973,95),self.marker(w*.96,h*.973,95)])
        self.aff=np.linalg.lstsq(np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float),corners,rcond=None)[0]
    def marker(self,x,y,r=20):
        a=self.a;gray=self.gray;h,w=gray.shape
        x0=max(0,int(x-r));y0=max(0,int(y-r));x1=min(w,int(x+r+1));y1=min(h,int(y+r+1))
        unseen=set(zip(*np.where(gray[y0:y1,x0:x1]<110)));best=[]
        while unseen:
            q=unseen.pop();stack=[q];part=[q]
            while stack:
                yy,xx=stack.pop()
                for near in ((yy-1,xx),(yy+1,xx),(yy,xx-1),(yy,xx+1)):
                    if near in unseen:unseen.remove(near);stack.append(near);part.append(near)
            if len(part)>len(best):best=part
        if not best:raise ValueError('Registration ring missing')
        p=np.array(best);cx=(x0+(p[:,1].min()+p[:,1].max())/2+.5)*self.sx-.5;cy=(y0+(p[:,0].min()+p[:,0].max())/2+.5)*self.sy-.5
        rr=80;xx=round(cx-rr);yy=round(cy-rr);ys,xs=np.where(a[yy:yy+2*rr+1,xx:xx+2*rr+1].max(2)<110)
        return [xx+(xs.min()+xs.max())/2,yy+(ys.min()+ys.max())/2]
    def matrix(self,panel):
        src=np.array(panel['marker_centers_mm']);pred=np.column_stack([src,np.ones(4)])@self.aff
        found=np.array([self.marker((x+.5)/self.sx-.5,(y+.5)/self.sy-.5) for x,y in pred])
        return homography(src,found)
    def grid(self,panel,matrix,x,y,n,rows=None):
        xx,yy=np.meshgrid(np.arange(n)+.5,np.arange(n)+.5 if rows is None else np.arange(*rows)+.5)
        step=panel['cell_mm'];a=self.a
        def read(params,nearest=False):
            ox,oy,kx,ky=params;gx=(xx-n/2)*kx+n/2+ox;gy=(yy-n/2)*ky+n/2+oy
            p=np.stack([x+gx*step,y+gy*step,np.ones_like(xx)],-1)@matrix.T
            u=p[...,0]/p[...,2];v=p[...,1]/p[...,2]
            if nearest:return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
            xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
            return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        return read

def explained(values,labels,mask,nc):
    x=values.reshape(-1,3)[mask];label=labels.ravel()[mask];count=np.bincount(label,minlength=nc)
    means=np.column_stack([np.bincount(label,weights=x[:,c],minlength=nc) for c in range(3)])/np.maximum(count[:,None],1)
    total=float(((x-x.mean(0))**2).sum());error=float(((x-means[label])**2).sum())
    return (total-error)/max(total,len(x)*25.)

def align(read,labels,mask,nc,initial=None,coarse=True):
    params=np.array([0.,0.,1.,1.] if initial is None else initial,dtype=float)
    def score(q):return explained(read(q),labels,mask,nc)
    if coarse:
        trials=[]
        for dx in np.arange(-1.5,1.501,.25):
            for dy in np.arange(-1.5,1.501,.25):
                q=params.copy();q[:2]+=[dx,dy];trials.append((score(q),q))
        seeds=[q for _,q in sorted(trials,key=lambda t:t[0],reverse=True)[:3]]
    else:seeds=[params]
    solutions=[]
    for seed in seeds:
        p=seed.copy()
        for radius in (.25,.08,.025):
            for axis in (2,3,0,1,2,3):
                choices=[]
                for delta in np.linspace(-radius,radius,9):
                    q=p.copy();q[axis]+=delta*(.08 if axis>=2 else 1)
                    if np.max(abs(q[:2]))>3 or np.max(abs(q[2:]-1))>.06:continue
                    choices.append((score(q),q))
                p=max(choices,key=lambda t:t[0])[1]
        solutions.append((score(p),p))
    return max(solutions,key=lambda t:t[0])[1]

def masks(n):
    y,x=np.indices((n,n));interior=((y>1)&(y<n-2)&(x>1)&(x<n-2)).ravel()
    validation=(np.arange(n*n)%5==0)&interior
    return interior&~validation,validation,interior

def evaluate_training(training,labels,nc):
    fitting,validation,interior=masks(len(labels));models=[]
    for cancel in (False,True):
        pred,_=classify(training,fit(training,labels,nc,cancel,fitting))
        accuracy=float((pred[validation]==labels.ravel()[validation]).mean())
        models.append((accuracy,cancel,fit(training,labels,nc,cancel,interior)))
    # Select solely on public calibration validation, tie goes to center-only.
    return max(models,key=lambda t:t[0])

def guided(read,initial):
    p=np.array(initial).copy();anchor=p.copy()
    for radius in (.2,.06,.02):
        for axis in (0,1,2,3):
            choices=[]
            for delta in np.linspace(-radius,radius,9):
                q=p.copy();q[axis]+=delta*(.02 if axis>=2 else 1)
                if np.max(abs(q[:2]-anchor[:2]))>.30 or np.max(abs(q[2:]-anchor[2:]))>.012:continue
                value=read(q);choices.append((float(value.var(axis=(0,1)).sum()),q))
            p=max(choices,key=lambda t:t[0])[1]
    return p

def main():
    path=Path(sys.argv[1]);page=Page(path);manifest=json.loads((root/'calibrated-v7-manifest.json').read_text())
    out=root/(path.stem+'-registration-diagnostic');out.mkdir(exist_ok=True);report=[]
    for panel in manifest['panels']:
        nc=panel['color_count']
        if nc not in (8,16):continue
        matrix=page.matrix(panel);labels=np.array(panel['training_symbols']);fitmask,valmask,interior=masks(32)
        calread=page.grid(panel,matrix,panel['training_x_mm'],panel['training_y_mm'],32)
        dataread=page.grid(panel,matrix,panel['x_mm'],panel['y_mm'],96)
        nearest=calread([0,0,1,1],True);palette=np.array(panel['colors'])
        is_exact=bool((((nearest.reshape(-1,1,3)-palette[None,:,:])**2).sum(2).min(1)<.25).all())
        cp=np.array([0.,0.,1.,1.]) if is_exact else align(calread,labels,fitmask,nc)
        training=calread(cp,True) if is_exact else calread(cp)
        accuracy,cancel,model=evaluate_training(training,labels,nc)
        dp=cp.copy();dp[:2]+=32*(cp[2:]-1) # transfer the calibrated top-left phase
        alternatives=[('calibration_transfer',dp)]
        if not is_exact:alternatives.append(('calibration_guided_blind_contrast',guided(dataread,dp)))
        fixed=[]
        for name,q in alternatives:
            values=dataread(q,True) if is_exact else dataread(q)
            pred,confidence=classify(values,model);payload,detail=recover(pred,confidence,nc)
            fixed.append((name,q,values,pred,payload,detail))
        # Payload references are first accessed here. This marks the boundary
        # between real decoder candidates (above) and oracle diagnostics below.
        truth=np.frombuffer((root/panel['reference_file']).read_bytes(),dtype='uint8').reshape(96,96)
        actual=[]
        for name,q,values,pred,payload,detail in fixed:
            digest=hashlib.sha256(payload).hexdigest() if payload is not None else None
            actual.append(dict(name=name,parameters=q.tolist(),symbol_accuracy=float((pred==truth.ravel()).mean()),
                sha256_match=digest==panel['payload_sha256'],**detail))
            if payload is not None:(out/f'{panel["density"]}-{nc}-{name}.bin').write_bytes(payload)
        oracle_fit,oracle_val,oracle_interior=masks(96)
        op=np.array([0.,0.,1.,1.]) if is_exact else align(dataread,truth,oracle_fit,nc)
        global_values=dataread(op,True) if is_exact else dataread(op)
        def oracle_score(values):
            scores={}
            for c in (False,True):
                prediction,_=classify(values,fit(values,truth,nc,c,oracle_fit))
                scores['neighbor_qda' if c else 'center_qda']=float((prediction[oracle_val]==truth.ravel()[oracle_val]).mean())
            return scores
        global_score=oracle_score(global_values);local_values=[];local_parameters=[]
        for start in range(0,96,16):
            read=page.grid(panel,matrix,panel['x_mm'],panel['y_mm'],96,(start,start+16))
            subset=truth[start:start+16];subset_mask=oracle_fit.reshape(96,96)[start:start+16].ravel()
            q=op.copy() if is_exact else align(read,subset,subset_mask,nc,op,coarse=True)
            local_values.append(read(q,True) if is_exact else read(q));local_parameters.append(q.tolist())
        local_values=np.concatenate(local_values,axis=0);local_score=oracle_score(local_values)
        row=dict(density=panel['density'],colors=nc,source_exact_palette=is_exact,
            calibration_parameters=cp.tolist(),calibration_validation_accuracy=accuracy,calibration_model_neighbor_cancel=cancel,
            actual_decoder_candidates=actual,oracle_diagnostic_only=dict(note='Reference-assisted, NOT actual decoding. Geometric and color model fitting use payload labels in 80% of interior cells. Scores are on the withheld 20%.',
                heldout_cells=int(oracle_val.sum()),global_parameters=op.tolist(),global_heldout_accuracy=global_score,
                local_strip_parameters=local_parameters,local_heldout_accuracy=local_score))
        report.append(row)
        np.savez_compressed(out/f'{panel["density"]}-{nc}-samples.npz',calibration=training,global_oracle=global_values,local_oracle=local_values,truth=truth)
        (out/'report.json').write_text(json.dumps(dict(image=str(path),focus='8 and 16 colors, all densities',exploratory_same_scan=True,panels=report),indent=2))
        print(panel['density'],nc,'cal',round(accuracy,4),'real',[(c['name'],round(c['symbol_accuracy'],4),c['sha256_match']) for c in actual],'ORACLE',global_score,local_score,flush=True)
    print(out,flush=True)

if __name__=='__main__':main()
