from __future__ import unicode_literals

from django.core import urlresolvers

try:
    import newrelic.agent
    NEWRELIC_ENABLED = True
except ImportError:
    NEWRELIC_ENABLED = False

class ContinueResolving(Exception):
    pass

def multiurl(*urls, **kwargs):
    exceptions = kwargs.get('catch', (ContinueResolving,))
    return MultiRegexURLResolver(urls, exceptions)

class MultiRegexURLResolver(urlresolvers.RegexURLResolver):
    def __init__(self, urls, exceptions):
        super(MultiRegexURLResolver, self).__init__('', None)
        self._urls = urls
        self._exceptions = exceptions

    @property
    def url_patterns(self):
        return self._urls

    def resolve(self, path):
        tried = []
        matched = []
        patterns_matched = []

        # This is a simplified version of RegexURLResolver. It doesn't
        # support a regex prefix, but otherwise this is mostly a copy/paste.
        for pattern in self.url_patterns:
            try:
                sub_match = pattern.resolve(path)
            except urlresolvers.Resolver404 as e:
                sub_tried = e.args[0].get('tried')
                if sub_tried is not None:
                    tried.extend([[pattern] + t for t in sub_tried])
                else:
                    tried.append([pattern])
            else:
                if sub_match:
                    # Here's the part that's different: instead of returning the
                    # first match, build up a list of all matches.
                    rm = urlresolvers.ResolverMatch(sub_match.func, sub_match.args, sub_match.kwargs, sub_match.url_name, self.app_name or sub_match.app_name, [self.namespace] + sub_match.namespaces)
                    matched.append(rm)
                    patterns_matched.append([pattern])
                tried.append([pattern])
        if matched:
            return MultiResolverMatch(matched, self._exceptions, patterns_matched, path, tried)
        raise urlresolvers.Resolver404({'tried': tried, 'path': path})

class MultiResolverMatch(object):
    def __init__(self, matches, exceptions, patterns_matched, path, tried):
        self.matches = matches
        self.exceptions = exceptions
        self.patterns_matched = patterns_matched
        self.path = path
        self.tried = tried

        # Attributes to emulate ResolverMatch
        self.kwargs = {}
        self.args = []
        self.url_name = None
        self.app_name = None
        self.namespaces = []

    @property
    def func(self):
        def multiview(request):
            resolver_match = request.resolver_match
            for i, match in enumerate(self.matches):
                try:
                    request.resolver_match = match

                    if NEWRELIC_ENABLED:
                        match.func = newrelic.agent.FunctionTraceWrapper(match.func)
                        newrelic.agent.set_transaction_name(name=newrelic.agent.callable_name(match.func))

                    response = match.func(request, *match.args, **match.kwargs)
                    return response
                except self.exceptions:
                    continue
            request.resolver_match = resolver_match
            raise urlresolvers.Resolver404({'tried': self.tried, 'path': self.path})
        multiview.multi_resolver_match = self

        if NEWRELIC_ENABLED:
            multiview = newrelic.agent.FunctionTraceWrapper(multiview)

        return multiview
