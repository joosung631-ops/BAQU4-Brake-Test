"""Explicit cross-recording merges of stage 5 points, retaining source lineage."""
import math
from aiohttp import web
from .gps_review import project, curve_segment


def source_points(document):
    if '5' not in document['stages']:raise web.HTTPConflict(text='먼저 5단계 결과를 저장하세요.')
    result=[]
    for color,t in enumerate(document['stages']['5']['tracks']):
        for index,p in enumerate(t['points']):
            result.append({'id':f"{t['id']}:{index}",'track_id':t['id'],'track_name':t['name'],'color_index':color,
                           'lat':p['lat'],'lon':p['lon'],'source_seqs':p['source_seqs'],'segment':p['segment']})
    return result


def fused_points(source,groups):
    if not isinstance(groups,list) or any(not isinstance(g,list) or not g or any(not isinstance(k,str) for k in g) for g in groups):
        raise web.HTTPBadRequest(text='병합 그룹이 잘못되었습니다.')
    flat=[k for group in groups for k in group]
    if sorted(flat)!=sorted(p['id'] for p in source):raise web.HTTPBadRequest(text='병합 그룹에 누락되거나 중복된 점이 있습니다.')
    known={p['id']:p for p in source};output=[]
    for group in groups:
        ps=[known[k] for k in group]
        output.append({'source_ids':group,'source_track_ids':list(dict.fromkeys(p['track_id'] for p in ps)),
                       'lat':sum(p['lat'] for p in ps)/len(ps),'lon':sum(p['lon'] for p in ps)/len(ps),'count':len(ps)})
    return output


def automatic_groups(source,groups,selected,radius,origin):
    current=fused_points(source,groups)
    if type(radius) not in (float,int) or not math.isfinite(radius) or radius<.000001:raise web.HTTPBadRequest(text='병합 거리는 0.000001m 이상의 값으로 입력하세요.')
    if not isinstance(selected,list) or any(type(i) is not int or not 0<=i<len(groups) for i in selected) or len(set(selected))!=len(selected) or len(selected)<2:
        raise web.HTTPBadRequest(text='자동 병합할 점을 2개 이상 선택하세요.')
    selected=sorted(selected);coordinates=project(current,origin);clusters=[];grid={}
    # A candidate must be strictly inside the radius of EVERY member. This avoids
    # long chains swallowing an entire route whose adjacent samples are close.
    for i in selected:
        p=coordinates[i];cell=(math.floor(p['e']/radius),math.floor(p['n']/radius));candidates=[]
        for x in range(cell[0]-1,cell[0]+2):
            for y in range(cell[1]-1,cell[1]+2):candidates.extend(grid.get((x,y),[]))
        chosen=None
        for ci in sorted(candidates):
            if all(math.hypot(p['e']-coordinates[j]['e'],p['n']-coordinates[j]['n'])<radius for j in clusters[ci]):chosen=ci;break
        if chosen is None:
            grid.setdefault(cell,[]).append(len(clusters));clusters.append([i])
        else:clusters[chosen].append(i)
    membership={i:cluster for cluster in clusters for i in cluster};result=[]
    for i,group in enumerate(groups):
        cluster=membership.get(i)
        if cluster is None:result.append(group)
        elif i==cluster[0]:result.append([k for j in cluster for k in groups[j]])
    return result


def fusion_curves(source,groups,origin):
    positions=project(fused_points(source,groups),origin)
    membership={key:i for i,g in enumerate(groups) for key in g}
    output=[];current=[];previous=None;last_group=None;track=None
    def finish():
        if current:track['curve_segments'].append(curve_segment(current,.5))
    for original in source:
        index=membership[original['id']]
        if previous is None or original['track_id']!=previous['track_id']:
            finish();current=[];last_group=None
            track={'id':original['track_id'],'color_index':original['color_index'],'curve_segments':[]};output.append(track)
        elif original['segment']!=previous['segment']:
            finish();current=[];last_group=None
        if index!=last_group:current.append({**positions[index],'seq':len(current)})
        previous=original;last_group=index
    finish()
    return output
