"""Import measured camera-report summaries; do not invent or execute report content."""
import math


def extract_evaluation(report):
    if report.get('schema')!='aura-camera-evaluation-v1':raise ValueError('Choose an AURA camera evaluation v1 JSON export')
    s=report.get('summary')
    if not isinstance(s,dict):raise ValueError('Report has no summary')
    clean={}
    for key in ('annotated_samples','tp','fp','fn'):
        value=s.get(key)
        if type(value)!=int or value<0 or value>1_000_000:raise ValueError('Invalid count: '+key)
        clean[key]=value
    for key in ('precision','recall','f1','mean_matched_iou'):
        value=s.get(key)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1):raise ValueError('Invalid metric: '+key)
        clean[key]=value
    t=s.get('timing_window',{})
    if not isinstance(t,dict):raise ValueError('Invalid timing window')
    for key in ('score_threshold','iou_threshold'):
        value=s.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=1:raise ValueError('Invalid evaluation threshold')
    for key in ('mean_ms','p95_ms'):
        value=t.get(key)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):raise ValueError('Invalid timing')
        clean[key]=value
    return {'summary':clean,'score_threshold':s.get('score_threshold'),'iou_threshold':s.get('iou_threshold'),'limitations':'User-imported measured summary, not independently verified. Compare only equivalent scenes, scope, thresholds and annotation protocol.'}
