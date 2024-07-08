from django.shortcuts import render

# Home
def home(request):
    return render(request, 'bio/home.html')

# Error Pages
def page_not_found_view(request, exception):
    return render(request, 'bio/404.html', status=404)

def page_forbidden_view(request, exception):
    return render(request, 'bio/403.html', status=403)