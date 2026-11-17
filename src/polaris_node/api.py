"""Small, fail-closed client for the verified Remnawave 3.4.11 API."""
import base64
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import PolarisError

_UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
_INSTALL = ['system:metadata','nodes:list','nodes:get','nodes:create',
            'config-profiles:list','config-profiles:get','config-profiles:create',
            'keygen:get','hosts:list','hosts:create']
_PUBLISH = ['system:metadata','nodes:get','config-profiles:get','hosts:get','hosts:update',
            'internal-squads:list','internal-squads:get','internal-squads:update']
_ROLLBACK = ['system:metadata','nodes:get','config-profiles:get','hosts:get',
             'hosts:delete','nodes:delete','config-profiles:delete']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PolarisError('Panel API redirects are forbidden; verify the panel URL.')


class API:
    def __init__(self, base_url: str, token: str, purpose='install'):
        if purpose not in ('install','publish','rollback'):
            raise PolarisError('Unknown API operation.')
        try:
            parsed = urllib.parse.urlsplit(base_url)
            port = parsed.port
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.path not in ('','/','/api','/api/') or port == 0
                    or any(c.isspace() for c in base_url)):
                raise ValueError()
        except (TypeError, ValueError):
            raise PolarisError('Panel URL must be an HTTPS origin without credentials or query parameters.') from None
        self.origin = urllib.parse.urlunsplit(('https',parsed.netloc,'','',''))
        self.purpose = purpose
        self._token = token
        self._check_token()
        self._metadata = None
        # Honor the runtime's HTTPS proxy/NO_PROXY and trusted CA settings.
        # HTTPS remains verified end to end, and HTTP redirects are forbidden.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler(), NoRedirect(),
                                                  urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def _check_token(self):
        try:
            if not isinstance(self._token,str) or any(c.isspace() for c in self._token):
                raise ValueError()
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',self._token):
                raise ValueError()
            parts = self._token.split('.')
            if len(parts) != 3 or len(self._token) > 16384:
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(parts[1]+'='*(-len(parts[1])%4)))
            if not isinstance(payload,dict):
                raise ValueError()
            expires = payload['exp']
            if (payload.get('role') != 'API' or isinstance(expires,bool) or not isinstance(expires,(int,float))
                    or not math.isfinite(expires) or not 60 <= expires-time.time() <= 86400+300):
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise PolarisError('Use a temporary API-role token valid for at least 60 seconds and at most 24 hours; create it with a one-day expiry.') from None
        # Decoded claims are only a preflight. The actual panel authenticates
        # every request, and authenticated metadata gates all other operations.

    @staticmethod
    def scope_list(purpose='install'):
        scopes = {'install':_INSTALL,'publish':_PUBLISH,'rollback':_ROLLBACK}.get(purpose)
        if scopes is None:
            raise PolarisError('Unknown API operation.')
        return list(scopes)

    def _allowed(self, method, path):
        read_install = ['/system/metadata','/nodes','/nodes/'+_UUID,'/hosts',
                        '/config-profiles','/config-profiles/'+_UUID,'/keygen']
        if self.purpose == 'install':
            rules = read_install if method == 'GET' else ['/config-profiles','/nodes','/hosts'] if method == 'POST' else []
        elif self.purpose == 'publish':
            rules = (['/system/metadata','/nodes/'+_UUID,'/config-profiles/'+_UUID,'/hosts/'+_UUID,
                      '/internal-squads','/internal-squads/'+_UUID] if method == 'GET'
                     else ['/hosts','/internal-squads'] if method == 'PATCH' else [])
        else:
            rules = (['/system/metadata','/nodes/'+_UUID,'/config-profiles/'+_UUID,'/hosts/'+_UUID] if method == 'GET'
                     else ['/hosts/'+_UUID,'/nodes/'+_UUID,'/config-profiles/'+_UUID] if method == 'DELETE' else [])
        return any(re.fullmatch(rule,path) for rule in rules)

    def request(self, method, path, data=None):
        method = method.upper()
        if not isinstance(path,str):
            raise PolarisError('Invalid API path.')
        if path.startswith('/api/'):
            path = path[4:]
        elif not path.startswith('/'):
            path = '/'+path
        if not self._allowed(method,path):
            raise PolarisError('This API operation is outside the selected purpose.')
        if method == 'POST' and path == '/hosts' and (not isinstance(data,dict)
                or data.get('isDisabled') is not True or data.get('isHidden') is not True):
            raise PolarisError('Installation may create only explicitly disabled and hidden Hosts.')
        self._check_token()
        if path != '/system/metadata' and self._metadata is None:
            self.metadata()
        payload = self._send(method,path,data)
        if path == '/system/metadata':
            if not isinstance(payload,dict) or payload.get('version') != '3.4.11':
                raise PolarisError('Panel version is unsupported; this release verifies Remnawave 3.4.11 only.')
            self._metadata = payload
        return payload

    def metadata(self):
        return self.request('GET','/system/metadata')

    def _send(self, method, path, data):
        headers = {'Authorization':'Bearer '+self._token,'Accept':'application/json',
                   'User-Agent':'Polaris-Node-Installer/1.0'}
        body = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(data,separators=(',',':')).encode()
        request = urllib.request.Request(self.origin+'/api'+path,method=method,headers=headers,data=body)
        try:
            with self._opener.open(request,timeout=20) as response:
                if not 200 <= response.status < 300:
                    raise PolarisError('Panel API returned an unexpected HTTP status.')
                if response.status == 204:
                    return None
                raw = response.read(4*1024*1024+1)
                if len(raw) > 4*1024*1024:
                    raise PolarisError('Panel API response exceeded the safety limit.')
                result = json.loads(raw)
                if not isinstance(result,dict) or 'response' not in result:
                    raise ValueError()
                return result['response']
        except urllib.error.HTTPError as exc:
            # Never include an error body, URL, headers or transport exception:
            # each may contain credentials or server-side sensitive details.
            suffix = ' POST outcome may be ambiguous; reconcile owned markers before rerunning.' if method == 'POST' else ''
            raise PolarisError('Panel API HTTP '+str(exc.code)+'.'+suffix) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            suffix = ' POST outcome is ambiguous; rerun to reconcile owned markers without blind retries.' if method == 'POST' else ''
            raise PolarisError('Panel API connection failed; verify network and trusted TLS.'+suffix) from None
        except (ValueError, UnicodeError):
            suffix = ' POST outcome may be ambiguous; reconcile owned markers before rerunning.' if method == 'POST' else ''
            raise PolarisError('Panel API returned an invalid response.'+suffix) from None
