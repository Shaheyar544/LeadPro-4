"""Production provider data-policy boundary."""
from dataclasses import dataclass
@dataclass(frozen=True)
class ProviderDataPolicy:
    durable_fields: frozenset[str]; transient_fields: frozenset[str]; export_fields: frozenset[str]; status: str; attribution: str|None=None
POLICIES={
 'google_places_new':ProviderDataPolicy(frozenset({'place_id'}),frozenset({'display_name','formatted_address','website_uri','phone','rating','user_rating_count','types','business_status'}),frozenset({'place_id'}),'enabled','Google Maps'),
 'google_places':ProviderDataPolicy(frozenset(),frozenset(),frozenset(),'rollback_only'),
 'serper_maps':ProviderDataPolicy(frozenset(),frozenset(),frozenset(),'review_required'),
 'yelp':ProviderDataPolicy(frozenset(),frozenset(),frozenset(),'review_required')}
def policy_for(provider): return POLICIES.get(provider,ProviderDataPolicy(frozenset(),frozenset(),frozenset(),'disabled'))
def sanitize_record(provider, record):
 p=policy_for(provider); return {k:v for k,v in record.items() if k in p.durable_fields or k in {'provider','provider_record_id','observed_at','browser_observed_url','browser_evidence'}}
def allowed_export_fields(provider): return policy_for(provider).export_fields
