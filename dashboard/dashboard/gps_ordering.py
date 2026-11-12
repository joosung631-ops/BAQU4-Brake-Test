"""Order stage 6 points by nearest projection onto one recording's smooth path."""
import math
from aiohttp import web
from .gps_review import project
from .gps_additions import reference_tracks


def ordering_source(document):
    stages=document['stages']
    if '6' not in stages:raise web.HTTPConflict(text='먼저 6단계 결과를 저장하세요.')
    references=[{'id':t['id'],'name':t['name'],'curve_segments':t['curve_segments'],
                 'point_count':len(t['retained_points'])} for t in stages['3']['tracks']]
    if '4' in stages:
        references=reference_tracks(stages['4']['tracks'],stages['2']['raw']['origin'],stages['3']['tracks'])
    return {'points':project(stages['6']['points'],stages['2']['raw']['origin']),
            'references':references,'origin':stages['2']['raw']['origin']}


def automatic_order(document,reference_id,max_distance):
    if type(max_distance) not in (int,float) or not math.isfinite(max_distance) or max_distance<=0:
        raise web.HTTPBadRequest(text='매칭 거리는 0보다 큰 m 값으로 입력하세요.')
    source=ordering_source(document);reference=next((t for t in source['references'] if t['id']==reference_id),None)
    if reference is None:raise web.HTTPBadRequest(text='선택한 로스백 중 기준 기록을 선택하세요.')
    edges=[];offset=0.
    for si,segment in enumerate(reference['curve_segments']):
        distance=0.
        if len(segment)==1:
            p=segment[0];edges.append((si,p['e'],p['n'],0.,0.,0.,offset,p.get('seq',0),p.get('seq',0)))
        for a,b in zip(segment,segment[1:]):
            dx=b['e']-a['e'];dy=b['n']-a['n'];length=math.hypot(dx,dy)
            edges.append((si,a['e'],a['n'],dx,dy,length,offset+distance,a.get('seq',0),b.get('seq',0)))
            distance+=length
        offset+=distance
    if not edges:raise web.HTTPBadRequest(text='기준 기록에 평활 경로가 없습니다. 다른 기록을 선택하세요.')
    matches=[]
    for index,p in enumerate(source['points']):
        best=None;best_sq=float('inf')
        for si,x,y,dx,dy,length,along,seq_a,seq_b in edges:
            f=max(0.,min(1.,((p['e']-x)*dx+(p['n']-y)*dy)/(length*length))) if length else 0.
            qx=x+f*dx;qy=y+f*dy;squared=(p['e']-qx)**2+(p['n']-qy)**2
            if squared<best_sq:
                best_sq=squared;best={'point_index':index,'distance_m':math.sqrt(squared),'path_m':along+f*length,
                    'segment_index':si,'reference_seq':seq_a+f*(seq_b-seq_a),'e':qx,'n':qy}
        best['matched']=best['distance_m']<=max_distance;matches.append(best)
    order=sorted((m['point_index'] for m in matches if m['matched']),key=lambda i:(matches[i]['segment_index'],matches[i]['path_m'],i))
    return {'reference_id':reference_id,'reference_name':reference['name'],'max_distance_m':max_distance,'matches':matches,'auto_order':order}


def order_result(document,reference_id,max_distance,order):
    result=automatic_order(document,reference_id,max_distance);points=document['stages']['6']['points']
    if not isinstance(order,list) or any(type(i) is not int or not 0<=i<len(points) for i in order) or len(set(order))!=len(order):
        raise web.HTTPBadRequest(text='순서에 중복되거나 알 수 없는 GPS 점이 있습니다.')
    selected=set(order)
    return {**result,'order':order,'ordered_points':[{'index':rank,'point_index':i,**points[i]} for rank,i in enumerate(order,1)],
            'unmatched_indices':[i for i in range(len(points)) if i not in selected]}
