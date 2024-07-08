from django.http import HttpResponsePermanentRedirect


class HerokuRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.get_host().endswith('.herokuapp.com') or request.get_host() == 'datamays.com':
            redirect_url = 'https://www.datamays.com' + request.get_full_path()
            return HttpResponsePermanentRedirect(redirect_url)

        return self.get_response(request)