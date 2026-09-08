"""Production scoring independent of persisted Google ratings/reviews."""
VERSION='website_conversion_v2'
CORE=('contact_form','quote_form','booking_form','contact_page','primary_cta','click_to_call','mobile_layout')
def score_browser_evidence(audit):
 f=audit.get('findings',{}) if isinstance(audit,dict) else {}
 present=sum(1 for k in CORE if (f.get(k,{}).get('status')=='present' or f.get(k,{}).get('value') is True))
 unknown=sum(1 for k in CORE if f.get(k,{}).get('status') in ('unknown','blocked','failed'))
 gap=round(max(0.0,1-present/len(CORE)),4); conf=round((len(CORE)-unknown)/len(CORE),4)
 return {'profile_version':VERSION,'opportunity_score':round(gap*conf*100,2),'digital_gap':gap,'business_strength':None,'evidence_confidence':conf,'contact_confidence':conf,'breakdown':{'findings':f,'source':'browser_evidence_only'}}
