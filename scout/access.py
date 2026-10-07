"""Optional Cloudflare Access verification, never trust an identity header alone."""
import re

class Access:
    def __init__(self,host,team,audience,email):
        if not isinstance(host,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '.' not in host:
            raise ValueError('Use an exact dashboard hostname, without scheme or path.')
        if not re.fullmatch(r'[a-z0-9-]+\.cloudflareaccess\.com',team or '') or not audience or not email or '@' not in email:
            raise ValueError('Access requires a team domain, application AUD, and owner email.')
        import jwt
        self.jwt=jwt;self.host=host;self.issuer='https://'+team;self.audience=audience;self.email=email.casefold()
        self.keys=jwt.PyJWKClient(self.issuer+'/cdn-cgi/access/certs',timeout=5)
    def verify(self,token):
        if not isinstance(token,str) or not 1<=len(token)<=16000:return False
        try:
            key=self.keys.get_signing_key_from_jwt(token).key
            claims=self.jwt.decode(token,key,algorithms=['RS256'],audience=self.audience,issuer=self.issuer,options={'require':['exp','iat','iss','aud','sub','email']})
            return isinstance(claims.get('email'),str) and claims['email'].casefold()==self.email and claims.get('type')=='app'
        except Exception:return False
