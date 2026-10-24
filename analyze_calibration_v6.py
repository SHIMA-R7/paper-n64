"""4096-color printer measurements. Fit A only; report B without tuning on B.

This is calibration, not payload decoding. Selected-color tests have only one
sample per class on B and require a fresh, repeated-symbol print for validation.
"""
from pathlib import Path
import sys,json
import numpy as np
from PIL import Image

root=Path(__file__).resolve().parent
Image.MAX_IMAGE_PIXELS=200_000_000

def lab(rgb):
    v=np.asarray(rgb,dtype=float)/255
    lin=np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)
    xyz=lin@np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]).T
    xyz/=np.array([.95047,1.,1.08883]);f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],-1)

def homography(src,dst):
    rows=[];rhs=[]
    for (x,y),(u,v) in zip(src,dst):
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
    return np.append(np.linalg.solve(rows,rhs),1).reshape(3,3)

def extract(path):
    im=Image.open(path).convert('RGB');thumb=im.copy();thumb.thumbnail((2480,3508))
    gray=np.asarray(thumb.convert('L'))
    def orientation(g):
        h,w=g.shape
        return (g[int(h*60/297):int(h*115/297),int(w*17/210):int(w*78/210)]<200).mean()
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
        if not best:raise ValueError('Missing registration ring')
        p=np.array(best);cx=(x0+(p[:,1].min()+p[:,1].max())/2+.5)*sx-.5;cy=(y0+(p[:,0].min()+p[:,0].max())/2+.5)*sy-.5
        rr=85;xx=round(cx-rr);yy=round(cy-rr)
        crop=a[yy:yy+2*rr+1,xx:xx+2*rr+1]
        ys,xs=np.where(crop.max(2)<110)
        return [xx+(xs.min()+xs.max())/2,yy+(ys.min()+ys.max())/2]
    corners=np.array([marker(w*.04,h*.027,95),marker(w*.96,h*.027,95),marker(w*.04,h*.973,95),marker(w*.96,h*.973,95)])
    aff=np.linalg.lstsq(np.array([[8,8,1],[202,8,1],[8,289,1],[202,289,1]],float),corners,rcond=None)[0]
    manifest=json.loads((root/'calibration-v6-manifest.json').read_text());colors=np.array(manifest['colors'])
    out=root/(path.stem+'-calibrated-v6');out.mkdir(exist_ok=True)
    preview=im.copy();preview.thumbnail((1000,1415));preview.save(out/'scan-preview.png')
    panels=[]
    for i,panel in enumerate(manifest['panels']):
        src=np.array(panel['marker_centers_mm']);pred=np.column_stack([src,np.ones(4)])@aff
        found=np.array([marker((x+.5)/sx-.5,(y+.5)/sy-.5) for x,y in pred]);matrix=homography(src,found)
        xx,yy=np.meshgrid(np.arange(64)+.5,np.arange(64)+.5);step=panel['cell_mm']
        def read(params,dx=0,dy=0,nearest=False):
            ox,oy,kx,ky=params
            gx=(xx-32)*kx+32+ox+dx;gy=(yy-32)*ky+32+oy+dy
            points=np.stack([panel['x_mm']+gx*step,panel['y_mm']+gy*step,np.ones_like(xx)],-1)@matrix.T
            u=points[...,0]/points[...,2];v=points[...,1]/points[...,2]
            if nearest:return a[np.rint(v).astype(int),np.rint(u).astype(int)].astype(float)
            xi=np.floor(u).astype(int);yi=np.floor(v).astype(int);fx=(u-xi)[...,None];fy=(v-yi)[...,None]
            return a[yi,xi]*(1-fx)*(1-fy)+a[yi,xi+1]*fx*(1-fy)+a[yi+1,xi]*(1-fx)*fy+a[yi+1,xi+1]*fx*fy
        params=np.array([0.,0.,1.,1.]);untouched=read(params,nearest=True)
        # All possible source colors lie on the 17-step grid. Image-only guard,
        # then require all six source panels exact as a separate geometry test.
        exact_grid=bool(np.max(abs(untouched/17-np.rint(untouched/17)))<1e-8)
        if panel['cell_mm']<.5 and not exact_grid:
            for radius in (.4,.12,.04):
                for axis in (0,1,2,3):
                    choices=[]
                    for delta in np.linspace(-radius,radius,11):
                        trial=params.copy();trial[axis]+=delta*(.02 if axis>=2 else 1)
                        if abs(trial[0])>.45 or abs(trial[1])>.45 or abs(trial[2]-1)>.008 or abs(trial[3]-1)>.008:continue
                        value=read(trial);choices.append((float(value.var(axis=(0,1)).sum())/(1+.04*(trial[0]**2+trial[1]**2)),trial))
                    params=max(choices,key=lambda q:q[0])[1]
        if exact_grid:values=untouched
        elif panel['cell_mm']>.5:
            values=np.median([read(params,dx,dy) for dx in (-.22,0,.22) for dy in (-.22,0,.22)],axis=0)
        else:values=np.mean([read(params,dx,dy) for dx,dy in [(0,0),(-.1,0),(.1,0),(0,-.1),(0,.1)]],axis=0)
        truth=colors[np.array(panel['color_indices'])].reshape(64,64,3)
        np.savez_compressed(out/f'panel-{i}.npz',values=values,truth=truth,color_indices=panel['color_indices'],matrix=matrix,params=params)
        panel=dict(panel,values=values,truth=truth,exact_source_cells=int(np.all(values==truth,axis=2).sum()),blind_grid_parameters=params.tolist())
        panels.append(panel)
        print(panel['split'],panel['label'],'exact RGB cells',panel['exact_source_cells'],flush=True)
    return out,colors,panels,rotated

def features(values,neighbors):
    v=values/255;flat=v.reshape(-1,3);r,g,b=flat.T
    terms=[np.ones((len(flat),1)),flat,np.column_stack([r*r,g*g,b*b,r*g,r*b,g*b])]
    if neighbors:
        p=np.pad(v,((1,1),(1,1),(0,0)),mode='edge')
        terms.extend(q.reshape(-1,3) for q in [p[:-2,1:-1],p[2:,1:-1],p[1:-1,:-2],p[1:-1,2:]])
    return np.column_stack(terms)

def main():
    path=Path(sys.argv[1]);out,colors,panels,rotated=extract(path)
    large=panels[0];measured=np.empty((4096,3));measured[np.array(large['color_indices'])]=large['values'].reshape(-1,3)
    # sRGB-derived Lab is a heuristic distance on scanner RGB, not a colorimetric
    # measurement. Only A supplies selected colors; B remains held out.
    gamut=lab(measured);chosen=[0,4095]
    while len(chosen)<20:
        dist=((gamut[:,None,:]-gamut[chosen][None,:,:])**2).sum(2).min(1);dist[chosen]=-1
        chosen.append(int(dist.argmax()))
    palettes={str(n):dict(indices=chosen[:n],rgb=colors[chosen[:n]].tolist(),measured_rgb_A=measured[chosen[:n]].tolist(),min_scanner_lab_distance=float(np.sqrt(((gamut[chosen[:n],None,:]-gamut[None,chosen[:n],:])**2).sum(2)+np.eye(n)*1e9).min())) for n in (8,10,12,16,20)}
    metrics=[]
    for ai in (0,2,4):
        train=panels[ai];test=panels[ai+1];row=dict(label=train['label'],models={})
        for neighbors in (False,True):
            x=features(train['values'],neighbors);target=train['truth'].reshape(-1,3)/255
            reg=np.eye(x.shape[1])*.001;reg[0,0]=0
            coef=np.linalg.solve(x.T@x+reg,x.T@target)
            predicted=(features(test['values'],neighbors)@coef)*255
            truth=test['truth'].reshape(-1,3);rmse=float(np.sqrt(np.mean((predicted-truth)**2)))
            key='center_and_four_neighbors' if neighbors else 'center_only'
            entry=dict(heldout_B_rgb_rmse=rmse,selected_color_checks={})
            labels=np.array(test['color_indices'])
            for n in (8,10,12,16,20):
                indices=chosen[:n];mask=np.isin(labels,indices)
                decoded=np.array(indices)[((predicted[mask,None,:]-colors[indices][None,:,:])**2).sum(2).argmin(1)]
                entry['selected_color_checks'][str(n)]=dict(correct=int((decoded==labels[mask]).sum()),samples=int(mask.sum()),note='Only one B sample per selected color, with neighbors drawn from all 4096 colors; not a payload benchmark.')
            row['models'][key]=entry
            np.savez(out/f'{ai}-{key}-model.npz',coef=coef)
        metrics.append(row)
    report=dict(scan_file=str(path),rotation_180=rotated,calibration_only=True,fit_split='A only',validation_split='B, no fitting or model selection',palette_selection='A large patches only; greedy max-min scanner RGB-derived Lab, 20 nested colors',palettes=palettes,metrics=metrics,
        geometry_checks=[dict(split=p['split'],label=p['label'],exact_source_cells=p['exact_source_cells'],cells=4096,blind_grid_parameters=p['blind_grid_parameters']) for p in panels],
        limitations=['B selected-color checks have just one observation per class.','Scanner RGB-derived Lab is a heuristic, not calibrated colorimetry.','Dense targets contain all 4096 colors; selected-palette neighbor behavior requires a fresh print.','Calibration error is not payload BER or ECC recovery.'])
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'selected-palettes.json').write_text(json.dumps(palettes,indent=2),encoding='utf-8')
    print(json.dumps(metrics,indent=2));print(out)

if __name__=='__main__':main()
