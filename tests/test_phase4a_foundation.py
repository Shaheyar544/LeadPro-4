def test_policy_boundary():
 from provider_policy import sanitize_record
 assert sanitize_record('google_places_new', {'place_id':'p','rating':5,'website_uri':'x'}) == {'place_id':'p'}
def test_production_score_ignores_provider_fields():
 from production_scoring import score_browser_evidence
 a={'findings':{'contact_form':{'status':'present'}} ,'rating':5,'review_count':100}
 assert score_browser_evidence(a)['profile_version']=='website_conversion_v2'
def test_cookie_csrf():
 from auth_sessions import issue_session,csrf_valid
 sid,csrf,_=issue_session('u')
 assert sid and csrf and csrf_valid(csrf,csrf) and not csrf_valid(csrf,'bad')
def test_health_shape():
 from health import liveness
 assert liveness()['status']=='ok'

def test_redaction():
 from log_redaction import redact
 assert 'supersecret' not in redact('api_key=supersecret')
def test_transient_result_not_durable():
 from provider_transient import TransientDiscoveryResult
 assert TransientDiscoveryResult('google_places_new','p',rating=5).durable_ref()=={'provider':'google_places_new','provider_record_id':'p'}
