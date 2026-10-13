"""Image-only raster assembly and centerline tracing. Output requires CAD review."""
import math
import cv2
import numpy as np
import pymupdf


def image_plane(page, dpi=300, check=lambda: None):
    """Reassemble original image tiles BEFORE tracing, without PDF vectors/text."""
    zoom = min(dpi / 72, math.sqrt(80_000_000 / (page.rect.width * page.rect.height)))
    width, height = math.ceil(page.rect.width * zoom), math.ceil(page.rect.height * zoom)
    canvas = np.full((height, width), 255, np.uint8)
    cache = {}
    for info in page.get_image_info(xrefs=True):
        check()
        xref = info['xref']
        if not xref:
            raise ValueError('인라인 이미지는 자동 선 추적을 지원하지 않습니다. 원본 이미지 검토가 필요합니다.')
        if xref not in cache:
            pix = pymupdf.Pixmap(page.parent, xref)
            if pix.colorspace and pix.colorspace.n != 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            smask = page.parent.extract_image(xref).get('smask', 0)
            if smask and not pix.alpha:
                pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(page.parent, smask))
            arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            gray = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY)
            alpha = arr[:, :, 3] if pix.alpha else np.full(gray.shape, 255, np.uint8)
            cache[xref] = gray, alpha
        gray, alpha = cache[xref]
        transform = pymupdf.Matrix(*info['transform']) * page.rotation_matrix
        corners = [pymupdf.Point(x,y)*transform for x,y in ((0,0),(1,0),(0,1),(1,1))]
        x0=max(0,math.floor(min(p.x for p in corners)*zoom)); y0=max(0,math.floor(min(p.y for p in corners)*zoom))
        x1=min(width,math.ceil(max(p.x for p in corners)*zoom)); y1=min(height,math.ceil(max(p.y for p in corners)*zoom))
        if x1<=x0 or y1<=y0: continue
        a,b,c,d,e,f=transform
        matrix=np.array([[a*zoom/gray.shape[1],c*zoom/gray.shape[0],e*zoom-x0],
                         [b*zoom/gray.shape[1],d*zoom/gray.shape[0],f*zoom-y0]],np.float64)
        warped=cv2.warpAffine(gray,matrix,(x1-x0,y1-y0),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        opacity=cv2.warpAffine(alpha,matrix,(x1-x0,y1-y0),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)/255
        coverage=np.zeros((y1-y0,x1-x0),np.uint8)
        polygon=np.array([[(corners[k].x*zoom-x0)*256,(corners[k].y*zoom-y0)*256] for k in (0,1,3,2)],np.int32)
        cv2.fillConvexPoly(coverage,polygon,1,shift=8)
        opacity*=coverage
        roi=canvas[y0:y1,x0:x1]
        roi[:]=(warped*opacity+roi*(1-opacity)).round().astype(np.uint8)
    return canvas, zoom


def centerlines(gray, check=lambda: None):
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,61,5)
    check()
    skeleton=cv2.ximgproc.thinning(binary,thinningType=cv2.ximgproc.THINNING_GUOHALL)
    ys,xs=np.nonzero(skeleton)
    pixels=set(zip(xs.tolist(),ys.tolist()))
    del binary, skeleton
    def neighbors(p):
        x,y=p
        out=[]
        for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            q=(x+dx,y+dy)
            if q in pixels:
                # Avoid triangular graph edges around a one-pixel right angle.
                if dx and dy and ((x+dx,y) in pixels or (x,y+dy) in pixels):continue
                out.append(q)
        return out
    graph={p:neighbors(p) for p in pixels}
    visited=set(); chains=[]; discarded=0
    def walk(p,q):
        chain=[p];prev=p;cur=q
        while True:
            visited.add(tuple(sorted((prev,cur))))
            chain.append(cur)
            if cur==p or len(graph[cur])!=2:break
            nxt=next(n for n in graph[cur] if n!=prev)
            if tuple(sorted((cur,nxt))) in visited:break
            prev,cur=cur,nxt
        return chain
    for k,p in enumerate(sorted(graph,key=lambda p:(len(graph[p])==2,p))):
        if k%10000==0:check()
        for q in graph[p]:
            if tuple(sorted((p,q))) in visited:continue
            chain=walk(p,q)
            closed=chain[0]==chain[-1]
            length=sum(math.dist(a,b) for a,b in zip(chain,chain[1:]))
            if length<3 and not (len(graph[chain[0]])>2 and len(graph[chain[-1]])>2):
                discarded+=1;continue
            pts=cv2.approxPolyDP(np.asarray(chain,np.float32).reshape(-1,1,2),.65,closed).reshape(-1,2)
            if len(pts)>=2:chains.append((pts,closed))
    return chains,dict(skeleton_pixels=len(pixels),discarded_short_fragments=discarded,
                      simplify_tolerance_px=.65,threshold_block_px=61,threshold_offset=5)


def trace_images(page, modelspace, scale, check=lambda: None, progress=lambda *args: None):
    progress('dxf',None,'이미지 타일 연결 · 원본 벡터를 제외한 건물 선 추적 중')
    gray, zoom=image_plane(page,check=check)
    chains,report=centerlines(gray,check)
    factor=25.4/72*scale
    for pts,closed in chains:
        coords=[((float(x)+.5)/zoom*factor,(page.rect.height-(float(y)+.5)/zoom)*factor) for x,y in pts]
        if len(coords)==2 and not closed:
            modelspace.add_line(*coords,dxfattribs={'layer':'RASTER_TRACE_REVIEW'})
        else:
            modelspace.add_lwpolyline(coords,close=closed,dxfattribs={'layer':'RASTER_TRACE_REVIEW'})
    # Only mathematically closed faces; never bridge gaps or assume wall/opening semantics.
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    segments=[]
    for pts,closed in chains:
        coords=[tuple(map(float,p)) for p in pts]
        if closed: coords.append(coords[0])
        segments.append(LineString(coords))
    faces=0
    if segments:
        for poly in polygonize(unary_union(segments)):
            check()
            if poly.interiors or poly.area < 9: continue
            coords=[((x+.5)/zoom*factor,(page.rect.height-(y+.5)/zoom)*factor) for x,y in list(poly.exterior.coords)[:-1]]
            modelspace.add_lwpolyline(coords,close=True,dxfattribs={'layer':'RASTER_AREAS_REVIEW'})
            faces+=1
    report.update(area_candidates=faces,area_layer_default='off',area_min_pixels=9,entities=len(chains),closed_paths=sum(closed for _,closed in chains),dpi=zoom*72,
                  pixel_size_mm=25.4/(zoom*72)*scale,requires_review=True,
                  method='image_only_mosaic_adaptive_threshold_centerline',quantity_certified=False)
    progress('dxf',None,f'이미지에서 CAD 선 {len(chains):,}개 생성 · 추적 레이어 검수 필요')
    return report
