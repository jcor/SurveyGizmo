
import collections
import hashlib
import logging

import oauth_helper
import requests

logger = logging.getLogger(__name__)


class ImproperlyConfigured(Exception):
    """ SurveyGizmo is somehow improperly configured."""
    pass


class _Config(object):
    def __init__(self, _sg, **kwargs):
        self._sg = _sg
        self.api_version = kwargs.get('api_version', 'head')
        self.auth_method = kwargs.get('auth_method', None)
        self.username = kwargs.get('username', None)
        self.password = kwargs.get('password', None)
        self.md5_hash = kwargs.get('md5_hash', None)
        self.consumer_key = kwargs.get('consumer_key', None)
        self.consumer_secret = kwargs.get('consumer_secret', None)
        self.access_token = kwargs.get('access_token', None)
        self.access_token_secret = kwargs.get('access_token_secret', None)
        self.response_type = kwargs.get('response_type', None)
        self.requests_kwargs = kwargs.get('requests_kwargs', {})

    def validate(self):
        """ Perform validation check on properties.
        """
        if not self.auth_method in ['user:pass', 'user:md5', 'oauth']:
            raise ImproperlyConfigured("No authentication method provided.")
        else:
            if self.auth_method == "user:pass":
                if not self.username or not self.password:
                    raise ImproperlyConfigured("Username and password for 'user:pass' authentication.")
            elif self.auth_method == "user:md5":
                if not self.username:
                    raise ImproperlyConfigured("Username required for 'user:md5' authentication.")
                elif not self.password and not self.md5_hash:
                    raise ImproperlyConfigured("Password or md5 hash of password required for 'user:md5' authentication.")
            elif self.auth_method == "oauth":
                if not self.consumer_key or not self.consumer_secret or \
                   not self.access_token or not self.access_token_secret:
                    raise ImproperlyConfigured("OAuth consumer key and secret, and OAuth access token and secret required for 'oauth' authentication.")

        if not self.response_type in ["json", "pson", "xml", "debug", None]:
            raise ImproperlyConfigured()


class _API(object):
    base_url = "https://restapi.surveygizmo.com/"

    def __init__(self, config):
        self._config = config

        self._resources = None
        self._filters = []
        self._session = None

    def _import_api(self):
        """ update api modules, wrap callables.
        """
        resources = __import__('surveygizmo.api', globals(), locals(), ['*'])

        for resource_name in resources.__all__:
            resource = getattr(resources, resource_name)

            for name, func in resource.__dict__.items():
                if isinstance(func, collections.Callable) and not name.startswith('__'):
                    setattr(resource, name, self._wrap(func))

            self._resources[resource_name] = resource

    def __getattr__(self, name):
        """ retrieve modules loaded from api
        """
        if self._modules.get(name, None) is not None:
            return self._modules[name]
        raise AttributeError(name)

    def _wrap(self, func):
        """ wrap api callable's such that their return values
            are immediately executed
        """
        def wrapper(*args, **kwargs):
            keep = kwargs.pop('keep', False)
            url_fetch = kwargs.pop('url_fetch', False)

            tail, params = func(*args, **kwargs)

            response_type = self._sg.config.response_type
            if response_type:
                tail = "%s.%s" % (tail, response_type)
            tail = "%s/%s" % (self._api_version, tail)

            vals = self.prepare(tail, params, keep)
            if url_fetch:
                return vals
            return self.execute(*vals)
        return wrapper

    def add_filter(self, field, operator, value):  # , object_type=None):
        """ Add a query filter to be applied to the next API call.
            :param field: Field name to filter by
            :type field: str
            :param operator: Operator value
            :type operator: str
            :param value: Value of filter
            :type value: str
            :param object_type: Optional. Checks field for object association
            :type object_type: str

            Known Filters:
                Question                    [question(2)]                   surveyresponse
                Question Option             [question(2), option(10001)]    surveyresponse
                Date Submitted              datesubmitted                   surveyresponse
                Is Test Data                istestdata                      surveyresponse
                Status                      status                          surveyresponse
                Contact ID                  contact_id                      surveyresponse
                Creation Time               createdon                       survey
                Last Modified Time          modifiedon                      survey
                Survey Title                title                           survey
                Type of Project             subtype                         survey
                Team Survey Belongs To      team                            survey
                Status                      status                          survey
                Type of Link                type                            surveycampaign
                Name of Link                name                            surveycampaign
                Secure / Unsecure Link      ssl                             surveycampaign
                Link Created Date           datecreated                     surveycampaign
                Link Last Modified Date     datemodified                    surveycampaign
                Status                      status                          surveycampaign


            Known Operators:
                ==
                !=
                >=
                <=
                >
                <
                =           (==)
                <>          (!=)
                IS NULL     Value is True or False
                IS NOT NULL Value is True or False
                in          Value is comma separated list
        """
        i = len(self._filters)
        self._filters.append({
            'filter[field][%d]' % i: str(field),
            'filter[operator][%d]' % i: str(operator),
            'filter[value][%d]' % i: str(value),
        })

    def prepare(self, tail, params, keep=False):
        """ Prepares the url and remaining params for execution
            :param tail: The tail portion of the URL. This should not include
            the domain name.
            :param params: Query parameters passed to API.
            :param keep: Keep filters for next API call. Defaults to False.
        """
        config = self._config
        config.validate()

        for _filter in self._filters:
            params.update(_filter)
        if not keep:
            self._filters = []

        if config.auth_method == 'user:pass':
            params.update({
                config.auth_method: "%s:%s" % (config.username, config.password),
            })

        elif config.auth_method == 'user:md5':
            if not config.md5_hash:
                config.md5_hash = hashlib.md5(config.password).hexdigest()
            params.update({
                config.auth_method: "%s:%s" % (config.username, config.md5_hash),
            })
        url = "%s%s" % (self.base_url, tail)

        return url, params

    def execute(self, url, params):
        """ Executes a call to the API.
            :param url: The full url for the api call.
            :param params: Query parameters passed to API.
        """
        config = self._config
        if config.auth_method == 'oauth':
            if not self._session:
                self._session = oauth_helper.SGAuthService(
                    config.consumer_key, config.consumer_secret,
                    config.access_token, config.access_token_secret
                ).get_session()

            response = self._session.get(url, params=params, **config.requests_kwargs)
        else:
            response = requests.get(url, params=params, **config.requests_kwargs)

        response.raise_for_status()

        if not config.response_type:
            return response.json()
        else:
            return response.text


class SurveyGizmo(object):
    """
    """
    def __init__(self, **kwargs):
        self.config = _Config(self, **kwargs)
        self.api = _API(self.config)
        # self.api._import_api()
