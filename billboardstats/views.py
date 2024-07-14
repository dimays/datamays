from django.shortcuts import render

# Search
def search(request):
    return render(request, 'billboardstats/search.html')

# Chart
def chart(request):
    return render(request, 'billboardstats/chart.html')

# Song
def song(request):
    return render(request, 'billboardstats/song.html')

# Artist
def artist(request):
    return render(request, 'billboardstats/artist.html')